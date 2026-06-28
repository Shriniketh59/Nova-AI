import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import CodeBlock from './CodeBlock';

export default function MessageContent({ content }) {
  if (!content) return null;
  return (
    <div className="text-[15px] leading-relaxed space-y-3 [&>*:first-child]:mt-0">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h1 className="text-xl font-semibold text-white mt-4 mb-2">{children}</h1>,
          h2: ({ children }) => <h2 className="text-lg font-semibold text-white mt-4 mb-2">{children}</h2>,
          h3: ({ children }) => <h3 className="text-base font-semibold text-white mt-3 mb-1.5">{children}</h3>,
          p: ({ children }) => <p className="whitespace-pre-wrap">{children}</p>,
          ul: ({ children }) => <ul className="list-disc pl-5 space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-5 space-y-1">{children}</ol>,
          li: ({ children }) => <li className="text-zinc-200">{children}</li>,
          strong: ({ children }) => <strong className="font-semibold text-white">{children}</strong>,
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noopener noreferrer" className="text-purple-400 hover:underline">
              {children}
            </a>
          ),
          blockquote: ({ children }) => (
            <div className="border-l-2 border-purple-400/60 bg-purple-500/5 pl-3 py-1.5 rounded-r-md text-zinc-300">
              {children}
            </div>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto rounded-lg border border-white/10 my-2">
              <table className="w-full text-sm">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-white/5">{children}</thead>,
          th: ({ children }) => <th className="px-3 py-2 text-left font-medium text-zinc-300 border-b border-white/10">{children}</th>,
          td: ({ children }) => <td className="px-3 py-2 border-b border-white/5 text-zinc-200">{children}</td>,
          code: ({ inline, className, children }) => {
            const match = /language-(\w+)/.exec(className || '');
            if (inline) {
              return <code className="px-1.5 py-0.5 rounded bg-white/10 text-purple-300 text-[13px] font-mono">{children}</code>;
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
