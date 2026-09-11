# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
import json
import hashlib
from genlayer import *


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
    questions: TreeMap[str, str]
    resolutions: TreeMap[str, str]
    disputes: TreeMap[str, str]
    min_fee: u256
    owner: Address

    def __init__(self):
        """
        Initializes the oracle contract with an anti-spam fee threshold.
        """
        self.min_fee = u256(1000000000000000)
        self.owner = gl.message.sender_address
        self.questions = TreeMap()
        self.resolutions = TreeMap()
        self.disputes = TreeMap()

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

        urls_list = list(source_urls)
        if not urls_list or len(urls_list) < 1:
            raise gl.Rollback("At least one source URL is required (multiple recommended)")

        # Compute deterministic question ID
        sender_str = str(gl.message.sender_address)
        payload = f"{text}:{resolution_date}:{','.join(urls_list)}:{sender_str}"
        question_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

        if question_id in self.questions:
            raise gl.Rollback("Identical question is already registered")

        q_record = {
            "question_id": question_id,
            "text": text.strip(),
            "resolution_date": resolution_date.strip(),
            "source_urls": urls_list,
            "status": "pending",  # pending | resolved | unresolved | disputed
            "creator": sender_str,
            "fee_paid": int(gl.message.value)
        }
        self.questions[question_id] = json.dumps(q_record)

        return question_id

    @gl.public.write
    def resolve_question(self, question_id: str) -> str:
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

        q_data = json.loads(self.questions[question_id])
        current_status = q_data.get("status", "pending")
        if current_status == "resolved":
            raise gl.Rollback("Question has already been successfully resolved")

        # ---------------------------------------------------------------------
        # 1. State Isolation: Copy persistent state into local variables
        # ---------------------------------------------------------------------
        target_text = str(q_data["text"])
        target_resolution_date = str(q_data["resolution_date"])
        target_source_urls = list(q_data["source_urls"])

        # ---------------------------------------------------------------------
        # 2. Leader Fact Reconciliation (Proposes candidate resolution)
        # ---------------------------------------------------------------------
        def leader_fact_reconciliation() -> str:
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

            # Step B: Leader Synthesis Prompt
            synthesis_prompt = f"""
You are an objective consensus leader on the GenLayer network.
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
   CRITICAL EVIDENCE-TO-ANSWER REQUIREMENT:
   The factual "answer" MUST strictly reflect and be directly corroborated by the extracted evidence recorded in "per_source_findings".
   Never speculate, assume, or extrapolate claims beyond what is explicitly evidenced in "per_source_findings".
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
        # 3. Validator Fact Verification (Independently acquires & verifies evidence)
        # ---------------------------------------------------------------------
        def validator_fact_verification(leader_res) -> bool:
            """
            Independent Validator Verification:
            - Validates return type and candidate JSON structure.
            - Independently fetches each target source URL (acquiring fresh evidence).
            - Re-evaluates per-source evidence against actual fetched page content.
            - Rejects any candidate that fabricated per-source findings, suppressed conflicts,
              or provided a factual answer not corroborated by independently verified evidence.
            """
            if not isinstance(leader_res, gl.vm.Return):
                return False

            try:
                candidate = json.loads(leader_res.calldata) if isinstance(leader_res.calldata, str) else leader_res.calldata
            except Exception:
                return False

            if not isinstance(candidate, dict):
                return False

            required_keys = ["status", "answer", "confidence", "conflict_detected", "per_source_findings", "reasoning"]
            if not all(k in candidate for k in required_keys):
                return False

            cand_status = str(candidate.get("status", ""))
            cand_answer = str(candidate.get("answer", ""))
            cand_conflict = bool(candidate.get("conflict_detected", False))
            cand_confidence = float(candidate.get("confidence", 0.0))
            cand_findings = candidate.get("per_source_findings", {})

            if cand_status not in ("resolved", "unresolved"):
                return False
            if not isinstance(cand_findings, dict):
                return False

            # Every source URL must have a committed finding entry
            for url in target_source_urls:
                if url not in cand_findings:
                    return False

            # Structural consistency checks
            if cand_conflict and (cand_status != "unresolved" or cand_answer != "CONFLICTING_SOURCES"):
                return False
            if cand_status == "resolved" and (cand_confidence < 0.70 or cand_conflict):
                return False

            # -----------------------------------------------------------------
            # Step A: Independent Evidence Acquisition by Validator
            # -----------------------------------------------------------------
            validator_sources = {}
            for url in target_source_urls:
                try:
                    res = gl.nondet.web.get(url, headers={
                        "User-Agent": "GenLayer-Oracle-Validator/1.0",
                        "Accept": "text/html,application/json,text/plain"
                    })
                    raw_text = getattr(res, "text", str(res))
                    validator_sources[url] = raw_text[:3500] if raw_text else "[Empty response]"
                except Exception as e:
                    validator_sources[url] = f"[FETCH_FAILED]: {str(e)}"

            validator_sources_json_str = json.dumps(validator_sources)
            candidate_json_str = json.dumps(candidate)

            # -----------------------------------------------------------------
            # Step B: Independent LLM Verification & Factual Binding Prompt
            # -----------------------------------------------------------------
            verification_prompt = f"""
You are an independent consensus validator on the GenLayer network.
Your task is to independently verify a candidate fact reconciliation against raw web evidence YOU independently fetched.

QUESTION TO VERIFY:
"{target_text}"

RESOLUTION DATE / CRITERIA:
"{target_resolution_date}"

INDEPENDENTLY FETCHED WEB EVIDENCE (Directly acquired by this validator node):
{validator_sources_json_str}

LEADER CANDIDATE TO VERIFY:
{candidate_json_str}

STRICT VALIDATION AND REJECTION RULES:
1. INDEPENDENT EVIDENCE VERIFICATION:
   - Compare the candidate's committed "per_source_findings" against the actual content of the independently fetched pages above.
   - If the candidate fabricated, misrepresented, or distorted what the fetched sources actually state (even if internally self-consistent), you MUST REJECT (is_valid = false).
2. INDEPENDENT CONFLICT DETECTION:
   - Assess whether the independently fetched sources contradict each other regarding the question.
   - If credible sources conflict, the candidate MUST have "conflict_detected": true, "status": "unresolved", and "answer": "CONFLICTING_SOURCES".
   - If sources conflict but candidate claimed "resolved" (e.g. by supplying one-sided or fabricated findings), you MUST REJECT (is_valid = false).
3. FACTUAL BINDING:
   - If "status" is "resolved", the proposed "answer" MUST strictly match and be directly corroborated by the independently acquired evidence.
   - If the factual answer is not corroborated by, or contradicts, the independently fetched pages, you MUST REJECT (is_valid = false).
   - If sources are unreachable or lack relevant data to resolve the question, "status" MUST be "unresolved" and "answer" MUST be "INSUFFICIENT_DATA".
4. CONFIDENCE:
   - If "status" is "resolved", "confidence" must be >= 0.70.

Return strictly valid JSON with no markdown wrapping or extra text:
{{
  "is_valid": <true or false>,
  "reason": "<clear explanation of independent verification verdict>"
}}
"""
            raw_eval = gl.nondet.exec_prompt(verification_prompt)
            clean_eval = raw_eval.strip()
            if clean_eval.startswith("```json"):
                clean_eval = clean_eval[7:]
            if clean_eval.startswith("```"):
                clean_eval = clean_eval[3:]
            if clean_eval.endswith("```"):
                clean_eval = clean_eval[:-3]
            clean_eval = clean_eval.strip()

            try:
                eval_data = json.loads(clean_eval)
                return bool(eval_data.get("is_valid", False))
            except Exception:
                return False

        # ---------------------------------------------------------------------
        # 4. Equivalence Principle Consensus via run_nondet_unsafe
        # ---------------------------------------------------------------------
        agreed_verdict_str = gl.vm.run_nondet_unsafe(
            leader_fact_reconciliation,
            validator_fact_verification
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
        q_data["status"] = final_status
        self.questions[question_id] = json.dumps(q_data)

        resolution_record = {
            "question_id": question_id,
            "status": final_status,
            "answer": str(verdict.get("answer", "UNKNOWN")),
            "confidence": float(verdict.get("confidence", 0.0)),
            "conflict_detected": bool(verdict.get("conflict_detected", False)),
            "per_source_findings": dict(verdict.get("per_source_findings", {})),
            "reasoning": str(verdict.get("reasoning", "")),
            "resolved_at": target_resolution_date
        }
        self.resolutions[question_id] = json.dumps(resolution_record)

        # Update active dispute if one was being resolved
        if question_id in self.disputes:
            disp_data = json.loads(self.disputes[question_id])
            if disp_data.get("status") == "open":
                disp_data["status"] = "settled"
                self.disputes[question_id] = json.dumps(disp_data)

        return final_status

    @gl.public.write.payable
    def dispute_resolution(
        self,
        question_id: str,
        reason: str,
        additional_sources: list[str]
    ) -> str:
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
        new_sources_list = list(additional_sources) if additional_sources else []
        dispute_record = {
            "question_id": question_id,
            "challenger": str(gl.message.sender_address),
            "reason": reason.strip(),
            "status": "open",
            "fee_paid": int(gl.message.value),
            "new_sources": new_sources_list
        }
        self.disputes[question_id] = json.dumps(dispute_record)

        # Expand source URLs with supplementary sources
        q_data = json.loads(self.questions[question_id])
        existing_sources = list(q_data.get("source_urls", []))
        for src in new_sources_list:
            if src not in existing_sources:
                existing_sources.append(src)

        q_data["source_urls"] = existing_sources
        q_data["status"] = "disputed"
        self.questions[question_id] = json.dumps(q_data)

        # Re-trigger resolution with augmented source pool
        return self.resolve_question(question_id)

    @gl.public.view
    def get_resolution(self, question_id: str) -> str:
        if question_id not in self.questions:
            raise gl.Rollback(f"Question {question_id} does not exist")

        q_data = json.loads(self.questions[question_id])
        res_data = json.loads(self.resolutions[question_id]) if question_id in self.resolutions else None
        disp_data = json.loads(self.disputes[question_id]) if question_id in self.disputes else None

        return json.dumps({
            "question": q_data,
            "resolution": res_data,
            "dispute": disp_data
        })
