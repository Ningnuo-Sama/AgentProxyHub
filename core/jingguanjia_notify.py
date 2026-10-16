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
            source_name = str(entry.get("source_name", "")).lower()
            if entry.get("category") == "notifications" and ("hermes" in source_name or "notify" in source_name or "jing" in source_name):
                raw = read_secret(entry["id"]).decode("utf-8", "replace").strip()
                if raw:
                    for line in raw.splitlines():
                        candidate = line.strip()
                        if candidate and "=" not in candidate and ":" not in candidate and not candidate.startswith("{"):
                            return candidate
    except (OSError, ValueError, KeyError, UnicodeError):
        return None
    return None


def _post_status(payload: dict[str, Any], timeout: float = DEFAULT_TIMEOUT) -> tuple[int, str]:
    """返回 (HTTP 状态码, 说明)。`/notify` 的成功口径是 **202**（P2-4 契约）。"""
    url = os.environ.get("JG_NOTIFY_URL", DEFAULT_URL)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    token = _vault_token()
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), "ok"
    except urllib.error.HTTPError as exc:
        return int(exc.code), f"http_error:{exc.code}"
    except (OSError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"[jingguanjia-notify] unavailable: {exc}", file=os.sys.stderr)
        return 0, f"unreachable:{type(exc).__name__}"


def _post(payload: dict[str, Any], timeout: float = DEFAULT_TIMEOUT) -> bool:
    status, _detail = _post_status(payload, timeout)
    return 200 <= status < 300


def notify_jingguanjia_verified(
    text: str,
    *,
    event_id: str | None = None,
    emote: str | None = None,
    motion: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """双条件告警通道校验：**先 `/health`=200，再 `/notify`=202**。

    单看进程存活或单看 POST 成功都不算通道可用（用户 P2-4 契约）。
    """
    health = jingguanjia_healthy(timeout)
    if not health:
        return {"ok": False, "channel": "jingguanjia", "health": "unreachable",
                "reason": "health_not_200", "notify_status": None}
    payload: dict[str, Any] = {"event_id": event_id or f"agentproxyhub-{uuid.uuid4().hex}",
                               "text": str(text)[:2000]}
    if emote:
        payload["emote"] = emote
    if motion:
        payload["motion"] = motion
    status, detail = _post_status(payload, timeout)
    return {"ok": status == 202, "channel": "jingguanjia", "health": "200",
            "notify_status": status, "detail": detail,
            "auth": "bearer" if _vault_token() else "none"}


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
    parser.add_argument("--verified", action="store_true",
                        help="双条件校验（/health=200 且 /notify=202），返回 JSON")
    args = parser.parse_args()
    if args.wait_health:
        return 0 if wait_for_health(args.wait_seconds) else 1
    if args.text is not None:
        if args.verified:
            result = notify_jingguanjia_verified(args.text, event_id=args.event_id,
                                                 emote=args.emote, motion=args.motion)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result.get("ok") else 1
        return 0 if notify_jingguanjia(args.text, event_id=args.event_id, emote=args.emote, motion=args.motion) else 1
    parser.error("--wait-health or --text is required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
