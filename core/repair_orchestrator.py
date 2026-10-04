"""Constrained autonomous repair orchestration.

This module records and evaluates repair plans. It does not execute shell commands,
modify production copies, change proxy bindings, call paid providers, or touch secrets.
A caller may hand an approved candidate plan to its own isolated runner.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Mapping

from .autonomy_core import EventStore, utc_now

ALLOWED_PHASES = (
    "discovered", "classified", "candidate_created", "testing", "verified",
    "applied", "rolled_back", "blocked", "reported",
)
BLOCKING_RISKS = {
    "paid_call", "credential_access", "production_deploy", "region_change",
    "binding_change", "irreversible", "unknown_side_effect",
}


def repair_id(scope: str, fingerprint: str) -> str:
    raw = f"{scope}:{fingerprint}".encode("utf-8")
    return "repair-" + hashlib.sha256(raw).hexdigest()[:16]


@dataclass(frozen=True)
class RepairPlan:
    repair_id: str
    scope: str
    symptom: str
    root_cause: str
    candidate: str
    tests: tuple[str, ...]
    risks: tuple[str, ...] = ()
    phase: str = "classified"

    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        if self.phase not in ALLOWED_PHASES:
            errors.append("invalid_phase")
        if not self.repair_id or not self.scope or not self.candidate:
            errors.append("missing_identity")
        if not self.tests:
            errors.append("no_tests")
        blocked = sorted(set(self.risks) & BLOCKING_RISKS)
        if blocked:
            errors.append("manual_gate:" + ",".join(blocked))
        return {"ok": not errors, "errors": errors, "repair_id": self.repair_id}


class RepairOrchestrator:
    """Persist repair evidence without performing the repair itself."""

    def __init__(self, state_file: str | os.PathLike[str], events: EventStore | None = None):
        self.state_file = Path(state_file)
        self.events = events or EventStore(self.state_file.with_name("repair_events.jsonl"))

    def record(self, plan: RepairPlan, *, result: Mapping[str, Any] | None = None) -> dict[str, Any]:
        validation = plan.validate()
        row = {"recorded_at": utc_now(), "plan": asdict(plan), "validation": validation,
               "result": dict(result or {})}
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=self.state_file.name + ".", suffix=".tmp", dir=self.state_file.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(row, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.state_file)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        self.events.append("repair.plan_recorded", {"repair_id": plan.repair_id,
                                                     "phase": plan.phase,
                                                     "validation_ok": validation["ok"]},
                           severity="notice" if validation["ok"] else "action_required",
                           dedupe_key=plan.repair_id)
        return row


def should_auto_repair(plan: RepairPlan) -> bool:
    """Only isolated, testable, non-sensitive repairs may run unattended."""
    return plan.validate()["ok"] and plan.phase in {"classified", "candidate_created", "testing"}


__all__ = ["ALLOWED_PHASES", "RepairPlan", "RepairOrchestrator", "repair_id", "should_auto_repair"]
