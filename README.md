# FactReconciliationOracle ⚖️

**A Decentralized Multi-Source Fact Verification and Consensus Primitive for GenLayer**

> **Live On-Chain Deployment:**
> - **Contract Address:** [`0x98997ec70AC233f8148f0dAD0dD6b3351413D495`](https://explorer-studio.genlayer.com/address/0x98997ec70AC233f8148f0dAD0dD6b3351413D495)
> - **Deployment Transaction:** [`0x9a7e413e419eff9ad6a7f868ef24b5f254e12618586cc49c9ab8f445bc11f24e`](https://explorer-studio.genlayer.com)
> - **Network:** GenLayer Studio Testnet (`studionet`)
> - **GenLayer Explorer:** [explorer-studio.genlayer.com/address/0x98997ec70AC233f8148f0dAD0dD6b3351413D495](https://explorer-studio.genlayer.com/address/0x98997ec70AC233f8148f0dAD0dD6b3351413D495)

---

## 1. Problem Statement & Motivation

Traditional blockchain oracles and naive "AI oracle" wrappers suffer from two fatal vulnerabilities:
1. **Single Point of Failure / Stale Data**: Pointing to a single API or URL makes the oracle brittle to downtime, censorship, or API schema changes.
2. **Forced False Consensus (The LLM Wrapper Trap)**: When two web sources contradict each other (e.g. Source A says *"Company X acquired Company Y"*, while Source B says *"The antitrust commission vetoed the merger"*), naive LLM prompts will hallucinate an average, pick an arbitrary majority, or force a binary outcome.

### What `FactReconciliationOracle` Solves
`FactReconciliationOracle` is a **contract primitive** designed for GenLayer Intelligent Contracts. It turns GenLayer validators into an objective, decentralized fact-checking court that:
- Independently pulls live web pages across multiple heterogeneous domains via `gl.nondet.web.get()`.
- Extracts evidence per source and evaluates semantic consistency across all sources.
- **Explicitly rejects forced consensus**: When sources genuinely contradict each other, the primitive marks the question as `unresolved` with `conflict_detected: true` and `answer: "CONFLICTING_SOURCES"`.
- Degrades gracefully when individual endpoints fail, timeout, or return HTTP errors.
- Provides a built-in on-chain **dispute mechanism** allowing callers to stake fees and expand the source pool for re-resolution.

---

## 2. Architecture & State Design

```
+---------------------------------------------------------------------------------+
|                               GenLayer Network                                  |
|                                                                                 |
|  +--------------------+                                                         |
|  | register_question  | <--- (text, resolution_date, source_urls, stake_fee)    |
|  +---------+----------+                                                         |
|            |                                                                    |
|            v                                                                    |
|  +--------------------+   PHASE 1: LEADER (leader_fact_reconciliation)          |
|  |  resolve_question  |   - Fetches target URLs via gl.nondet.web.get()         |
|  +---------+----------+   - Synthesizes findings & proposes candidate JSON      |
|            |                                                                    |
|            |              PHASE 2: VALIDATOR (validator_fact_verification)      |
|            |              - Independently fetches target URLs (fresh evidence)  |
|            |              - Verifies committed findings against fetched pages   |
|            |              - Rejects fabricated findings or answer mismatches    |
|            v                                                                    |
|  Equivalence Principle: gl.vm.run_nondet_unsafe(leader, validator)              |
|            |                                                                    |
|            v                                                                    |
|  +--------------------+                                                         |
|  | State Mutation:    | ---> status: "resolved" | "unresolved"                  |
|  | resolutions[id]    | ---> answer: consensus answer OR "CONFLICTING_SOURCES"  |
|  +---------+----------+ ---> per_source_findings: { url -> verified_evidence }  |
|            |                                                                    |
|            v (If challenged with new sources + fee)                             |
|  +--------------------+                                                         |
|  | dispute_resolution | ---> Appends sources & re-runs multi-validator round    |
|  +--------------------+                                                         |
+---------------------------------------------------------------------------------+
```

### State Variables
```python
questions: dict[str, dict]
# question_id -> { text, resolution_date, source_urls, status, creator, fee_paid }
# Statuses: "pending" | "resolved" | "unresolved" | "disputed"

resolutions: dict[str, dict]
# question_id -> { answer, confidence, per_source_findings, resolved_at, conflict_detected, reasoning }

disputes: dict[str, dict]
# question_id -> { challenger, reason, status, fee_paid, new_sources }
```

---

## 3. Consensus Logic & The Equivalence Principle

### Independent Evidence Acquisition & Verification (`gl.vm.run_nondet_unsafe`)
In decentralized consensus, **validators must never trust the leader's reported evidence**. If validators only inspect the candidate output, a malicious or hallucinating leader could supply internally self-consistent `per_source_findings` for conflicting or false claims (e.g. claiming both sources agreed when one actually disagreed) and pass superficial checks.

`FactReconciliationOracle` solves this using GenLayer's recommended **independent verification pattern** with `gl.vm.run_nondet_unsafe(leader_fact_reconciliation, validator_fact_verification)`:

1. **Phase 1: Leader Execution (`leader_fact_reconciliation`)**:
   - The leader node fetches each URL in `source_urls` with error isolation (`gl.nondet.web.get`).
   - The leader synthesizes per-source evidence and evaluates cross-source consistency.
   - It outputs a structured candidate resolution containing `status`, `answer`, `confidence`, `conflict_detected`, `per_source_findings`, and `reasoning`.

2. **Phase 2: Independent Validator Verification (`validator_fact_verification`)**:
   - Every validator node in the committee independently executes the verification function.
   - **Independent Evidence Acquisition**: Each validator directly calls `gl.nondet.web.get()` on the target URLs to acquire its own fresh snapshot of the source evidence.
   - **Committed Evidence Verification**: The validator compares the leader's committed `per_source_findings` against the actual content of the independently fetched pages. If findings were fabricated or distorted, the validator **rejects** the candidate (`is_valid = false`).
   - **Independent Conflict Verification**: If the independently fetched pages reveal a conflict, the candidate MUST report `conflict_detected: true`, `status: "unresolved"`, and `answer: "CONFLICTING_SOURCES"`. Any attempt to force a resolved consensus over conflicting sources is **rejected**.
   - **Factual Binding**: If `status` is `resolved`, the proposed `answer` must strictly and directly follow from the independently acquired evidence.
   - **Confidence Threshold**: For resolved answers, `confidence` must be $\ge 0.70$.

### What "Equivalent" Means in this Contract
Consensus is achieved when the validator committee confirms that the leader's committed findings and factual answer **truthfully bind to the independently acquired live web evidence**. If the candidate fails any check, validators reject the proposal, triggering leader rotation or transaction rollback.

---

## 4. Anti-Spam & Economic Defense
Because resolving a question triggers $N$ live external web fetches across multiple validators:
- `register_question()` requires a minimum fee deposit (`msg.value >= min_fee`).
- `dispute_resolution()` requires an additional deposit to prevent malicious griefing or endless re-rolling without economic commitment.

---

## 5. Plug-and-Play Integration for Other Builders

Other smart contracts (Prediction Markets, Parametric Insurance, DAO Governance, Tokenized Real-World Assets) can use `FactReconciliationOracle` out-of-the-box without altering contract code.

### Example: Consuming from another Intelligent Contract or dApp
```python
# 1. Register any real-world factual claim with reputable endpoints
question_id = oracle.register_question(
    text="Did Flight BA142 from LHR to JFK experience a delay greater than 180 minutes on 2026-04-12?",
    resolution_date="2026-04-13T00:00:00Z",
    source_urls=[
        "https://flightradar24.com/data/flights/ba142",
        "https://flightstats.com/v2/flight-tracker/BA/142",
        "https://aviation-api.gov/flight/history/ba142"
    ]
)

# 2. Trigger resolution after resolution_date
oracle.resolve_question(question_id)

# 3. Read structured result (JSON)
data = json.loads(oracle.get_resolution(question_id))
if data["resolution"]["status"] == "resolved":
    payout_insurance(data["resolution"]["answer"])
elif data["resolution"]["conflict_detected"]:
    route_to_human_arbitration_or_dispute(question_id)
```

---

## 6. Testing & Verification

The suite includes 6 direct-mode unit tests covering all required operational conditions:

| Test Case | Scenario | Expected Behavior |
| :--- | :--- | :--- |
| **Test 1** | Sources clearly agree | Resolves cleanly (`status='resolved'`, confidence $\ge 0.70$, factual answer verified). |
| **Test 2** | Sources clearly conflict | Returns `status='unresolved'`, `conflict_detected=True`, `answer='CONFLICTING_SOURCES'`. |
| **Test 3** | Source is unreachable / 500 / timeout | Degrades gracefully without crashing; synthesizes remaining active sources. |
| **Test 4** | Fee enforcement & Dispute cycle | Rejects underpaid transactions; processes disputes and updates sources. |
| **Test 5** | Byzantine Candidate Rejection (Fabricated Findings) | Candidate supplies self-consistent findings for conflicting sources; validator independently acquires real pages, detects the contradiction, and **rejects** the candidate. |
| **Test 6** | Answer Mismatch Rejection | Candidate proposes a factual answer not corroborated by the independently acquired source evidence; validator detects mismatch and **rejects** the candidate. |

### Running the Tests
```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

### Running GenVM Linting
```bash
python -m genvm_linter.cli lint contracts/fact_reconciliation_oracle.py
```

### Running the Demo
```bash
python examples/demo_event_verification.py
```
