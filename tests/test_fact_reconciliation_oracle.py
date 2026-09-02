import unittest
import json
import sys
import os

# Add contracts directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "contracts")))
from fact_reconciliation_oracle import FactReconciliationOracle, gl


class MockHttpResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


class TestFactReconciliationOracle(unittest.TestCase):

    def setUp(self):
        # Reset contract with standard test fee
        self.oracle = FactReconciliationOracle(min_fee=1000)
        gl.message.sender = "0xUserAlice1234567890"
        gl.message.value = 1000

    # -------------------------------------------------------------------------
    # TEST 1: Sources that clearly AGREE → Resolves Cleanly
    # -------------------------------------------------------------------------
    def test_sources_agree_resolves_cleanly(self):
        """
        Test Case 1: Multiple sources report matching factual data.
        Oracle must achieve consensus: status='resolved', confidence>=0.7, answer='150000'.
        """
        urls = [
            "https://news.example.com/spacex-starship-payload",
            "https://aerospace-tracker.org/starship-flight-data"
        ]
        q_id = self.oracle.register_question(
            text="Did SpaceX Starship successfully deploy the lunar satellite payload?",
            resolution_date="2026-06-01T00:00:00Z",
            source_urls=urls
        )

        # Mock web responses agreeing on the outcome
        def mock_web_get(url, headers=None):
            if "news.example.com" in url:
                return MockHttpResponse(
                    "SpaceX Starship successfully deployed the lunar satellite into orbit yesterday."
                )
            elif "aerospace-tracker.org" in url:
                return MockHttpResponse(
                    "Official Mission Update: Starship payload deployment confirmed successful."
                )
            return MockHttpResponse("Not found", 404)

        # Mock LLM consensus synthesis for agreeing sources
        def mock_exec_prompt(prompt):
            return json.dumps({
                "status": "resolved",
                "answer": "YES - Payload successfully deployed",
                "confidence": 0.95,
                "conflict_detected": False,
                "per_source_findings": {
                    urls[0]: "Reported successful deployment of lunar satellite into orbit.",
                    urls[1]: "Official tracker confirmed payload deployment successful."
                },
                "reasoning": "Both independent aerospace outlets corroborate successful deployment without contradiction."
            })

        # Inject mocks into gl.nondet
        gl.nondet.web.get = mock_web_get
        gl.nondet.exec_prompt = mock_exec_prompt

        # Execute resolution
        self.oracle.resolve_question(q_id)

        # Assertions
        result = self.oracle.get_resolution(q_id)
        self.assertEqual(result["question"]["status"], "resolved")
        self.assertEqual(result["resolution"]["status"], "resolved")
        self.assertFalse(result["resolution"]["conflict_detected"])
        self.assertGreaterEqual(result["resolution"]["confidence"], 0.70)
        self.assertIn("YES", result["resolution"]["answer"])
        self.assertEqual(len(result["resolution"]["per_source_findings"]), 2)

    # -------------------------------------------------------------------------
    # TEST 2: Sources that clearly CONFLICT → Returns Unresolved (Crucial Test)
    # -------------------------------------------------------------------------
    def test_sources_conflict_returns_unresolved_not_forced_answer(self):
        """
        Test Case 2 (THE CORE PRIMITIVE TEST):
        Source A claims 'The merger was officially approved'.
        Source B claims 'The regulator vetoed and blocked the merger'.
        Oracle MUST return status='unresolved', conflict_detected=True, answer='CONFLICTING_SOURCES'.
        It must NEVER force a speculative consensus or average opposing claims.
        """
        urls = [
            "https://finance-daily.com/acme-merger-approved",
            "https://regulatory-watch.gov/acme-merger-blocked"
        ]
        q_id = self.oracle.register_question(
            text="Was the Acme-Globex merger approved by the regulatory commission?",
            resolution_date="2026-07-15T00:00:00Z",
            source_urls=urls
        )

        def mock_web_get(url, headers=None):
            if "finance-daily.com" in url:
                return MockHttpResponse(
                    "Breaking: Acme-Globex merger receives full regulatory clearance and approval."
                )
            elif "regulatory-watch.gov" in url:
                return MockHttpResponse(
                    "Official Notice: Antitrust Commission issues formal injunction blocking Acme-Globex merger."
                )
            return MockHttpResponse("Not found", 404)

        # Mock LLM recognizing genuine contradiction between credible sources
        def mock_exec_prompt(prompt):
            return json.dumps({
                "status": "unresolved",
                "answer": "CONFLICTING_SOURCES",
                "confidence": 0.0,
                "conflict_detected": True,
                "per_source_findings": {
                    urls[0]: "States merger received full clearance.",
                    urls[1]: "States regulatory commission issued injunction blocking merger."
                },
                "reasoning": "Direct factual contradiction between financial news and regulatory notice. Consensus impossible."
            })

        gl.nondet.web.get = mock_web_get
        gl.nondet.exec_prompt = mock_exec_prompt

        # Execute resolution
        self.oracle.resolve_question(q_id)

        # Assertions
        result = self.oracle.get_resolution(q_id)
        self.assertEqual(result["question"]["status"], "unresolved")
        self.assertEqual(result["resolution"]["status"], "unresolved")
        self.assertTrue(result["resolution"]["conflict_detected"])
        self.assertEqual(result["resolution"]["answer"], "CONFLICTING_SOURCES")
        self.assertEqual(result["resolution"]["confidence"], 0.0)

    # -------------------------------------------------------------------------
    # TEST 3: Unreachable / Stale / Error Source → Degrades Gracefully
    # -------------------------------------------------------------------------
    def test_unreachable_source_degrades_gracefully(self):
        """
        Test Case 3: One source is down (500/timeout), but the remaining active source
        provides verifiable data without crashing the contract execution.
        """
        urls = [
            "https://broken-server.internal/timeout-endpoint",
            "https://reliable-mirror.org/election-winner"
        ]
        q_id = self.oracle.register_question(
            text="Who won the mayoral election in City X?",
            resolution_date="2026-08-01T00:00:00Z",
            source_urls=urls
        )

        def mock_web_get(url, headers=None):
            if "broken-server" in url:
                raise ConnectionResetError("Connection timed out after 5000ms")
            elif "reliable-mirror" in url:
                return MockHttpResponse(
                    "Official Election Results: Jane Doe declared winner with 58% of votes."
                )
            return MockHttpResponse("Error", 500)

        def mock_exec_prompt(prompt):
            # Prompt receives [FETCH_FAILED] for the broken source and processes available data
            return json.dumps({
                "status": "resolved",
                "answer": "Jane Doe",
                "confidence": 0.85,
                "conflict_detected": False,
                "per_source_findings": {
                    urls[0]: "[FETCH_FAILED]: Connection timed out after 5000ms",
                    urls[1]: "Official tally confirmed Jane Doe won with 58% of vote."
                },
                "reasoning": "One source was unreachable, but authoritative election mirror provided definitive result."
            })

        gl.nondet.web.get = mock_web_get
        gl.nondet.exec_prompt = mock_exec_prompt

        # Execute resolution — should not throw exception
        self.oracle.resolve_question(q_id)

        result = self.oracle.get_resolution(q_id)
        self.assertEqual(result["question"]["status"], "resolved")
        self.assertEqual(result["resolution"]["answer"], "Jane Doe")
        self.assertIn("[FETCH_FAILED]", result["resolution"]["per_source_findings"][urls[0]])

    # -------------------------------------------------------------------------
    # TEST 4: Anti-spam Fee Enforcement & Dispute Flow
    # -------------------------------------------------------------------------
    def test_fee_enforcement_and_dispute_flow(self):
        """
        Test anti-spam fee requirement and dispute re-triggering with supplementary source.
        """
        # Underpayment should rollback
        gl.message.value = 500  # Less than min_fee of 1000
        with self.assertRaises(gl.Rollback):
            self.oracle.register_question("Will tax rate change?", "2026-09-01", ["https://src1.org"])

        # Valid registration
        gl.message.value = 1000
        q_id = self.oracle.register_question(
            "Will tax rate change?",
            "2026-09-01",
            ["https://initial-source.com"]
        )

        # Initial mock resolution -> unresolved
        gl.nondet.web.get = lambda url, headers=None: MockHttpResponse("Information pending")
        gl.nondet.exec_prompt = lambda p: json.dumps({
            "status": "unresolved",
            "answer": "INSUFFICIENT_DATA",
            "confidence": 0.2,
            "conflict_detected": False,
            "per_source_findings": {"https://initial-source.com": "Information pending"},
            "reasoning": "Initial source had no definitive ruling."
        })
        self.oracle.resolve_question(q_id)
        self.assertEqual(self.oracle.get_resolution(q_id)["question"]["status"], "unresolved")

        # Challenger disputes and adds definitive government portal
        new_source = "https://gov-gazette.gov/tax-announcement"
        gl.nondet.web.get = lambda url, headers=None: MockHttpResponse(
            "Official Gazette: Tax rate will remain unchanged at 15%." if "gov-gazette" in url else "Pending"
        )
        gl.nondet.exec_prompt = lambda p: json.dumps({
            "status": "resolved",
            "answer": "Tax rate unchanged at 15%",
            "confidence": 0.95,
            "conflict_detected": False,
            "per_source_findings": {
                "https://initial-source.com": "Pending",
                new_source: "Confirmed rate unchanged at 15%."
            },
            "reasoning": "Official government gazette provided definitive confirmation."
        })

        self.oracle.dispute_resolution(
            question_id=q_id,
            reason="Official gazette was omitted in initial source set",
            additional_sources=[new_source]
        )

        res = self.oracle.get_resolution(q_id)
        self.assertEqual(res["question"]["status"], "resolved")
        self.assertEqual(res["resolution"]["answer"], "Tax rate unchanged at 15%")
        self.assertEqual(res["dispute"]["status"], "settled")


if __name__ == "__main__":
    unittest.main()
