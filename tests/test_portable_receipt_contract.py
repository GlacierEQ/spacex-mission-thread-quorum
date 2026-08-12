from __future__ import annotations

import copy
import unittest

from src.portable_receipt import export_portable, verify_portable
from src.quorum import MissionThreadQuorum, Severity, StackState, SubsystemVote, Vote


class PortableReceiptContractTests(unittest.TestCase):
    def build(self):
        q = MissionThreadQuorum()
        q.cast(SubsystemVote("weather", Vote.NO_GO, Severity.HIGH, "WINDS", 101.0, 30.0))
        q.cast(SubsystemVote("propulsion", Vote.GO, Severity.LOW, "NOMINAL", 100.0, 30.0))
        q.cast(SubsystemVote("conjunction", Vote.GO, Severity.LOW, "CLEAR", 100.0, 30.0))
        q.cast(SubsystemVote("sequencer", Vote.GO, Severity.LOW, "READY", 100.0, 30.0))
        return q

    def test_portable_hold_reconstructs(self):
        q = self.build()
        portable = export_portable(q, q.evaluate(110.0))
        ok, reason = verify_portable(portable)
        self.assertTrue(ok, reason)
        self.assertEqual(portable["state"], StackState.HOLD.value)
        self.assertIn("weather:WINDS:HIGH", portable["hold_reason"])

    def test_state_tamper_refuses(self):
        q = self.build()
        portable = export_portable(q, q.evaluate(110.0))
        portable["state"] = StackState.GO.value
        portable["hold_reason"] = None
        ok, reason = verify_portable(portable)
        self.assertFalse(ok)
        self.assertEqual(reason, "PORTABLE_DECISION_MISMATCH")

    def test_vote_tamper_refuses(self):
        q = self.build()
        portable = export_portable(q, q.evaluate(110.0))
        portable["live_votes"]["weather"]["reason_code"] = "FORGED"
        ok, reason = verify_portable(portable)
        self.assertFalse(ok)
        self.assertEqual(reason, "PORTABLE_VOTE_FINGERPRINT_MISMATCH:weather")

    def test_missing_set_tamper_refuses(self):
        q = self.build()
        portable = export_portable(q, q.evaluate(110.0))
        portable["missing_subsystems"] = ["weather"]
        ok, reason = verify_portable(portable)
        self.assertFalse(ok)
        self.assertEqual(reason, "PORTABLE_MISSING_SET_MISMATCH")

    def test_stale_receipt_reconstructs_as_incomplete(self):
        q = MissionThreadQuorum()
        q.cast(SubsystemVote("weather", Vote.GO, Severity.LOW, "OLD", 0.0, 10.0))
        q.cast(SubsystemVote("propulsion", Vote.GO, Severity.LOW, "NOMINAL", 95.0, 30.0))
        q.cast(SubsystemVote("conjunction", Vote.GO, Severity.LOW, "CLEAR", 95.0, 30.0))
        portable = export_portable(q, q.evaluate(100.0))
        ok, reason = verify_portable(portable)
        self.assertTrue(ok, reason)
        self.assertEqual(portable["state"], StackState.INCOMPLETE.value)
        self.assertIn("weather", portable["stale_subsystems"])
        self.assertIn("sequencer", portable["missing_subsystems"])


if __name__ == "__main__":
    unittest.main()
