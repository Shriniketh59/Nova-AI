import re

DOC_VERB_RE = re.compile(r"\b(write|create|draft|generate|prepare|build|design|make)\b", re.I)

DOC_TYPE_PATTERNS = [
    (re.compile(r"implementation plan", re.I), "implementation_plan", "Implementation Plan"),
    (re.compile(r"project report", re.I), "project_report", "Project Report"),
    (re.compile(r"research paper", re.I), "research_paper", "Research Paper"),
    (re.compile(r"\bsrs\b|software requirements? specification", re.I), "srs", "Software Requirements Specification"),
    (re.compile(r"\bresume\b|\bcv\b", re.I), "resume", "Resume"),
    (re.compile(r"cover letter", re.I), "cover_letter", "Cover Letter"),
    (re.compile(r"business proposal", re.I), "business_proposal", "Business Proposal"),
    (re.compile(r"meeting minutes", re.I), "meeting_minutes", "Meeting Minutes"),
    (re.compile(r"api documentation", re.I), "api_documentation", "API Documentation"),
    (re.compile(r"technical documentation", re.I), "technical_documentation", "Technical Documentation"),
    (re.compile(r"\bassignment\b", re.I), "assignment", "Assignment"),
    (re.compile(r"white ?paper", re.I), "white_paper", "White Paper"),
    (re.compile(r"\bdocumentation\b", re.I), "documentation", "Documentation"),
]


def detect_document_request(query: str):
    if not query or not DOC_VERB_RE.search(query):
        return None
    for regex, doc_type, label in DOC_TYPE_PATTERNS:
        if regex.search(query):
            return {"type": doc_type, "label": label}
    return None


def build_summary(answer: str, max_len: int = 160) -> str:
    stripped = re.sub(r"\s+", " ", re.sub(r"[#*_`>-]", " ", answer or "")).strip()
    return f"{stripped[:max_len]}…" if len(stripped) > max_len else stripped
