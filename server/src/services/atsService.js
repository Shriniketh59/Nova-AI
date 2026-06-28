// Real resume parsing for ATS scoring — no hypothetical/generated explanations.
const SKILL_KEYWORDS = ['javascript', 'python', 'java', 'react', 'node', 'sql', 'aws', 'docker', 'kubernetes', 'git', 'html', 'css', 'typescript', 'c++', 'machine learning', 'data analysis', 'communication', 'leadership'];
const SECTION_RE = {
  education: /education[\s\S]{0,400}/i,
  experience: /experience[\s\S]{0,600}/i,
  projects: /projects?[\s\S]{0,600}/i,
  certifications: /certificat\w*[\s\S]{0,300}/i
};

export function calculateAtsScore(resumeText) {
  const lower = resumeText.toLowerCase();

  const skills = SKILL_KEYWORDS.filter(k => lower.includes(k));
  const sections = {};
  for (const [name, re] of Object.entries(SECTION_RE)) {
    sections[name] = re.test(resumeText);
  }

  const missingKeywords = SKILL_KEYWORDS.filter(k => !skills.includes(k)).slice(0, 8);

  let score = 0;
  score += Math.min(skills.length, 10) * 4; // up to 40
  score += Object.values(sections).filter(Boolean).length * 12; // up to 48 (4 sections)
  score += /\b\d+%|\$\d+|\d+ years?\b/i.test(resumeText) ? 12 : 0; // quantified impact
  score = Math.min(100, score);

  const strengths = [];
  if (skills.length >= 5) strengths.push(`${skills.length} relevant technical skills found.`);
  if (sections.experience) strengths.push('Experience section present.');
  if (sections.projects) strengths.push('Projects section present.');
  if (sections.education) strengths.push('Education section present.');
  if (strengths.length === 0) strengths.push('Resume parsed, but few standard ATS sections detected.');

  const suggestions = [];
  if (!sections.certifications) suggestions.push('Add a Certifications section if applicable.');
  if (skills.length < 5) suggestions.push('Add more role-relevant keywords/skills.');
  if (!/\b\d+%|\$\d+|\d+ years?\b/i.test(resumeText)) suggestions.push('Quantify achievements (numbers, %, $).');

  return {
    score,
    skillsFound: skills,
    sectionsDetected: sections,
    strengths,
    missingKeywords,
    suggestions
  };
}

export function isAtsRequest(query) {
  return /\bats\b.*(score|calculate|rate)|calculate.*\bats\b/i.test(query);
}

export function formatAtsAnswer(result) {
  return `ATS Score: ${result.score}/100

Strengths:
${result.strengths.map(s => `- ${s}`).join('\n')}

Missing Keywords:
${result.missingKeywords.length ? result.missingKeywords.map(k => `- ${k}`).join('\n') : '- None detected'}

Improvement Suggestions:
${result.suggestions.length ? result.suggestions.map(s => `- ${s}`).join('\n') : '- None — resume covers standard ATS sections.'}`;
}
