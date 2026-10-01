"""Secret-free model usage ledger for AgentProxyHub.

Callers record provider/model, request outcome, tokens and estimated cost only;
credential values and prompt bodies are never accepted or persisted.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("APHUB_DATA_DIR") or ROOT_DIR / "data")
USAGE_FILE = DATA_DIR / "model_usage.jsonl"


def record_usage(provider: str, model: str, *, status: str = "unknown", input_tokens: int = 0,
                 output_tokens: int = 0, total_tokens: int | None = None,
                 estimated_cost: float | None = None, request_id: str | None = None) -> dict[str, Any]:
    """Append a redacted usage record. Prompt/key/content fields are intentionally absent."""
    if not provider or not model:
        raise ValueError("provider and model are required")
    row = {
        "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "provider": str(provider)[:80], "model": str(model)[:120],
        "status": str(status)[:40], "input_tokens": max(0, int(input_tokens)),
        "output_tokens": max(0, int(output_tokens)),
        "total_tokens": max(0, int(total_tokens if total_tokens is not None else input_tokens + output_tokens)),
    }
    if estimated_cost is not None:
        row["estimated_cost"] = max(0.0, float(estimated_cost))
    if request_id:
        row["request_id_hash"] = __import__("hashlib").sha256(str(request_id).encode()).hexdigest()[:16]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with USAGE_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return {"ok": True, "recorded": True, "file": str(USAGE_FILE), "row": row}


def usage_summary() -> dict[str, Any]:
    totals: dict[str, dict[str, float]] = {}
    count = 0
    if USAGE_FILE.exists():
        for line in USAGE_FILE.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                key = f"{row.get('provider')}/{row.get('model')}"
                item = totals.setdefault(key, {"requests": 0, "tokens": 0, "estimated_cost": 0.0})
                item["requests"] += 1
                item["tokens"] += int(row.get("total_tokens") or 0)
                item["estimated_cost"] += float(row.get("estimated_cost") or 0)
                count += 1
            except (ValueError, TypeError, json.JSONDecodeError):
                continue
    return {"ok": True, "count": count, "by_model": totals, "file": str(USAGE_FILE), "secrets_logged": False}


__all__ = ["USAGE_FILE", "record_usage", "usage_summary"]
