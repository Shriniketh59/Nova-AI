import hashlib
import re
from typing import Tuple

# Common navigation, footer, boilerplate markers
BOILERPLATE_PATTERNS = [
    re.compile(r"^\s*(cookie policy|terms of service|privacy policy|all rights reserved|copyright ©|© \d{4}).*$", re.I | re.M),
    re.compile(r"^\s*(home\s*\|\s*about\s*\|\s*contact|menu\s*\|\s*search|skip to content).*$", re.I | re.M),
    re.compile(r"^\s*<!--[\s\S]*?-->\s*$", re.M),
]

ERROR_PAGE_PATTERNS = [
    re.compile(r"\b(404 not found|403 forbidden|500 internal server error|502 bad gateway|page not found|access denied|error occurred while processing)\b", re.I),
    re.compile(r"\{\s*\"error\"\s*:\s*\{.*?\}\s*\}", re.S),
    re.compile(r"\{\s*\"message\"\s*:\s*\"(?:Not Found|Unauthorized|Internal Server Error)\"\s*\}", re.I),
]

# Anti-contamination: detect Llama / AI generated disclaimers or assistant greetings
LLM_GENERATED_PATTERNS = [
    re.compile(r"\b(as an ai (?:language )?model|as an ai assistant|as an ai developed by|i am an ai|based on my training data|my knowledge cutoff)\b", re.I),
    re.compile(r"(here is a summary of the uploaded document|let me know if you need anything else|feel free to ask any other questions)", re.I),
]


def normalize_whitespace(text: str) -> str:
    if not text:
        return ""
    # Normalize carriage returns and non-breaking spaces
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    # Replace sequences of 3+ newlines with 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Replace runs of horizontal whitespace with single space
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def clean_content(raw_text: str) -> str:
    """Removes repetitive headers/footers, navigation links, and normalizes text."""
    if not raw_text:
        return ""
    text = raw_text
    for pat in BOILERPLATE_PATTERNS:
        text = pat.sub("", text)
    return normalize_whitespace(text)


def compute_content_hash(text: str) -> str:
    """Computes SHA-256 hash of normalized text."""
    norm = normalize_whitespace(text).lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def validate_document_quality(text: str, source_name: str = "") -> Tuple[bool, str]:
    """Validates that a document is real, non-empty content, and not an error or LLM hallucination."""
    if not text or len(text.strip()) < 20:
        return False, "Content too short or empty"

    cleaned = clean_content(text)
    if len(cleaned) < 20:
        return False, "Content too short after cleaning boilerplate"

    # Check for error pages or API error payloads
    for pat in ERROR_PAGE_PATTERNS:
        if pat.search(cleaned[:500]):
            return False, "Document appears to be an error page or API error response"

    # Check for LLM self-contamination
    for pat in LLM_GENERATED_PATTERNS:
        if pat.search(cleaned[:300]):
            return False, "Document appears to be AI-generated conversational output (preventing RAG self-contamination)"

    return True, "Valid"
