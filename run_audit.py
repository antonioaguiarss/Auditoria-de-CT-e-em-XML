"""
Audits a folder of CT-e XML files against a contract table.

    python scripts/run_audit.py                               (uses the fictional batch in data/)
    python scripts/run_audit.py --xml path/to/xmls --contract path/to/contract.csv

Writes to output/: findings.csv, summary_by_rule.csv, quarantine.csv, audit_report.md
If data/ground_truth.csv exists (simulated data only), also writes evaluation.csv.
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cte_audit import Settings, audit, evaluate, summarize, write_report  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--xml", default=str(ROOT / "data" / "xml"))
parser.add_argument("--contract", default=str(ROOT / "data" / "contract.csv"))
parser.add_argument("--truth", default=str(ROOT / "data" / "ground_truth.csv"))
parser.add_argument("--tolerance-cents", type=int, default=5, help="differences up to this are rounding (default 5)")
parser.add_argument("--out", default=str(ROOT / "output"))
args = parser.parse_args()

out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
result = audit(args.xml, args.contract, Settings(tolerance_cents=args.tolerance_cents))
summary = summarize(result)

result.findings.to_csv(out / "findings.csv", index=False, encoding="utf-8-sig")
summary["by_rule"].to_csv(out / "summary_by_rule.csv", index=False, encoding="utf-8-sig")
result.quarantine.to_csv(out / "quarantine.csv", index=False, encoding="utf-8-sig")
write_report(result, summary, out / "audit_report.md")

brl = lambda x: f"R$ {x:,.2f}"
print(f"Files read: {summary['files_read']:,}   quarantined: {summary['files_quarantined']}")
print(f"Value audited: {brl(summary['total_value_audited'])}   documents flagged: {summary['documents_flagged']}")
print(summary["by_category"].to_string(index=False))
print()
print(summary["by_rule"][["rule", "severity", "documents", "amount"]].to_string(index=False))

if Path(args.truth).exists():
    truth = pd.read_csv(args.truth)
    ev = evaluate(result, truth)
    ev.to_csv(out / "evaluation.csv", index=False, encoding="utf-8-sig")
    print("\nEvaluation against the answer key:")
    print(ev.to_string(index=False))
