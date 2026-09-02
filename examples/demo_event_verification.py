"""
Reference Example: Event Verification with FactReconciliationOracle
===================================================================
Demonstrates how an external consumer application (e.g., decentralized insurance,
prediction market, or bounty resolver) integrates with FactReconciliationOracle.
"""

import sys
import os
import json

# Add contracts directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "contracts")))
from fact_reconciliation_oracle import FactReconciliationOracle, gl


def run_demo():
    print("=" * 70)
    print("FactReconciliationOracle — Event Verification Demonstration")
    print("=" * 70)

    # 1. Deploy / Initialize the Oracle
    oracle = FactReconciliationOracle(min_fee=1000000000000000)
    gl.message.sender = "0xPredictMarketDApp1111"
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
    
    # Mocking independent web fetch responses for demonstration
    gl.nondet.web.get = lambda url, headers=None: type("Res", (), {
        "text": f"Confirmed Dencun hardfork mainnet activation epoch: 269568. Status: Finalized and live.",
        "status_code": 200
    })()

    gl.nondet.exec_prompt = lambda p: json.dumps({
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

    oracle.resolve_question(question_id)
    print("-> Resolution executed through GenLayer Equivalence Principle.")

    # 3. Read back verified oracle data
    print("\n[Step 3] Querying resolution payload via get_resolution()...")
    record = oracle.get_resolution(question_id)

    print("\n--- Oracle Result Payload ---")
    print(f"Status:            {record['resolution']['status'].upper()}")
    print(f"Answer:            {record['resolution']['answer']}")
    print(f"Confidence:        {record['resolution']['confidence'] * 100:.1f}%")
    print(f"Conflict Detected: {record['resolution']['conflict_detected']}")
    print(f"Reasoning:         {record['resolution']['reasoning']}")
    print("\nPer-Source Findings:")
    for url, finding in record['resolution']['per_source_findings'].items():
        print(f"  • {url}:\n    {finding}")

    print("\n" + "=" * 70)
    print("Demo completed successfully!")
    print("=" * 70)


if __name__ == "__main__":
    run_demo()
