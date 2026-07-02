import ast
import re

from .complexity_analyzer import check_complexity_claim

BRACE_PAIRS = [("{", "}"), ("(", ")"), ("[", "]")]

IMPORT_HINTS = [
    {"lang": "python", "uses": re.compile(r"\bnp\."), "importRe": re.compile(r"^\s*import\s+numpy", re.M), "missing": "numpy"},
    {"lang": "python", "uses": re.compile(r"\bpd\."), "importRe": re.compile(r"^\s*import\s+pandas", re.M), "missing": "pandas"},
    {"lang": "javascript", "uses": re.compile(r"\baxios\."), "importRe": re.compile(r"require\(['\"]axios['\"]\)|from ['\"]axios['\"]"), "missing": "axios"},
    {"lang": "java", "uses": re.compile(r"\bList<"), "importRe": re.compile(r"import\s+java\.util\.(List|\*)"), "missing": "java.util.List"},
    {"lang": "java", "uses": re.compile(r"\bArrayList<"), "importRe": re.compile(r"import\s+java\.util\.(ArrayList|\*)"), "missing": "java.util.ArrayList"},
    {"lang": "java", "uses": re.compile(r"\bHashMap<"), "importRe": re.compile(r"import\s+java\.util\.(HashMap|\*)"), "missing": "java.util.HashMap"},
    {"lang": "java", "uses": re.compile(r"\bScanner\("), "importRe": re.compile(r"import\s+java\.util\.(Scanner|\*)"), "missing": "java.util.Scanner"},
]

_CODE_BLOCK_RE = re.compile(r"```(\w+)?\n([\s\S]*?)```")


def _extract_code_blocks(text: str) -> list[dict]:
    return [{"lang": (m.group(1) or "").lower(), "code": m.group(2)} for m in _CODE_BLOCK_RE.finditer(text)]


def _check_brace_balance(code: str) -> list[str]:
    issues = []
    for open_c, close_c in BRACE_PAIRS:
        opens = len(re.findall(re.escape(open_c), code))
        closes = len(re.findall(re.escape(close_c), code))
        if opens != closes:
            issues.append(f"Unbalanced {open_c}{close_c}: {opens} open vs {closes} close")
    return issues


def _check_missing_imports(lang: str, code: str) -> list[str]:
    return [
        f"Uses {h['missing']} without importing it"
        for h in IMPORT_HINTS
        if h["lang"] == lang and h["uses"].search(code) and not h["importRe"].search(code)
    ]


def _check_missing_return(lang: str, code: str) -> list[str]:
    issues = []
    if lang == "python":
        defs = re.findall(r"def\s+\w+\([^)]*\)\s*:", code)
        for d in defs:
            name = re.search(r"def\s+(\w+)", d).group(1)
            if name == "__init__":
                continue
            idx = code.index(d)
            body_match = re.search(r":\n([\s\S]*?)(?=\ndef\s|\nclass\s|$)", code[idx:])
            body = body_match.group(1) if body_match else ""
            if body.strip() and not re.search(r"\breturn\b", body) and not re.search(r"\byield\b", body) and not re.search(r"\bprint\(", body):
                issues.append(f'Function "{name}" has no return statement — likely meant to return a value')
    if lang == "java":
        method_re = re.compile(r"\b(?!void\b)(?:public|private|protected|static|\s)*[\w<>[\],\s]+\s+(\w+)\s*\([^)]*\)\s*\{")
        for m in method_re.finditer(code):
            start = m.end()
            depth = 1
            i = start
            while i < len(code) and depth > 0:
                if code[i] == "{":
                    depth += 1
                if code[i] == "}":
                    depth -= 1
                i += 1
            body = code[start:i - 1]
            name = m.group(1)
            if body.strip() and not re.search(r"\breturn\b", body) and "void" not in m.group(0) and not re.match(r"^(class|interface)\b", name):
                issues.append(f'Method "{name}" has a non-void signature but no return statement')
    return issues


def _check_infinite_loop_risk(code: str) -> list[str]:
    issues = []
    for m in re.finditer(r"\bwhile\s*\(?\s*(true|True|1)\s*\)?\s*[:{]", code):
        after = code[m.start():m.start() + 500]
        if not re.search(r"\bbreak\b", after) and not re.search(r"\breturn\b", after):
            issues.append("while(true)/while True loop with no break or return found in scanned range — possible infinite loop")
    return issues


def _check_python_syntax(code: str) -> list[str]:
    """Cheap, no-execution correctness check for Python: ast.parse() will
    raise SyntaxError on invalid syntax (unclosed brackets, bad indentation,
    truncated statements, etc). This is real validation, not a heuristic."""
    try:
        ast.parse(code)
        return []
    except SyntaxError as err:
        return [f"Python syntax error: {err.msg} (line {err.lineno})"]
    except Exception as err:
        return [f"Python syntax check failed: {err}"]


def _check_java_structure(code: str) -> list[str]:
    issues = []
    if re.search(r"\bpublic\s+class\s+(\w+)", code) and not re.search(r"\}\s*$", code.strip()):
        issues.append("Java class does not appear to close with a final closing brace")
    return issues


def quick_validate_code(answer_text: str) -> dict:
    issues: list[str] = []

    if len(re.findall(r"```", answer_text)) % 2 != 0:
        issues.append("Unclosed code fence")

    blocks = _extract_code_blocks(answer_text)
    if not blocks:
        issues.append("No code block found in response")

    for block in blocks:
        issues.extend(_check_brace_balance(block["code"]))
        issues.extend(_check_missing_imports(block["lang"], block["code"]))
        issues.extend(_check_missing_return(block["lang"], block["code"]))
        issues.extend(_check_infinite_loop_risk(block["code"]))
        if block["lang"] == "java":
            issues.extend(_check_java_structure(block["code"]))
        if block["lang"] == "python":
            issues.extend(_check_python_syntax(block["code"]))

    if blocks:
        complexity_check = check_complexity_claim(answer_text, blocks[0]["code"])
        issues.extend(complexity_check["issues"])

    return {"pass": len(issues) == 0, "issues": issues}
