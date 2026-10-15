"""
Reads one CT-e XML file into a flat dictionary.

Design choices worth knowing:
  * Money is read with Decimal and stored as integer CENTS. Floats would turn 0.1 + 0.2 into 0.30000000000000004
    and create fake differences in an audit.
  * A file that cannot be read never stops the batch. It raises ParseError, and the pipeline puts the file
    in quarantine with the reason, so someone can look at it.
  * The parser only READS. Judging (is this value right?) is the job of rules.py.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

NS = {"c": "http://www.portalfiscal.inf.br/cte"}


class ParseError(Exception):
    """The file is not a readable CT-e."""


def _find(node, path: str):
    found = node.find(path, NS)
    if found is None:
        raise ParseError(f"missing tag <{path.split('/')[-1].split(':')[-1]}>")
    return found


def _text(node, path: str) -> str:
    return (_find(node, path).text or "").strip()


def _cents(text: str) -> int:
    try:
        return int((Decimal(text) * 100).to_integral_value())
    except (InvalidOperation, ValueError) as exc:
        raise ParseError(f"invalid amount {text!r}") from exc


def parse_cte(path) -> dict:
    """Parses one file. Raises ParseError with a short reason if it cannot be used."""
    path = Path(path)
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ParseError(f"XML is not well-formed ({exc})") from exc
    except OSError as exc:
        raise ParseError(f"cannot open file ({exc})") from exc

    cte = root.find("c:CTe", NS)
    if cte is None and root.tag == f"{{{NS['c']}}}CTe":
        cte = root
    if cte is None:
        raise ParseError("not a CT-e (no <CTe> element)")
    inf = _find(cte, "c:infCte")
    ide, emit, v_prest = _find(inf, "c:ide"), _find(inf, "c:emit"), _find(inf, "c:vPrest")

    comps: dict[str, int] = {}
    for comp in v_prest.findall("c:Comp", NS):
        name = _text(comp, "c:xNome").upper()
        comps[name] = comps.get(name, 0) + _cents(_text(comp, "c:vComp"))

    nfe_keys = [(k.text or "").strip() for k in inf.findall("c:infCTeNorm/c:infDoc/c:infNFe/c:chave", NS)]
    carga = inf.find("c:infCTeNorm/c:infCarga", NS)
    weight, v_carga = 0.0, 0
    if carga is not None:
        v_carga = _cents(_text(carga, "c:vCarga"))
        quantities = carga.findall("c:infQ", NS)
        gross = [q for q in quantities if (q.findtext("c:tpMed", default="", namespaces=NS) or "").upper() == "PESO BRUTO"]
        if quantities:
            weight = float(_text((gross or quantities)[0], "c:qCarga"))
    comp_ref = inf.find("c:infCteComp/c:chCTe", NS)

    prot = root.find("c:protCTe/c:infProt", NS)
    try:
        issued = datetime.fromisoformat(_text(ide, "c:dhEmi"))
    except ValueError as exc:
        raise ParseError("invalid dhEmi") from exc

    return {
        "file": path.name,
        "key": inf.get("Id", "").removeprefix("CTe"),
        "uf_code": _text(ide, "c:cUF"),
        "model": _text(ide, "c:mod"),
        "serie": _text(ide, "c:serie"),
        "number": _text(ide, "c:nCT"),
        "issued_at": issued.replace(tzinfo=None),
        "doc_type": int(_text(ide, "c:tpCTe")),          # 0 = normal, 1 = value complement
        "origin_mun": _text(ide, "c:cMunIni"),
        "dest_mun": _text(ide, "c:cMunFim"),
        "carrier_cnpj": _text(emit, "c:CNPJ"),
        "carrier_name": _text(emit, "c:xNome"),
        "total_cents": _cents(_text(v_prest, "c:vTPrest")),
        "components": comps,
        "cargo_value_cents": v_carga,
        "weight_kg": weight,
        "nfe_keys": nfe_keys,
        "complement_of": (comp_ref.text or "").strip() if comp_ref is not None else "",
        "status_code": int(prot.findtext("c:cStat", default="0", namespaces=NS)) if prot is not None else 0,
        "protocol_key": (prot.findtext("c:chCTe", default="", namespaces=NS) if prot is not None else "").strip(),
    }
