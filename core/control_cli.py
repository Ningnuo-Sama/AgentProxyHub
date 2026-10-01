#!/usr/bin/env python3
"""Small local control bridge for the AgentProxyHub maintenance UI."""
from __future__ import annotations
import argparse
import json
from .autonomy_core import AutonomyState, EventStore
from .resident_engineer import ResidentEngineer
from .resident_scheduler import ResidentScheduler


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("status", "engineer", "run_once", "summary"))
    args = parser.parse_args()
    state = AutonomyState()
    if args.action == "status":
        result = {"state": state.load(), "events": EventStore().summary(), "engineer": ResidentEngineer().load_state()}
    elif args.action == "engineer":
        result = ResidentEngineer().dispatch("health_check", {"ports": [21001, 21008, 22002, 39999]})
    elif args.action == "run_once":
        scheduler = ResidentScheduler(state=state, events=EventStore())
        result = scheduler.run_once(notify=False)
    else:
        result = EventStore().summary()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
