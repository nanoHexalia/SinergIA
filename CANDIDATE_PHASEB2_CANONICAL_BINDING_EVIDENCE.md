# SCOL Config Phase B2 · Canonical Binding 018

Status: `CLOSED_PASS_CANDIDATE_INCREMENT`
Human Gate: `HG-SCOL-CONFIG-PHASEB2-CLEANENGINE-CANONICAL-BINDING-001 · APPROVED`
Base candidate: `3195c8b3cf5354570dbee1f3d6f8a75681c54334`

## Authorized scope
Candidate-only implementation and QA on `scol/config-phaseb2-candidate-001` for an executable CleanEngine, exact `Estructuras ↔ CleanSpec` target binding, and evidence. No merge to `main`, deployment, runtime activation, Config mutation, or TER mutation is authorized by this unit.

## Implemented
- Added an import-safe, injected `CleanEngineCandidate` with no network/runtime side effects.
- Added exact binding through `Estructuras.NombreColumna` or `Estructuras.AliasCanonico` within the canonical logical-file scope.
- Fuzzy correction is forbidden; missing, duplicate, or ambiguous bindings produce explicit evidence.
- Rules with zero bound targets are not counted as applied.
- Binding failures under block policy fail closed.
- `severity` / `action_on_fail` remain resolved by the 016 contract: explicit raw `CleanSpec` fields first, then `CleanPresets` defaults; `severity_eff` / `action_eff` are ignored.
- Both U2 bridge paths now inject the optional Estructuras frame.
- Hard rule failure is surfaced as `FAIL_HARD_RULE` at the promotion-evidence boundary.

## QA
- Inherited regression: `14/14 PASS` before new tests.
- Full candidate suite: `24/24 PASS`.
- `compileall`: PASS.
- `git diff --check`: PASS.
- Provenance SHA-256 remains `60e45001b91a1d41faf095fccd56a03462dffe42b1b0ea5f5ed19fe5709a89db`.
- Independent clean-clone challenge from base candidate: `24/24 PASS`; 5-code-file patch applied cleanly.

## Current Config challenge
The CURRENT enabled shape is intentionally not silently repaired. The test fixture mirroring the readback demonstrates `19` exact bindings and `12` failed binding occurrences across the four enabled rules, with `7` unique unbound target names. Three rules have executable bound targets; `DOC_NORMALIZE` is not falsely counted as applied for the unbound `DocumentoDelIdentidad` target.

Therefore this code increment may close PASS while promotion remains gated by live Config canonicalization. Any Config edit requires a separate explicit Human Gate.
