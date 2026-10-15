"""
The end-to-end pipeline: folder of XML files + contract table  ->  findings, summary, quarantine, report.

    load_batch()   reads every XML; files that cannot be read go to quarantine (with the reason)
    audit()        runs all rules
    summarize()    counts and amounts by rule, and a headline that never counts a document twice
    evaluate()     (only for the simulated data) compares the findings with the answer key
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .parser import ParseError, parse_cte
from .rules import RULES, Settings, run_rules


@dataclass
class AuditResult:
    docs: pd.DataFrame
    quarantine: pd.DataFrame
    findings: pd.DataFrame


def load_batch(xml_dir) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, bad = [], []
    for path in sorted(Path(xml_dir).glob("*.xml")):
        try:
            rows.append(parse_cte(path))
        except ParseError as exc:
            bad.append({"file": path.name, "reason": str(exc)})
    return pd.DataFrame(rows), pd.DataFrame(bad, columns=["file", "reason"])


def load_contract(path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"carrier_cnpj": str, "origin_mun": str, "dest_mun": str})


def audit(xml_dir, contract_csv, settings: Settings = Settings()) -> AuditResult:
    docs, quarantine = load_batch(xml_dir)
    findings = run_rules(docs, load_contract(contract_csv), settings)
    return AuditResult(docs, quarantine, findings)


def summarize(result: AuditResult) -> dict:
    f, d = result.findings, result.docs
    by_rule = (f.groupby("rule").agg(documents=("file", "nunique"), amount=("amount_at_risk", "sum")).round(2)
               .reindex(list(RULES)).dropna(how="all").fillna(0).reset_index())
    by_rule["severity"] = by_rule["rule"].map(lambda r: RULES[r][0])
    by_rule["what_it_checks"] = by_rule["rule"].map(lambda r: RULES[r][2])
    # Headline without double counting: inside each category, a document counts once, with its largest amount
    f = f.assign(category=f["rule"].map(lambda r: RULES[r][1]))
    per_doc = f.groupby(["category", "file"])["amount_at_risk"].max().reset_index()
    by_category = (per_doc.groupby("category").agg(documents=("file", "nunique"), amount=("amount_at_risk", "sum"))
                   .round(2).reset_index())
    return {
        "files_read": len(d), "files_quarantined": len(result.quarantine),
        "documents_flagged": int(f["file"].nunique()), "findings": len(f),
        "total_value_audited": round(d["total_cents"].sum() / 100, 2),
        "by_rule": by_rule, "by_category": by_category,
    }


def evaluate(result: AuditResult, truth: pd.DataFrame) -> pd.DataFrame:
    """Precision and recall per rule against the answer key of the simulated data."""
    rows = []
    flagged_any = set(result.findings["file"])
    for rule in list(RULES) + ["quarantine"]:
        expected = set(truth.loc[truth["expected_rule"] == rule, "file"])
        if rule == "quarantine":
            got = set(result.quarantine["file"])
        else:
            got = set(result.findings.loc[result.findings["rule"] == rule, "file"])
        tp = len(expected & got)
        rows.append({"rule": rule, "planted": len(expected), "found": tp, "missed": len(expected - got),
                     "false_alarms": len(got - expected),
                     "precision": round(tp / len(got), 3) if got else None,
                     "recall": round(tp / len(expected), 3) if expected else None})
    traps = set(truth.loc[truth["expected_rule"] == "none", "file"])
    rows.append({"rule": "(traps flagged by any rule)", "planted": len(traps), "found": len(traps & flagged_any),
                 "missed": None, "false_alarms": len(traps & flagged_any), "precision": None, "recall": None})
    return pd.DataFrame(rows)


def write_report(result: AuditResult, summary: dict, path) -> None:
    f = result.findings
    brl = lambda x: f"R$ {x:,.2f}"
    lines = ["# CT-e audit report", "",
             f"- Files read: **{summary['files_read']:,}** (+ {summary['files_quarantined']} in quarantine)",
             f"- Total value of the CT-e audited: **{brl(summary['total_value_audited'])}**",
             f"- Documents with at least one finding: **{summary['documents_flagged']:,}**", "",
             "## Amounts by category (a document counts once per category)", "",
             "| Category | Documents | Amount |", "|---|---|---|"]
    for r in summary["by_category"].itertuples():
        lines.append(f"| {r.category} | {r.documents} | {brl(r.amount)} |")
    lines += ["", "## Findings by rule", "", "| Rule | Severity | Documents | Amount | What it checks |", "|---|---|---|---|---|"]
    for r in summary["by_rule"].itertuples():
        lines.append(f"| `{r.rule}` | {r.severity} | {int(r.documents)} | {brl(r.amount)} | {r.what_it_checks} |")
    lines += ["", "## Top 10 findings by amount", "", "| File | Carrier | Rule | Detail | Amount |", "|---|---|---|---|---|"]
    for r in f.sort_values("amount_at_risk", ascending=False).head(10).itertuples():
        lines.append(f"| `...{r.file[-22:]}` | {r.carrier.title()} | `{r.rule}` | {r.detail} | {brl(r.amount_at_risk)} |")
    if len(result.quarantine):
        lines += ["", "## Quarantine (files that could not be read)", "", "| File | Reason |", "|---|---|"]
        lines += [f"| `{r.file}` | {r.reason} |" for r in result.quarantine.itertuples()]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
