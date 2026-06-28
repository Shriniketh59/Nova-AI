// Detects "the user is asking for a standalone document" independent of
// file attachment — taskRouter.js's document_analysis/resume_analysis only
// fire when a file is already attached, which is the wrong signal for
// "write me an implementation plan" (no file involved at all). Regex, not
// an LLM call, so this adds zero latency to either chat path.
const DOC_VERB_RE = /\b(write|create|draft|generate|prepare|build|design|make)\b/i;

const DOC_TYPE_PATTERNS = [
  [/implementation plan/i, 'implementation_plan', 'Implementation Plan'],
  [/project report/i, 'project_report', 'Project Report'],
  [/research paper/i, 'research_paper', 'Research Paper'],
  [/\bsrs\b|software requirements? specification/i, 'srs', 'Software Requirements Specification'],
  [/\bresume\b|\bcv\b/i, 'resume', 'Resume'],
  [/cover letter/i, 'cover_letter', 'Cover Letter'],
  [/business proposal/i, 'business_proposal', 'Business Proposal'],
  [/meeting minutes/i, 'meeting_minutes', 'Meeting Minutes'],
  [/api documentation/i, 'api_documentation', 'API Documentation'],
  [/technical documentation/i, 'technical_documentation', 'Technical Documentation'],
  [/\bassignment\b/i, 'assignment', 'Assignment'],
  [/white ?paper/i, 'white_paper', 'White Paper'],
  [/\bdocumentation\b/i, 'documentation', 'Documentation']
];

export function detectDocumentRequest(query) {
  if (!query || !DOC_VERB_RE.test(query)) return null;
  for (const [re, type, label] of DOC_TYPE_PATTERNS) {
    if (re.test(query)) return { type, label };
  }
  return null;
}

// Strips markdown syntax for a short preview line — same intent as
// DocumentCard's existing inline preview, used here for the `summary` field
// stored alongside the full content.
export function buildSummary(answer, maxLen = 160) {
  const stripped = (answer || '').replace(/[#*_`>-]/g, ' ').replace(/\s+/g, ' ').trim();
  return stripped.length > maxLen ? `${stripped.slice(0, maxLen)}…` : stripped;
}
