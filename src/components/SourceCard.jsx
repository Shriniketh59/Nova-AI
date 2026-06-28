function matchLevel(score) {
  if (score == null) return null;
  if (score >= 0.7) return { label: 'High match', cls: 'text-emerald-400' };
  if (score >= 0.4) return { label: 'Medium match', cls: 'text-amber-400' };
  return { label: 'Low match', cls: 'text-red-400' };
}

export default function SourceCard({ source }) {
  const isWeb = source.type === 'web';
  const match = matchLevel(source.confidence);

  const inner = (
    <div className="flex items-start gap-2.5 px-3 py-2.5 bg-white/5 border border-white/10 rounded-xl max-w-[240px] hover:bg-white/10 hover:border-white/20 transition-colors">
      <span className="text-base leading-none mt-0.5">{isWeb ? '🌐' : '📄'}</span>
      <div className="overflow-hidden min-w-0">
        <p className="text-xs text-zinc-200 truncate font-medium">{source.title || source.filename}</p>
        {source.page != null && (
          <p className="text-[10px] text-zinc-500">Page {source.page}</p>
        )}
        {match && (
          <p className={`text-[10px] font-medium ${match.cls}`}>{match.label}</p>
        )}
      </div>
    </div>
  );

  return isWeb && source.url ? (
    <a href={source.url} target="_blank" rel="noopener noreferrer">{inner}</a>
  ) : inner;
}
