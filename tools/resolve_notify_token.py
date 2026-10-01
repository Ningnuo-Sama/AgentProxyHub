"""Emit the DPAPI-protected Jingguanjia notify token for a local child process only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VAULT = Path(r"D:\ProgramData\AgentProxyHub\credentials\vault")
sys.path.insert(0, str(ROOT))

from core.credential_vault import _unprotect  # noqa: E402


def main() -> int:
    manifest = json.loads((VAULT / "manifest.json").read_text(encoding="utf-8"))
    for entry in manifest.get("entries", []):
        name = str(entry.get("source_name", "")).lower()
        if entry.get("category") != "notifications" or not any(k in name for k in ("hermes", "notify", "jing")):
            continue
        raw = _unprotect((VAULT / entry["blob"]).read_bytes()).decode("utf-8", "replace")
        for line in raw.splitlines():
            candidate = line.strip()
            if candidate and "=" not in candidate and ":" not in candidate and not candidate.startswith("{"):
                sys.stdout.write(candidate)
                return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
