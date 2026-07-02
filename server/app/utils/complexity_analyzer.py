import re

SORT_CALLS = re.compile(r"\.sort\(|Arrays\.sort|Collections\.sort|sorted\(")


def _max_loop_nesting_depth(code: str) -> int:
    lines = code.split("\n")
    max_depth = 0
    loop_indents: list[int] = []

    for line in lines:
        trimmed = line.strip()
        indent = len(line) - len(line.lstrip())

        while loop_indents and indent <= loop_indents[-1]:
            loop_indents.pop()
        if re.match(r"^(for|while)\b", trimmed):
            loop_indents.append(indent)
            max_depth = max(max_depth, len(loop_indents))
    return max_depth


def _detect_recursion(code: str) -> bool:
    def_match = re.search(r"\bdef\s+(\w+)\s*\(", code) or re.search(
        r"\b(?:public|private|protected|static|\s)*\w+\s+(\w+)\s*\([^)]*\)\s*\{", code
    )
    if not def_match:
        return False
    fn_name = def_match.group(1)
    if not fn_name:
        return False
    calls = len(re.findall(rf"\b{re.escape(fn_name)}\s*\(", code))
    return calls > 1


def analyze_structure(code: str) -> dict:
    return {
        "loopDepth": _max_loop_nesting_depth(code),
        "hasRecursion": _detect_recursion(code),
        "hasSort": bool(SORT_CALLS.search(code)),
    }


def check_complexity_claim(stated_text: str, code: str) -> dict:
    """Flags only blatant mismatches — a stated O(1)/O(log n) next to an actual
    nested loop, which is the failure mode that actually shows up (model
    copies a generic complexity line without checking its own code)."""
    structure = analyze_structure(code)
    issues = []
    stated = stated_text.lower()

    claims_constant = bool(re.search(r"\bo\(1\)", stated))
    claims_log = bool(re.search(r"\bo\(log", stated)) and not re.search(r"\bo\(n log", stated)
    claims_linear = bool(re.search(r"\bo\(n\)\b", stated)) and not re.search(r"\bo\(n[\s\S]{0,3}\^?2\)|\bo\(n²\)", stated)

    if (claims_constant or claims_log) and structure["loopDepth"] >= 1 and not structure["hasRecursion"]:
        issues.append(
            f"Stated complexity claims {'O(1)' if claims_constant else 'O(log n)'} but the code contains a loop — recheck the analysis."
        )
    if claims_linear and structure["loopDepth"] >= 2:
        issues.append("Stated complexity claims O(n) but the code has nested loops (likely O(n^2) or worse) — recheck the analysis.")

    return {"pass": len(issues) == 0, "issues": issues, "structure": structure}
