import jsPDF from 'jspdf';

const MARGIN = 48;
const HEADING_SIZE = { 1: 20, 2: 16, 3: 13 };

// Manual layout: jsPDF has no flow/pagination primitive, so this tracks a
// cursor and adds a page whenever content would overflow — the bug in the
// old implementation (handleDownloadPdf in DocumentCard.jsx) was relying on
// splitTextToSize alone, which wraps within a page but never adds new ones,
// so anything past the first page silently ran off the bottom.
class PdfCursor {
  constructor(pdf) {
    this.pdf = pdf;
    this.pageWidth = pdf.internal.pageSize.getWidth();
    this.pageHeight = pdf.internal.pageSize.getHeight();
    this.maxWidth = this.pageWidth - MARGIN * 2;
    this.y = MARGIN;
  }

  ensureSpace(neededHeight) {
    if (this.y + neededHeight > this.pageHeight - MARGIN) {
      this.pdf.addPage();
      this.y = MARGIN;
    }
  }

  newPage() {
    this.pdf.addPage();
    this.y = MARGIN;
  }

  text(lines, { fontSize = 11, font = 'helvetica', style = 'normal', color = [0, 0, 0], lineHeight = 1.4, indent = 0 } = {}) {
    this.pdf.setFont(font, style);
    this.pdf.setFontSize(fontSize);
    this.pdf.setTextColor(...color);
    const wrapped = this.pdf.splitTextToSize(lines, this.maxWidth - indent);
    const lineGap = fontSize * lineHeight * 0.3528; // pt-ish conversion, matches jsPDF's unit:'pt' setup
    for (const line of wrapped) {
      this.ensureSpace(lineGap);
      this.pdf.text(line, MARGIN + indent, this.y);
      this.y += lineGap;
    }
  }
}

function renderCodeBlock(cursor, block) {
  const lines = block.text.split('\n');
  const fontSize = 9;
  const lineGap = fontSize * 1.4 * 0.3528;
  const blockHeight = lines.length * lineGap + 8;
  cursor.ensureSpace(Math.min(blockHeight, cursor.pageHeight - MARGIN * 2));

  cursor.pdf.setFillColor(240, 240, 240);
  const startY = cursor.y;
  cursor.pdf.rect(MARGIN - 4, startY - fontSize, cursor.maxWidth + 8, Math.min(blockHeight, cursor.pageHeight - startY), 'F');

  cursor.pdf.setFont('courier', 'normal');
  cursor.pdf.setFontSize(fontSize);
  cursor.pdf.setTextColor(20, 20, 20);
  for (const line of lines) {
    cursor.ensureSpace(lineGap);
    cursor.pdf.text(line, MARGIN, cursor.y);
    cursor.y += lineGap;
  }
  cursor.y += 8;
}

function renderTable(cursor, block) {
  const colCount = block.headers.length;
  const colWidth = cursor.maxWidth / colCount;
  const rowHeight = 20;

  const drawRow = (cells, { bold = false, fill = null } = {}) => {
    cursor.ensureSpace(rowHeight);
    if (fill) {
      cursor.pdf.setFillColor(...fill);
      cursor.pdf.rect(MARGIN, cursor.y - 12, cursor.maxWidth, rowHeight, 'F');
    }
    cursor.pdf.setFont('helvetica', bold ? 'bold' : 'normal');
    cursor.pdf.setFontSize(10);
    cursor.pdf.setTextColor(0, 0, 0);
    cells.forEach((cell, i) => {
      cursor.pdf.text(String(cell ?? ''), MARGIN + i * colWidth + 4, cursor.y);
    });
    cursor.pdf.setDrawColor(200, 200, 200);
    cursor.pdf.rect(MARGIN, cursor.y - 12, cursor.maxWidth, rowHeight);
    cursor.y += rowHeight;
  };

  drawRow(block.headers, { bold: true, fill: [224, 224, 224] });
  for (const row of block.rows) drawRow(row);
  cursor.y += 8;
}

function blockToPdf(cursor, block, { afterFirstH1 }) {
  switch (block.type) {
    case 'heading': {
      if (block.level === 1 && afterFirstH1.seen) cursor.newPage();
      if (block.level === 1) afterFirstH1.seen = true;
      cursor.y += 10;
      cursor.text(block.text, { fontSize: HEADING_SIZE[block.level], style: 'bold' });
      cursor.y += 4;
      break;
    }
    case 'paragraph':
      cursor.text(block.text, { fontSize: 11 });
      cursor.y += 6;
      break;
    case 'bullet':
      for (const item of block.items) {
        cursor.text(`•  ${item}`, { fontSize: 11, indent: 12 });
      }
      cursor.y += 4;
      break;
    case 'numbered':
      block.items.forEach((item, i) => cursor.text(`${i + 1}. ${item}`, { fontSize: 11, indent: 12 }));
      cursor.y += 4;
      break;
    case 'code':
      renderCodeBlock(cursor, block);
      break;
    case 'table':
      renderTable(cursor, block);
      break;
  }
}

function addPageNumbers(pdf) {
  const total = pdf.internal.getNumberOfPages();
  for (let i = 1; i <= total; i++) {
    pdf.setPage(i);
    pdf.setFont('helvetica', 'normal');
    pdf.setFontSize(9);
    pdf.setTextColor(120, 120, 120);
    pdf.text(`Page ${i} of ${total}`, pdf.internal.pageSize.getWidth() / 2, pdf.internal.pageSize.getHeight() - 24, { align: 'center' });
  }
}

export function toPdf(blocks, meta = {}) {
  const { title, subtitle, author, date } = meta;
  const pdf = new jsPDF({ unit: 'pt', format: 'a4' });
  const cursor = new PdfCursor(pdf);

  // Cover page
  cursor.y = cursor.pageHeight / 3;
  cursor.text(title || 'Untitled Document', { fontSize: 26, style: 'bold' });
  cursor.y += 10;
  if (subtitle) {
    cursor.text(subtitle, { fontSize: 14, color: [90, 90, 90] });
    cursor.y += 10;
  }
  cursor.text(author || 'Nova AI', { fontSize: 12 });
  cursor.text((date || new Date()).toLocaleDateString(), { fontSize: 10, color: [128, 128, 128] });
  cursor.newPage();

  const afterFirstH1 = { seen: false };
  for (const block of blocks) blockToPdf(cursor, block, { afterFirstH1 });

  addPageNumbers(pdf);
  return pdf.output('blob');
}
