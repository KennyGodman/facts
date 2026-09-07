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
|  +--------------------+       [ Validator 1 ] ---> gl.nondet.web.get(URL 1..N)  |
|  |  resolve_question  |  ==>  [ Validator 2 ] ---> gl.nondet.web.get(URL 1..N)  |
|  +---------+----------+       [ Validator N ] ---> gl.nondet.web.get(URL 1..N)  |
|            |                                                                    |
|            |  Equivalence Principle: gl.eq_principle.prompt_non_comparative     |
|            |  [Criteria: Valid JSON, Strict Evidence-to-Answer Matching, ...]   |
|            v                                                                    |
|  +--------------------+                                                         |
|  | State Mutation:    | ---> status: "resolved" | "unresolved"                  |
|  | resolutions[id]    | ---> answer: consensus answer OR "CONFLICTING_SOURCES"  |
|  +---------+----------+ ---> per_source_findings: { url -> evidence }           |
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

### Why Non-Comparative Validation (`gl.eq_principle.prompt_non_comparative`) Fits Here
In `FactReconciliationOracle`, each validator synthesizes multiple raw HTML/JSON texts into a structured judgment payload.

Using `gl.eq_principle.prompt_non_comparative` provides deterministic evaluation of the candidate resolution payload against strict, unambiguous invariant rules:
1. **Structural Invariant**: Output must be valid JSON containing all designated keys (`status`, `answer`, `confidence`, `conflict_detected`, `per_source_findings`, `reasoning`).
2. **Explicit Evidence-to-Answer Validation Requirement**: If `status` is `resolved`, the factual `answer` MUST be independently verified against and strictly match the fetched evidence documented in `per_source_findings`. The stored `answer` must be directly corroborated by the verified source findings without contradiction, distortion, or unsubstantiated extrapolation. If the factual answer is not directly supported by the fetched evidence in `per_source_findings`, the candidate fails validation.
3. **Conflict Invariant**: If `conflict_detected` is `true`, `status` MUST be `unresolved` and `answer` MUST be `"CONFLICTING_SOURCES"`.
4. **Consensus Invariant**: If `status` is `resolved`, `confidence` MUST be $\ge 0.70$, and all accessible sources must be mutually consistent.
5. **Data Sufficiency Invariant**: If sources fail or contain no factual information, `status` MUST be `unresolved` with `"INSUFFICIENT_DATA"`.
6. **Coverage Invariant**: Every queried source URL must have a corresponding entry in `per_source_findings`.

### Lint-Valid Equivalence Flow
The nondeterministic extraction task is passed as a direct positional argument to `gl.eq_principle.prompt_non_comparative(task_fn, task_description, criteria_rules)`, satisfying GenVM AST safety linter checks by guaranteeing the nondeterministic execution scope is strictly bounded by the equivalence principle.

### What "Equivalent" Means in this Contract
"Equivalence" is not mere string equality or arbitrary prompt acceptance. An outcome is considered equivalent if and only if **all validators agree on the underlying state classification** (Consensus vs. Contradiction vs. Insufficient Data) and the answer is strictly bound by the corroborated evidence from the web snapshots.

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

The suite includes 5 direct-mode unit tests covering all required operational conditions:

| Test Case | Scenario | Expected Behavior |
| :--- | :--- | :--- |
| **Test 1** | Sources clearly agree | Resolves cleanly (`status='resolved'`, confidence $\ge 0.70$, factual answer). |
| **Test 2** | Sources clearly conflict | Returns `status='unresolved'`, `conflict_detected=True`, `answer='CONFLICTING_SOURCES'`. |
| **Test 3** | Source is unreachable / 500 / timeout | Degrades gracefully without crashing; synthesizes remaining active sources. |
| **Test 4** | Fee enforcement & Dispute cycle | Rejects underpaid transactions; processes disputes and updates sources. |
| **Test 5** | Evidence-to-Answer Validation Requirement | Enforces strict corroboration between fetched evidence in `per_source_findings` and stored `answer`. |

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
