import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import CodeBlock from './CodeBlock';

export default function MessageContent({ content }) {
  if (!content) return null;

  return (
    <div className="text-[14.5px] leading-relaxed text-zinc-200 space-y-3.5 [&>*:first-child]:mt-0 font-normal">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <div className="flex items-center gap-2 mt-5 mb-2.5 pb-1 border-b border-white/10">
              <span className="w-1 h-5 rounded-full bg-purple-500"></span>
              <h1 className="text-lg font-bold text-white tracking-tight">{children}</h1>
            </div>
          ),
          h2: ({ children }) => (
            <div className="flex items-center gap-2 mt-4 mb-2">
              <span className="w-1.5 h-1.5 rounded-full bg-purple-400"></span>
              <h2 className="text-[16px] font-semibold text-zinc-100 tracking-tight">{children}</h2>
            </div>
          ),
          h3: ({ children }) => (
            <h3 className="text-[15px] font-semibold text-purple-300 mt-3 mb-1">{children}</h3>
          ),
          p: ({ children }) => (
            <p className="whitespace-pre-wrap leading-relaxed text-zinc-200">{children}</p>
          ),
          ul: ({ children }) => (
            <ul className="space-y-1.5 pl-2 my-2">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal pl-5 space-y-1.5 my-2 text-zinc-200">{children}</ol>
          ),
          li: ({ children }) => (
            <li className="flex items-start gap-2 text-zinc-200 leading-relaxed">
              <span className="text-purple-400 mt-1 select-none text-xs">◆</span>
              <div className="flex-1">{children}</div>
            </li>
          ),
          strong: ({ children }) => (
            <strong className="font-semibold text-white bg-white/[0.04] px-1 py-0.5 rounded text-[14px]">{children}</strong>
          ),
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-purple-400 hover:text-purple-300 underline underline-offset-2 transition-colors font-medium"
            >
              {children}
            </a>
          ),
          blockquote: ({ children }) => (
            <div className="border-l-2 border-purple-500/80 bg-purple-950/20 pl-4 py-2 my-3 rounded-r-lg text-zinc-300 text-sm shadow-inner">
              {children}
            </div>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto rounded-xl border border-white/10 my-3 bg-zinc-900/50 shadow-md">
              <table className="w-full text-sm text-left">{children}</table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-white/[0.06] text-zinc-200 font-semibold border-b border-white/10">{children}</thead>
          ),
          th: ({ children }) => (
            <th className="px-4 py-2.5 text-xs uppercase tracking-wider font-semibold text-purple-300 border-b border-white/10">{children}</th>
          ),
          td: ({ children }) => (
            <td className="px-4 py-2.5 border-b border-white/5 text-zinc-300 text-[13.5px]">{children}</td>
          ),
          code: ({ inline, className, children }) => {
            const match = /language-(\w+)/.exec(className || '');
            if (inline) {
              return (
                <code className="px-1.5 py-0.5 rounded-md bg-purple-500/10 border border-purple-500/20 text-purple-300 text-[13px] font-mono font-medium">
                  {children}
                </code>
              );
            }
            return <CodeBlock language={match?.[1] || 'text'} code={String(children).replace(/\n$/, '')} />;
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
