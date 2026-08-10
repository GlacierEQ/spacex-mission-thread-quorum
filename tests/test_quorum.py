from __future__ import annotations

import unittest

from src.quorum import (
    DEFAULT_REQUIRED,
    MissionThreadQuorum,
    Severity,
    StackState,
    SubsystemVote,
    Vote,
)


def v(sub, vote, sev=Severity.LOW, t=100.0, code="OK", hl=30.0):
    return SubsystemVote(sub, vote, sev, code, t, half_life_s=hl)


class QuorumLeveledTests(unittest.TestCase):
    def _all_go(self, q: MissionThreadQuorum, *, t: float = 100.0) -> None:
        for subsystem in q.required:
            q.cast(v(subsystem, Vote.GO, t=t))

    def test_go(self):
        q = MissionThreadQuorum()
        self._all_go(q)
        r = q.evaluate(110.0)
        self.assertEqual(r.state, StackState.GO)
        self.assertEqual(r.missing_subsystems, ())
        self.assertEqual(r.future_subsystems, ())
        self.assertEqual(r.stale_subsystems, ())

    def test_high_no_hold(self):
        q = MissionThreadQuorum()
        self._all_go(q)
        q.cast(v("weather", Vote.NO_GO, Severity.HIGH, t=101.0, code="WINDS"))
        r = q.evaluate(110.0)
        self.assertEqual(r.state, StackState.HOLD)
        self.assertIn("WINDS", r.hold_reason or "")

    def test_critical_holds(self):
        q = MissionThreadQuorum(freeze_at=Severity.HIGH)
        self._all_go(q)
        q.cast(v("propulsion", Vote.NO_GO, Severity.CRITICAL, t=101.0, code="CHAMBER"))
        r = q.evaluate(110.0)
        self.assertEqual(r.state, StackState.HOLD)
        self.assertIn("CHAMBER", r.hold_reason or "")

    def test_stale_incomplete(self):
        q = MissionThreadQuorum()
        self._all_go(q, t=0.0)
        r = q.evaluate(1000.0)
        self.assertEqual(r.state, StackState.INCOMPLETE)
        self.assertEqual(set(r.stale_subsystems), set(DEFAULT_REQUIRED))
        self.assertEqual(set(r.missing_subsystems), set(DEFAULT_REQUIRED))

    def test_future_votes_do_not_count_as_live(self):
        q = MissionThreadQuorum()
        self._all_go(q, t=200.0)
        r = q.evaluate(100.0)
        self.assertEqual(r.state, StackState.INCOMPLETE)
        self.assertEqual(set(r.future_subsystems), set(DEFAULT_REQUIRED))
        self.assertEqual(set(r.missing_subsystems), set(DEFAULT_REQUIRED))
        self.assertIn("FUTURE:", r.hold_reason or "")

    def test_low_nogo_is_nogo_not_hold(self):
        q = MissionThreadQuorum(freeze_at=Severity.HIGH)
        self._all_go(q)
        q.cast(v("weather", Vote.NO_GO, Severity.LOW, t=101.0, code="GUSTY"))
        r = q.evaluate(110.0)
        self.assertEqual(r.state, StackState.NO_GO)

    def test_abstain_incomplete(self):
        q = MissionThreadQuorum()
        for subsystem in DEFAULT_REQUIRED:
            q.cast(v(subsystem, Vote.GO if subsystem != "sequencer" else Vote.ABSTAIN))
        r = q.evaluate(110.0)
        self.assertEqual(r.state, StackState.INCOMPLETE)
        self.assertEqual(r.hold_reason, "ABSTAIN_PRESENT")

    def test_vote_supersession(self):
        q = MissionThreadQuorum()
        self._all_go(q, t=100.0)
        q.cast(v("weather", Vote.NO_GO, Severity.HIGH, t=101.0, code="WINDS"))
        q.cast(v("weather", Vote.GO, t=102.0, code="CLEAR"))
        r = q.evaluate(110.0)
        self.assertEqual(r.state, StackState.GO)

    def test_older_arrival_cannot_rewrite_newer_decision(self):
        q = MissionThreadQuorum()
        q.cast(v("weather", Vote.GO, t=102.0, code="CLEAR"))
        with self.assertRaisesRegex(ValueError, "strictly advance"):
            q.cast(v("weather", Vote.NO_GO, Severity.HIGH, t=101.0, code="WINDS"))
        self.assertEqual(q.history()[-1].vote.reason_code, "CLEAR")

    def test_equal_timestamp_cannot_rewrite_decision(self):
        q = MissionThreadQuorum()
        q.cast(v("weather", Vote.GO, t=100.0, code="CLEAR"))
        with self.assertRaisesRegex(ValueError, "strictly advance"):
            q.cast(v("weather", Vote.NO_GO, Severity.HIGH, t=100.0, code="WINDS"))

    def test_custom_required(self):
        q = MissionThreadQuorum(required=("a", "b"))
        q.cast(v("a", Vote.GO))
        r = q.evaluate(110.0)
        self.assertEqual(r.missing_subsystems, ("b",))

    def test_unknown_subsystem_refused(self):
        q = MissionThreadQuorum()
        with self.assertRaisesRegex(ValueError, "not in required quorum"):
            q.cast(v("unknown", Vote.GO))

    def test_duplicate_required_subsystem_refused(self):
        with self.assertRaisesRegex(ValueError, "must be unique"):
            MissionThreadQuorum(required=("weather", "weather"))

    def test_history_records_casts_and_vote_fingerprints(self):
        q = MissionThreadQuorum()
        first = q.cast(v("weather", Vote.GO, t=100.0))
        second = q.cast(v("weather", Vote.NO_GO, Severity.HIGH, t=101.0, code="W"))
        self.assertEqual(len(q.history()), 2)
        self.assertEqual(len(first.vote_fingerprint), 64)
        self.assertNotEqual(first.vote_fingerprint, second.vote_fingerprint)

    def test_residuals_for_hold(self):
        q = MissionThreadQuorum()
        self._all_go(q)
        q.cast(v("weather", Vote.NO_GO, Severity.HIGH, t=101.0, code="WINDS"))
        res = q.residuals_for_hold(110.0)
        self.assertEqual(res[0][0], "weather")
        self.assertEqual(res[0][1], "WINDS")

    def test_receipt_fingerprint_stable_for_identical_state(self):
        q = MissionThreadQuorum()
        self._all_go(q)
        first = q.evaluate(110.0)
        second = q.evaluate(110.0)
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(len(first.fingerprint), 64)
        self.assertEqual(first.policy_fingerprint, q.policy_fingerprint)

    def test_receipt_binds_vote_evidence(self):
        q = MissionThreadQuorum()
        self._all_go(q)
        before = q.evaluate(110.0)
        q.cast(v("weather", Vote.GO, t=101.0, code="RECONFIRMED"))
        after = q.evaluate(110.0)
        self.assertEqual(before.state, after.state)
        self.assertNotEqual(before.fingerprint, after.fingerprint)
        self.assertNotEqual(
            before.live_votes["weather"]["vote_fingerprint"],
            after.live_votes["weather"]["vote_fingerprint"],
        )

    def test_receipt_binds_policy(self):
        high = MissionThreadQuorum(freeze_at=Severity.HIGH)
        critical = MissionThreadQuorum(freeze_at=Severity.CRITICAL)
        self._all_go(high)
        self._all_go(critical)
        high_receipt = high.evaluate(110.0)
        critical_receipt = critical.evaluate(110.0)
        self.assertEqual(high_receipt.state, critical_receipt.state)
        self.assertNotEqual(high_receipt.policy_fingerprint, critical_receipt.policy_fingerprint)
        self.assertNotEqual(high_receipt.fingerprint, critical_receipt.fingerprint)

    def test_non_finite_evaluation_time_refused(self):
        q = MissionThreadQuorum()
        with self.assertRaisesRegex(ValueError, "evaluation time must be finite"):
            q.evaluate(float("nan"))


if __name__ == "__main__":
    unittest.main()
