import { useState } from 'react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { saveAs } from 'file-saver';

const EXT_MAP = {
  javascript: 'js', jsx: 'jsx', typescript: 'ts', tsx: 'tsx', python: 'py',
  java: 'java', c: 'c', cpp: 'cpp', csharp: 'cs', go: 'go', rust: 'rs',
  ruby: 'rb', php: 'php', html: 'html', css: 'css', json: 'json',
  bash: 'sh', shell: 'sh', sql: 'sql', yaml: 'yml', markdown: 'md',
};

export default function CodeBlock({ language = 'text', code }) {
  const [copied, setCopied] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  const handleDownload = () => {
    const ext = EXT_MAP[language.toLowerCase()] || 'txt';
    const blob = new Blob([code], { type: 'text/plain;charset=utf-8' });
    saveAs(blob, `nova-snippet.${ext}`);
  };

  const lineCount = code.split('\n').length;

  return (
    <div className="my-4 rounded-xl border border-white/10 bg-[#0A0A0E] overflow-hidden shadow-xl group">
      {/* Header Bar */}
      <div className="flex items-center justify-between px-3.5 py-2.5 bg-zinc-900/90 backdrop-blur-md border-b border-white/10 select-none">
        <div className="flex items-center gap-2">
          <div className="flex gap-1.5 mr-1">
            <span className="w-2.5 h-2.5 rounded-full bg-red-500/40 border border-red-500/60 inline-block"></span>
            <span className="w-2.5 h-2.5 rounded-full bg-amber-500/40 border border-amber-500/60 inline-block"></span>
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/40 border border-emerald-500/60 inline-block"></span>
          </div>
          <span className="text-[11px] font-mono font-semibold uppercase tracking-wider text-purple-300 bg-gradient-to-r from-purple-500/15 to-indigo-500/15 border border-purple-500/30 px-2.5 py-0.5 rounded-md shadow-sm">
            {language || 'text'}
          </span>
          <span className="text-[11px] text-zinc-500 font-mono hidden sm:inline">
            {lineCount} {lineCount === 1 ? 'line' : 'lines'}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setCollapsed(c => !c)}
            className="text-[11px] font-medium text-zinc-400 hover:text-white px-2 py-1 rounded-md hover:bg-white/10 transition-colors"
            title={collapsed ? 'Expand code block' : 'Collapse code block'}
          >
            {collapsed ? 'Expand' : 'Collapse'}
          </button>
          <button
            onClick={handleDownload}
            className="text-[11px] font-medium text-zinc-400 hover:text-white px-2 py-1 rounded-md hover:bg-white/10 transition-colors hidden sm:block"
            title="Download snippet"
          >
            Download
          </button>
          <button
            onClick={handleCopy}
            className={`flex items-center gap-1 text-[11px] font-medium px-2.5 py-1 rounded-md transition-all shadow-sm ${
              copied
                ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                : 'text-zinc-200 hover:text-white bg-white/5 hover:bg-white/10 border border-white/10'
            }`}
            title="Copy code"
          >
            {copied ? (
              <>
                <svg className="w-3 h-3 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
                <span>Copied!</span>
              </>
            ) : (
              <>
                <svg className="w-3 h-3 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
                <span>Copy</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Code Area */}
      {!collapsed && (
        <div className="overflow-x-auto text-[13px] font-mono leading-relaxed">
          <SyntaxHighlighter
            language={language}
            style={oneDark}
            showLineNumbers={lineCount > 1}
            customStyle={{
              margin: 0,
              padding: '16px',
              background: 'transparent',
              fontSize: '13px',
              lineHeight: '1.6',
            }}
          >
            {code}
          </SyntaxHighlighter>
        </div>
      )}
    </div>
  );
}
