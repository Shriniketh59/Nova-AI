export default function SourceCard({ source }) {
  const isWeb = source.type === 'web';
  const domain = source.website || source.domain;
  const snippet = source.snippet || source.content;

  const inner = (
    <div
      title={snippet ? `${source.title || source.filename}\n\n${snippet}` : source.title || source.filename}
      className="flex items-start gap-2.5 px-3 py-2 bg-white/5 border border-white/10 rounded-xl max-w-[260px] hover:bg-white/10 hover:border-white/20 transition-all cursor-pointer group"
    >
      <span className="text-base leading-none mt-0.5 shrink-0">{isWeb ? '🌐' : '📄'}</span>
      <div className="overflow-hidden min-w-0 flex-1">
        <p className="text-xs text-zinc-200 truncate font-medium group-hover:text-blue-400 transition-colors">
          {source.title || source.filename}
        </p>
        <div className="flex items-center gap-1.5 mt-0.5">
          {domain && (
            <span className="text-[10px] text-zinc-400 truncate max-w-[140px] font-mono">
              {domain}
            </span>
          )}
          {source.page != null && (
            <span className="text-[10px] text-zinc-500">Page {source.page}</span>
          )}
        </div>
      </div>
    </div>
  );

  return isWeb && source.url ? (
    <a href={source.url} target="_blank" rel="noopener noreferrer" className="no-underline">
      {inner}
    </a>
  ) : inner;
}
