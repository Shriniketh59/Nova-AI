import {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  TableOfContents, PageBreak, Header, Footer, PageNumber, Table, TableRow,
  TableCell, WidthType, ShadingType
} from 'docx';

const BODY_FONT = 'Calibri';
const CODE_FONT = 'Consolas';

const HEADING_LEVEL_MAP = {
  1: HeadingLevel.HEADING_1,
  2: HeadingLevel.HEADING_2,
  3: HeadingLevel.HEADING_3
};

function buildCoverPage({ title, subtitle, author, date }) {
  return [
    new Paragraph({ text: '', spacing: { before: 2000 } }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new TextRun({ text: title || 'Untitled Document', bold: true, size: 56, font: BODY_FONT })]
    }),
    subtitle ? new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 200 },
      children: [new TextRun({ text: subtitle, size: 28, color: '595959', font: BODY_FONT })]
    }) : null,
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 600 },
      children: [new TextRun({ text: author || 'Nova AI', size: 24, font: BODY_FONT })]
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 100 },
      children: [new TextRun({ text: (date || new Date()).toLocaleDateString(), size: 20, color: '808080', font: BODY_FONT })]
    }),
    new Paragraph({ children: [new PageBreak()] })
  ].filter(Boolean);
}

function buildTocPage() {
  return [
    new Paragraph({ text: 'Table of Contents', heading: HeadingLevel.HEADING_1 }),
    new TableOfContents('Table of Contents', { hyperlink: true, headingStyleRange: '1-3' }),
    new Paragraph({ children: [new PageBreak()] })
  ];
}

function codeBlockParagraph(block) {
  return block.text.split('\n').map(line => new Paragraph({
    children: [new TextRun({ text: line || ' ', font: CODE_FONT, size: 20 })],
    shading: { type: ShadingType.SOLID, color: 'F0F0F0', fill: 'F0F0F0' },
    spacing: { after: 0 }
  }));
}

function buildTable(block) {
  const headerRow = new TableRow({
    children: block.headers.map(h => new TableCell({
      children: [new Paragraph({ children: [new TextRun({ text: h, bold: true, font: BODY_FONT })] })],
      shading: { type: ShadingType.SOLID, color: 'E0E0E0', fill: 'E0E0E0' }
    }))
  });
  const bodyRows = block.rows.map(row => new TableRow({
    children: row.map(cell => new TableCell({
      children: [new Paragraph({ children: [new TextRun({ text: cell, font: BODY_FONT })] })]
    }))
  }));
  return new Table({ width: { size: 100, type: WidthType.PERCENTAGE }, rows: [headerRow, ...bodyRows] });
}

// Page break before every H1 after the first — the cover/TOC pages already
// supply one page break each, so the body's own first H1 doesn't need another.
function blocksToDocxElements(blocks) {
  const elements = [];
  let seenFirstH1 = false;

  for (const block of blocks) {
    if (block.type === 'heading') {
      if (block.level === 1) {
        if (seenFirstH1) elements.push(new Paragraph({ children: [new PageBreak()] }));
        seenFirstH1 = true;
      }
      elements.push(new Paragraph({ text: block.text, heading: HEADING_LEVEL_MAP[block.level] }));
    } else if (block.type === 'paragraph') {
      elements.push(new Paragraph({ children: [new TextRun({ text: block.text, font: BODY_FONT, size: 22 })], spacing: { after: 160 } }));
    } else if (block.type === 'bullet') {
      for (const item of block.items) {
        elements.push(new Paragraph({ text: item, bullet: { level: 0 }, spacing: { after: 80 } }));
      }
    } else if (block.type === 'numbered') {
      block.items.forEach((item, idx) => {
        elements.push(new Paragraph({ children: [new TextRun({ text: `${idx + 1}. ${item}`, font: BODY_FONT, size: 22 })], spacing: { after: 80 } }));
      });
    } else if (block.type === 'code') {
      elements.push(...codeBlockParagraph(block));
    } else if (block.type === 'table') {
      elements.push(buildTable(block), new Paragraph({ text: '', spacing: { after: 160 } }));
    }
  }
  return elements;
}

export async function toDocx(blocks, meta = {}) {
  const { title, subtitle, author, date } = meta;

  const doc = new Document({
    sections: [{
      properties: {},
      headers: {
        default: new Header({
          children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: title || 'Document', size: 18, color: '808080' })] })]
        })
      },
      footers: {
        default: new Footer({
          children: [new Paragraph({
            alignment: AlignmentType.CENTER,
            children: [
              new TextRun({ text: 'Page ', size: 18 }),
              new TextRun({ children: [PageNumber.CURRENT], size: 18 }),
              new TextRun({ text: ' of ', size: 18 }),
              new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 18 })
            ]
          })]
        })
      },
      children: [
        ...buildCoverPage({ title, subtitle, author, date }),
        ...buildTocPage(),
        ...blocksToDocxElements(blocks)
      ]
    }],
    styles: {
      default: {
        document: { run: { font: BODY_FONT, size: 22 } },
        heading1: { run: { size: 36, bold: true, font: BODY_FONT }, paragraph: { spacing: { before: 240, after: 160 } } },
        heading2: { run: { size: 28, bold: true, font: BODY_FONT }, paragraph: { spacing: { before: 200, after: 120 } } },
        heading3: { run: { size: 24, bold: true, font: BODY_FONT }, paragraph: { spacing: { before: 160, after: 100 } } }
      }
    }
  });

  return Packer.toBlob(doc);
}
