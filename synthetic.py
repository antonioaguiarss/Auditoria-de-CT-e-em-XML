"""
Generates FICTIONAL CT-e (electronic freight document) XML files, a contract table and an answer key.

The XML layout is SIMPLIFIED and inspired by the Brazilian CT-e layout (same tag names for the parts used
here, same 44-digit access key with check digit). It is not a real fiscal document, nothing here can be
authorized or queried at the tax authority, and every company, CNPJ and number is invented. CNPJs are
random; any similarity with a real company is a coincidence.

What gets planted (the answer key lists each one):

    invalid_key_dv           access key with a wrong check digit
    key_field_mismatch       numbers inside the key disagree with the XML body
    duplicate_xml            the same CT-e file received twice
    duplicate_service        a NEW CT-e number for an NF-e that another CT-e already transported
    cancelled_cte            CT-e with protocol status 101 (cancelled) in the batch
    total_mismatch           total of the service is not the sum of its components
    freight_above_contract   freight component above the contract (weight x rate, or minimum charge)
    gris_mismatch            risk-management fee different from contract % x cargo value
    toll_above_contract      toll above what the contract allows
    no_contract              route the carrier has no contract for
    orphan_complement        complement CT-e pointing to an original that is not in the batch
    quarantine               files that cannot be read (truncated, empty, wrong document type)

And traps, which must NOT be flagged: freight off by a few cents (rounding), legitimate complement CT-e,
and a cancelled CT-e whose replacement carries the same NF-e (the replacement is not a duplicate).
"""
from __future__ import annotations

import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from .keys import build_key, cnpj_check_digits
from .rules import expected_charges

TZ = "-03:00"
_ROOT = "58210437"
OUR_CNPJ = _ROOT + "0001" + cnpj_check_digits(_ROOT + "0001")   # the (fictional) shipper that issues the NF-e

CARRIERS = [  # name, price factor, gris %
    ("TRANSLOG EXPRESS TRANSPORTES LTDA", 1.00, 0.0030),
    ("RODOFACIL TRANSPORTES LTDA", 0.95, 0.0030),
    ("VELOZ CARGAS LTDA", 1.10, 0.0025),
    ("ATLANTICO LOGISTICA LTDA", 1.05, 0.0030),
    ("NORTE SUL FRETES LTDA", 0.92, 0.0030),
]
CARRIER_WEIGHTS = [0.28, 0.24, 0.18, 0.16, 0.14]

DESTINATIONS = [  # IBGE municipality code, name, state, state code, km from Campinas, toll R$ (simplified)
    ("3550308", "SAO PAULO", "SP", "35", 100, 24.80),
    ("3304557", "RIO DE JANEIRO", "RJ", "33", 500, 61.40),
    ("3106200", "BELO HORIZONTE", "MG", "31", 590, 38.70),
    ("4106902", "CURITIBA", "PR", "41", 410, 52.10),
    ("4314902", "PORTO ALEGRE", "RS", "43", 1100, 0.0),
    ("2927408", "SALVADOR", "BA", "29", 1960, 0.0),
    ("2611606", "RECIFE", "PE", "26", 2650, 0.0),
    ("5208707", "GOIANIA", "GO", "52", 930, 0.0),
]
ORIGIN = ("3509502", "CAMPINAS", "SP", "35")
CARRIER_ROUTES = [  # which destinations (indexes) each carrier has in its contract
    [0, 1, 2, 3, 4], [0, 1, 2, 3, 7], [1, 2, 4, 5, 6, 7], [2, 3, 4, 5, 6], [0, 3, 5, 6, 7],
]
CARGO = ["AUTOPECAS", "FERRAMENTAS ELETRICAS", "MATERIAL ELETRICO", "EMBALAGENS PLASTICAS", "PECAS DE REPOSICAO"]

# How many of each anomaly at the default size (850 base documents)
PLAN = {"invalid_key_dv": 12, "key_field_mismatch": 10, "total_mismatch": 10, "freight_above_contract": 35,
        "gris_mismatch": 10, "toll_above_contract": 12, "cancelled_cte": 8, "replaced_pairs": 10,
        "duplicate_xml": 10, "duplicate_service": 14, "no_contract": 10, "complement_legit": 15,
        "orphan_complement": 4, "rounding_trap": 30, "malformed": 3}


def _fake_cnpj(rng: random.Random) -> str:
    root = f"{rng.randint(10_000_000, 99_999_999)}0001"
    return root + cnpj_check_digits(root)


def make_contract(rng: random.Random):
    carriers = []
    for name, factor, gris in CARRIERS:
        carriers.append(dict(name=name, cnpj=_fake_cnpj(rng), factor=factor, gris=gris))
    rows = []
    for c, route_idx in zip(carriers, CARRIER_ROUTES):
        for i in route_idx:
            code, city, uf, _, km, toll = DESTINATIONS[i]
            rows.append(dict(carrier_cnpj=c["cnpj"], carrier_name=c["name"], origin_mun=ORIGIN[0], dest_mun=code,
                             dest_city=city, dest_uf=uf,
                             rate_per_kg=round((0.20 + 0.0016 * km) * c["factor"], 4),
                             min_charge=round((60 + 0.12 * km) * c["factor"], 2),
                             toll=toll, gris_pct=c["gris"], valid_from="2026-01-01", valid_to="2026-12-31"))
    return carriers, rows


def _cents(x: float) -> int:
    return int(round(x * 100))


def _money(c: int) -> str:
    return f"{c / 100:.2f}"


def _prot(rng: random.Random) -> str:
    return "135" + "".join(str(rng.randint(0, 9)) for _ in range(12))


def render_cte(d: dict) -> str:
    """Writes one simplified CT-e XML (with the authorization protocol) as text."""
    comps = "".join(f"<Comp><xNome>{escape(n)}</xNome><vComp>{_money(v)}</vComp></Comp>" for n, v in d["comps"])
    if d["tp_cte"] == 0:
        body = (f"<infCTeNorm><infCarga><vCarga>{_money(d['v_carga'])}</vCarga><proPred>{escape(d['cargo'])}</proPred>"
                f"<infQ><cUnid>01</cUnid><tpMed>PESO BRUTO</tpMed><qCarga>{d['weight']:.4f}</qCarga></infQ></infCarga>"
                f"<infDoc>{''.join(f'<infNFe><chave>{k}</chave></infNFe>' for k in d['nfe_keys'])}</infDoc></infCTeNorm>")
    else:
        body = f"<infCteComp><chCTe>{d['ch_comp']}</chCTe></infCteComp>"
    stat = ("100", "Autorizado o uso do CT-e") if d["c_stat"] == 100 else ("101", "Cancelamento de CT-e homologado")
    cfop = "5353" if d["uf_ini"] == d["uf_fim"] else "6353"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!-- FICTITIOUS SAMPLE: simplified layout inspired by the CT-e. Not a real fiscal document. -->\n"
        '<cteProc xmlns="http://www.portalfiscal.inf.br/cte" versao="4.00">\n'
        f'<CTe><infCte Id="CTe{d["id_key"]}" versao="4.00">\n'
        f"<ide><cUF>{d['xml_cuf']}</cUF><CFOP>{cfop}</CFOP><natOp>PRESTACAO DE SERVICO DE TRANSPORTE</natOp><mod>57</mod>"
        f"<serie>{d['serie']}</serie><nCT>{d['xml_nct']}</nCT><dhEmi>{d['dh_emi']:%Y-%m-%dT%H:%M:%S}{TZ}</dhEmi>"
        f"<tpCTe>{d['tp_cte']}</tpCTe><cMunIni>{d['mun_ini']}</cMunIni><xMunIni>{d['x_ini']}</xMunIni><UFIni>{d['uf_ini']}</UFIni>"
        f"<cMunFim>{d['mun_fim']}</cMunFim><xMunFim>{d['x_fim']}</xMunFim><UFFim>{d['uf_fim']}</UFFim></ide>\n"
        f"<emit><CNPJ>{d['xml_cnpj']}</CNPJ><xNome>{escape(d['carrier_name'])}</xNome></emit>\n"
        f"<vPrest><vTPrest>{_money(d['v_tprest'])}</vTPrest><vRec>{_money(d['v_tprest'])}</vRec>{comps}</vPrest>\n"
        f"{body}</infCte></CTe>\n"
        f'<protCTe versao="4.00"><infProt><tpAmb>1</tpAmb><chCTe>{d["prot_key"]}</chCTe>'
        f"<dhRecbto>{(d['dh_emi'] + timedelta(minutes=3)):%Y-%m-%dT%H:%M:%S}{TZ}</dhRecbto><nProt>{d['nprot']}</nProt>"
        f"<cStat>{stat[0]}</cStat><xMotivo>{stat[1]}</xMotivo></infProt></protCTe>\n"
        "</cteProc>\n")


def generate(out_dir, n_base: int = 850, seed: int = 3) -> dict:
    """Creates out_dir/xml/*.xml, out_dir/contract.csv and out_dir/ground_truth.csv."""
    rng = random.Random(seed)
    out = Path(out_dir)
    xml_dir = out / "xml"
    xml_dir.mkdir(parents=True, exist_ok=True)
    for old in xml_dir.glob("*.xml"):
        old.unlink()

    carriers, contract = make_contract(rng)
    contract_by = {(r["carrier_cnpj"], r["dest_mun"]): r for r in contract}
    scale = n_base / 850
    n = {k: max(2, round(v * scale)) for k, v in PLAN.items()}
    counter = {c["cnpj"]: rng.randint(2000, 30000) for c in carriers}
    nfe_counter = [rng.randint(5000, 90000)]
    truth = []  # (file, expected_rule, note)

    def nfe_key(day: date) -> str:
        nfe_counter[0] += rng.randint(1, 4)
        return build_key("35", f"{day:%y%m}", OUR_CNPJ, "55", 1, nfe_counter[0], 1, f"{rng.randint(0, 99_999_999):08d}")

    def seal(d: dict) -> dict:
        """Number the document, build its access key and the fields that normally repeat the key."""
        c = next(x for x in carriers if x["cnpj"] == d["carrier_cnpj"])
        counter[c["cnpj"]] += 1
        d["nct"] = counter[c["cnpj"]]
        d["serie"] = 1
        d["code"] = f"{rng.randint(0, 99_999_999):08d}"
        d["chave"] = build_key("35", f"{d['dh_emi']:%y%m}", d["carrier_cnpj"], "57", 1, d["nct"], 1, d["code"])
        d.update(id_key=d["chave"], prot_key=d["chave"], xml_cuf="35", xml_nct=d["nct"], xml_cnpj=d["carrier_cnpj"],
                 nprot=_prot(rng), c_stat=d.get("c_stat", 100), carrier_name=c["name"])
        d["file"] = f"{d['chave']}-cte.xml"
        return d

    def retotal(d: dict):
        d["v_tprest"] = sum(v for _, v in d["comps"])

    def base_doc() -> dict:
        ci = rng.choices(range(len(carriers)), weights=CARRIER_WEIGHTS)[0]
        c = carriers[ci]
        code, city, uf, cuf, km, toll = DESTINATIONS[rng.choice(CARRIER_ROUTES[ci])]
        day = date(2026, 1, 5) + timedelta(days=rng.randint(0, 255))
        row = contract_by[(c["cnpj"], code)]
        weight = round(min(max(rng.lognormvariate(6.3, 0.9), 50), 9000), 1)
        v_carga = _cents(min(max(rng.lognormvariate(10.3, 0.7), 3000), 400000))
        freight, gris = expected_charges(weight, v_carga, row["rate_per_kg"], row["min_charge"], row["gris_pct"])
        comps = [("FRETE PESO", freight), ("GRIS", gris)] + ([("PEDAGIO", _cents(toll))] if toll else [])
        d = dict(carrier_cnpj=c["cnpj"], dh_emi=datetime(day.year, day.month, day.day, rng.randint(7, 18), rng.randint(0, 59)),
                 tp_cte=0, mun_ini=ORIGIN[0], x_ini=ORIGIN[1], uf_ini=ORIGIN[2], mun_fim=code, x_fim=city, uf_fim=uf,
                 weight=weight, v_carga=v_carga, cargo=rng.choice(CARGO), comps=comps,
                 nfe_keys=[nfe_key(day) for _ in range(rng.choice([1, 1, 1, 2]))], route_km=km)
        retotal(d)
        return d

    # ---- 1) base documents, numbered in date order per carrier
    drafts = sorted((base_doc() for _ in range(n_base)), key=lambda x: x["dh_emi"])
    docs = [seal(d) for d in drafts]
    order = list(range(len(docs)))
    rng.shuffle(order)

    def take(k):
        picked, rest = order[:k], order[k:]
        order[:] = rest
        return [docs[i] for i in picked]

    extra, copies = [], []   # extra documents, and duplicate files (same content, other name)

    # ---- 2) anomalies that change an existing document
    for d in take(n["invalid_key_dv"]):
        bad = (int(d["chave"][-1]) + rng.randint(1, 9)) % 10
        key = d["chave"][:-1] + str(bad)
        d["id_key"] = d["prot_key"] = key
        truth.append((d["file"], "invalid_key_dv", "check digit changed"))
    for d in take(n["key_field_mismatch"]):
        if rng.random() < 0.5:
            d["xml_nct"] = d["nct"] + rng.randint(1, 50)
            note = "nCT in the body differs from the key"
        else:
            d["dh_emi"] = d["dh_emi"] + timedelta(days=40)
            note = "issue date in the body is in a different month than the key"
        truth.append((d["file"], "key_field_mismatch", note))
    for d in take(n["total_mismatch"]):
        d["v_tprest"] += rng.choice([-1, 1]) * rng.randint(500, 9000)
        truth.append((d["file"], "total_mismatch", "total differs from the sum of components"))
    for d in take(n["freight_above_contract"]):
        extra_c = round(d["comps"][0][1] * rng.uniform(0.04, 0.20))
        d["comps"][0] = ("FRETE PESO", d["comps"][0][1] + max(extra_c, 300))
        retotal(d)
        truth.append((d["file"], "freight_above_contract", "freight 4% to 20% above contract"))
    for d in take(n["gris_mismatch"]):
        i = next(k for k, (nm, _) in enumerate(d["comps"]) if nm == "GRIS")
        d["comps"][i] = ("GRIS", int(d["comps"][i][1] * rng.choice([0.5, 2.0, 3.0])) + 200)
        retotal(d)
        truth.append((d["file"], "gris_mismatch", "GRIS different from contract %"))
    for d in take(n["toll_above_contract"]):
        i = next((k for k, (nm, _) in enumerate(d["comps"]) if nm == "PEDAGIO"), None)
        add = rng.randint(1500, 9000)
        if i is None:
            d["comps"].append(("PEDAGIO", add))
        else:
            d["comps"][i] = ("PEDAGIO", d["comps"][i][1] + add)
        retotal(d)
        truth.append((d["file"], "toll_above_contract", "toll above contract"))
    for d in take(n["cancelled_cte"]):
        d["c_stat"] = 101
        truth.append((d["file"], "cancelled_cte", "cancelled, standalone"))
    for d in take(n["rounding_trap"]):
        d["comps"][0] = ("FRETE PESO", d["comps"][0][1] + rng.choice([-3, -2, 2, 3]))
        retotal(d)
        truth.append((d["file"], "none", "trap: freight off by a few cents (rounding)"))

    # ---- 3) documents that must stay untouched, used as the "original" of other cases
    for d in take(n["replaced_pairs"]):
        d["c_stat"] = 101
        truth.append((d["file"], "cancelled_cte", "cancelled, replaced by a new CT-e"))
        new = dict(d, dh_emi=d["dh_emi"] + timedelta(days=rng.randint(1, 6)), c_stat=100)
        extra.append(seal(new))
        truth.append((new["file"], "none", "trap: replacement of a cancelled CT-e (same NF-e, not a duplicate)"))
    for d in take(n["duplicate_xml"]):
        copies.append((d, f"copy_{d['file']}"))
        truth.append((f"copy_{d['file']}", "duplicate_xml", f"same file as {d['file']}"))
    for d in take(n["duplicate_service"]):
        new = dict(d, dh_emi=d["dh_emi"] + timedelta(days=rng.randint(2, 12)))
        extra.append(seal(new))
        truth.append((new["file"], "duplicate_service", f"same NF-e as CT-e {d['nct']}"))
    for d in take(n["complement_legit"]):
        c = rng.choice([x for x in [1500, 2500, 4000, 6500, 9000]])
        comp = dict(carrier_cnpj=d["carrier_cnpj"], dh_emi=d["dh_emi"] + timedelta(days=rng.randint(1, 20)), tp_cte=1,
                    mun_ini=d["mun_ini"], x_ini=d["x_ini"], uf_ini=d["uf_ini"], mun_fim=d["mun_fim"], x_fim=d["x_fim"],
                    uf_fim=d["uf_fim"], weight=0.0, v_carga=0, cargo="", nfe_keys=[], ch_comp=d["chave"],
                    comps=[("COMPLEMENTO DE VALORES", c)])
        retotal(comp)
        extra.append(seal(comp))
        truth.append((comp["file"], "none", "trap: legitimate complement CT-e"))
    for _ in range(n["orphan_complement"]):
        d = docs[rng.randrange(len(docs))]
        ghost = build_key("35", f"{d['dh_emi']:%y%m}", d["carrier_cnpj"], "57", 1, rng.randint(900000, 999999), 1,
                          f"{rng.randint(0, 99_999_999):08d}")
        comp = dict(carrier_cnpj=d["carrier_cnpj"], dh_emi=d["dh_emi"] + timedelta(days=3), tp_cte=1,
                    mun_ini=d["mun_ini"], x_ini=d["x_ini"], uf_ini=d["uf_ini"], mun_fim=d["mun_fim"], x_fim=d["x_fim"],
                    uf_fim=d["uf_fim"], weight=0.0, v_carga=0, cargo="", nfe_keys=[], ch_comp=ghost,
                    comps=[("COMPLEMENTO DE VALORES", rng.randint(2000, 8000))])
        retotal(comp)
        extra.append(seal(comp))
        truth.append((comp["file"], "orphan_complement", "original CT-e is not in the batch"))

    # ---- 4) routes the carrier has no contract for
    for _ in range(n["no_contract"]):
        ci = rng.randrange(len(carriers))
        c = carriers[ci]
        missing = [i for i in range(len(DESTINATIONS)) if i not in CARRIER_ROUTES[ci]]
        code, city, uf, cuf, km, toll = DESTINATIONS[rng.choice(missing)]
        day = date(2026, 1, 5) + timedelta(days=rng.randint(0, 255))
        weight = round(min(max(rng.lognormvariate(6.3, 0.9), 50), 9000), 1)
        v_carga = _cents(min(max(rng.lognormvariate(10.3, 0.7), 3000), 400000))
        freight = max(_cents(weight * (0.20 + 0.0016 * km) * 1.3), _cents(80 + 0.15 * km))
        d = dict(carrier_cnpj=c["cnpj"], dh_emi=datetime(day.year, day.month, day.day, 9, rng.randint(0, 59)), tp_cte=0,
                 mun_ini=ORIGIN[0], x_ini=ORIGIN[1], uf_ini=ORIGIN[2], mun_fim=code, x_fim=city, uf_fim=uf, weight=weight,
                 v_carga=v_carga, cargo=rng.choice(CARGO), comps=[("FRETE PESO", freight), ("GRIS", round(v_carga * 0.003))],
                 nfe_keys=[nfe_key(day)])
        retotal(d)
        extra.append(seal(d))
        truth.append((d["file"], "no_contract", "route not in the carrier's contract"))

    # ---- 5) write everything
    for d in docs + extra:
        (xml_dir / d["file"]).write_text(render_cte(d), encoding="utf-8")
    for orig, name in copies:
        (xml_dir / name).write_text((xml_dir / orig["file"]).read_text(encoding="utf-8"), encoding="utf-8")
    good = (xml_dir / docs[0]["file"]).read_text(encoding="utf-8")
    bad_files = {"malformed_truncated.xml": good[: len(good) // 2], "malformed_empty.xml": "",
                 "malformed_not_a_cte.xml": '<?xml version="1.0"?><nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe/></nfeProc>'}
    for name, text in list(bad_files.items())[: max(3, n["malformed"])]:
        (xml_dir / name).write_text(text, encoding="utf-8")
        truth.append((name, "quarantine", "file cannot be read as a CT-e"))

    with open(out / "contract.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(contract[0]))
        w.writeheader()
        w.writerows(contract)
    with open(out / "ground_truth.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "expected_rule", "note"])
        w.writerows(sorted(truth))
    total_files = len(list(xml_dir.glob("*.xml")))
    return {"xml_files": total_files, "base_documents": n_base, "planted": sum(1 for t in truth if t[1] not in ("none",)),
            "traps": sum(1 for t in truth if t[1] == "none")}
