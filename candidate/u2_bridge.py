"""Testable U2 bridge for the B2 candidate.

Dependencies are injected so importing/testing this module never touches Drive, Colab,
Gradio or production data. Business-rule functions remain external to this bridge.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from .run_context import CandidateRunContext
from .runtime_contract import CURRENT_CONFIG_SPREADSHEET_ID, normalize_cleanengine_config, validate_u2_evidence


def execute_u2_cleanengine(
    dataframe: Any,
    *,
    load_config: Callable[[], Mapping[str, Any]],
    apply_engine: Callable[..., tuple[Any, Mapping[str, Any]]],
    dataset_alias: str = "df_final_sorted",
    overrides_enabled_by_rule_id: Mapping[str, bool] | None = None,
    overrides_enabled_by_preset_id: Mapping[str, bool] | None = None,
) -> tuple[Any, Mapping[str, Any], Mapping[str, Any]]:
    frames = normalize_cleanengine_config(load_config())
    output, qa = apply_engine(
        dataframe,
        dataset_alias,
        df_spec=frames.spec,
        df_presets=frames.presets,
        overrides_enabled_by_rule_id=dict(overrides_enabled_by_rule_id or {}),
        overrides_enabled_by_preset_id=dict(overrides_enabled_by_preset_id or {}),
    )
    evidence = validate_u2_evidence(qa)
    return output, qa, evidence


@dataclass(frozen=True)
class U2CandidateResult:
    output: Any
    qa: Mapping[str, Any]
    evidence: Mapping[str, Any]
    run: Mapping[str, Any]


def _normalize_gate_result(value: Any) -> tuple[bool, Any]:
    if isinstance(value, tuple):
        if not value:
            raise ValueError("quality_gate returned an empty tuple")
        return bool(value[0]), value[1] if len(value) > 1 else None
    return bool(value), None


def execute_u2_candidate(
    dataframe: Any,
    *,
    load_config: Callable[[], Mapping[str, Any]],
    quality_gate: Callable[[Any, CandidateRunContext], Any],
    apply_engine: Callable[..., tuple[Any, Mapping[str, Any]]],
    dataset_alias: str = "df_final_sorted",
    run_id: str | None = None,
    overrides_enabled_by_rule_id: Mapping[str, bool] | None = None,
    overrides_enabled_by_preset_id: Mapping[str, bool] | None = None,
) -> U2CandidateResult:
    """Exercise U2 under one evidence context without activating external runtime IO."""
    ctx = CandidateRunContext("U2_CANDIDATE", run_id=run_id, meta={"dataset_alias": dataset_alias})
    ctx.set_manifest("config.spreadsheet_id", CURRENT_CONFIG_SPREADSHEET_ID)
    ctx.add_event("U2_START", stage="U2", message="Candidate U2 evaluation started")
    try:
        frames = normalize_cleanengine_config(load_config())
        gate_ok, gate_detail = _normalize_gate_result(quality_gate(dataframe, ctx))
        ctx.set_manifest("gates.quality_in.ok", gate_ok)
        if gate_detail is not None:
            ctx.set_manifest("gates.quality_in.detail", gate_detail)
        if not gate_ok:
            evidence = {
                "promotion_ok": False,
                "status": "FAIL_QUALITY_GATE",
                "applied_rules_count": 0,
                "warn_count": 0,
                "run_id": ctx.run_id,
            }
            ctx.add_event("U2_QUALITY_GATE_FAIL", level="ERROR", stage="U2")
            ctx.set_manifest("metrics.U2", dict(evidence))
            ctx.finalize("FAIL")
            return U2CandidateResult(dataframe, {}, evidence, ctx.snapshot())

        output, qa = apply_engine(
            dataframe,
            dataset_alias,
            df_spec=frames.spec,
            df_presets=frames.presets,
            overrides_enabled_by_rule_id=dict(overrides_enabled_by_rule_id or {}),
            overrides_enabled_by_preset_id=dict(overrides_enabled_by_preset_id or {}),
        )
        evidence = dict(validate_u2_evidence(qa))
        evidence["run_id"] = ctx.run_id
        ctx.set_manifest("metrics.U2", dict(evidence))
        if evidence["promotion_ok"]:
            ctx.add_event("U2_PASS", stage="U2", data={"applied_rules_count": evidence["applied_rules_count"]})
            ctx.finalize("PASS")
        elif evidence["status"] == "REVIEW_REQUIRED_WARNINGS":
            ctx.add_event("U2_REVIEW_REQUIRED", level="WARNING", stage="U2", data={"warn_count": evidence["warn_count"]})
            ctx.finalize("REVIEW_REQUIRED")
        else:
            ctx.add_event("U2_FAIL", level="ERROR", stage="U2", data={"status": evidence["status"]})
            ctx.finalize("FAIL")
        return U2CandidateResult(output, qa, evidence, ctx.snapshot())
    except Exception as exc:
        evidence = {
            "promotion_ok": False,
            "status": "FAIL_EXCEPTION",
            "applied_rules_count": 0,
            "warn_count": 0,
            "run_id": ctx.run_id,
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
        }
        ctx.add_event("U2_EXCEPTION", level="ERROR", stage="U2", message=str(exc), data={"exception_type": type(exc).__name__})
        ctx.set_manifest("metrics.U2", dict(evidence))
        ctx.finalize("FAIL")
        return U2CandidateResult(dataframe, {}, evidence, ctx.snapshot())
