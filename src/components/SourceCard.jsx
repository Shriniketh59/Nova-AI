export default function SourceCard({ source }) {
  const isWeb = source.type === 'web';

  const inner = (
    <div className="flex items-start gap-2.5 px-3 py-2.5 bg-white/5 border border-white/10 rounded-xl max-w-[240px] hover:bg-white/10 hover:border-white/20 transition-colors">
      <span className="text-base leading-none mt-0.5">{isWeb ? '🌐' : '📄'}</span>
      <div className="overflow-hidden min-w-0">
        <p className="text-xs text-zinc-200 truncate font-medium">{source.title || source.filename}</p>
        {source.page != null && (
          <p className="text-[10px] text-zinc-500">Page {source.page}</p>
        )}
      </div>
    </div>
  );

  return isWeb && source.url ? (
    <a href={source.url} target="_blank" rel="noopener noreferrer">{inner}</a>
  ) : inner;
}
