import { parseMarkdown } from './markdownParser.js';
import { validateAndClean } from './validate.js';
import { toDocx } from './toDocx.js';
import { toPdf } from './toPdf.js';
import { toPptx } from './toPptx.js';
import { toXlsx } from './toXlsx.js';

function blocksToPlainText(blocks) {
  const lines = [];
  for (const block of blocks) {
    switch (block.type) {
      case 'heading':
        lines.push(block.text.toUpperCase(), '');
        break;
      case 'paragraph':
        lines.push(block.text, '');
        break;
      case 'bullet':
        for (const item of block.items) lines.push(`- ${item}`);
        lines.push('');
        break;
      case 'numbered':
        block.items.forEach((item, i) => lines.push(`${i + 1}. ${item}`));
        lines.push('');
        break;
      case 'code':
        lines.push(...block.text.split('\n'), '');
        break;
      case 'table':
        lines.push(block.headers.join('\t'));
        for (const row of block.rows) lines.push(row.join('\t'));
        lines.push('');
        break;
    }
  }
  return lines.join('\n').trim();
}

// Single entry point: parse -> validate/dedup -> hand the same clean block
// list to every renderer, so DOCX/PDF/TXT all agree on structure and none
// of them re-implement markdown parsing or duplicate-content cleanup.
export function buildExportableDocument(content, meta = {}) {
  const blocks = validateAndClean(parseMarkdown(content));
  return {
    toDocxBlob: () => toDocx(blocks, meta),
    toPdfBlob: () => toPdf(blocks, meta),
    toPptxBlob: () => toPptx(blocks, meta),
    toXlsxBlob: () => toXlsx(blocks, meta),
    toMarkdown: () => content,
    toTxt: () => blocksToPlainText(blocks)
  };
}
