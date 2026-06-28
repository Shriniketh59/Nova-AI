import { useState } from 'react';
import { saveAs } from 'file-saver';
import { buildExportableDocument } from '../utils/documentExport/index.js';

function humanizeType(type) {
  if (!type) return null;
  return type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

export default function DocumentCard({ title, summary, content, type }) {
  const [busy, setBusy] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(content);
  };

  const withBusy = async (fn) => {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  const meta = { title: title || 'Untitled Document', subtitle: summary, author: 'Nova AI', date: new Date() };

  const handleDownloadDocx = () => withBusy(async () => {
    const doc = buildExportableDocument(content, meta);
    const blob = await doc.toDocxBlob();
    saveAs(blob, `${title || 'document'}.docx`);
  });

  const handleDownloadPdf = () => withBusy(async () => {
    const doc = buildExportableDocument(content, meta);
    const blob = doc.toPdfBlob();
    saveAs(blob, `${title || 'document'}.pdf`);
  });

  const handleDownloadMarkdown = () => withBusy(async () => {
    const doc = buildExportableDocument(content, meta);
    saveAs(new Blob([doc.toMarkdown()], { type: 'text/markdown' }), `${title || 'document'}.md`);
  });

  const handleDownloadTxt = () => withBusy(async () => {
    const doc = buildExportableDocument(content, meta);
    saveAs(new Blob([doc.toTxt()], { type: 'text/plain' }), `${title || 'document'}.txt`);
  });

  const handleDownloadPptx = () => withBusy(async () => {
    const doc = buildExportableDocument(content, meta);
    const blob = await doc.toPptxBlob();
    saveAs(blob, `${title || 'document'}.pptx`);
  });

  const handleDownloadXlsx = () => withBusy(async () => {
    const doc = buildExportableDocument(content, meta);
    const blob = await doc.toXlsxBlob();
    saveAs(blob, `${title || 'document'}.xlsx`);
  });

  return (
    <div className="my-3 rounded-2xl border border-white/10 bg-white/[0.03] shadow-md overflow-hidden max-w-xl">
      <div className="px-4 py-3 border-b border-white/10 bg-white/5">
        <div className="flex items-center gap-2">
          <p className="text-sm font-semibold text-white">{title || 'Generated Document'}</p>
          {type && (
            <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-purple-500/15 text-purple-300 border border-purple-500/20">
              {humanizeType(type)}
            </span>
          )}
        </div>
        {summary && <p className="text-xs text-zinc-400 mt-1">{summary}</p>}
      </div>

      <div className="px-4 py-3 max-h-64 overflow-y-auto">
        <p className="text-[13px] text-zinc-300 whitespace-pre-wrap leading-relaxed">
          {content?.slice(0, 800)}{content?.length > 800 ? '…' : ''}
        </p>
      </div>

      <div className="flex items-center gap-2 px-4 py-2.5 border-t border-white/10 bg-white/5 flex-wrap">
        <button
          onClick={handleDownloadDocx}
          disabled={busy}
          className="text-xs font-medium px-3 py-1.5 rounded-lg bg-purple-500/15 text-purple-300 hover:bg-purple-500/25 transition-colors disabled:opacity-50"
        >
          Download DOCX
        </button>
        <button
          onClick={handleDownloadPdf}
          disabled={busy}
          className="text-xs font-medium px-3 py-1.5 rounded-lg bg-white/10 text-zinc-200 hover:bg-white/20 transition-colors disabled:opacity-50"
        >
          Download PDF
        </button>
        <button
          onClick={handleDownloadMarkdown}
          disabled={busy}
          className="text-xs font-medium px-3 py-1.5 rounded-lg bg-white/10 text-zinc-200 hover:bg-white/20 transition-colors disabled:opacity-50"
        >
          Download Markdown
        </button>
        <button
          onClick={handleDownloadTxt}
          disabled={busy}
          className="text-xs font-medium px-3 py-1.5 rounded-lg bg-white/10 text-zinc-200 hover:bg-white/20 transition-colors disabled:opacity-50"
        >
          Download TXT
        </button>
        <button
          onClick={handleDownloadPptx}
          disabled={busy}
          className="text-xs font-medium px-3 py-1.5 rounded-lg bg-white/10 text-zinc-200 hover:bg-white/20 transition-colors disabled:opacity-50"
        >
          Download PPTX
        </button>
        <button
          onClick={handleDownloadXlsx}
          disabled={busy}
          className="text-xs font-medium px-3 py-1.5 rounded-lg bg-white/10 text-zinc-200 hover:bg-white/20 transition-colors disabled:opacity-50"
        >
          Download XLSX
        </button>
        <button
          onClick={handleCopy}
          className="text-xs font-medium px-3 py-1.5 rounded-lg bg-white/10 text-zinc-200 hover:bg-white/20 transition-colors"
        >
          Copy Content
        </button>
      </div>
    </div>
  );
}
