# Auditoria de CT-e em XML

Audita uma pasta de **CT-e** (Conhecimento de Transporte Eletrônico) **antes de pagar** a transportadora.
Lê os XML, confere o próprio documento (a chave de acesso de 44 dígitos é verdadeira? é uma cópia? foi cancelado?) e depois confere o dinheiro (a cobrança bate com o contrato?).

> Todos os dados são **fictícios** (transportadoras e CNPJs inventados). O layout do XML é uma **versão simplificada** do CT-e real, suficiente para mostrar a lógica da auditoria. Não consulta a SEFAZ.

## O que há de diferente de uma auditoria em planilha

A maioria das auditorias compara fatura × tabela. Aqui a entrada é o **XML bruto** emitido pela transportadora, o que permite checagens que planilha não faz:

| Grupo | Regra | O que pega |
|---|---|---|
| Não dá para verificar | `invalid_key_dv` | Chave cujo dígito verificador (módulo 11) está errado: erro de digitação ou chave editada à mão |
| | `key_field_mismatch` | Números dentro da chave (UF, mês, CNPJ, série, número) diferentes do corpo do XML |
| | `no_contract` | Não existe contrato para a transportadora, rota e data |
| Pagamento que não deveria ocorrer | `duplicate_xml` | Mesmo CT-e enviado em mais de um arquivo |
| | `duplicate_service` | CT-e *novo* para uma NF-e que outro CT-e autorizado já transportou (cobrança em duplicidade) |
| | `cancelled_cte` | CT-e cancelado (status 101) no lote |
| | `orphan_complement` | CT-e de complemento cujo original não está no lote |
| Cobrança acima do contrato | `total_mismatch` | Total diferente da soma dos componentes |
| | `freight_above_contract` | Frete acima de `max(peso × tarifa, mínimo)` |
| | `gris_mismatch` | GRIS diferente de % do contrato × valor da carga |
| | `toll_above_contract` | Pedágio acima do contrato |

Arquivos ilegíveis (vazios, cortados, formato errado) vão para uma **quarentena** com o motivo, sem parar o lote.

## Decisões de projeto

- **Dinheiro em centavos inteiros.** Decimais em ponto flutuante criam diferenças falsas (`0.1 + 0.2`). Diferenças até R$ 0,05 são arredondamento (ajustável com `--tolerance-cents`).
- **Sem contar em dobro.** Um documento pode quebrar várias regras. O valor do resumo conta cada documento uma vez por categoria, pelo maior valor.
- **Armadilhas de propósito.** O lote fictício tem casos legítimos parecidos que *não* podem ser marcados: frete com 2–3 centavos de diferença, CT-e de complemento verdadeiro e substituição de um CT-e cancelado (só o cancelado é marcado).
- **O parser só lê, as regras só julgam.**

## Resultado no lote fictício

916 arquivos XML (semente fixa), R$ 1.374.275,67 auditados, 145 documentos sinalizados:

| Categoria | Documentos | Valor |
|---|---|---|
| Pagamento que não deveria ocorrer | 46 | R$ 66.858,56 |
| Não dá para verificar | 32 | R$ 45.537,24 |
| Cobrança acima do contrato | 67 | R$ 8.010,36 |

O gerador guarda um gabarito (`data/ground_truth.csv`), então a auditoria é corrigida: os 148 problemas plantados foram achados, com 0 falso alarme e 0 das 55 armadilhas marcadas.
**Sendo honesto:** as regras e o gerador foram escritos pela mesma pessoa, então 100% prova que o código faz o que foi desenhado, não que pegaria todo caso real. Com dados reais, será preciso ajustar as regras.

## Como rodar

```bash
pip install -r requirements.txt
python scripts/generate_data.py      # cria data/xml, data/contract.csv, data/ground_truth.csv
python scripts/run_audit.py          # cria output/ (findings.csv, summary_by_rule.csv, quarantine.csv, audit_report.md, evaluation.csv)
pytest                               # 10 testes
```

Para auditar seus arquivos: `python scripts/run_audit.py --xml minha_pasta --contract meu_contrato.csv`
(colunas do contrato: `carrier_cnpj, origin_mun, dest_mun, rate_per_kg, min_charge, toll, gris_pct, valid_from, valid_to`).

## Estrutura

```
cte_audit/keys.py       chave de acesso: dígito verificador, montar, separar
cte_audit/parser.py     um XML -> um registro simples (dinheiro em centavos)
cte_audit/rules.py      as 11 regras + busca do contrato pela data de vigência
cte_audit/pipeline.py   leitura com quarentena, auditoria, resumo, avaliação, relatório
cte_audit/synthetic.py  lote fictício + gabarito
scripts/                generate_data.py, run_audit.py
tests/                  dígitos verificadores calculados à mão, parser, cada regra ponta a ponta
```

## Limites

Layout simplificado; sem verificação de assinatura digital nem situação na SEFAZ; uma única origem; contrato modelado como peso × tarifa com mínimo, GRIS % e pedágio fixo.
