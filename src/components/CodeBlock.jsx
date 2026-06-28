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
    setTimeout(() => setCopied(false), 1500);
  };

  const handleDownload = () => {
    const ext = EXT_MAP[language.toLowerCase()] || 'txt';
    const blob = new Blob([code], { type: 'text/plain;charset=utf-8' });
    saveAs(blob, `nova-snippet.${ext}`);
  };

  const lineCount = code.split('\n').length;

  return (
    <div className="my-3 rounded-xl border border-white/10 bg-[#0d0d12] overflow-hidden shadow-md">
      <div className="flex items-center justify-between px-3 py-2 bg-white/5 border-b border-white/10">
        <span className="text-[11px] font-mono uppercase tracking-wide text-purple-400 bg-purple-500/10 px-2 py-0.5 rounded-md">
          {language || 'text'}
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setCollapsed(c => !c)}
            className="text-[11px] text-zinc-400 hover:text-white px-2 py-1 rounded-md hover:bg-white/10 transition-colors"
            title={collapsed ? 'Expand' : 'Collapse'}
          >
            {collapsed ? 'Expand' : 'Collapse'}
          </button>
          <button
            onClick={handleDownload}
            className="text-[11px] text-zinc-400 hover:text-white px-2 py-1 rounded-md hover:bg-white/10 transition-colors"
            title="Download as file"
          >
            Download
          </button>
          <button
            onClick={handleCopy}
            className="text-[11px] text-zinc-200 hover:text-white px-2 py-1 rounded-md hover:bg-white/10 transition-colors"
            title="Copy code"
          >
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
      </div>
      {!collapsed && (
        <SyntaxHighlighter
          language={language}
          style={oneDark}
          showLineNumbers={lineCount > 1}
          customStyle={{
            margin: 0,
            padding: '14px 16px',
            background: 'transparent',
            fontSize: '13px',
            lineHeight: '1.6',
          }}
        >
          {code}
        </SyntaxHighlighter>
      )}
    </div>
  );
}
