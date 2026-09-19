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
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback if clipboard API is restricted
      const textarea = document.createElement('textarea');
      textarea.value = code;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleDownload = () => {
    const ext = EXT_MAP[language.toLowerCase()] || 'txt';
    const blob = new Blob([code], { type: 'text/plain;charset=utf-8' });
    saveAs(blob, `solution.${ext}`);
  };

  const lineCount = code.split('\n').length;

  return (
    <div className="my-4 rounded-xl border border-white/10 bg-[#0E0E14] overflow-hidden shadow-2xl shadow-black/60 transition-all hover:border-purple-500/30">
      {/* Code Header Bar */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-zinc-900/90 border-b border-white/5 backdrop-blur-md">
        <div className="flex items-center gap-2.5">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-rose-500/70 inline-block"></span>
            <span className="w-2.5 h-2.5 rounded-full bg-amber-500/70 inline-block"></span>
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/70 inline-block"></span>
          </div>
          <span className="text-[11px] font-mono uppercase tracking-wider text-purple-300 bg-purple-500/15 px-2.5 py-0.5 rounded-md font-semibold border border-purple-500/20">
            {language || 'code'}
          </span>
          <span className="text-[11px] text-zinc-500 font-mono hidden sm:inline">
            {lineCount} {lineCount === 1 ? 'line' : 'lines'}
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setCollapsed(c => !c)}
            className="flex items-center gap-1 text-[11px] text-zinc-400 hover:text-zinc-100 px-2 py-1 rounded-lg hover:bg-white/5 transition-all"
            title={collapsed ? 'Expand code' : 'Collapse code'}
          >
            <svg className={`w-3.5 h-3.5 transition-transform duration-200 ${collapsed ? '-rotate-90' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
            <span className="hidden sm:inline">{collapsed ? 'Expand' : 'Collapse'}</span>
          </button>

          <button
            onClick={handleDownload}
            className="flex items-center gap-1 text-[11px] text-zinc-400 hover:text-zinc-100 px-2.5 py-1 rounded-lg hover:bg-white/5 transition-all"
            title="Download file"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            <span className="hidden sm:inline">Export</span>
          </button>

          <button
            onClick={handleCopy}
            className={`flex items-center gap-1 text-[11px] px-3 py-1 rounded-lg font-medium transition-all shadow-sm ${
              copied
                ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                : 'bg-white/10 hover:bg-white/15 text-zinc-200 hover:text-white border border-white/10'
            }`}
            title="Copy code to clipboard"
          >
            {copied ? (
              <>
                <svg className="w-3.5 h-3.5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                </svg>
                <span>Copied!</span>
              </>
            ) : (
              <>
                <svg className="w-3.5 h-3.5 text-zinc-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" />
                </svg>
                <span>Copy</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Code Body */}
      {!collapsed && (
        <div className="relative">
          <SyntaxHighlighter
            language={language}
            style={oneDark}
            showLineNumbers={lineCount > 1}
            customStyle={{
              margin: 0,
              padding: '16px 18px',
              background: '#09090D',
              fontSize: '13.5px',
              lineHeight: '1.65',
              fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
            }}
            lineNumberStyle={{
              minWidth: '2.5em',
              paddingRight: '1em',
              color: '#4B5563',
              userSelect: 'none',
              textAlign: 'right',
            }}
          >
            {code}
          </SyntaxHighlighter>
        </div>
      )}
    </div>
  );
}
