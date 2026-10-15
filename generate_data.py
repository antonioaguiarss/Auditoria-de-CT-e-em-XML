"""
Creates the fictional batch: data/xml/*.xml, data/contract.csv and data/ground_truth.csv.

    python scripts/generate_data.py            (always the same result: fixed seed)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cte_audit.synthetic import generate  # noqa: E402

if __name__ == "__main__":
    info = generate(ROOT / "data")
    print(f"XML files written:            {info['xml_files']}")
    print(f"Planted problems (answer key): {info['planted']}")
    print(f"Legitimate look-alike traps:   {info['traps']}")
