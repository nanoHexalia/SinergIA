"""Non-activating, import-safe entrypoint boundary for the B2 candidate."""
from __future__ import annotations
from .runtime_contract import CURRENT_CONFIG_SPREADSHEET_ID

def describe_candidate() -> dict[str, object]:
    return {
        "project": "SinergIACollect",
        "config_spreadsheet_id": CURRENT_CONFIG_SPREADSHEET_ID,
        "runtime_activation": False,
        "production_data_access": False,
        "status": "CANDIDATE_NOT_PROMOTED",
    }

def main() -> int:
    info = describe_candidate()
    print("SinergIA candidate boundary · no runtime activation")
    print(info)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
