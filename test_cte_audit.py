import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cte_audit import RULES, audit, evaluate  # noqa: E402
from cte_audit.keys import build_key, check_digit, is_valid_key, parse_key  # noqa: E402
from cte_audit.parser import ParseError, parse_cte  # noqa: E402
from cte_audit.rules import expected_charges  # noqa: E402
from cte_audit.synthetic import generate  # noqa: E402


# ---------- keys ----------
def test_check_digit_hand_computed():
    # 42 zeros + "1": only the right-most digit counts, weight 2 -> sum 2 -> 11 - 2 = 9
    assert check_digit("0" * 42 + "1") == 9
    # sum 0 -> remainder 0 -> digit 0
    assert check_digit("0" * 43) == 0
    # 42 zeros followed by 5 would give 10 -> remainder 10 -> 1
    assert check_digit("0" * 42 + "5") == 1


def test_build_and_parse_roundtrip():
    key = build_key("35", "2603", "12345678000195", "57", 1, 42, 1, "12345678")
    assert len(key) == 44 and is_valid_key(key)
    p = parse_key(key)
    assert (p.cuf, p.aamm, p.model, p.serie, p.number) == ("35", "2603", "57", 1, 42)


def test_one_wrong_digit_breaks_key():
    key = build_key("35", "2603", "12345678000195", "57", 1, 42, 1, "12345678")
    bad = key[:10] + str((int(key[10]) + 1) % 10) + key[11:]
    assert not is_valid_key(bad)
    assert not is_valid_key(key[:-1])


def test_expected_charges_minimum_wins():
    freight, gris = expected_charges(10, 100_000, 1.0, 50.0, 0.003)
    assert freight == 5000 and gris == 300
    freight, _ = expected_charges(100, 100_000, 1.0, 50.0, 0.003)
    assert freight == 10000


# ---------- parser ----------
def test_parser_rejects_bad_files(tmp_path):
    (tmp_path / "empty.xml").write_text("")
    (tmp_path / "wrong.xml").write_text("<html/>")
    for name in ("empty.xml", "wrong.xml"):
        with pytest.raises(ParseError):
            parse_cte(tmp_path / name)


# ---------- end to end on a small batch ----------
@pytest.fixture(scope="module")
def batch(tmp_path_factory):
    d = tmp_path_factory.mktemp("batch")
    info = generate(d, n_base=200, seed=11)
    result = audit(d / "xml", d / "contract.csv")
    truth = pd.read_csv(d / "ground_truth.csv")
    return info, result, truth


def test_every_planted_problem_found_no_false_alarms(batch):
    _, result, truth = batch
    ev = evaluate(result, truth)
    rules = ev[ev["rule"].isin(list(RULES) + ["quarantine"])]
    assert (rules["missed"] == 0).all()
    assert (rules["false_alarms"] == 0).all()


def test_traps_are_not_flagged(batch):
    _, result, truth = batch
    traps = set(truth.loc[truth["expected_rule"] == "none", "file"])
    assert traps and not (traps & set(result.findings["file"]))


def test_rounding_difference_is_tolerated_but_not_a_big_one(batch):
    _, result, _ = batch
    f = result.findings[result.findings["rule"] == "freight_above_contract"]
    assert (f["amount_at_risk"] > 0.05).all()


def test_quarantine_has_reasons(batch):
    _, result, _ = batch
    assert len(result.quarantine) >= 1 and result.quarantine["reason"].str.len().gt(0).all()


def test_same_seed_same_data(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate(a, n_base=60, seed=5)
    generate(b, n_base=60, seed=5)
    assert sorted(p.name for p in (a / "xml").glob("*")) == sorted(p.name for p in (b / "xml").glob("*"))
