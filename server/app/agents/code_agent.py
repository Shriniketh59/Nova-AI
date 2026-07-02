import json
import re
from typing import Callable

import httpx

from ..core.config import (
    OLLAMA_URL, OLLAMA_CODE_MODEL, CODE_LLM_REVIEW, CODE_NUM_PREDICT, MAX_CONTINUATIONS,
)
from ..utils.completion_guard import is_truncated, close_unbalanced_fences
from ..utils.code_validation import quick_validate_code
from .base_agent import BaseAgent
from .review_agent import ReviewAgent

MAX_REGENERATIONS = 1

REQUIRED_SECTIONS = [
    "Problem Understanding", "Key Concepts", "Approach", "Algorithm", "Code",
    "Complexity Analysis", "Edge Cases", "Example Execution", "Conclusion", "Confidence Score",
]

DSA_RE = re.compile(
    r"\b(leetcode|dsa|hackerrank|codeforces|two sum|merge sort|quick sort|binary search|fibonacci|dynamic programming|graph traversal|knapsack|sliding window)\b",
    re.I,
)

BROAD_BUILD_RE = re.compile(
    r"\b(build|create|design|develop|make)\b(?:(?!\b(?:function|method|class|component|endpoint|query|regex|script|snippet)\b)[\s\S]){0,40}\b(app|application|system|platform|website|web ?app|service|api|dashboard|game|bot|chatbot|tool)\b",
    re.I,
)

CODE_SYSTEM_PROMPT = """You are Nova AI's elite coding assistant — answer at the quality of a senior software architect and competitive programmer. Never generate incomplete, uncompilable, or low-quality code. Never write a generic or filler explanation — every sentence must say something specific to this exact problem.

Workflow before writing anything: understand the problem fully (input/output/constraints/edge cases), identify the concepts/data structures involved, design the algorithm, then write complete code, then check it, then derive real complexity from the code you actually wrote.

Structure every answer with these exact markdown sections, in order, every time — never skip one:
# Problem Understanding
Restate the problem precisely: input, output, constraints, edge cases to handle.
# Key Concepts
The specific data structures, algorithms, or language features this problem requires, and why each is needed.
# Approach
The reasoning behind the chosen method — what alternatives were considered and why this one wins.
# Algorithm
Numbered steps.
# Code
One fenced code block, correct language tag, complete and runnable — every brace closed, every function returns what its signature promises, no missing imports.
# Complexity Analysis
Time Complexity: derived from the actual loops/recursion in the code above — never guessed. If genuinely uncertain (e.g. depends on input distribution), say so explicitly and state the assumption.
Space Complexity: same — derived from the actual data structures used.
Worst Case: the specific input shape that triggers it.
Average Case: only if it meaningfully differs from worst case.
# Edge Cases
List the concrete edge cases this code handles (empty input, single element, duplicates, overflow, etc.) — not generic boilerplate.
# Example Execution
A concrete input run through the code with the actual output.
# Conclusion
One paragraph: summarize the solution and its real tradeoffs (when you'd pick a different approach).
# Confidence Score
A percentage with one line on why (validated vs assumptions made).

Never return code only — every section above is mandatory."""

LEETCODE_SYSTEM_PROMPT = f"""{CODE_SYSTEM_PROMPT}

This is a DSA/competitive-programming question. In the # Code section, provide BOTH:
1. Brute Force Solution — correct but naive.
2. Optimized Solution — the efficient approach.
Then in Complexity Analysis, compare both and explain concretely why the optimized solution is better (what work it avoids)."""

PLAN_SYSTEM_PROMPT = """You are Nova AI's planning assistant for broad build/design requests. The user asked to build something too large for a single code answer — scope it first, don't write code yet.

Reply with ONLY this markdown structure:
# Implementation Plan
## Phase 1: <name>
<1-2 sentences>
## Phase 2: <name>
<1-2 sentences>
## Phase 3: <name>
<1-2 sentences>
# Estimated Files
A bullet list of the files/modules this would need.
# Estimated Components
A bullet list of the major components/classes/services.
# Estimated APIs
A bullet list of the endpoints or interfaces needed (omit this section if not applicable).

End with exactly this line, verbatim:
Want me to generate the code for this plan?"""


def _build_fix_prompt(answer: str, issues: list[str]) -> str:
    issues_list = "\n".join(f"- {i}" for i in issues)
    return f"Your previous answer has these specific defects:\n{issues_list}\n\nHere is your previous answer:\n{answer}\n\nReturn the FULL corrected answer (all sections, same structure), fixing only these defects. Do not add commentary about the fix."


def _build_regenerate_prompt(question: str, issues: list[str]) -> str:
    return f"{question}\n\nA previous attempt at this had unresolved defects after one fix pass: {'; '.join(issues)}. Write a fresh, careful answer that avoids these specific mistakes."


def _missing_sections(text: str) -> list[str]:
    return [s for s in REQUIRED_SECTIONS if s not in text]


def _confidence_from_validation(validation: dict, regenerated: bool) -> dict:
    if validation["pass"] and not regenerated:
        return {"score": 97, "label": "high", "reason": "Code reviewed and passed all validation checks (syntax, imports, returns, complexity)."}
    if validation["pass"] and regenerated:
        return {"score": 88, "label": "high", "reason": "Code passed validation after one regeneration pass — minor assumptions possible."}
    return {"score": 65, "label": "medium", "reason": f"Validation still flags: {'; '.join(validation['issues'])} — review before using in production."}


class CodeAgent(BaseAgent):
    """Coding fast path: Question -> Code Agent -> Quick Validation -> Response.
    Deliberately bypasses Research/Planner/Review."""

    def __init__(self):
        super().__init__("CodeAgent")
        self.review_agent = ReviewAgent()

    async def run(self, question: str, context: dict | None = None) -> dict:
        result = await self.run_stream(question, lambda token: None)
        return {"success": True, "output": result}

    async def run_stream(self, question: str, on_token: Callable[[str], None]) -> dict:
        if BROAD_BUILD_RE.search(question):
            plan = await self._generate_once(PLAN_SYSTEM_PROMPT, question, on_token)
            return {
                "answer": plan,
                "validation": {"pass": True, "issues": []},
                "confidence": {"score": 90, "label": "high", "reason": "Implementation plan only — no code generated yet."},
            }

        system_prompt = LEETCODE_SYSTEM_PROMPT if DSA_RE.search(question) else CODE_SYSTEM_PROMPT
        regenerated = False

        answer = await self._generate_once(system_prompt, question, on_token)
        validation = self._validate(answer)

        if not validation["pass"]:
            fixed = await self._fix(system_prompt, answer, validation["issues"])
            if fixed:
                answer = fixed
                validation = self._validate(answer)

        if not validation["pass"] and validation["codeBroken"]:
            regenerated = True
            answer = await self._generate_once(system_prompt, _build_regenerate_prompt(question, validation["issues"]), lambda t: None)
            validation = self._validate(answer)

        confidence = _confidence_from_validation(validation, regenerated)

        if CODE_LLM_REVIEW and validation["pass"]:
            code_critique = await self.review_agent.critique(answer, question, domain="code")
            if not code_critique["pass"]:
                validation = {**validation, "pass": False, "issues": [*validation["issues"], *code_critique["issues"]]}
                score = min(confidence["score"], code_critique["confidenceScore"])
                confidence = {
                    "score": score,
                    "label": "high" if score >= 70 else "medium" if score >= 30 else "low",
                    "reason": code_critique["confidenceReason"] or "LLM review flagged algorithm/complexity issues.",
                }

        return {"answer": answer, "validation": validation, "confidence": confidence}

    def _validate(self, answer: str) -> dict:
        code_issues = quick_validate_code(answer)
        section_issues = _missing_sections(answer)
        return {
            "pass": code_issues["pass"] and len(section_issues) == 0,
            "codeBroken": not code_issues["pass"],
            "issues": [*code_issues["issues"], *[f"Missing required section: {s}" for s in section_issues]],
        }

    async def _generate_once(self, system_prompt: str, user_content: str, on_token: Callable[[str], None]) -> str:
        convo = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]
        answer = ""

        async with httpx.AsyncClient(timeout=180) as client:
            for _ in range(MAX_CONTINUATIONS + 1):
                piece = ""
                done_reason = "stop"

                async with client.stream(
                    "POST",
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": OLLAMA_CODE_MODEL,
                        "stream": True,
                        "messages": convo,
                        "options": {"temperature": 0.2, "top_p": 0.9, "num_predict": CODE_NUM_PREDICT},
                    },
                ) as res:
                    if res.status_code >= 400:
                        raise RuntimeError(f"Code generation failed: {res.status_code}")
                    async for line in res.aiter_lines():
                        if not line.strip():
                            continue
                        chunk = json.loads(line)
                        token = (chunk.get("message") or {}).get("content", "")
                        if token:
                            piece += token
                            answer += token
                            on_token(token)
                        if chunk.get("done"):
                            done_reason = chunk.get("done_reason", "stop")

                if not is_truncated(answer, done_reason):
                    break
                convo = [
                    *convo,
                    {"role": "assistant", "content": piece},
                    {"role": "user", "content": "Continue exactly where you left off. Do not repeat anything already written."},
                ]

        return close_unbalanced_fences(answer)

    async def _fix(self, system_prompt: str, answer: str, issues: list[str]):
        async with httpx.AsyncClient(timeout=180) as client:
            res = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_CODE_MODEL,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": _build_fix_prompt(answer, issues)},
                    ],
                    "options": {"temperature": 0.2, "top_p": 0.9, "num_predict": CODE_NUM_PREDICT},
                },
            )
            if res.status_code >= 400:
                return None
            data = res.json()
            fixed = (data.get("message") or {}).get("content", "")
            return close_unbalanced_fences(fixed) if fixed else None
