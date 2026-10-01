"""Best-effort local notification client for Jingguanjia.

This module deliberately has no third-party dependencies. Notification failures are
non-fatal: proxy recovery and startup must continue when the desktop pet is absent.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

DEFAULT_URL = "http://127.0.0.1:8766/notify"
DEFAULT_HEALTH_URL = "http://127.0.0.1:8766/health"
DEFAULT_TIMEOUT = 1.0


def _vault_token() -> str | None:
    """Resolve the long-lived local token from the DPAPI vault when configured."""
    if os.environ.get("JG_NOTIFY_TOKEN"):
        return os.environ["JG_NOTIFY_TOKEN"]
    try:
        from .credential_vault import MANIFEST, read_secret
        import json
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        for entry in manifest.get("entries", []):
            if entry.get("category") == "notifications" and "token" in str(entry.get("source_name", "")).lower():
                raw = read_secret(entry["id"]).decode("utf-8", "replace").strip()
                if raw:
                    return raw.splitlines()[0].strip()
    except (OSError, ValueError, KeyError, UnicodeError):
        return None
    return None


def _post(payload: dict[str, Any], timeout: float = DEFAULT_TIMEOUT) -> bool:
    url = os.environ.get("JG_NOTIFY_URL", DEFAULT_URL)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **({"Authorization": f"Bearer {_vault_token()}"}
               if _vault_token() else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        # Best effort by design; never turn a desktop notification outage into a
        # proxy-engine outage. Keep the log short and avoid payload/token leakage.
        print(f"[jingguanjia-notify] unavailable: {exc}", file=os.sys.stderr)
        return False


def notify_jingguanjia(
    text: str,
    *,
    event_id: str | None = None,
    emote: str | None = None,
    motion: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> bool:
    payload: dict[str, Any] = {
        "event_id": event_id or f"agentproxyhub-{uuid.uuid4().hex}",
        "text": str(text)[:2000],
    }
    if emote:
        payload["emote"] = emote
    if motion:
        payload["motion"] = motion
    return _post(payload, timeout)


def jingguanjia_healthy(timeout: float = DEFAULT_TIMEOUT) -> bool:
    url = os.environ.get("JG_NOTIFY_HEALTH_URL", DEFAULT_HEALTH_URL)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError, TimeoutError, ValueError):
        return False


def wait_for_health(seconds: float = 8.0, interval: float = 0.25) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if jingguanjia_healthy():
            return True
        time.sleep(interval)
    return jingguanjia_healthy()


def main() -> int:
    parser = argparse.ArgumentParser(description="Best-effort Jingguanjia notify client")
    parser.add_argument("--wait-health", action="store_true")
    parser.add_argument("--wait-seconds", type=float, default=8.0)
    parser.add_argument("--text")
    parser.add_argument("--event-id")
    parser.add_argument("--emote")
    parser.add_argument("--motion")
    args = parser.parse_args()
    if args.wait_health:
        return 0 if wait_for_health(args.wait_seconds) else 1
    if args.text is not None:
        return 0 if notify_jingguanjia(args.text, event_id=args.event_id, emote=args.emote, motion=args.motion) else 1
    parser.error("--wait-health or --text is required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
