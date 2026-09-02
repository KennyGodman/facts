# { "Depends": "py-genlayer:testnet" }
import json
import hashlib

# Standard GenLayer environment imports with graceful fallback for direct unit testing
try:
    from genlayer import *
except ImportError:
    # Direct test-mode fallback shim if running in raw Python
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
            sender = "0x0000000000000000000000000000000000000001"
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
        class eq_principle:
            @staticmethod
            def prompt_non_comparative(func, task, criteria):
                return func()
    gl = _MockGl()


class FactReconciliationOracle(gl.Contract):
    """
    FactReconciliationOracle
    =========================
    An Intelligent Contract primitive for GenLayer that performs decentralized
    multi-source web fact reconciliation.

    Unlike naive oracle wrappers or binary LLM judges:
    1. Validators independently scrape designated live web endpoints.
    2. Validators synthesize cross-source evidence and evaluate semantic consistency.
    3. If sources genuinely contradict each other, the oracle explicitly yields an
       'unresolved' status rather than hallucinating or forcing a false consensus.
    4. Supports on-chain dispute challenges with source expansion.
    """

    # -------------------------------------------------------------------------
    # Persistent State
    # -------------------------------------------------------------------------
    questions: dict[str, dict]
    resolutions: dict[str, dict]
    disputes: dict[str, dict]
    min_fee: int
    owner: str

    def __init__(self, min_fee: int = 1000000000000000):
        """
        Initializes the oracle contract with an anti-spam fee threshold.
        :param min_fee: Minimum wei deposit required per registration/dispute.
        """
        self.questions = {}
        self.resolutions = {}
        self.disputes = {}
        self.min_fee = min_fee
        self.owner = str(gl.message.sender)

    # -------------------------------------------------------------------------
    # Public Methods
    # -------------------------------------------------------------------------

    @gl.public.write.payable
    def register_question(
        self,
        text: str,
        resolution_date: str,
        source_urls: list[str]
    ) -> str:
        """
        Registers a new factual claim or question to be verified against external sources.
        Requires an anti-spam deposit (msg.value >= min_fee).
        """
        if gl.message.value < self.min_fee:
            raise gl.Rollback(f"Insufficient fee: required at least {self.min_fee} wei")

        if not text or len(text.strip()) == 0:
            raise gl.Rollback("Question text cannot be empty")

        if not source_urls or len(source_urls) < 1:
            raise gl.Rollback("At least one source URL is required (multiple recommended)")

        # Compute deterministic question ID
        payload = f"{text}:{resolution_date}:{','.join(source_urls)}:{gl.message.sender}"
        question_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

        if question_id in self.questions:
            raise gl.Rollback("Identical question is already registered")

        self.questions[question_id] = {
            "question_id": question_id,
            "text": text.strip(),
            "resolution_date": resolution_date.strip(),
            "source_urls": list(source_urls),
            "status": "pending",  # pending | resolved | unresolved | disputed
            "creator": str(gl.message.sender),
            "fee_paid": int(gl.message.value)
        }

        return question_id

    @gl.public.write
    def resolve_question(self, question_id: str) -> None:
        """
        Executes multi-validator fact reconciliation on the registered question.
        
        Process:
        - Isolates state variables into local execution scope.
        - Calls gl.nondet.web.get() across all target sources with error isolation.
        - Evaluates cross-source agreement vs. contradiction via validator LLM prompt.
        - Reconciles across validators via gl.eq_principle.prompt_non_comparative.
        - Marks status as 'resolved' (if consensus reached) or 'unresolved' (if sources conflict/fail).
        """
        if question_id not in self.questions:
            raise gl.Rollback(f"Question {question_id} does not exist")

        current_status = self.questions[question_id]["status"]
        if current_status == "resolved":
            raise gl.Rollback("Question has already been successfully resolved")

        # ---------------------------------------------------------------------
        # 1. State Isolation: Copy persistent state into local variables
        # ---------------------------------------------------------------------
        target_text = str(self.questions[question_id]["text"])
        target_resolution_date = str(self.questions[question_id]["resolution_date"])
        target_source_urls = list(self.questions[question_id]["source_urls"])

        # ---------------------------------------------------------------------
        # 2. Non-deterministic Execution Block (Each validator runs independently)
        # ---------------------------------------------------------------------
        def validator_fact_reconciliation() -> str:
            # Step A: Fetch external web snapshots independently
            extracted_sources = {}
            for url in target_source_urls:
                try:
                    res = gl.nondet.web.get(url, headers={
                        "User-Agent": "GenLayer-Oracle/1.0",
                        "Accept": "text/html,application/json,text/plain"
                    })
                    raw_text = getattr(res, "text", str(res))
                    # Bound source text size to keep prompt token-efficient
                    extracted_sources[url] = raw_text[:3500] if raw_text else "[Empty response]"
                except Exception as e:
                    # Graceful degradation for unreachable / stale endpoints
                    extracted_sources[url] = f"[FETCH_FAILED]: {str(e)}"

            sources_json_str = json.dumps(extracted_sources)

            # Step B: Validator Synthesis Prompt
            synthesis_prompt = f"""
You are an objective consensus validator on the GenLayer network.
Your task is to reconcile facts regarding a specific question based ONLY on raw external web snapshots.

QUESTION TO VERIFY:
"{target_text}"

RESOLUTION DATE / CRITERIA:
"{target_resolution_date}"

COLLECTED EXTERNAL SOURCES:
{sources_json_str}

RECONCILIATION INSTRUCTIONS:
1. Examine each source and extract what it states regarding the question.
2. Determine if the sources collectively:
   - AGREE: All accessible credible sources support the same factual conclusion.
   - CONFLICT: Two or more credible sources make mutually incompatible, conflicting, or opposing claims.
   - INSUFFICIENT: Sources are unreachable, failed to load, or lack relevant evidence.
3. CRITICAL CONFLICT HANDLING:
   - If sources contradict one another on the core answer, set "status" to "unresolved", "conflict_detected" to true, and "answer" to "CONFLICTING_SOURCES".
   - Do NOT average contradictory numbers, speculate, or force a majority vote.
4. If sources agree, set "status" to "resolved", "conflict_detected" to false, and provide the concise factual "answer".
5. Return strictly valid JSON with no markdown wrapping or preamble, matching this exact schema:
{{
  "status": "resolved" or "unresolved",
  "answer": "<factual answer | CONFLICTING_SOURCES | INSUFFICIENT_DATA>",
  "confidence": <float between 0.0 and 1.0>,
  "conflict_detected": <true or false>,
  "per_source_findings": {{
    "<source_url>": "<specific evidence or error from this source>"
  }},
  "reasoning": "<brief explanation of consensus or conflict>"
}}
"""
            raw_llm_response = gl.nondet.exec_prompt(synthesis_prompt)

            # Sanitize response to ensure valid JSON
            clean_response = raw_llm_response.strip()
            if clean_response.startswith("```json"):
                clean_response = clean_response[7:]
            if clean_response.startswith("```"):
                clean_response = clean_response[3:]
            if clean_response.endswith("```"):
                clean_response = clean_response[:-3]
            clean_response = clean_response.strip()

            return clean_response

        # ---------------------------------------------------------------------
        # 3. Equivalence Principle Consensus
        # ---------------------------------------------------------------------
        task_description = f"Reconcile facts for claim '{target_text}' from sources: {target_source_urls}"
        criteria_rules = """
        The candidate JSON must satisfy all criteria:
        1. Valid JSON containing keys: 'status', 'answer', 'confidence', 'conflict_detected', 'per_source_findings', 'reasoning'.
        2. If 'conflict_detected' is true, 'status' MUST be 'unresolved' and 'answer' MUST be 'CONFLICTING_SOURCES'.
        3. If 'status' is 'resolved', 'confidence' must be >= 0.70 and sources must be mutually consistent.
        4. If insufficient or failed sources preclude a definitive answer, 'status' must be 'unresolved' and 'answer' must be 'INSUFFICIENT_DATA'.
        5. 'per_source_findings' must contain an entry for every source URL evaluated.
        """

        agreed_verdict_str = gl.eq_principle.prompt_non_comparative(
            func=validator_fact_reconciliation,
            task=task_description,
            criteria=criteria_rules
        )

        try:
            verdict = json.loads(agreed_verdict_str)
        except Exception:
            # Fallback if raw string formatting had unexpected tokens
            verdict = {
                "status": "unresolved",
                "answer": "PARSING_FAILED",
                "confidence": 0.0,
                "conflict_detected": False,
                "per_source_findings": {},
                "reasoning": "Validator output could not be parsed as valid JSON"
            }

        # ---------------------------------------------------------------------
        # 4. State Updates
        # ---------------------------------------------------------------------
        final_status = verdict.get("status", "unresolved")
        self.questions[question_id]["status"] = final_status

        self.resolutions[question_id] = {
            "question_id": question_id,
            "status": final_status,
            "answer": str(verdict.get("answer", "UNKNOWN")),
            "confidence": float(verdict.get("confidence", 0.0)),
            "conflict_detected": bool(verdict.get("conflict_detected", False)),
            "per_source_findings": dict(verdict.get("per_source_findings", {})),
            "reasoning": str(verdict.get("reasoning", "")),
            "resolved_at": target_resolution_date
        }

        # Update active dispute if one was being resolved
        if question_id in self.disputes and self.disputes[question_id]["status"] == "open":
            self.disputes[question_id]["status"] = "settled"

    @gl.public.write.payable
    def dispute_resolution(
        self,
        question_id: str,
        reason: str,
        additional_sources: list[str]
    ) -> None:
        """
        Challenges a prior resolution or unresolved state by submitting additional sources
        and paying the dispute deposit. Re-triggers resolution with the expanded source pool.
        """
        if question_id not in self.questions:
            raise gl.Rollback(f"Question {question_id} not found")

        if gl.message.value < self.min_fee:
            raise gl.Rollback(f"Dispute fee of at least {self.min_fee} wei is required")

        if not reason or len(reason.strip()) == 0:
            raise gl.Rollback("A valid reason for dispute is required")

        # Record dispute record
        self.disputes[question_id] = {
            "question_id": question_id,
            "challenger": str(gl.message.sender),
            "reason": reason.strip(),
            "status": "open",
            "fee_paid": int(gl.message.value),
            "new_sources": list(additional_sources) if additional_sources else []
        }

        # Expand source URLs with supplementary sources
        existing_sources = self.questions[question_id]["source_urls"]
        for src in (additional_sources or []):
            if src not in existing_sources:
                existing_sources.append(src)

        self.questions[question_id]["status"] = "disputed"

        # Re-trigger resolution with augmented source pool
        self.resolve_question(question_id)

    @gl.public.view
    def get_resolution(self, question_id: str) -> dict:
        """
        Read-only lookup returning question metadata, consensus status, resolution data,
        and dispute details.
        """
        if question_id not in self.questions:
            raise gl.Rollback(f"Question {question_id} does not exist")

        q = self.questions[question_id]
        res = self.resolutions.get(question_id, None)
        disp = self.disputes.get(question_id, None)

        return {
            "question": q,
            "resolution": res,
            "dispute": disp
        }
