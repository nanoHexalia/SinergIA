"""Import-safe runtime contract for the SinergIA Phase B2 candidate.

No network, Drive, Colab, Gradio, production data, or runtime activation occurs on import.
Business-rule execution remains in the legacy source until separately promoted.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping

CURRENT_CONFIG_SPREADSHEET_ID = "12LoMTA8MirP9GIiG3VOInVejGNlvBMYZp9_mmSJbUhM"

@dataclass(frozen=True)
class CleanEngineFrames:
    presets: Any
    spec: Any

def normalize_cleanengine_config(value: Mapping[str, Any]) -> CleanEngineFrames:
    """Resolve the demonstrated 20260211 dict contract without tuple-unpacking keys."""
    if not isinstance(value, Mapping):
        raise TypeError("CleanEngine config must be a mapping with presets/spec")
    if "presets" not in value or "spec" not in value:
        raise KeyError("CleanEngine config requires presets and spec")
    return CleanEngineFrames(presets=value["presets"], spec=value["spec"])

def validate_u2_evidence(qa: Mapping[str, Any]) -> dict[str, Any]:
    """Promotion evidence only; does not invent severity/action_on_fail semantics.

    A U2 candidate cannot be considered demonstrated unless at least one rule ran.
    Warnings remain REVIEW_REQUIRED at the candidate promotion boundary; canonical severity/action precedence is resolved separately from Config evidence.
    """
    applied = list((qa or {}).get("applied") or [])
    warnings = list((qa or {}).get("warn") or [])
    if not applied:
        return {"promotion_ok": False, "status": "FAIL_NO_RULES_APPLIED", "applied_rules_count": 0, "warn_count": len(warnings)}
    if warnings:
        return {"promotion_ok": False, "status": "REVIEW_REQUIRED_WARNINGS", "applied_rules_count": len(applied), "warn_count": len(warnings)}
    return {"promotion_ok": True, "status": "PASS", "applied_rules_count": len(applied), "warn_count": 0}
