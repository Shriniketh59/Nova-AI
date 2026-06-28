import PptxGenJS from 'pptxgenjs';

// One slide per top-level section (H1/H2), title slide first. Reuses the
// same Block[] every other format renders from, so a duplicate-heading-free,
// hierarchy-fixed document is what becomes slides too.
export async function toPptx(blocks, meta = {}) {
  const { title, subtitle, author, date } = meta;
  const pptx = new PptxGenJS();
  pptx.author = author || 'Nova AI';
  pptx.title = title || 'Document';

  const titleSlide = pptx.addSlide();
  titleSlide.addText(title || 'Untitled Document', { x: 0.5, y: 2, w: 9, h: 1.2, fontSize: 32, bold: true, align: 'center' });
  if (subtitle) {
    titleSlide.addText(subtitle, { x: 0.5, y: 3.2, w: 9, h: 0.6, fontSize: 16, color: '595959', align: 'center' });
  }
  titleSlide.addText(`${author || 'Nova AI'}  •  ${(date || new Date()).toLocaleDateString()}`, {
    x: 0.5, y: 4.2, w: 9, h: 0.5, fontSize: 12, color: '808080', align: 'center'
  });

  let currentSlide = null;
  let cursorY = 0.5;

  const ensureSlide = () => {
    if (!currentSlide) {
      currentSlide = pptx.addSlide();
      cursorY = 0.5;
    }
    return currentSlide;
  };

  const newSlideFor = (headingText) => {
    currentSlide = pptx.addSlide();
    cursorY = 0.4;
    currentSlide.addText(headingText, { x: 0.4, y: cursorY, w: 9.2, h: 0.6, fontSize: 24, bold: true });
    cursorY += 0.8;
    return currentSlide;
  };

  for (const block of blocks) {
    if (block.type === 'heading' && (block.level === 1 || block.level === 2)) {
      newSlideFor(block.text);
      continue;
    }

    const slide = ensureSlide();
    if (cursorY > 6.5) {
      currentSlide = pptx.addSlide();
      cursorY = 0.5;
    }

    if (block.type === 'heading') {
      slide.addText(block.text, { x: 0.6, y: cursorY, w: 8.8, h: 0.4, fontSize: 18, bold: true });
      cursorY += 0.5;
    } else if (block.type === 'paragraph') {
      slide.addText(block.text, { x: 0.6, y: cursorY, w: 8.8, h: 0.8, fontSize: 14 });
      cursorY += 0.9;
    } else if (block.type === 'bullet' || block.type === 'numbered') {
      const textItems = block.items.map(item => ({ text: item, options: { bullet: block.type === 'bullet' } }));
      const h = Math.max(0.4, block.items.length * 0.35);
      slide.addText(textItems, { x: 0.6, y: cursorY, w: 8.8, h, fontSize: 13 });
      cursorY += h + 0.1;
    } else if (block.type === 'code') {
      const lines = block.text.split('\n');
      const h = Math.max(0.5, lines.length * 0.25);
      slide.addText(block.text, { x: 0.6, y: cursorY, w: 8.8, h, fontSize: 11, fontFace: 'Consolas', fill: { color: 'F0F0F0' } });
      cursorY += h + 0.2;
    } else if (block.type === 'table') {
      const rows = [block.headers.map(h => ({ text: h, options: { bold: true, fill: { color: 'E0E0E0' } } })), ...block.rows];
      const h = Math.max(0.5, rows.length * 0.35);
      slide.addTable(rows, { x: 0.6, y: cursorY, w: 8.8, h, fontSize: 11 });
      cursorY += h + 0.2;
    }
  }

  return pptx.write({ outputType: 'blob' });
}
