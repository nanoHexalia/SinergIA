# SCOL Config Phase B2 candidate integration evidence

Material unit: `SCOL-CONFIG-PHASEB2-CANDIDATE-INTEGRATION-016`
Human Gate: `HG-SCOL-CONFIG-PHASEB2-CANDIDATE-INTEGRATION-001`
Base candidate: `7b4e067bdaf698cfdfb9de45888bbda1809e1280`
Protected base `main`: `537de761035c6b0cf7c2c5693af444eb051a2f36`

## Scope integrated
- Pure `SettingID` resolver: exact single match, fail-closed on missing or ambiguous authority.
- Pure CleanEngine policy resolver preserving demonstrated provenance precedence.
- In-memory `CandidateRunContext`: one `run_id` shared by manifest and events; no filesystem/network activation.
- U2 integration boundary: injected Config loader, injected QualityGate, injected CleanEngine, explicit PASS/REVIEW_REQUIRED/FAIL evidence.

## CleanEngine policy evidence
The preserved provenance reads `severity` and `action_on_fail` from CleanSpec first and only falls back to `default_severity` / `default_action_on_fail` from the referenced CleanPreset when the CleanSpec value is blank. Preset params are loaded first; an explicit raw CleanSpec `params_json` overlays them. The demonstrated engine does not consume `severity_eff` or `action_eff`.

CURRENT Config evidence used for the contract test includes `DOC_DI_NORMALIZE`: CleanPreset default severity `block` / action `set_null`, while enabled CleanSpec for `df_final_sorted` explicitly supplies severity `info` / action `set_null`. The candidate therefore proves that the explicit CleanSpec value wins and that derived `*_eff` fields cannot override it.

## Isolation guarantees
- No import of the preserved provenance monolith.
- No Drive, Colab, Gradio, production-data or runtime activation on import.
- No merge to `main`, deployment, TER mutation, or Config mutation in this unit.
- Any QualityGate failure stops U2 before CleanEngine execution and leaves FAIL evidence under the same `run_id`.
- Engine exceptions are captured as candidate FAIL evidence under the same `run_id`.
- Warnings remain `REVIEW_REQUIRED` at the candidate promotion boundary; they are not silently promoted.
