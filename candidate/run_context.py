"""In-memory evidence context for an import-safe SinergIA candidate run."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from uuid import uuid4


def _deep_set(target: dict[str, Any], path: str, value: Any) -> None:
    parts = [p for p in str(path).split(".") if p]
    if not parts:
        raise ValueError("manifest path must be non-empty")
    cursor = target
    for part in parts[:-1]:
        child = cursor.get(part)
        if not isinstance(child, dict):
            child = {}
            cursor[part] = child
        cursor = child
    cursor[parts[-1]] = value


class CandidateRunContext:
    """One run_id shared by manifest and every event; no filesystem persistence."""
    def __init__(
        self,
        action: str,
        *,
        run_id: str | None = None,
        now: Callable[[], datetime] | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.run_id = run_id or f"candidate_{uuid4().hex}"
        self.action = str(action)
        self.events: list[dict[str, Any]] = []
        self.manifest: dict[str, Any] = {
            "run_id": self.run_id,
            "action": self.action,
            "started_at": self._iso(),
            "ended_at": None,
            "status": None,
            "meta": dict(meta or {}),
            "config": {},
            "metrics": {},
            "gates": {},
            "outputs": {},
        }

    def _iso(self) -> str:
        value = self._now()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()

    def add_event(self, code: str, *, level: str = "INFO", stage: str = "RUNTIME", message: str = "", data: Mapping[str, Any] | None = None) -> None:
        self.events.append({
            "ts": self._iso(), "run_id": self.run_id, "stage": str(stage),
            "code": str(code), "level": str(level).upper(), "message": str(message),
            "data": dict(data or {}),
        })

    def set_manifest(self, path: str, value: Any) -> None:
        _deep_set(self.manifest, path, value)

    def finalize(self, status: str) -> None:
        self.manifest["ended_at"] = self._iso()
        self.manifest["status"] = str(status)
        self.manifest["summary"] = {
            "events_total": len(self.events),
            "events_by_level": {
                level: sum(1 for event in self.events if event["level"] == level)
                for level in sorted({event["level"] for event in self.events})
            },
        }

    def snapshot(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "manifest": deepcopy(self.manifest), "events": deepcopy(self.events)}
