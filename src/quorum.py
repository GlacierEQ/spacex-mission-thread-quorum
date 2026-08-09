
"""Mission thread quorum — multi-subsystem GO with freeze on dissent.

Leveled (L1): CRITICAL severity, configurable required set, vote supersession,
audit trail of casts, stale vs missing distinction, deterministic receipts.

Independent reference simulation only — no flight operations claim.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, Sequence


def digest(obj: object) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Vote(str, Enum):
    GO = "GO"
    NO_GO = "NO_GO"
    ABSTAIN = "ABSTAIN"


class Severity(str, Enum):
    LOW = "LOW"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class StackState(str, Enum):
    GO = "GO"
    HOLD = "HOLD"
    NO_GO = "NO_GO"
    INCOMPLETE = "INCOMPLETE"


_SEV_RANK = {Severity.LOW: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}


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
    stale_subsystems: tuple[str, ...]
    missing_subsystems: tuple[str, ...]
    fingerprint: str


@dataclass
class CastRecord:
    seq: int
    vote: SubsystemVote


DEFAULT_REQUIRED = ("weather", "propulsion", "conjunction", "sequencer")


class MissionThreadQuorum:
    def __init__(
        self,
        required: Sequence[str] = DEFAULT_REQUIRED,
        freeze_at: Severity = Severity.HIGH,
    ) -> None:
        if not required:
            raise ValueError("required subsystems cannot be empty")
        self.required = tuple(required)
        self.freeze_at = freeze_at
        self._votes: Dict[str, SubsystemVote] = {}
        self._history: list[CastRecord] = []
        self._lock = threading.RLock()
        self._seq = 0

    def cast(self, vote: SubsystemVote) -> None:
        if vote.half_life_s <= 0:
            raise ValueError("half_life_s must be positive")
        if not vote.reason_code:
            raise ValueError("reason_code required")
        with self._lock:
            self._seq += 1
            self._votes[vote.subsystem] = vote
            self._history.append(CastRecord(self._seq, vote))

    def history(self) -> tuple[CastRecord, ...]:
        with self._lock:
            return tuple(self._history)

    def evaluate(self, now: float) -> QuorumReceipt:
        with self._lock:
            live = {k: v for k, v in self._votes.items() if v.live(now)}
            stale = tuple(sorted(k for k, v in self._votes.items() if not v.live(now)))
            missing = tuple(r for r in self.required if r not in live)

            if missing:
                body = {
                    "state": "INCOMPLETE",
                    "missing": list(missing),
                    "stale": list(stale),
                    "live": {k: v.vote.value for k, v in live.items()},
                }
                return QuorumReceipt(
                    StackState.INCOMPLETE,
                    f"MISSING:{','.join(missing)}",
                    {k: v.vote.value for k, v in live.items()},
                    stale,
                    missing,
                    digest(body),
                )

            # freeze on high/critical NO_GO
            freeze_hits: list[str] = []
            for name in self.required:
                v = live[name]
                if v.vote is Vote.NO_GO and _SEV_RANK[v.severity] >= _SEV_RANK[self.freeze_at]:
                    freeze_hits.append(f"{name}:{v.reason_code}:{v.severity.value}")

            if freeze_hits:
                # critical prefers first in required order
                body = {"state": "HOLD", "hits": freeze_hits}
                return QuorumReceipt(
                    StackState.HOLD,
                    f"HOLD:{';'.join(freeze_hits)}",
                    {k: x.vote.value for k, x in live.items()},
                    stale,
                    (),
                    digest(body),
                )

            if any(live[n].vote is Vote.NO_GO for n in self.required):
                body = {"state": "NO_GO"}
                return QuorumReceipt(
                    StackState.NO_GO,
                    "NO_GO_STACK",
                    {k: x.vote.value for k, x in live.items()},
                    stale,
                    (),
                    digest(body),
                )

            if any(live[n].vote is Vote.ABSTAIN for n in self.required):
                body = {"state": "INCOMPLETE", "r": "ABSTAIN"}
                return QuorumReceipt(
                    StackState.INCOMPLETE,
                    "ABSTAIN_PRESENT",
                    {k: x.vote.value for k, x in live.items()},
                    stale,
                    (),
                    digest(body),
                )

            body = {"state": "GO", "subs": list(self.required)}
            return QuorumReceipt(
                StackState.GO,
                None,
                {k: x.vote.value for k, x in live.items()},
                stale,
                (),
                digest(body),
            )

    def residuals_for_hold(self, now: float) -> list[tuple[str, str, str]]:
        """Return (subsystem, code, detail) for hold-capable NO_GOs currently live."""
        with self._lock:
            out = []
            for name in self.required:
                v = self._votes.get(name)
                if v is None or not v.live(now):
                    continue
                if v.vote is Vote.NO_GO and _SEV_RANK[v.severity] >= _SEV_RANK[self.freeze_at]:
                    out.append((name, v.reason_code, f"severity={v.severity.value}"))
            return out
