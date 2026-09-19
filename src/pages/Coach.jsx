import { useState, useEffect, useCallback } from 'react';
import Editor from '@monaco-editor/react';
import MessageContent from '../components/MessageContent';
import { csrfHeaders } from '../utils/csrf';

const CATEGORIES = ['arrays', 'strings', 'dynamic programming', 'graphs', 'trees', 'linked lists', 'sorting', 'searching'];
const DIFFICULTIES = ['easy', 'medium', 'hard'];
const LANGUAGES = ['python', 'javascript', 'java', 'cpp'];

const STARTER = {
  python: '# Write your solution here\ndef solve():\n    pass\n',
  javascript: '// Write your solution here\nfunction solve() {\n\n}\n',
  java: '// Write your solution here\nclass Solution {\n    void solve() {\n\n    }\n}\n',
  cpp: '// Write your solution here\n#include <bits/stdc++.h>\nusing namespace std;\n\nvoid solve() {\n\n}\n',
};

function ConfidenceBadge({ confidence }) {
  return null;
}

export default function Coach() {
  const [category, setCategory] = useState(CATEGORIES[0]);
  const [difficulty, setDifficulty] = useState('easy');
  const [language, setLanguage] = useState('python');
  const [problem, setProblem] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [code, setCode] = useState(STARTER.python);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState(null);
  const [sessions, setSessions] = useState([]);

  const fetchSessions = useCallback(async () => {
    try {
      const res = await fetch('/api/coach/sessions', { credentials: 'include' });
      if (res.ok) setSessions(await res.json());
    } catch (err) {
      console.error('Error fetching coach sessions:', err);
    }
  }, []);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  const generateProblem = async () => {
    setLoading(true);
    setFeedback(null);
    try {
      const res = await fetch('/api/coach/problems', {
        method: 'POST',
        headers: csrfHeaders({ 'Content-Type': 'application/json' }),
        credentials: 'include',
        body: JSON.stringify({ category, difficulty }),
      });
      if (res.ok) {
        const data = await res.json();
        setProblem(data.problem);
        setSessionId(data.sessionId);
        setCode(STARTER[language]);
        fetchSessions();
      }
    } catch (err) {
      console.error('Error generating problem:', err);
    } finally {
      setLoading(false);
    }
  };

  const resumeSession = async (id) => {
    try {
      const res = await fetch(`/api/coach/sessions/${id}`, { credentials: 'include' });
      if (!res.ok) return;
      const data = await res.json();
      setProblem(data.session);
      setSessionId(data.session.id);
      const last = data.submissions[data.submissions.length - 1];
      setCode(last ? last.code : STARTER[language]);
      setFeedback(null);
    } catch (err) {
      console.error('Error resuming session:', err);
    }
  };

  const submit = async () => {
    if (!sessionId) return;
    setSubmitting(true);
    try {
      const res = await fetch(`/api/coach/sessions/${sessionId}/submit`, {
        method: 'POST',
        headers: csrfHeaders({ 'Content-Type': 'application/json' }),
        credentials: 'include',
        body: JSON.stringify({ code, language }),
      });
      if (res.ok) {
        setFeedback(await res.json());
        fetchSessions();
      }
    } catch (err) {
      console.error('Error submitting solution:', err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex h-screen w-full nova-surface bg-[#0B0B0F] text-zinc-200 nova-text">
      {/* Session history rail */}
      <div className="w-56 nova-surface-alt border-r border-white/5 nova-border flex-shrink-0 hidden lg:flex flex-col overflow-y-auto p-3 space-y-1">
        <h2 className="text-xs font-semibold text-zinc-500 nova-text-muted uppercase tracking-wide px-2 mb-2">Practice history</h2>
        {sessions.length === 0 && <p className="text-xs text-zinc-600 nova-text-muted px-2">No sessions yet</p>}
        {sessions.map((s) => (
          <button
            key={s.id}
            onClick={() => resumeSession(s.id)}
            className={`text-left px-2 py-2 rounded-lg text-xs transition-colors ${
              sessionId === s.id ? 'bg-white/10 text-white nova-text' : 'text-zinc-400 nova-text-muted hover:bg-white/5'
            }`}
          >
            <div className="truncate font-medium">{s.title}</div>
            <div className="flex items-center gap-1 mt-0.5 text-[10px] text-zinc-500 nova-text-muted">
              <span>{s.difficulty}</span>
              <span>·</span>
              <span className={s.status === 'solved' ? 'text-emerald-400' : ''}>{s.status}</span>
            </div>
          </button>
        ))}
      </div>

      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Controls */}
        <div className="flex items-center gap-3 p-4 border-b border-white/5 nova-border flex-wrap">
          <select value={category} onChange={(e) => setCategory(e.target.value)} className="nova-surface-alt bg-white/5 border border-white/10 nova-border rounded-lg px-3 py-1.5 text-sm nova-text">
            {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <select value={difficulty} onChange={(e) => setDifficulty(e.target.value)} className="nova-surface-alt bg-white/5 border border-white/10 nova-border rounded-lg px-3 py-1.5 text-sm nova-text">
            {DIFFICULTIES.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
          <button
            onClick={generateProblem}
            disabled={loading}
            className="bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white px-4 py-1.5 rounded-lg text-sm font-medium transition-colors"
          >
            {loading ? 'Generating…' : 'New Problem'}
          </button>
          <select value={language} onChange={(e) => { setLanguage(e.target.value); if (!problem) setCode(STARTER[e.target.value]); }} className="nova-surface-alt bg-white/5 border border-white/10 nova-border rounded-lg px-3 py-1.5 text-sm nova-text ml-auto">
            {LANGUAGES.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        </div>

        {!problem ? (
          <div className="flex-1 flex items-center justify-center text-zinc-500 nova-text-muted text-sm">
            Pick a category and difficulty, then click "New Problem" to start practicing.
          </div>
        ) : (
          <div className="flex-1 flex overflow-hidden">
            {/* Problem panel */}
            <div className="w-1/2 overflow-y-auto p-5 border-r border-white/5 nova-border">
              <h1 className="text-lg font-semibold text-white nova-text mb-1">{problem.title}</h1>
              <div className="text-xs text-zinc-500 nova-text-muted mb-4">{problem.difficulty} · {problem.category}</div>
              <MessageContent content={problem.description} />
              {problem.constraints && (
                <>
                  <h3 className="text-sm font-semibold text-white nova-text mt-4 mb-1">Constraints</h3>
                  <MessageContent content={problem.constraints} />
                </>
              )}
              {(problem.example_input || problem.example_output) && (
                <>
                  <h3 className="text-sm font-semibold text-white nova-text mt-4 mb-1">Example</h3>
                  <pre className="nova-surface-alt bg-white/5 rounded-lg p-3 text-xs overflow-x-auto nova-text">Input: {problem.example_input}{'\n'}Output: {problem.example_output}</pre>
                </>
              )}

              {feedback && (
                <div className="mt-6 border-t border-white/10 nova-border pt-4">
                  <div className="flex items-center gap-2 mb-2">
                    <ConfidenceBadge confidence={feedback.confidence} />
                    {feedback.status === 'solved' && <span className="text-xs text-emerald-400 font-medium">Solved ✓</span>}
                  </div>
                  {feedback.validation.issues.length > 0 && (
                    <div className="mb-2">
                      <div className="text-xs font-semibold text-zinc-400 nova-text-muted mb-1">Static validation issues</div>
                      <ul className="list-disc pl-5 text-xs text-rose-300 space-y-0.5">
                        {feedback.validation.issues.map((i, idx) => <li key={idx}>{i}</li>)}
                      </ul>
                    </div>
                  )}
                  {feedback.feedback.length > 0 && (
                    <div>
                      <div className="text-xs font-semibold text-zinc-400 nova-text-muted mb-1">Review feedback</div>
                      <ul className="list-disc pl-5 text-xs text-amber-300 space-y-0.5">
                        {feedback.feedback.map((i, idx) => <li key={idx}>{i}</li>)}
                      </ul>
                    </div>
                  )}
                  {feedback.validation.issues.length === 0 && feedback.feedback.length === 0 && (
                    <p className="text-xs text-emerald-300">No issues found.</p>
                  )}
                </div>
              )}
            </div>

            {/* Editor panel */}
            <div className="w-1/2 flex flex-col">
              <div className="flex-1">
                <Editor
                  height="100%"
                  language={language === 'cpp' ? 'cpp' : language}
                  theme="vs-dark"
                  value={code}
                  onChange={(v) => setCode(v ?? '')}
                  options={{ fontSize: 13, minimap: { enabled: false } }}
                />
              </div>
              <div className="p-3 border-t border-white/5 nova-border">
                <button
                  onClick={submit}
                  disabled={submitting}
                  className="w-full bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
                >
                  {submitting ? 'Reviewing…' : 'Submit for Feedback'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
