"""
Access key ("chave de acesso") of Brazilian electronic fiscal documents (CT-e, NF-e).

The key has 44 digits. Reading from left to right:

    2   state code (cUF)                       e.g. 35 = Sao Paulo
    4   year and month of issue (AAMM)         e.g. 2603 = March 2026
    14  CNPJ of the issuer
    2   model (mod)                            57 = CT-e, 55 = NF-e
    3   series
    9   document number (nCT / nNF)
    1   emission type (tpEmis)
    8   random numeric code (cCT / cNF)
    1   check digit (cDV)                      calculated with modulo 11 over the 43 digits before it

Why this matters for an audit: the key is a fingerprint of the document. If a digit was typed wrong, or the
key was edited by hand, the check digit no longer matches. And if the numbers inside the key disagree with the
fields written in the XML body, someone changed one of them.

All data in this project is fictional.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

KEY_LENGTH = 44
_FIELDS = [("cUF", 2), ("aamm", 4), ("cnpj", 14), ("mod", 2), ("serie", 3), ("number", 9),
           ("tpEmis", 1), ("code", 8), ("dv", 1)]


def check_digit(first_43: str) -> int:
    """Modulo 11 check digit. Weights 2..9 repeat from the right-most digit to the left."""
    if not re.fullmatch(r"\d{43}", first_43):
        raise ValueError("the check digit is calculated over exactly 43 digits")
    total = 0
    weight = 2
    for digit in reversed(first_43):
        total += int(digit) * weight
        weight = 2 if weight == 9 else weight + 1
    remainder = total % 11
    return 0 if remainder in (0, 1) else 11 - remainder


def build_key(cuf: str, aamm: str, cnpj: str, model: str, serie: int, number: int, tp_emis: int, code: str) -> str:
    """Builds a valid 44-digit key from its parts."""
    body = f"{cuf}{aamm}{cnpj}{model}{serie:03d}{number:09d}{tp_emis}{code}"
    if len(body) != 43 or not body.isdigit():
        raise ValueError(f"parts do not make 43 digits: {body!r}")
    return body + str(check_digit(body))


def is_valid_key(key: str) -> bool:
    """True when the key has 44 digits and the last one is the correct check digit."""
    key = (key or "").strip()
    return bool(re.fullmatch(r"\d{44}", key)) and int(key[-1]) == check_digit(key[:43])


@dataclass(frozen=True)
class KeyParts:
    cuf: str
    aamm: str
    cnpj: str
    model: str
    serie: int
    number: int
    tp_emis: str
    code: str
    dv: int


def parse_key(key: str) -> KeyParts:
    """Splits a 44-digit key into its parts (does not validate the check digit)."""
    key = (key or "").strip()
    if not re.fullmatch(r"\d{44}", key):
        raise ValueError(f"not a 44-digit key: {key!r}")
    pos, parts = 0, {}
    for name, size in _FIELDS:
        parts[name] = key[pos:pos + size]
        pos += size
    return KeyParts(cuf=parts["cUF"], aamm=parts["aamm"], cnpj=parts["cnpj"], model=parts["mod"],
                    serie=int(parts["serie"]), number=int(parts["number"]), tp_emis=parts["tpEmis"],
                    code=parts["code"], dv=int(parts["dv"]))


def cnpj_check_digits(first_12: str) -> str:
    """The two check digits of a CNPJ (used only to make FICTIONAL CNPJs look well-formed)."""
    def calc(digits: str, weights: list[int]) -> int:
        r = sum(int(d) * w for d, w in zip(digits, weights)) % 11
        return 0 if r < 2 else 11 - r
    d1 = calc(first_12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = calc(first_12 + str(d1), [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return f"{d1}{d2}"
