// Cleans a parsed block list before it's handed to a renderer — fixes the
// specific complaints (duplicate headings, duplicate paragraphs, broken
// heading hierarchy, multiple titles/conclusions, empty sections) without
// ever silently dropping real content, only de-duplicating or demoting it.

const norm = (text) => text.trim().toLowerCase().replace(/\s+/g, ' ');
const CONCLUSION_RE = /^(conclusion|summary|final thoughts)s?$/i;

function dedupeHeadingsAndParagraphs(blocks) {
  const seenHeadings = new Set();
  const seenParagraphs = new Set();
  const out = [];
  for (const block of blocks) {
    if (block.type === 'heading') {
      const key = norm(block.text);
      if (seenHeadings.has(key)) continue;
      seenHeadings.add(key);
    }
    if (block.type === 'paragraph') {
      const key = norm(block.text);
      if (seenParagraphs.has(key)) continue;
      seenParagraphs.add(key);
    }
    out.push(block);
  }
  return out;
}

// Word's TOC needs a contiguous hierarchy (H1 -> H2 -> H3, never H1 -> H3
// directly) — demote any heading that jumps more than one level deeper
// than the heading before it.
function fixHeadingHierarchy(blocks) {
  let lastLevel = 0;
  return blocks.map(block => {
    if (block.type !== 'heading') return block;
    const level = block.level > lastLevel + 1 ? lastLevel + 1 : block.level;
    lastLevel = level;
    return { ...block, level };
  });
}

// Only the first H1 stays a title; later H1s demote to H2 so "one title
// only" holds without deleting whatever content followed them.
function enforceSingleTitle(blocks) {
  let titleSeen = false;
  return blocks.map(block => {
    if (block.type !== 'heading' || block.level !== 1) return block;
    if (!titleSeen) {
      titleSeen = true;
      return block;
    }
    return { ...block, level: 2 };
  });
}

// Multiple "Conclusion"/"Summary" headings: keep the last (usually most
// complete after a regenerate/continue pass), demote earlier ones to H3
// so they read as sub-notes instead of competing top-level sections.
function enforceSingleConclusion(blocks) {
  const conclusionIndexes = blocks
    .map((b, i) => (b.type === 'heading' && CONCLUSION_RE.test(b.text) ? i : -1))
    .filter(i => i !== -1);
  if (conclusionIndexes.length <= 1) return blocks;

  const keepIndex = conclusionIndexes[conclusionIndexes.length - 1];
  return blocks.map((block, i) => {
    if (conclusionIndexes.includes(i) && i !== keepIndex) {
      return { ...block, level: 3 };
    }
    return block;
  });
}

// A heading with nothing but another heading (or end of doc) right after
// it is an empty section — drop it, it can't render meaningfully and
// breaks "no empty sections" + leaves a dangling TOC entry.
function dropEmptySections(blocks) {
  const out = [];
  for (let i = 0; i < blocks.length; i++) {
    const block = blocks[i];
    if (block.type === 'heading') {
      const next = blocks[i + 1];
      if (!next || next.type === 'heading') continue;
    }
    out.push(block);
  }
  return out;
}

export function validateAndClean(blocks) {
  let result = dedupeHeadingsAndParagraphs(blocks);
  result = fixHeadingHierarchy(result);
  result = enforceSingleTitle(result);
  result = enforceSingleConclusion(result);
  result = dropEmptySections(result);
  return result;
}
