// Turns a markdown-ish answer string into a structured block list so every
// export target (docx/pdf/txt) renders the same structure instead of each
// reinventing its own ad-hoc line-splitting (the bug this module replaces:
// DocumentCard.jsx used to make one docx Paragraph PER RAW LINE, fragmenting
// prose and never recognizing lists/tables/code at all).

const HEADING_RE = /^(#{1,3})\s+(.*)$/;
const BULLET_RE = /^[-*]\s+(.*)$/;
const NUMBERED_RE = /^\d+\.\s+(.*)$/;
const CODE_FENCE_RE = /^```(\w*)\s*$/;
const TABLE_ROW_RE = /^\|(.+)\|\s*$/;
const TABLE_SEP_RE = /^\|[\s:|-]+\|\s*$/;

function splitTableRow(line) {
  return line.replace(/^\||\|$/g, '').split('|').map(c => c.trim());
}

export function parseMarkdown(content) {
  const lines = (content || '').split('\n');
  const blocks = [];
  let i = 0;

  let paragraphBuffer = [];
  const flushParagraph = () => {
    if (paragraphBuffer.length > 0) {
      const text = paragraphBuffer.join(' ').trim();
      if (text) blocks.push({ type: 'paragraph', text });
      paragraphBuffer = [];
    }
  };

  while (i < lines.length) {
    const line = lines[i];

    const fenceMatch = line.match(CODE_FENCE_RE);
    if (fenceMatch) {
      flushParagraph();
      const lang = fenceMatch[1] || '';
      const codeLines = [];
      i++;
      while (i < lines.length && !CODE_FENCE_RE.test(lines[i])) {
        codeLines.push(lines[i]);
        i++;
      }
      blocks.push({ type: 'code', lang, text: codeLines.join('\n') });
      i++; // skip closing fence
      continue;
    }

    const headingMatch = line.match(HEADING_RE);
    if (headingMatch) {
      flushParagraph();
      blocks.push({ type: 'heading', level: headingMatch[1].length, text: headingMatch[2].trim() });
      i++;
      continue;
    }

    if (TABLE_ROW_RE.test(line) && TABLE_SEP_RE.test(lines[i + 1] || '')) {
      flushParagraph();
      const headers = splitTableRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && TABLE_ROW_RE.test(lines[i])) {
        rows.push(splitTableRow(lines[i]));
        i++;
      }
      blocks.push({ type: 'table', headers, rows });
      continue;
    }

    if (BULLET_RE.test(line)) {
      flushParagraph();
      const items = [];
      while (i < lines.length && BULLET_RE.test(lines[i])) {
        items.push(lines[i].match(BULLET_RE)[1].trim());
        i++;
      }
      blocks.push({ type: 'bullet', items });
      continue;
    }

    if (NUMBERED_RE.test(line)) {
      flushParagraph();
      const items = [];
      while (i < lines.length && NUMBERED_RE.test(lines[i])) {
        items.push(lines[i].match(NUMBERED_RE)[1].trim());
        i++;
      }
      blocks.push({ type: 'numbered', items });
      continue;
    }

    if (line.trim() === '') {
      flushParagraph();
      i++;
      continue;
    }

    paragraphBuffer.push(line.trim());
    i++;
  }

  flushParagraph();
  return blocks;
}
