from __future__ import annotations
import unittest
from src.quorum import MissionThreadQuorum, Severity, StackState, SubsystemVote, Vote

def v(sub, vote, sev=Severity.LOW, t=100.0, code="OK"):
    return SubsystemVote(sub, vote, sev, code, t)

class QuorumTests(unittest.TestCase):
    def test_go(self):
        q = MissionThreadQuorum()
        for s in ("weather", "propulsion", "conjunction", "sequencer"):
            q.cast(v(s, Vote.GO))
        r = q.evaluate(110.0)
        self.assertEqual(r.state, StackState.GO)

    def test_high_no_hold(self):
        q = MissionThreadQuorum()
        for s in ("weather", "propulsion", "conjunction", "sequencer"):
            q.cast(v(s, Vote.GO))
        q.cast(v("weather", Vote.NO_GO, Severity.HIGH, code="WINDS"))
        r = q.evaluate(110.0)
        self.assertEqual(r.state, StackState.HOLD)
        self.assertIn("WINDS", r.hold_reason or "")

    def test_stale_incomplete(self):
        q = MissionThreadQuorum()
        for s in ("weather", "propulsion", "conjunction", "sequencer"):
            q.cast(v(s, Vote.GO, t=0.0))
        r = q.evaluate(1000.0)
        self.assertEqual(r.state, StackState.INCOMPLETE)

if __name__ == "__main__":
    unittest.main()
