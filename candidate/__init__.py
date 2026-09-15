"""SinergIA Phase B2 candidate package. Import-safe by contract."""
from .runtime_contract import CURRENT_CONFIG_SPREADSHEET_ID, normalize_cleanengine_config, validate_u2_evidence
from .clean_engine import apply_cleanengine_candidate, bind_target_exact

__all__ = [
    "CURRENT_CONFIG_SPREADSHEET_ID",
    "normalize_cleanengine_config",
    "validate_u2_evidence",
    "apply_cleanengine_candidate",
    "bind_target_exact",
]
