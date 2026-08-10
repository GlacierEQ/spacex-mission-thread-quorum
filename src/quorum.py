"""Mission thread quorum — fresh multi-subsystem decision evidence.

The quorum owns deterministic aggregation of configured subsystem votes under a
freshness policy. It does not authenticate voters, command hardware, decide real
flight safety, or clear/issue an operational launch hold.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Sequence


def digest(obj: object) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


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


_SEV_RANK: Mapping[Severity, int] = MappingProxyType(
    {Severity.LOW: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}
)
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
DEFAULT_REQUIRED = ("weather", "propulsion", "conjunction", "sequencer")


@dataclass(frozen=True)
class SubsystemVote:
    subsystem: str
    vote: Vote
    severity: Severity
    reason_code: str
    decided_at: float
    half_life_s: float = 30.0

    def fingerprint(self) -> str:
        return digest(
            {
                "subsystem": self.subsystem,
                "vote": self.vote.value,
                "severity": self.severity.value,
                "reason_code": self.reason_code,
                "decided_at": self.decided_at,
                "half_life_s": self.half_life_s,
            }
        )

    def live(self, now: float) -> bool:
        return self.decided_at <= now <= self.decided_at + self.half_life_s

    def future(self, now: float) -> bool:
        return now < self.decided_at

    def stale(self, now: float) -> bool:
        return now > self.decided_at + self.half_life_s


@dataclass(frozen=True)
class QuorumReceipt:
    state: StackState
    hold_reason: str | None
    live_votes: dict[str, dict[str, object]]
    stale_subsystems: tuple[str, ...]
    future_subsystems: tuple[str, ...]
    missing_subsystems: tuple[str, ...]
    evaluation_time: float
    policy_fingerprint: str
    fingerprint: str


@dataclass(frozen=True)
class CastRecord:
    seq: int
    vote: SubsystemVote
    vote_fingerprint: str


class MissionThreadQuorum:
    def __init__(
        self,
        required: Sequence[str] = DEFAULT_REQUIRED,
        freeze_at: Severity = Severity.HIGH,
    ) -> None:
        if not required:
            raise ValueError("required subsystems cannot be empty")
        if any(not subsystem.strip() or not _TOKEN_RE.match(subsystem) for subsystem in required):
            raise ValueError("required subsystem names must be non-empty machine-safe tokens")
        if len(required) != len(set(required)):
            raise ValueError("required subsystems must be unique")
        if not isinstance(freeze_at, Severity):
            raise ValueError("freeze_at must be a Severity")

        self.required = tuple(required)
        self.freeze_at = freeze_at
        self.policy_fingerprint = digest(
            {
                "required": list(self.required),
                "freeze_at": self.freeze_at.value,
                "freshness": "decided_at<=now<=decided_at+half_life_s",
                "non_monotonic_supersession": "refuse",
                "unknown_subsystem_cast": "refuse",
            }
        )
        self._votes: dict[str, SubsystemVote] = {}
        self._history: list[CastRecord] = []
        self._lock = threading.RLock()
        self._seq = 0

    @staticmethod
    def _validate_vote(vote: SubsystemVote) -> None:
        if not vote.subsystem.strip() or not _TOKEN_RE.match(vote.subsystem):
            raise ValueError("subsystem must be a non-empty machine-safe token")
        if not isinstance(vote.vote, Vote):
            raise ValueError("vote must be a Vote")
        if not isinstance(vote.severity, Severity):
            raise ValueError("severity must be a Severity")
        if not vote.reason_code.strip() or not _TOKEN_RE.match(vote.reason_code):
            raise ValueError("reason_code must be a non-empty machine-safe token")
        if not math.isfinite(vote.decided_at):
            raise ValueError("decided_at must be finite")
        if not math.isfinite(vote.half_life_s) or vote.half_life_s <= 0:
            raise ValueError("half_life_s must be finite and positive")

    def cast(self, vote: SubsystemVote) -> CastRecord:
        """Record a strictly newer decision for a configured subsystem.

        Cast order may never rewrite newer decision-time state with an older or
        equal-timestamp decision. This keeps supersession causal rather than
        dependent on transport arrival order.
        """
        self._validate_vote(vote)
        if vote.subsystem not in self.required:
            raise ValueError(f"subsystem is not in required quorum: {vote.subsystem}")
        with self._lock:
            previous = self._votes.get(vote.subsystem)
            if previous is not None and vote.decided_at <= previous.decided_at:
                raise ValueError(
                    "decision time must strictly advance for subsystem supersession"
                )
            self._seq += 1
            self._votes[vote.subsystem] = vote
            record = CastRecord(self._seq, vote, vote.fingerprint())
            self._history.append(record)
            return record

    def history(self) -> tuple[CastRecord, ...]:
        with self._lock:
            return tuple(self._history)

    @staticmethod
    def _vote_view(vote: SubsystemVote) -> dict[str, object]:
        return {
            "vote": vote.vote.value,
            "severity": vote.severity.value,
            "reason_code": vote.reason_code,
            "decided_at": vote.decided_at,
            "half_life_s": vote.half_life_s,
            "vote_fingerprint": vote.fingerprint(),
        }

    def _receipt(
        self,
        *,
        state: StackState,
        hold_reason: str | None,
        live: Mapping[str, SubsystemVote],
        stale: tuple[str, ...],
        future: tuple[str, ...],
        missing: tuple[str, ...],
        now: float,
    ) -> QuorumReceipt:
        live_votes = {
            subsystem: self._vote_view(live[subsystem])
            for subsystem in self.required
            if subsystem in live
        }
        body = {
            "state": state.value,
            "hold_reason": hold_reason,
            "required": list(self.required),
            "freeze_at": self.freeze_at.value,
            "policy_fingerprint": self.policy_fingerprint,
            "evaluation_time": now,
            "live_votes": live_votes,
            "stale_subsystems": list(stale),
            "future_subsystems": list(future),
            "missing_subsystems": list(missing),
        }
        return QuorumReceipt(
            state=state,
            hold_reason=hold_reason,
            live_votes=live_votes,
            stale_subsystems=stale,
            future_subsystems=future,
            missing_subsystems=missing,
            evaluation_time=now,
            policy_fingerprint=self.policy_fingerprint,
            fingerprint=digest(body),
        )

    def evaluate(self, now: float) -> QuorumReceipt:
        if not math.isfinite(now):
            raise ValueError("evaluation time must be finite")
        with self._lock:
            live = {
                subsystem: vote
                for subsystem, vote in self._votes.items()
                if vote.live(now)
            }
            stale = tuple(
                subsystem
                for subsystem in self.required
                if (vote := self._votes.get(subsystem)) is not None and vote.stale(now)
            )
            future = tuple(
                subsystem
                for subsystem in self.required
                if (vote := self._votes.get(subsystem)) is not None and vote.future(now)
            )
            missing = tuple(
                subsystem for subsystem in self.required if subsystem not in live
            )

            if missing:
                reason_parts: list[str] = []
                if stale:
                    reason_parts.append(f"STALE:{','.join(stale)}")
                if future:
                    reason_parts.append(f"FUTURE:{','.join(future)}")
                never_seen = tuple(
                    subsystem for subsystem in missing if subsystem not in stale and subsystem not in future
                )
                if never_seen:
                    reason_parts.append(f"MISSING:{','.join(never_seen)}")
                hold_reason = ";".join(reason_parts) or "INCOMPLETE_QUORUM"
                return self._receipt(
                    state=StackState.INCOMPLETE,
                    hold_reason=hold_reason,
                    live=live,
                    stale=stale,
                    future=future,
                    missing=missing,
                    now=now,
                )

            freeze_hits: list[str] = []
            for subsystem in self.required:
                vote = live[subsystem]
                if (
                    vote.vote is Vote.NO_GO
                    and _SEV_RANK[vote.severity] >= _SEV_RANK[self.freeze_at]
                ):
                    freeze_hits.append(
                        f"{subsystem}:{vote.reason_code}:{vote.severity.value}"
                    )

            if freeze_hits:
                return self._receipt(
                    state=StackState.HOLD,
                    hold_reason=f"HOLD:{';'.join(freeze_hits)}",
                    live=live,
                    stale=stale,
                    future=future,
                    missing=(),
                    now=now,
                )

            if any(live[subsystem].vote is Vote.NO_GO for subsystem in self.required):
                return self._receipt(
                    state=StackState.NO_GO,
                    hold_reason="NO_GO_STACK",
                    live=live,
                    stale=stale,
                    future=future,
                    missing=(),
                    now=now,
                )

            if any(live[subsystem].vote is Vote.ABSTAIN for subsystem in self.required):
                return self._receipt(
                    state=StackState.INCOMPLETE,
                    hold_reason="ABSTAIN_PRESENT",
                    live=live,
                    stale=stale,
                    future=future,
                    missing=(),
                    now=now,
                )

            return self._receipt(
                state=StackState.GO,
                hold_reason=None,
                live=live,
                stale=stale,
                future=future,
                missing=(),
                now=now,
            )

    def residuals_for_hold(self, now: float) -> list[tuple[str, str, str]]:
        """Return live hold-capable NO_GO residuals in configured subsystem order."""
        if not math.isfinite(now):
            raise ValueError("evaluation time must be finite")
        with self._lock:
            out: list[tuple[str, str, str]] = []
            for subsystem in self.required:
                vote = self._votes.get(subsystem)
                if vote is None or not vote.live(now):
                    continue
                if (
                    vote.vote is Vote.NO_GO
                    and _SEV_RANK[vote.severity] >= _SEV_RANK[self.freeze_at]
                ):
                    out.append(
                        (
                            subsystem,
                            vote.reason_code,
                            f"severity={vote.severity.value}",
                        )
                    )
            return out
