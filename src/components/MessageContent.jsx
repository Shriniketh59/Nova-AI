import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import CodeBlock from './CodeBlock';

export default function MessageContent({ content }) {
  if (!content) return null;
  return (
    <div className="text-[15px] leading-relaxed text-zinc-100 space-y-3.5 [&>*:first-child]:mt-0 font-normal tracking-normal">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1 className="text-xl font-bold text-white tracking-tight mt-5 mb-2.5 pb-1 border-b border-white/10 flex items-center gap-2">
              <span className="w-1.5 h-4 bg-purple-500 rounded-full inline-block"></span>
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-lg font-semibold text-white tracking-tight mt-4 mb-2">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-base font-semibold text-purple-300 tracking-tight mt-3 mb-1.5">
              {children}
            </h3>
          ),
          p: ({ children }) => <p className="whitespace-pre-wrap text-zinc-200">{children}</p>,
          ul: ({ children }) => <ul className="list-disc pl-5 space-y-1.5 text-zinc-200 marker:text-purple-400">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-5 space-y-1.5 text-zinc-200 marker:text-purple-400 font-medium">{children}</ol>,
          li: ({ children }) => <li className="text-zinc-200 leading-relaxed">{children}</li>,
          strong: ({ children }) => <strong className="font-semibold text-white">{children}</strong>,
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noopener noreferrer" className="text-purple-400 hover:text-purple-300 underline underline-offset-4 font-medium transition-colors">
              {children}
            </a>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l-4 border-purple-500/80 bg-purple-500/10 px-4 py-2.5 rounded-r-xl text-zinc-200 italic my-3 shadow-sm border-y border-r border-purple-500/20">
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto rounded-xl border border-white/10 my-3 shadow-lg bg-[#0E0E14]">
              <table className="w-full text-sm text-left">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-white/5 border-b border-white/10 text-purple-300 uppercase text-[11px] font-mono font-semibold tracking-wider">{children}</thead>,
          th: ({ children }) => <th className="px-4 py-2.5 font-semibold border-b border-white/10">{children}</th>,
          td: ({ children }) => <td className="px-4 py-2.5 border-b border-white/5 text-zinc-200">{children}</td>,
          code: ({ inline, className, children }) => {
            const match = /language-(\w+)/.exec(className || '');
            if (inline) {
              return (
                <code className="px-1.5 py-0.5 rounded-md bg-purple-500/15 border border-purple-500/30 text-purple-300 text-[13px] font-mono font-medium shadow-xs">
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
