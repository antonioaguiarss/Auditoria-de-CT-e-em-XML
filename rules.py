"""
Audit rules. Each rule is a small function: it receives the table of documents (one row per XML file)
and returns a list of findings. A document can trigger several rules.

Rules 1 to 3 look at every file. Rules 4 to 11 look only at AUTHORIZED documents (status 100),
because a cancelled document is not a service to be paid.

Amounts are integer cents inside the code and R$ in the output.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .keys import check_digit, is_valid_key, parse_key

# rule id: (severity, category, short description)
RULES = {
    "invalid_key_dv":         ("HIGH",   "Cannot be verified",           "Access key check digit is wrong"),
    "key_field_mismatch":     ("HIGH",   "Cannot be verified",           "Numbers inside the key disagree with the XML body"),
    "duplicate_xml":          ("HIGH",   "Payment that should not happen", "Same CT-e received in more than one file"),
    "duplicate_service":      ("HIGH",   "Payment that should not happen", "New CT-e for an NF-e that another CT-e already carried"),
    "cancelled_cte":          ("MEDIUM", "Payment that should not happen", "Cancelled CT-e in the batch"),
    "total_mismatch":         ("MEDIUM", "Overcharge vs contract",       "Total is not the sum of the components"),
    "freight_above_contract": ("MEDIUM", "Overcharge vs contract",       "Freight above weight x rate (or minimum charge)"),
    "gris_mismatch":          ("LOW",    "Overcharge vs contract",       "Risk-management fee differs from contract % x cargo value"),
    "toll_above_contract":    ("MEDIUM", "Overcharge vs contract",       "Toll above what the contract allows"),
    "no_contract":            ("MEDIUM", "Cannot be verified",           "No contract for this carrier on this route and date"),
    "orphan_complement":      ("HIGH",   "Payment that should not happen", "Complement CT-e whose original is not in the batch"),
}

FREIGHT, GRIS, TOLL = "FRETE PESO", "GRIS", "PEDAGIO"


@dataclass(frozen=True)
class Settings:
    tolerance_cents: int = 5      # differences up to R$ 0.05 are rounding, not findings


def expected_charges(weight_kg: float, cargo_value_cents: int, rate_per_kg: float, min_charge: float, gris_pct: float):
    """What the contract says should be charged: (freight, GRIS) in cents.
    Freight is the HIGHER of weight x rate and the minimum charge. GRIS is a % of the cargo value."""
    freight = max(round(weight_kg * rate_per_kg * 100), round(min_charge * 100))
    gris = round(cargo_value_cents * gris_pct)
    return int(freight), int(gris)


def _brl(cents: int) -> str:
    return f"R$ {cents / 100:,.2f}"


def _finding(r, rule: str, detail: str, amount_cents: int = 0) -> dict:
    severity = RULES[rule][0]
    return {"file": r.file, "key": r.key, "number": r.number, "carrier": r.carrier_name,
            "issued": r.issued_at.date().isoformat(), "rule": rule, "severity": severity,
            "detail": detail, "amount_at_risk": round(max(amount_cents, 0) / 100, 2)}


# ----------------------------------------------------------------------------
# Contract lookup
# ----------------------------------------------------------------------------
def attach_contract(docs: pd.DataFrame, contract: pd.DataFrame) -> pd.DataFrame:
    """One row per document that HAS a valid contract line (carrier + route + date inside the validity)."""
    merged = docs.merge(contract, how="inner", on=["carrier_cnpj", "origin_mun", "dest_mun"], suffixes=("", "_contract"))
    day = merged["issued_at"].dt.normalize()
    valid = merged[(day >= pd.to_datetime(merged["valid_from"])) & (day <= pd.to_datetime(merged["valid_to"]))]
    return valid.sort_values("valid_from").drop_duplicates("file", keep="last").set_index("file")


# ----------------------------------------------------------------------------
# Rules 1-3: integrity of the document (all files)
# ----------------------------------------------------------------------------
def rule_invalid_key_dv(docs, **_):
    out = []
    for r in docs.itertuples():
        if is_valid_key(r.key):
            continue
        if len(r.key) == 44 and r.key.isdigit():
            detail = f"check digit is {r.key[-1]}, should be {check_digit(r.key[:43])}"
        else:
            detail = "key does not have 44 digits"
        out.append(_finding(r, "invalid_key_dv", detail, r.total_cents))
    return out


def rule_key_field_mismatch(docs, **_):
    out = []
    for r in docs.itertuples():
        if not is_valid_key(r.key) and not (len(r.key) == 44 and r.key.isdigit()):
            continue
        p, diffs = parse_key(r.key), []
        if p.cuf != r.uf_code:
            diffs.append(f"state: key {p.cuf}, body {r.uf_code}")
        if p.aamm != f"{r.issued_at:%y%m}":
            diffs.append(f"month of issue: key {p.aamm}, body {r.issued_at:%y%m}")
        if p.cnpj != r.carrier_cnpj:
            diffs.append("issuer CNPJ differs")
        if p.model != r.model:
            diffs.append(f"model: key {p.model}, body {r.model}")
        if p.serie != int(r.serie):
            diffs.append(f"series: key {p.serie}, body {r.serie}")
        if p.number != int(r.number):
            diffs.append(f"number: key {p.number}, body {r.number}")
        if r.protocol_key and r.protocol_key != r.key:
            diffs.append("protocol key differs from the document key")
        if diffs:
            out.append(_finding(r, "key_field_mismatch", "; ".join(diffs), r.total_cents))
    return out


def rule_duplicate_xml(docs, **_):
    out = []
    for key, g in docs.groupby("key"):
        if len(g) < 2:
            continue
        g = g.sort_values("file")
        first = g.iloc[0]["file"]
        for r in g.iloc[1:].itertuples():
            out.append(_finding(r, "duplicate_xml", f"same key as file {first}", r.total_cents))
    return out


# ----------------------------------------------------------------------------
# Rules 4-11: money (authorized documents only)
# ----------------------------------------------------------------------------
def rule_duplicate_service(docs, **_):
    """One NF-e (the customer's invoice) is normally carried by ONE CT-e. A second authorized CT-e from the same
    carrier for the same NF-e is a double billing, unless the first was cancelled (then it is a replacement) or
    the new one is a value complement (it carries no NF-e)."""
    normal = docs[(docs["status_code"] == 100) & (docs["doc_type"] == 0)].drop_duplicates("key")
    rows = normal[["key", "file", "number", "carrier_cnpj", "carrier_name", "issued_at", "total_cents", "nfe_keys"]]
    exploded = rows.explode("nfe_keys").dropna(subset=["nfe_keys"])
    out, flagged = [], set()
    for (_, nfe), g in exploded.groupby(["carrier_cnpj", "nfe_keys"]):
        if g["key"].nunique() < 2:
            continue
        g = g.sort_values(["issued_at", "key"])
        first = g.iloc[0]
        for r in g.iloc[1:].itertuples():
            if r.key in flagged:
                continue
            flagged.add(r.key)
            out.append(_finding(r, "duplicate_service",
                                f"NF-e ...{nfe[-9:]} was already carried by CT-e {first['number']} ({first['issued_at']:%Y-%m-%d})",
                                r.total_cents))
    return out


def rule_cancelled(docs, **_):
    return [_finding(r, "cancelled_cte", "protocol status 101: must not be paid", r.total_cents)
            for r in docs[docs["status_code"] == 101].itertuples()]


def _authorized(docs):
    return docs[docs["status_code"] == 100]


def rule_total_mismatch(docs, settings: Settings, **_):
    out = []
    for r in _authorized(docs).itertuples():
        diff = r.total_cents - sum(r.components.values())
        if abs(diff) > settings.tolerance_cents:
            out.append(_finding(r, "total_mismatch",
                                f"total {_brl(r.total_cents)} vs components {_brl(sum(r.components.values()))}", diff))
    return out


def rule_freight_above_contract(docs, contract_rows, settings: Settings, **_):
    out = []
    for r in _authorized(docs).itertuples():
        if r.doc_type != 0 or r.file not in contract_rows.index or FREIGHT not in r.components:
            continue
        c = contract_rows.loc[r.file]
        freight, _gris = expected_charges(r.weight_kg, r.cargo_value_cents, c["rate_per_kg"], c["min_charge"], c["gris_pct"])
        diff = r.components[FREIGHT] - freight
        if diff > settings.tolerance_cents:
            out.append(_finding(r, "freight_above_contract",
                                f"freight {_brl(r.components[FREIGHT])} vs contract {_brl(freight)} (+{diff * 100 / freight:.1f}%)", diff))
    return out


def rule_gris_mismatch(docs, contract_rows, settings: Settings, **_):
    out = []
    for r in _authorized(docs).itertuples():
        if r.doc_type != 0 or r.file not in contract_rows.index or GRIS not in r.components:
            continue
        c = contract_rows.loc[r.file]
        _f, gris = expected_charges(r.weight_kg, r.cargo_value_cents, c["rate_per_kg"], c["min_charge"], c["gris_pct"])
        diff = r.components[GRIS] - gris
        if abs(diff) > settings.tolerance_cents:
            out.append(_finding(r, "gris_mismatch", f"GRIS {_brl(r.components[GRIS])} vs expected {_brl(gris)}", diff))
    return out


def rule_toll_above_contract(docs, contract_rows, settings: Settings, **_):
    out = []
    for r in _authorized(docs).itertuples():
        if r.doc_type != 0 or r.file not in contract_rows.index or TOLL not in r.components:
            continue
        allowed = round(float(contract_rows.loc[r.file]["toll"]) * 100)
        diff = r.components[TOLL] - allowed
        if diff > settings.tolerance_cents:
            out.append(_finding(r, "toll_above_contract", f"toll {_brl(r.components[TOLL])} vs contract {_brl(allowed)}", diff))
    return out


def rule_no_contract(docs, contract_rows, **_):
    out = []
    for r in _authorized(docs).itertuples():
        if r.doc_type == 0 and r.file not in contract_rows.index:
            out.append(_finding(r, "no_contract", f"no contract line for route {r.origin_mun} > {r.dest_mun} on {r.issued_at:%Y-%m-%d}",
                                r.total_cents))
    return out


def rule_orphan_complement(docs, **_):
    known = set(docs["key"])
    return [_finding(r, "orphan_complement", f"original CT-e ...{r.complement_of[-9:]} is not in the batch", r.total_cents)
            for r in _authorized(docs).itertuples() if r.doc_type == 1 and r.complement_of not in known]


ALL_RULES = [rule_invalid_key_dv, rule_key_field_mismatch, rule_duplicate_xml, rule_duplicate_service, rule_cancelled,
             rule_total_mismatch, rule_freight_above_contract, rule_gris_mismatch, rule_toll_above_contract,
             rule_no_contract, rule_orphan_complement]


def run_rules(docs: pd.DataFrame, contract: pd.DataFrame, settings: Settings = Settings()) -> pd.DataFrame:
    contract_rows = attach_contract(docs, contract)
    findings = []
    for rule in ALL_RULES:
        findings.extend(rule(docs, contract_rows=contract_rows, settings=settings))
    columns = ["file", "key", "number", "carrier", "issued", "rule", "severity", "detail", "amount_at_risk"]
    out = pd.DataFrame(findings, columns=columns)
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return (out.assign(_s=out["severity"].map(order)).sort_values(["_s", "amount_at_risk"], ascending=[True, False])
            .drop(columns="_s").reset_index(drop=True))
