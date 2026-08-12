"""Portable serialization/verifier for MissionThreadQuorum receipts.

This adapter preserves the existing quorum engine while adding the policy facts
that its current dataclass does not serialize (`required` and `freeze_at`). A
downstream process can therefore reconstruct the existing receipt fingerprint
and decision without importing the producer instance.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

try:
    from .quorum import (
        MissionThreadQuorum,
        QuorumReceipt,
        Severity,
        StackState,
        SubsystemVote,
        Vote,
        _SEV_RANK,
        digest,
    )
except ImportError:
    from quorum import (
        MissionThreadQuorum,
        QuorumReceipt,
        Severity,
        StackState,
        SubsystemVote,
        Vote,
        _SEV_RANK,
        digest,
    )

SCHEMA = "glaciereq.mission-thread-quorum-portable.v1"


def export_portable(quorum: MissionThreadQuorum, receipt: QuorumReceipt) -> dict[str, Any]:
    """Bind an existing receipt to the quorum policy that produced it."""
    if receipt.policy_fingerprint != quorum.policy_fingerprint:
        raise ValueError("receipt_policy_does_not_match_quorum")
    return {
        "schema": SCHEMA,
        "state": receipt.state.value,
        "hold_reason": receipt.hold_reason,
        "required_subsystems": list(quorum.required),
        "freeze_at": quorum.freeze_at.value,
        "live_votes": receipt.live_votes,
        "stale_subsystems": list(receipt.stale_subsystems),
        "future_subsystems": list(receipt.future_subsystems),
        "missing_subsystems": list(receipt.missing_subsystems),
        "evaluation_time": receipt.evaluation_time,
        "policy_fingerprint": receipt.policy_fingerprint,
        "receipt_fingerprint": receipt.fingerprint,
    }


def _policy_fingerprint(required: list[str], freeze_at: Severity) -> str:
    return digest({
        "required": required,
        "freeze_at": freeze_at.value,
        "freshness": "decided_at<=now<=decided_at+half_life_s",
        "non_monotonic_supersession": "refuse",
        "unknown_subsystem_cast": "refuse",
    })


def verify_portable(receipt: Mapping[str, Any]) -> tuple[bool, str | None]:
    if receipt.get("schema") != SCHEMA:
        return False, "PORTABLE_SCHEMA_MISMATCH"
    required = receipt.get("required_subsystems")
    live_votes = receipt.get("live_votes")
    stale = receipt.get("stale_subsystems")
    future = receipt.get("future_subsystems")
    missing = receipt.get("missing_subsystems")
    now = receipt.get("evaluation_time")
    if not isinstance(required, list) or not required or not all(isinstance(x, str) and x for x in required):
        return False, "PORTABLE_REQUIRED_INVALID"
    if len(required) != len(set(required)):
        return False, "PORTABLE_REQUIRED_DUPLICATE"
    try:
        freeze_at = Severity(receipt.get("freeze_at"))
        declared_state = StackState(receipt.get("state"))
    except (ValueError, TypeError):
        return False, "PORTABLE_ENUM_INVALID"
    if not isinstance(now, (int, float)) or not math.isfinite(float(now)):
        return False, "PORTABLE_TIME_INVALID"
    if not isinstance(live_votes, Mapping) or not all(isinstance(x, list) for x in (stale, future, missing)):
        return False, "PORTABLE_SHAPE_INVALID"

    required_set = set(required)
    if set(missing) != required_set - set(live_votes):
        return False, "PORTABLE_MISSING_SET_MISMATCH"
    if not set(stale) <= set(missing) or not set(future) <= set(missing) or set(stale) & set(future):
        return False, "PORTABLE_FRESHNESS_SET_MISMATCH"

    normalized_live: dict[str, dict[str, object]] = {}
    for subsystem in required:
        if subsystem not in live_votes:
            continue
        raw = live_votes[subsystem]
        if not isinstance(raw, Mapping):
            return False, f"PORTABLE_VOTE_INVALID:{subsystem}"
        try:
            vote = SubsystemVote(
                subsystem=subsystem,
                vote=Vote(raw.get("vote")),
                severity=Severity(raw.get("severity")),
                reason_code=str(raw.get("reason_code") or ""),
                decided_at=float(raw.get("decided_at")),
                half_life_s=float(raw.get("half_life_s")),
            )
            MissionThreadQuorum._validate_vote(vote)
        except (ValueError, TypeError):
            return False, f"PORTABLE_VOTE_INVALID:{subsystem}"
        if not vote.live(float(now)):
            return False, f"PORTABLE_VOTE_NOT_LIVE:{subsystem}"
        view = MissionThreadQuorum._vote_view(vote)
        if raw.get("vote_fingerprint") != view["vote_fingerprint"]:
            return False, f"PORTABLE_VOTE_FINGERPRINT_MISMATCH:{subsystem}"
        normalized_live[subsystem] = view

    policy_fp = _policy_fingerprint(required, freeze_at)
    if receipt.get("policy_fingerprint") != policy_fp:
        return False, "PORTABLE_POLICY_FINGERPRINT_MISMATCH"

    if missing:
        parts = []
        if stale:
            parts.append(f"STALE:{','.join(stale)}")
        if future:
            parts.append(f"FUTURE:{','.join(future)}")
        never_seen = [s for s in missing if s not in stale and s not in future]
        if never_seen:
            parts.append(f"MISSING:{','.join(never_seen)}")
        state, reason = StackState.INCOMPLETE, ";".join(parts) or "INCOMPLETE_QUORUM"
    else:
        freeze_hits = []
        for subsystem in required:
            raw = normalized_live[subsystem]
            if raw["vote"] == Vote.NO_GO.value and _SEV_RANK[Severity(raw["severity"])] >= _SEV_RANK[freeze_at]:
                freeze_hits.append(f"{subsystem}:{raw['reason_code']}:{raw['severity']}")
        if freeze_hits:
            state, reason = StackState.HOLD, f"HOLD:{';'.join(freeze_hits)}"
        elif any(normalized_live[s]["vote"] == Vote.NO_GO.value for s in required):
            state, reason = StackState.NO_GO, "NO_GO_STACK"
        elif any(normalized_live[s]["vote"] == Vote.ABSTAIN.value for s in required):
            state, reason = StackState.INCOMPLETE, "ABSTAIN_PRESENT"
        else:
            state, reason = StackState.GO, None

    if declared_state is not state or receipt.get("hold_reason") != reason:
        return False, "PORTABLE_DECISION_MISMATCH"

    body = {
        "state": state.value,
        "hold_reason": reason,
        "required": required,
        "freeze_at": freeze_at.value,
        "policy_fingerprint": policy_fp,
        "evaluation_time": now,
        "live_votes": normalized_live,
        "stale_subsystems": list(stale),
        "future_subsystems": list(future),
        "missing_subsystems": list(missing),
    }
    if receipt.get("receipt_fingerprint") != digest(body):
        return False, "PORTABLE_RECEIPT_FINGERPRINT_MISMATCH"
    return True, None
