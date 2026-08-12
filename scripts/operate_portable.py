#!/usr/bin/env python3
"""Execute quorum → portable receipt → independent verification."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.portable_receipt import export_portable, verify_portable
from src.quorum import MissionThreadQuorum, Severity, StackState, SubsystemVote, Vote


def main() -> int:
    q = MissionThreadQuorum()
    q.cast(SubsystemVote("weather", Vote.NO_GO, Severity.HIGH, "WINDS", 101.0, 30.0))
    q.cast(SubsystemVote("propulsion", Vote.GO, Severity.LOW, "NOMINAL", 100.0, 30.0))
    q.cast(SubsystemVote("conjunction", Vote.GO, Severity.LOW, "CLEAR", 100.0, 30.0))
    q.cast(SubsystemVote("sequencer", Vote.GO, Severity.LOW, "READY", 100.0, 30.0))
    portable = export_portable(q, q.evaluate(110.0))
    verified, reason = verify_portable(portable)
    print(json.dumps({
        "status": "PASS" if verified and portable["state"] == StackState.HOLD.value else "FAIL",
        "verified": verified,
        "reason": reason,
        "receipt": portable,
    }, indent=2, sort_keys=True))
    return 0 if verified and portable["state"] == StackState.HOLD.value else 2


if __name__ == "__main__":
    raise SystemExit(main())
