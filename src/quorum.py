"""Mission thread quorum — multi-subsystem GO with freeze on dissent."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Dict


def digest(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Vote(str, Enum):
    GO = "GO"
    NO_GO = "NO_GO"
    ABSTAIN = "ABSTAIN"


class Severity(str, Enum):
    LOW = "LOW"
    HIGH = "HIGH"


class StackState(str, Enum):
    GO = "GO"
    HOLD = "HOLD"
    NO_GO = "NO_GO"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True)
class SubsystemVote:
    subsystem: str
    vote: Vote
    severity: Severity
    reason_code: str
    decided_at: float
    half_life_s: float = 30.0

    def live(self, now: float) -> bool:
        return now <= self.decided_at + self.half_life_s


@dataclass(frozen=True)
class QuorumReceipt:
    state: StackState
    hold_reason: str | None
    live_votes: dict
    fingerprint: str


REQUIRED = ("weather", "propulsion", "conjunction", "sequencer")


class MissionThreadQuorum:
    def __init__(self) -> None:
        self._votes: Dict[str, SubsystemVote] = {}

    def cast(self, vote: SubsystemVote) -> None:
        self._votes[vote.subsystem] = vote

    def evaluate(self, now: float) -> QuorumReceipt:
        live = {k: v for k, v in self._votes.items() if v.live(now)}
        missing = [r for r in REQUIRED if r not in live]
        if missing:
            body = {"state": "INCOMPLETE", "missing": missing}
            return QuorumReceipt(
                StackState.INCOMPLETE,
                f"MISSING:{','.join(missing)}",
                {k: v.vote.value for k, v in live.items()},
                digest(body),
            )
        # high severity NO_GO freezes
        for name in REQUIRED:
            v = live[name]
            if v.vote is Vote.NO_GO and v.severity is Severity.HIGH:
                body = {"state": "HOLD", "by": name, "code": v.reason_code}
                return QuorumReceipt(
                    StackState.HOLD,
                    f"HOLD:{name}:{v.reason_code}",
                    {k: x.vote.value for k, x in live.items()},
                    digest(body),
                )
        if any(live[n].vote is Vote.NO_GO for n in REQUIRED):
            body = {"state": "NO_GO"}
            return QuorumReceipt(
                StackState.NO_GO,
                "NO_GO_STACK",
                {k: x.vote.value for k, x in live.items()},
                digest(body),
            )
        if any(live[n].vote is Vote.ABSTAIN for n in REQUIRED):
            body = {"state": "INCOMPLETE", "r": "ABSTAIN"}
            return QuorumReceipt(
                StackState.INCOMPLETE,
                "ABSTAIN_PRESENT",
                {k: x.vote.value for k, x in live.items()},
                digest(body),
            )
        body = {"state": "GO"}
        return QuorumReceipt(
            StackState.GO,
            None,
            {k: x.vote.value for k, x in live.items()},
            digest(body),
        )
