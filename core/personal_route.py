"""Offline personal TUN candidate planning; never applies configuration or enables TUN.

Candidate dictionaries contain runtime credentials and MUST NOT be logged. Use
candidate_summary() for UI/MCP output. Fixed-node business listeners are immutable.
"""
from __future__ import annotations

import copy
import json
import ipaddress
from pathlib import Path
from typing import Any, Mapping

PERSONAL_GROUP = "PERSONAL"
EXCLUDED_ROUTES = ["127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "::1/128", "fc00::/7", "fe80::/10"]
FIXED_PORTS = frozenset(range(21001, 21081)) | frozenset(range(22001, 22046))


def fixed_listener_map(config: Mapping[str, Any]) -> dict[int, str]:
    """Require exactly the original 125 fixed SOCKS ports and direct node targets."""
    result = {}
    for item in config.get("listeners", []):
        port = item.get("port")
        if port not in FIXED_PORTS:
            continue
        expected = ("fw-" if port < 22000 else "xc-") + str(port)
        if port in result or item.get("proxy") != expected:
            raise ValueError("fixed_listener_mapping_invalid")
        result[port] = expected
    if result.keys() != FIXED_PORTS:
        raise ValueError("fixed_listener_ports_missing")
    return result


def build_candidate(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return a disabled-TUN candidate, without touching any runtime files.

    Personal rule changes affect rule-routed traffic (39999 and future TUN), not
    listeners with explicit proxy fields. Physical-interface binding is retained.
    """
    before = fixed_listener_map(config)
    candidate = copy.deepcopy(dict(config))
    names = {group.get("name") for group in candidate.get("proxy-groups", [])}
    if "AUTO-POOL" not in names:
        raise ValueError("auto_pool_missing")
    groups = candidate.setdefault("proxy-groups", [])
    groups[:] = [g for g in groups if g.get("name") != PERSONAL_GROUP]
    groups.append({"name": PERSONAL_GROUP, "type": "select", "proxies": ["AUTO-POOL", "DIRECT"]})
    # Candidate fake-IP preserves domain identity; DNS hijack is required for TUN.
    # These defaults alone do not prove remote DoH routing or production readiness.
    dns = candidate.setdefault("dns", {})
    dns.update({"enable": True, "enhanced-mode": "fake-ip", "fake-ip-filter": ["+.cn", "+.lan", "+.local"]})
    dns["nameserver"] = ["https://223.5.5.5/dns-query", "https://doh.pub/dns-query"]
    dns["proxy-server-nameserver"] = ["https://223.5.5.5/dns-query"]
    dns["fallback"] = ["https://1.1.1.1/dns-query", "https://8.8.8.8/dns-query"]
    candidate["mode"] = "rule"
    # PyYAML YAML1.1 将原配置未加引号的 off 读成 False；内核需要枚举字符串。
    if candidate.get("find-process-mode") is False:
        candidate["find-process-mode"] = "off"
    tun = candidate.setdefault("tun", {})
    tun.update({"enable": False, "auto-route": True, "auto-detect-interface": True,
                "dns-hijack": ["any:53"]})
    # Do not invent strict-route or a platform-specific stack. Preserve an explicit
    # upstream setting, and leave unspecified settings to versioned kernel defaults.
    excluded = list(tun.get("route-exclude-address") or [])
    for cidr in EXCLUDED_ROUTES:
        if cidr not in excluded:
            excluded.append(cidr)
    tun["route-exclude-address"] = excluded
    candidate["rules"] = [
        "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
        "IP-CIDR6,::1/128,DIRECT,no-resolve",
        "GEOIP,lan,DIRECT,no-resolve",
        "GEOSITE,cn,DIRECT",
        "GEOIP,cn,DIRECT",
        f"MATCH,{PERSONAL_GROUP}",
    ]
    if fixed_listener_map(candidate) != before or candidate["listeners"] != config["listeners"]:
        raise ValueError("business_listeners_changed")
    return candidate


def candidate_summary(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Strict allowlist output: no arbitrary config, DNS URLs or credentials."""
    ports = fixed_listener_map(candidate)
    return {"ok": True, "candidate_only": True, "applied": False,
            "tun_enabled": bool(candidate.get("tun", {}).get("enable", False)),
            "fixed_port_count": len(ports), "business_listeners_changed": False,
            "personal_group": PERSONAL_GROUP, "mode": candidate.get("mode"),
            "rules": list(candidate.get("rules", [])),
            "requires_privileged_apply": True}


def is_halted() -> bool:
    from .kernel_control import is_halted as shared_is_halted
    return shared_is_halted()


def read_manual_halt(state_file: str | Path) -> bool:
    """Fail closed on malformed state. Absent state means no previous manual halt."""
    path = Path(state_file)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("manual_halt"), bool):
            return True
        return data["manual_halt"]
    except (OSError, ValueError, TypeError):
        return True


def activation_preflight(config: Mapping[str, Any], state_file: str | Path | None = None,
                         *, privileged: bool = False) -> dict[str, Any]:
    """Plan only. Caller must obtain privilege from a legitimate verified service.

    This flag is evidence supplied by the caller, NOT a privilege escalation. Even
    success does not change TUN. Production apply must recheck halt under its lock.
    """
    if (read_manual_halt(state_file) if state_file is not None else is_halted()):
        return {"ok": False, "code": "manual_halt", "applied": False}
    if not privileged:
        return {"ok": False, "code": "privilege_required", "applied": False}
    try:
        candidate = build_candidate(config)
    except (ValueError, TypeError, KeyError):
        return {"ok": False, "code": "candidate_invalid", "applied": False}
    if not candidate.get("interface-name"):
        return {"ok": False, "code": "physical_interface_required", "applied": False}
    return {"ok": True, "code": "candidate_ready_not_applied", "applied": False,
            "summary": candidate_summary(candidate)}


def prepare_candidate(runtime_config: str | Path, target: str | Path) -> dict[str, Any]:
    """Write a private disabled candidate outside the runtime directory (never Git).

    Contains runtime credentials: caller must use an access-controlled candidate
    directory, not repository docs or logs. This function refuses overwrite.
    """
    import yaml
    source, output = Path(runtime_config).resolve(), Path(target).resolve()
    if output == source or output.parent == source.parent:
        return {"ok": False, "code": "runtime_overwrite_refused", "applied": False}
    try:
        with source.open(encoding="utf-8-sig") as handle:
            candidate = build_candidate(yaml.safe_load(handle))
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            yaml.safe_dump(candidate, handle, allow_unicode=True, sort_keys=False)
        return candidate_summary(candidate)
    except (OSError, ValueError, TypeError, KeyError):
        return {"ok": False, "code": "candidate_prepare_failed", "applied": False}


def status() -> dict[str, Any]:
    return {"ok": True, "manual_halt": is_halted(), "implemented": "candidate_only",
            "tun_state": "unknown", "applied": False, "privileged_service_verified": False}


def start() -> dict[str, Any]:
    # Production enabling intentionally unavailable until a legitimate dedicated
    # privileged service and independent rollback watchdog are verified.
    return {"ok": False, "code": "manual_halt" if is_halted() else "privilege_required",
            "applied": False, "tun_enabled": False}


def runtime_controller_auth(config_path: str | Path) -> tuple[str, dict[str, str]]:
    """Read controller auth from the selected runtime YAML; never return in UI output.

    PyYAML is needed only for this function, not for candidate transforms/tests.
    Only loopback controller addresses are accepted. Returned headers are sensitive.
    """
    import yaml
    with Path(config_path).open(encoding="utf-8-sig") as handle:
        config = yaml.safe_load(handle)
    endpoint = str(config.get("external-controller") or "")
    host, separator, port = endpoint.rpartition(":")
    host = host.strip("[]")
    try:
        if not separator or not ipaddress.ip_address(host).is_loopback or not 1 <= int(port) <= 65535:
            raise ValueError
    except ValueError:
        raise ValueError("loopback_controller_required") from None
    secret = config.get("secret")
    if not isinstance(secret, str) or not secret:
        raise ValueError("controller_auth_missing")
    return "http://" + endpoint, {"Authorization": "Bearer " + secret}
