import re

SKILL_KEYWORDS = [
    "javascript", "python", "java", "react", "node", "sql", "aws", "docker",
    "kubernetes", "git", "html", "css", "typescript", "c++", "machine learning",
    "data analysis", "communication", "leadership",
]
SECTION_RE = {
    "education": re.compile(r"education[\s\S]{0,400}", re.I),
    "experience": re.compile(r"experience[\s\S]{0,600}", re.I),
    "projects": re.compile(r"projects?[\s\S]{0,600}", re.I),
    "certifications": re.compile(r"certificat\w*[\s\S]{0,300}", re.I),
}
QUANTIFIED_RE = re.compile(r"\b\d+%|\$\d+|\d+ years?\b", re.I)
ATS_REQUEST_RE = re.compile(r"\bats\b.*(score|calculate|rate)|calculate.*\bats\b", re.I)


def calculate_ats_score(resume_text: str) -> dict:
    lower = resume_text.lower()

    skills = [k for k in SKILL_KEYWORDS if k in lower]
    sections = {name: bool(regex.search(resume_text)) for name, regex in SECTION_RE.items()}

    missing_keywords = [k for k in SKILL_KEYWORDS if k not in skills][:8]

    score = 0
    score += min(len(skills), 10) * 4  # up to 40
    score += sum(1 for v in sections.values() if v) * 12  # up to 48
    score += 12 if QUANTIFIED_RE.search(resume_text) else 0
    score = min(100, score)

    strengths = []
    if len(skills) >= 5:
        strengths.append(f"{len(skills)} relevant technical skills found.")
    if sections["experience"]:
        strengths.append("Experience section present.")
    if sections["projects"]:
        strengths.append("Projects section present.")
    if sections["education"]:
        strengths.append("Education section present.")
    if not strengths:
        strengths.append("Resume parsed, but few standard ATS sections detected.")

    suggestions = []
    if not sections["certifications"]:
        suggestions.append("Add a Certifications section if applicable.")
    if len(skills) < 5:
        suggestions.append("Add more role-relevant keywords/skills.")
    if not QUANTIFIED_RE.search(resume_text):
        suggestions.append("Quantify achievements (numbers, %, $).")

    return {
        "score": score,
        "skillsFound": skills,
        "sectionsDetected": sections,
        "strengths": strengths,
        "missingKeywords": missing_keywords,
        "suggestions": suggestions,
    }


def is_ats_request(query: str) -> bool:
    return bool(ATS_REQUEST_RE.search(query))


def format_ats_answer(result: dict) -> str:
    strengths = "\n".join(f"- {s}" for s in result["strengths"])
    missing = "\n".join(f"- {k}" for k in result["missingKeywords"]) if result["missingKeywords"] else "- None detected"
    suggestions = (
        "\n".join(f"- {s}" for s in result["suggestions"])
        if result["suggestions"]
        else "- None — resume covers standard ATS sections."
    )
    return f"""ATS Score: {result['score']}/100

Strengths:
{strengths}

Missing Keywords:
{missing}

Improvement Suggestions:
{suggestions}"""
