import unittest
import json
import sys
import os
import types

# Provide mock genlayer environment shim if genlayer is not installed in local python environment
if "genlayer" not in sys.modules:
    genlayer_mod = types.ModuleType("genlayer")

    class _WriteDecorator:
        def __call__(self, f):
            return f
        @staticmethod
        def payable(f):
            return f

    class _MockGl:
        class public:
            @staticmethod
            def view(f):
                return f
            write = _WriteDecorator()

        class message:
            sender_address = "0x0000000000000000000000000000000000000001"
            value = 1000000000000000
        class Rollback(Exception):
            pass
        class Contract:
            pass
        class nondet:
            class web:
                @staticmethod
                def get(url, headers=None):
                    raise NotImplementedError("Direct mode test must mock gl.nondet.web.get")
            @staticmethod
            def exec_prompt(prompt):
                raise NotImplementedError("Direct mode test must mock gl.nondet.exec_prompt")
        class vm:
            class Return:
                def __init__(self, calldata):
                    self.calldata = calldata
            class UserError(Exception):
                pass
            class VMError(Exception):
                pass

            @staticmethod
            def run_nondet_unsafe(leader_fn, validator_fn):
                leader_val = leader_fn()
                leader_res = _MockGl.vm.Return(leader_val)
                is_valid = validator_fn(leader_res)
                if not is_valid:
                    raise _MockGl.Rollback("Validator rejected candidate: factual answer does not match independently verified evidence")
                return leader_val

        class eq_principle:
            @staticmethod
            def prompt_non_comparative(*args, **kwargs):
                fn = kwargs.get("task") or kwargs.get("func") or (args[0] if args else None)
                return fn() if callable(fn) else ""

    class _MockTreeMap(dict):
        pass

    class _MockDynArray(list):
        pass

    class _MockU256(int):
        pass

    class _MockAddress(str):
        pass

    genlayer_mod.gl = _MockGl()
    genlayer_mod.TreeMap = _MockTreeMap
    genlayer_mod.DynArray = _MockDynArray
    genlayer_mod.u256 = _MockU256
    genlayer_mod.Address = _MockAddress
    genlayer_mod.Rollback = _MockGl.Rollback

    sys.modules["genlayer"] = genlayer_mod

# Add contracts directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "contracts")))
from genlayer import gl, u256
from fact_reconciliation_oracle import FactReconciliationOracle


class MockHttpResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code


class TestFactReconciliationOracle(unittest.TestCase):

    def setUp(self):
        # Reset contract with standard test fee
        self.oracle = FactReconciliationOracle()
        self.oracle.min_fee = u256(1000)
        gl.message.sender_address = "0xUserAlice1234567890"
        gl.message.value = u256(1000)

    # -------------------------------------------------------------------------
    # TEST 1: Sources that clearly AGREE -> Resolves Cleanly
    # -------------------------------------------------------------------------
    def test_sources_agree_resolves_cleanly(self):
        """
        Test Case 1: Multiple sources report matching factual data.
        Leader proposes resolved candidate; validator independently acquires sources,
        verifies evidence corroboration, and accepts.
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

        # Mock LLM handling both leader synthesis and validator independent verification
        def mock_exec_prompt(prompt):
            if "objective consensus leader" in prompt:
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
            elif "independent consensus validator" in prompt:
                return json.dumps({
                    "is_valid": True,
                    "reason": "Independently verified: both fetched sources confirm successful deployment."
                })
            return "{}"

        # Inject mocks into gl.nondet
        gl.nondet.web.get = mock_web_get
        gl.nondet.exec_prompt = mock_exec_prompt

        # Execute resolution
        self.oracle.resolve_question(q_id)

        # Assertions
        result = json.loads(self.oracle.get_resolution(q_id))
        self.assertEqual(result["question"]["status"], "resolved")
        self.assertEqual(result["resolution"]["status"], "resolved")
        self.assertFalse(result["resolution"]["conflict_detected"])
        self.assertGreaterEqual(result["resolution"]["confidence"], 0.70)
        self.assertIn("YES", result["resolution"]["answer"])
        self.assertEqual(len(result["resolution"]["per_source_findings"]), 2)

    # -------------------------------------------------------------------------
    # TEST 2: Sources that clearly CONFLICT -> Returns Unresolved
    # -------------------------------------------------------------------------
    def test_sources_conflict_returns_unresolved_not_forced_answer(self):
        """
        Test Case 2 (CONFLICT RESOLUTION):
        Source A claims 'The merger was officially approved'.
        Source B claims 'The regulator vetoed and blocked the merger'.
        Leader reports conflict; validator independently fetches both sources,
        verifies that genuine conflict exists, and accepts unresolved status.
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

        def mock_exec_prompt(prompt):
            if "objective consensus leader" in prompt:
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
            elif "independent consensus validator" in prompt:
                return json.dumps({
                    "is_valid": True,
                    "reason": "Independently verified: sources directly contradict each other. Unresolved status is correct."
                })
            return "{}"

        gl.nondet.web.get = mock_web_get
        gl.nondet.exec_prompt = mock_exec_prompt

        # Execute resolution
        self.oracle.resolve_question(q_id)

        # Assertions
        result = json.loads(self.oracle.get_resolution(q_id))
        self.assertEqual(result["question"]["status"], "unresolved")
        self.assertEqual(result["resolution"]["status"], "unresolved")
        self.assertTrue(result["resolution"]["conflict_detected"])
        self.assertEqual(result["resolution"]["answer"], "CONFLICTING_SOURCES")
        self.assertEqual(result["resolution"]["confidence"], 0.0)

    # -------------------------------------------------------------------------
    # TEST 3: Unreachable / Stale / Error Source -> Degrades Gracefully
    # -------------------------------------------------------------------------
    def test_unreachable_source_degrades_gracefully(self):
        """
        Test Case 3: One source is down (500/timeout), but the remaining active source
        provides verifiable data without crashing either leader or validator.
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
            if "objective consensus leader" in prompt:
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
            elif "independent consensus validator" in prompt:
                return json.dumps({
                    "is_valid": True,
                    "reason": "Independently verified: reliable mirror unambiguously confirms Jane Doe winner."
                })
            return "{}"

        gl.nondet.web.get = mock_web_get
        gl.nondet.exec_prompt = mock_exec_prompt

        # Execute resolution — should not throw exception
        self.oracle.resolve_question(q_id)

        result = json.loads(self.oracle.get_resolution(q_id))
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
        gl.message.value = u256(500)  # Less than min_fee of 1000
        with self.assertRaises(gl.Rollback):
            self.oracle.register_question("Will tax rate change?", "2026-09-01", ["https://src1.org"])

        # Valid registration
        gl.message.value = u256(1000)
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
        }) if "objective consensus leader" in p else json.dumps({
            "is_valid": True,
            "reason": "Independently verified insufficient data."
        })
        self.oracle.resolve_question(q_id)
        self.assertEqual(json.loads(self.oracle.get_resolution(q_id))["question"]["status"], "unresolved")

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
        }) if "objective consensus leader" in p else json.dumps({
            "is_valid": True,
            "reason": "Independently verified official gazette confirmation."
        })

        self.oracle.dispute_resolution(
            question_id=q_id,
            reason="Official gazette was omitted in initial source set",
            additional_sources=[new_source]
        )

        res = json.loads(self.oracle.get_resolution(q_id))
        self.assertEqual(res["question"]["status"], "resolved")
        self.assertEqual(res["resolution"]["answer"], "Tax rate unchanged at 15%")
        self.assertEqual(res["dispute"]["status"], "settled")

    # -------------------------------------------------------------------------
    # TEST 5: Byzantine Candidate Rejection (Self-Consistent Fabricated Findings)
    # -------------------------------------------------------------------------
    def test_validator_rejects_self_consistent_findings_for_conflicting_sources(self):
        """
        Test Case 5 (REJECTION OF FABRICATED PER-SOURCE FINDINGS):
        This tests the specific vulnerability described in the rejection:
        A malicious candidate supplies internally self-consistent per-source findings
        and a resolved answer for a claim where sources actually conflict.
        The validator independently fetches the actual web pages, discovers that
        one of the sources contradicts the candidate's fabricated finding, and REJECTS
        the candidate.
        """
        urls = [
            "https://finance-daily.com/acme-merger-approved",
            "https://regulatory-watch.gov/acme-merger-blocked"
        ]
        q_id = self.oracle.register_question(
            text="Was the Acme-Globex merger approved?",
            resolution_date="2026-07-15T00:00:00Z",
            source_urls=urls
        )

        # The REAL web pages on the internet:
        def mock_web_get(url, headers=None):
            if "finance-daily.com" in url:
                return MockHttpResponse("Acme merger approved by board.")
            elif "regulatory-watch.gov" in url:
                return MockHttpResponse("Antitrust Commission issued formal injunction blocking merger.")
            return MockHttpResponse("Not found", 404)

        # A MALICIOUS leader attempts to return fabricated self-consistent findings:
        # It fabricates that both sources agreed it was approved!
        def mock_exec_prompt(prompt):
            if "objective consensus leader" in prompt:
                return json.dumps({
                    "status": "resolved",
                    "answer": "Acme merger approved",
                    "confidence": 0.95,
                    "conflict_detected": False,
                    "per_source_findings": {
                        urls[0]: "Reported merger was approved.",
                        urls[1]: "Reported merger was approved without regulatory objection."  # FABRICATED!
                    },
                    "reasoning": "Self-consistent fabricated consensus claiming approval."
                })
            elif "independent consensus validator" in prompt:
                # The validator independently fetched regulatory-watch.gov and found it BLOCKED the merger!
                # Therefore, the validator REJECTS the candidate!
                return json.dumps({
                    "is_valid": False,
                    "reason": "REJECT: regulatory-watch.gov actually states the merger was blocked. Candidate fabricated per-source finding and suppressed conflict."
                })
            return "{}"

        gl.nondet.web.get = mock_web_get
        gl.nondet.exec_prompt = mock_exec_prompt

        # The validator must reject the transaction, triggering a rollback
        with self.assertRaises(gl.Rollback) as ctx:
            self.oracle.resolve_question(q_id)

        self.assertIn("Validator rejected candidate", str(ctx.exception))

    # -------------------------------------------------------------------------
    # TEST 6: Candidate Answer Mismatch Rejection
    # -------------------------------------------------------------------------
    def test_validator_rejects_answer_not_matching_independently_verified_evidence(self):
        """
        Test Case 6: Candidate supplies a factual answer that does not match
        the independently acquired source evidence. Validator detects mismatch and rejects.
        """
        urls = [
            "https://science-journal.org/neutrino-detector-finding",
            "https://physics-archive.edu/neutrino-experiment-results"
        ]
        q_id = self.oracle.register_question(
            text="Did the neutrino observatory observe sterile neutrino oscillation?",
            resolution_date="2026-08-15T00:00:00Z",
            source_urls=urls
        )

        def mock_web_get(url, headers=None):
            if "science-journal" in url:
                return MockHttpResponse("Observatory reports no sterile neutrino signal detected within 95% CL.")
            elif "physics-archive" in url:
                return MockHttpResponse("Null hypothesis upheld; sterile neutrino oscillations excluded.")
            return MockHttpResponse("Not found", 404)

        # Leader hallucinating or lying: claims "YES - sterile neutrinos confirmed"
        def mock_exec_prompt(prompt):
            if "objective consensus leader" in prompt:
                return json.dumps({
                    "status": "resolved",
                    "answer": "YES - Sterile neutrinos confirmed discovered",
                    "confidence": 0.90,
                    "conflict_detected": False,
                    "per_source_findings": {
                        urls[0]: "No sterile neutrino signal detected.",
                        urls[1]: "Null hypothesis upheld."
                    },
                    "reasoning": "Forced positive answer."
                })
            elif "independent consensus validator" in prompt:
                # Validator inspects fetched pages and candidate answer:
                # Fetched pages say "no signal", but answer says "YES" -> REJECT!
                return json.dumps({
                    "is_valid": False,
                    "reason": "REJECT: The factual answer 'YES' directly contradicts the independently verified evidence of null detection."
                })
            return "{}"

        gl.nondet.web.get = mock_web_get
        gl.nondet.exec_prompt = mock_exec_prompt

        with self.assertRaises(gl.Rollback) as ctx:
            self.oracle.resolve_question(q_id)

        self.assertIn("Validator rejected candidate", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
