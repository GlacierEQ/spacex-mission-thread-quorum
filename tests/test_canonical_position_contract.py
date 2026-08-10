from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: str):
    return json.loads((ROOT / path).read_text())


CANONICAL = load("machine/canonical-position.json")
CAPABILITIES = load("machine/capabilities.json")
TARGET = load("machine/target-contract.json")
STATE = load("machine/excellence-state.json")
PROOF = load("machine/canonical-position-proof.json")


class CanonicalPositionContractTests(unittest.TestCase):
    def test_repository_owns_quorum_aggregation_not_flight_authority(self):
        self.assertEqual(CANONICAL["role"], "CANONICAL_SPECIALIST")
        self.assertEqual(
            CANONICAL["owns"],
            "freshness_bound_multi_subsystem_quorum_aggregation",
        )
        self.assertIn(
            "real flight safety or launch go/no-go authority",
            CANONICAL["does_not_own"],
        )
        self.assertIn(
            "hold clearance or hardware actuation",
            CANONICAL["does_not_own"],
        )

    def test_hold_compiler_relationship_is_not_inflated_to_integration(self):
        edge = CANONICAL["relationships"][0]
        self.assertEqual(
            edge["repository"], "GlacierEQ/spacex-hold-reason-compiler"
        )
        self.assertFalse(edge["integration_exercised"])

    def test_capabilities_are_repository_native(self):
        capabilities = set(CAPABILITIES["capabilities"])
        self.assertNotIn("hyper-scaling", capabilities)
        self.assertIn("freshness_bounded_vote_authority", capabilities)
        self.assertIn("strictly_monotonic_vote_supersession", capabilities)
        self.assertIn("future_stale_missing_vote_separation", capabilities)
        self.assertIn("terminal_quorum_decision_receipt", capabilities)

    def test_machine_state_is_evolving_after_exact_proof(self):
        self.assertEqual(TARGET["current"]["state"], "EVOLVING")
        self.assertTrue(TARGET["current"]["canonical_position_resolved"])
        self.assertEqual(STATE["principal_state"], "EVOLVING")
        self.assertEqual(
            STATE["gates"]["CANONICAL_POSITION_RESOLVED"]["status"], "PASS"
        )

    def test_proof_binds_exact_tested_source_and_run(self):
        self.assertEqual(
            PROOF["source_sha"],
            "853882c0e4c4993718b6f4ce3c2cbdc336ba857a",
        )
        self.assertEqual(PROOF["workflow"]["run_id"], 31398267420)
        self.assertEqual(PROOF["workflow"]["conclusion"], "success")

    def test_truth_boundary_excludes_operational_claims(self):
        boundary = CAPABILITIES["truth_boundary"]
        self.assertIn("does not authenticate voters or telemetry", boundary)
        self.assertIn("decide real flight safety", boundary)
        self.assertIn("actuate hardware", boundary)
        self.assertIn("operate SpaceX systems", boundary)


if __name__ == "__main__":
    unittest.main()
