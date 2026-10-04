"""Fail-closed, no-side-effect captcha policy decisions.

This module never contacts a captcha provider and never returns a token or key.
Flow-Tools remains the only component allowed to execute a provider task.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

CONTRACT_VERSION = 1


@dataclass(frozen=True)
class Decision:
    decision: str
    provider: str
    reason_code: str
    would_create_task: bool = False
    max_new_tasks: int = 0
    estimated_points: int = 0

    def as_dict(self, request_id: str, budget: Mapping[str, Any] | None = None) -> dict[str, Any]:
        budget = dict(budget or {})
        max_attempts = max(0, int(budget.get("max_attempts", 0) or 0))
        max_points = max(0, int(budget.get("max_points", 0) or 0))
        spent_points = max(0, int(budget.get("spent_points", 0) or 0))
        return {
            "ok": True,
            "contract_version": CONTRACT_VERSION,
            "request_id": request_id,
            "decision": self.decision,
            "provider": self.provider,
            "mode": "dry_run",
            "would_create_task": False,
            "max_new_tasks": 0,
            "estimated_points": 0,
            "budget": {
                "max_attempts": max_attempts,
                "max_points": max_points,
                "spent_points": spent_points,
                "remaining_attempts": max(0, max_attempts - int(budget.get("attempt", 0) or 0)),
                "remaining_points": max(0, max_points - spent_points),
            },
            "reason_code": self.reason_code,
        }


def decide(request: Mapping[str, Any]) -> Decision:
    """Return a deterministic dry-run decision; unknown or unsafe states deny."""
    if request.get("contract_version", CONTRACT_VERSION) != CONTRACT_VERSION:
        return Decision("deny", "none", "policy_unavailable")
    if request.get("mode", "dry_run") != "dry_run":
        return Decision("deny", "none", "policy_unavailable")
    if not request.get("request_id") or not request.get("operation"):
        return Decision("deny", "none", "policy_unavailable")

    prior = str(request.get("prior_error_category") or "").lower()
    status = str(request.get("prior_upstream_status") or "")
    stage = str(request.get("stage") or "preflight")
    route = str(request.get("route") or "unknown")
    budget = request.get("budget") or {}
    if not isinstance(budget, Mapping):
        return Decision("deny", "none", "policy_unavailable")
    if int(budget.get("spent_points", 0) or 0) >= int(budget.get("max_points", 0) or 0) and int(budget.get("max_points", 0) or 0) > 0:
        return Decision("deny", "none", "budget_exhausted")
    if int(budget.get("attempt", request.get("attempt", 1)) or 1) > int(budget.get("max_attempts", 1) or 1):
        return Decision("deny", "none", "budget_exhausted")
    if status == "401" or prior in {"auth_failure", "unauthorized", "invalid_session", "invalid_cookie"}:
        return Decision("deny", "none", "auth_failure_circuit_open")
    if prior in {"already_submitted", "task_started", "generation_started"} or stage == "submit":
        return Decision("deny", "none", "already_submitted")
    if route == "unknown":
        return Decision("defer", "none", "route_unknown")
    if prior not in {"captcha_indicated", "recaptcha_failed", "captcha_expired"}:
        return Decision("deny", "none", "captcha_not_indicated")
    if route == "browser" or request.get("captcha_provider") == "local":
        return Decision("allow_local", "local", "captcha_indicated")
    return Decision("defer", "none", "paid_authorization_required")


__all__ = ["CONTRACT_VERSION", "Decision", "decide"]
