"""Testable U2 bridge for the B2 candidate.

Dependencies are injected so importing/testing this module never touches Drive, Colab,
Gradio or production data. Business-rule functions remain external to this bridge.
"""
from __future__ import annotations
from typing import Any, Callable, Mapping
from .runtime_contract import normalize_cleanengine_config, validate_u2_evidence

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
