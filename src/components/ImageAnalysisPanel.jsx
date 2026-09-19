export default function ImageAnalysisPanel({ imageUrl, extractedText, analysis, findings }) {
  return (
    <div className="nova-surface-alt my-3 rounded-2xl border border-white/10 nova-border bg-white/[0.03] shadow-md overflow-hidden max-w-xl">
      {imageUrl && (
        <img src={imageUrl} alt="Uploaded" className="w-full max-h-64 object-contain bg-black/30" />
      )}

      <div className="divide-y divide-white/10">
        {extractedText && (
          <div className="px-4 py-3">
            <p className="text-xs font-semibold text-zinc-400 nova-text-muted mb-1.5 uppercase tracking-wide">Extracted Text</p>
            <p className="text-[13px] text-zinc-300 nova-text-muted whitespace-pre-wrap leading-relaxed">{extractedText}</p>
          </div>
        )}

        {analysis && (
          <div className="px-4 py-3">
            <div className="flex items-center justify-between mb-1.5">
              <p className="text-xs font-semibold text-zinc-400 nova-text-muted uppercase tracking-wide">Analysis</p>
            </div>
            <p className="text-[13px] text-zinc-300 nova-text-muted leading-relaxed">{analysis}</p>
          </div>
        )}

        {findings && findings.length > 0 && (
          <div className="px-4 py-3">
            <p className="text-xs font-semibold text-zinc-400 nova-text-muted mb-2 uppercase tracking-wide">Key Findings</p>
            <div className="space-y-1.5">
              {findings.map((f, i) => (
                <div key={i} className="flex items-start gap-2 text-[13px] text-zinc-200 nova-text">
                  <span className="text-purple-400 mt-0.5">•</span>
                  <span>{f}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
