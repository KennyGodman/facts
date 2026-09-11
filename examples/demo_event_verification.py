"""
Reference Example: Event Verification with FactReconciliationOracle
===================================================================
Demonstrates how an external consumer application (e.g., decentralized insurance,
prediction market, or bounty resolver) integrates with FactReconciliationOracle.
"""

import sys
import os
import json
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
                    pass
            @staticmethod
            def exec_prompt(prompt):
                pass
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


def run_demo():
    print("=" * 70)
    print("FactReconciliationOracle — Event Verification Demonstration")
    print("=" * 70)

    # 1. Deploy / Initialize the Oracle
    oracle = FactReconciliationOracle()
    gl.message.sender_address = "0xPredictMarketDApp1111"
    gl.message.value = 1000000000000000

    print("\n[Step 1] Registering a multi-source fact-checking query...")
    question_text = "Did Ethereum core developers confirm the Dencun hard fork activation epoch on mainnet?"
    resolution_date = "2026-03-15T00:00:00Z"
    sources = [
        "https://blog.ethereum.org/updates/dencun-activation",
        "https://github.com/ethereum/consensus-specs/releases/tag/v1.4.0",
        "https://etherscan.io/block/epoch/dencun"
    ]

    question_id = oracle.register_question(
        text=question_text,
        resolution_date=resolution_date,
        source_urls=sources
    )
    print(f"-> Question Registered Successfully! ID: {question_id}")
    print(f"-> Question: {question_text}")
    print(f"-> Sources: {sources}")

    # 2. Simulate validator consensus resolution
    print("\n[Step 2] Triggering decentralized consensus resolution...")
    print("-> Phase A: Leader fetches web snapshots and synthesizes candidate resolution.")
    print("-> Phase B: Validator independently fetches web snapshots and verifies evidence corroboration.")
    
    # Mocking independent web fetch responses for demonstration
    gl.nondet.web.get = lambda url, headers=None: type("Res", (), {
        "text": f"Confirmed Dencun hardfork mainnet activation epoch: 269568. Status: Finalized and live.",
        "status_code": 200
    })()

    def mock_prompt_handler(prompt):
        if "objective consensus leader" in prompt:
            return json.dumps({
                "status": "resolved",
                "answer": "YES - Activated at epoch 269568",
                "confidence": 0.98,
                "conflict_detected": False,
                "per_source_findings": {
                    sources[0]: "Official blog post confirms mainnet activation at epoch 269568.",
                    sources[1]: "Consensus release notes document activation parameters.",
                    sources[2]: "Etherscan beacon chain confirms block finalized at slot."
                },
                "reasoning": "Unanimous agreement across official developer communication, protocol releases, and explorer."
            })
        elif "independent consensus validator" in prompt:
            return json.dumps({
                "is_valid": True,
                "reason": "Independently verified: all fetched sources corroborate activation at epoch 269568 without conflict."
            })
        return "{}"

    gl.nondet.exec_prompt = mock_prompt_handler

    oracle.resolve_question(question_id)
    print("-> Resolution verified and accepted through GenLayer Equivalence Principle (run_nondet_unsafe).")

    # 3. Read back verified oracle data
    print("\n[Step 3] Querying resolution payload via get_resolution()...")
    raw_record = oracle.get_resolution(question_id)
    record = json.loads(raw_record) if isinstance(raw_record, str) else raw_record

    print("\n--- Oracle Result Payload ---")
    print(f"Status:            {record['resolution']['status'].upper()}")
    print(f"Answer:            {record['resolution']['answer']}")
    print(f"Confidence:        {record['resolution']['confidence'] * 100:.1f}%")
    print(f"Conflict Detected: {record['resolution']['conflict_detected']}")
    print(f"Reasoning:         {record['resolution']['reasoning']}")
    print("\nPer-Source Findings (Independently Verified):")
    for url, finding in record['resolution']['per_source_findings'].items():
        print(f"  • {url}:\n    {finding}")

    print("\n" + "=" * 70)
    print("Demo completed successfully!")
    print("=" * 70)


if __name__ == "__main__":
    run_demo()
