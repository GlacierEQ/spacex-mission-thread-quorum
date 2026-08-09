
from __future__ import annotations
import unittest
from src.quorum import (
    MissionThreadQuorum, Severity, StackState, SubsystemVote, Vote, DEFAULT_REQUIRED,
)

def v(sub, vote, sev=Severity.LOW, t=100.0, code="OK", hl=30.0):
    return SubsystemVote(sub, vote, sev, code, t, half_life_s=hl)

class QuorumLeveledTests(unittest.TestCase):
    def test_go(self):
        q = MissionThreadQuorum()
        for s in DEFAULT_REQUIRED:
            q.cast(v(s, Vote.GO))
        r = q.evaluate(110.0)
        self.assertEqual(r.state, StackState.GO)
        self.assertEqual(r.missing_subsystems, ())

    def test_high_no_hold(self):
        q = MissionThreadQuorum()
        for s in DEFAULT_REQUIRED:
            q.cast(v(s, Vote.GO))
        q.cast(v("weather", Vote.NO_GO, Severity.HIGH, code="WINDS"))
        r = q.evaluate(110.0)
        self.assertEqual(r.state, StackState.HOLD)
        self.assertIn("WINDS", r.hold_reason or "")

    def test_critical_holds(self):
        q = MissionThreadQuorum(freeze_at=Severity.HIGH)
        for s in DEFAULT_REQUIRED:
            q.cast(v(s, Vote.GO))
        q.cast(v("propulsion", Vote.NO_GO, Severity.CRITICAL, code="CHAMBER"))
        r = q.evaluate(110.0)
        self.assertEqual(r.state, StackState.HOLD)
        self.assertIn("CHAMBER", r.hold_reason or "")

    def test_stale_incomplete(self):
        q = MissionThreadQuorum()
        for s in DEFAULT_REQUIRED:
            q.cast(v(s, Vote.GO, t=0.0, hl=10.0))
        r = q.evaluate(1000.0)
        self.assertEqual(r.state, StackState.INCOMPLETE)
        self.assertEqual(set(r.stale_subsystems), set(DEFAULT_REQUIRED))

    def test_low_nogo_is_nogo_not_hold(self):
        q = MissionThreadQuorum(freeze_at=Severity.HIGH)
        for s in DEFAULT_REQUIRED:
            q.cast(v(s, Vote.GO))
        q.cast(v("weather", Vote.NO_GO, Severity.LOW, code="GUSTY"))
        r = q.evaluate(110.0)
        self.assertEqual(r.state, StackState.NO_GO)

    def test_abstain_incomplete(self):
        q = MissionThreadQuorum()
        for s in DEFAULT_REQUIRED:
            q.cast(v(s, Vote.GO if s != "sequencer" else Vote.ABSTAIN))
        r = q.evaluate(110.0)
        self.assertEqual(r.state, StackState.INCOMPLETE)
        self.assertEqual(r.hold_reason, "ABSTAIN_PRESENT")

    def test_vote_supersession(self):
        q = MissionThreadQuorum()
        for s in DEFAULT_REQUIRED:
            q.cast(v(s, Vote.GO, t=100.0))
        q.cast(v("weather", Vote.NO_GO, Severity.HIGH, t=101.0, code="WINDS"))
        q.cast(v("weather", Vote.GO, t=102.0, code="CLEAR"))
        r = q.evaluate(110.0)
        self.assertEqual(r.state, StackState.GO)

    def test_custom_required(self):
        q = MissionThreadQuorum(required=("a", "b"))
        q.cast(v("a", Vote.GO))
        r = q.evaluate(110.0)
        self.assertEqual(r.missing_subsystems, ("b",))

    def test_history_records_casts(self):
        q = MissionThreadQuorum()
        q.cast(v("weather", Vote.GO))
        q.cast(v("weather", Vote.NO_GO, Severity.HIGH, code="W"))
        self.assertEqual(len(q.history()), 2)

    def test_residuals_for_hold(self):
        q = MissionThreadQuorum()
        for s in DEFAULT_REQUIRED:
            q.cast(v(s, Vote.GO))
        q.cast(v("weather", Vote.NO_GO, Severity.HIGH, code="WINDS"))
        res = q.residuals_for_hold(110.0)
        self.assertEqual(res[0][0], "weather")
        self.assertEqual(res[0][1], "WINDS")

    def test_receipt_fingerprint_stable(self):
        q = MissionThreadQuorum()
        for s in DEFAULT_REQUIRED:
            q.cast(v(s, Vote.GO))
        r = q.evaluate(110.0)
        self.assertEqual(r.fingerprint, r.fingerprint)
        self.assertEqual(len(r.fingerprint), 64)

if __name__ == "__main__":
    unittest.main()
