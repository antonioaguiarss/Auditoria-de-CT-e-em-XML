# CT-e audit report

- Files read: **913** (+ 3 in quarantine)
- Total value of the CT-e audited: **R$ 1,374,275.67**
- Documents with at least one finding: **145**

## Amounts by category (a document counts once per category)

| Category | Documents | Amount |
|---|---|---|
| Cannot be verified | 32 | R$ 45,537.24 |
| Overcharge vs contract | 67 | R$ 8,010.36 |
| Payment that should not happen | 46 | R$ 66,858.56 |

## Findings by rule

| Rule | Severity | Documents | Amount | What it checks |
|---|---|---|---|---|
| `invalid_key_dv` | HIGH | 12 | R$ 13,222.15 | Access key check digit is wrong |
| `key_field_mismatch` | HIGH | 10 | R$ 18,142.77 | Numbers inside the key disagree with the XML body |
| `duplicate_xml` | HIGH | 10 | R$ 21,365.48 | Same CT-e received in more than one file |
| `duplicate_service` | HIGH | 14 | R$ 10,216.58 | New CT-e for an NF-e that another CT-e already carried |
| `cancelled_cte` | MEDIUM | 18 | R$ 35,018.63 | Cancelled CT-e in the batch |
| `total_mismatch` | MEDIUM | 10 | R$ 285.39 | Total is not the sum of the components |
| `freight_above_contract` | MEDIUM | 35 | R$ 5,752.35 | Freight above weight x rate (or minimum charge) |
| `gris_mismatch` | LOW | 10 | R$ 1,426.68 | Risk-management fee differs from contract % x cargo value |
| `toll_above_contract` | MEDIUM | 12 | R$ 545.94 | Toll above what the contract allows |
| `no_contract` | MEDIUM | 10 | R$ 14,172.32 | No contract for this carrier on this route and date |
| `orphan_complement` | HIGH | 4 | R$ 257.87 | Complement CT-e whose original is not in the batch |

## Top 10 findings by amount

| File | Carrier | Rule | Detail | Amount |
|---|---|---|---|---|
| `...10761295657219-cte.xml` | Atlantico Logistica Ltda | `duplicate_xml` | same key as file 35260327505051000121570010000210761295657219-cte.xml | R$ 12,452.78 |
| `...11451215766951-cte.xml` | Atlantico Logistica Ltda | `cancelled_cte` | protocol status 101: must not be paid | R$ 9,329.82 |
| `...20191181329890-cte.xml` | Translog Express Transportes Ltda | `no_contract` | no contract line for route 3509502 > 2611606 on 2026-03-20 | R$ 5,349.90 |
| `...26161837613859-cte.xml` | Veloz Cargas Ltda | `cancelled_cte` | protocol status 101: must not be paid | R$ 4,398.38 |
| `...11341412644347-cte.xml` | Atlantico Logistica Ltda | `key_field_mismatch` | number: key 21134, body 21183 | R$ 4,360.35 |
| `...25181351792500-cte.xml` | Veloz Cargas Ltda | `key_field_mismatch` | number: key 22518, body 22540 | R$ 3,511.09 |
| `...10401993494196-cte.xml` | Atlantico Logistica Ltda | `key_field_mismatch` | number: key 21040, body 21059 | R$ 3,509.12 |
| `...41851821126227-cte.xml` | Norte Sul Fretes Ltda | `cancelled_cte` | protocol status 101: must not be paid | R$ 3,503.90 |
| `...20201286497991-cte.xml` | Translog Express Transportes Ltda | `no_contract` | no contract line for route 3509502 > 2927408 on 2026-04-01 | R$ 3,294.45 |
| `...25511084464702-cte.xml` | Veloz Cargas Ltda | `invalid_key_dv` | check digit is 6, should be 2 | R$ 3,252.87 |

## Quarantine (files that could not be read)

| File | Reason |
|---|---|
| `malformed_empty.xml` | XML is not well-formed (no element found: line 1, column 0) |
| `malformed_not_a_cte.xml` | not a CT-e (no <CTe> element) |
| `malformed_truncated.xml` | XML is not well-formed (unclosed token: line 7, column 23) |
