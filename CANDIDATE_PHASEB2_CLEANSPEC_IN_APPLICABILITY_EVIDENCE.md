# SCOL Config Phase B2 · CleanSpec IN Applicability 020

Status: `MATERIAL_QA_PASS_PENDING_DURABLE_CLOSE`
Human Gate: `HG-SCOL-CONFIG-PHASEB2-CLEANSPEC-IN-APPLICABILITY-001 · APPROVED`
Base candidate: `b292af2e1c9b86393f1637b41600c6d9a265a173`

## Authorized scope
Align CURRENT `CleanSpec` applicability for the IN-shaped `df_final_sorted` and `df_in_full` outputs, then align candidate CURRENT-shape test/evidence only. CleanEngine implementation, `CleanPresets`, `Estructuras`, derived formulas, `main`, deployment, runtime activation and TER/storage are outside this unit.

## Config CURRENT postcondition
Only `CleanSpec!E11`, `E12`, `E20`, and `E21` were changed. Each now contains exactly:

`["TipoDocumento","NombreCompleto","DireccionCliente","EstadoCentrales","Credito","Almacen","DireccionAlmacen"]`

The removed targets are canonical TER fields that are not projected into the canonical IN-shaped outputs: `ConsecutivoAlmacen`, `CodigoInterno`, `NombreAlmacen`, `ReglaCarteraCodigo`, `TieneCompromiso`, and (where present) `Email`.

`DocumentoDeIdentidad` remains enabled in `E13/E22`; phone targets remain enabled in `E14/E23`. Formula columns and enabled states are unchanged.

## Candidate evidence alignment
The pre-019 CURRENT-shape fixture was replaced with a fixture matching Config CURRENT after 019/020. It exercises both `df_final_sorted` and `df_in_full` and requires, for each dataset alias:

- `resolved_count = 20`
- `failure_count = 0`
- `applied_rules = 4`
- `hard_fail = false`

Negative typo, ambiguity, unbound-target and block-policy tests remain unchanged, including `DocumentoDelIdentidad` as a deliberate negative input proving that fuzzy correction is not allowed.

## Safety boundary
No CleanEngine production logic was changed. No merge to `main`, deployment, runtime activation or TER/storage mutation is authorized by 020.
