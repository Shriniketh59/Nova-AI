import ExcelJS from 'exceljs';

// Best-effort tabular dump of a markdown document — prose doesn't naturally
// belong in cells, so headings become bold section-header rows and
// paragraphs/bullets become single-column rows; `table` blocks are the only
// part that maps cleanly, and get real multi-column ranges with header styling.
export async function toXlsx(blocks, meta = {}) {
  const { title, author } = meta;
  const workbook = new ExcelJS.Workbook();
  workbook.creator = author || 'Nova AI';
  workbook.created = new Date();

  const sheet = workbook.addWorksheet('Document');
  sheet.getColumn(1).width = 100;

  sheet.addRow([title || 'Untitled Document']).font = { bold: true, size: 16 };
  sheet.addRow([]);

  for (const block of blocks) {
    if (block.type === 'heading') {
      const row = sheet.addRow([block.text]);
      row.font = { bold: true, size: block.level === 1 ? 14 : block.level === 2 ? 12 : 11 };
    } else if (block.type === 'paragraph') {
      sheet.addRow([block.text]);
    } else if (block.type === 'bullet') {
      for (const item of block.items) sheet.addRow([`•  ${item}`]);
    } else if (block.type === 'numbered') {
      block.items.forEach((item, i) => sheet.addRow([`${i + 1}. ${item}`]));
    } else if (block.type === 'code') {
      for (const line of block.text.split('\n')) {
        const row = sheet.addRow([line]);
        row.font = { name: 'Consolas', size: 10 };
      }
    } else if (block.type === 'table') {
      const headerRow = sheet.addRow(block.headers);
      headerRow.font = { bold: true };
      headerRow.eachCell(cell => { cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE0E0E0' } }; });
      for (const dataRow of block.rows) sheet.addRow(dataRow);
    }
    sheet.addRow([]);
  }

  const buffer = await workbook.xlsx.writeBuffer();
  return new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
}
