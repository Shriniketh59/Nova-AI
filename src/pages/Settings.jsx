import { useState, useEffect } from 'react';
import GlassCard from '../components/GlassCard';

export default function Settings() {
  const [minScore, setMinScore] = useState(8.0);
  const [verbosity, setVerbosity] = useState("detailed");
  const [voiceModel, setVoiceModel] = useState("llama3.2:3b");
  const [voiceLang, setVoiceLang] = useState("en-IN");
  const [voiceRate, setVoiceRate] = useState("1.0");
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [backendConfig, setBackendConfig] = useState(null);

  useEffect(() => {
    const storedModel = localStorage.getItem('nova_voice_model') || 'llama3.2:3b';
    const storedLang = localStorage.getItem('nova_voice_lang') || 'en-IN';
    const storedRate = localStorage.getItem('nova_voice_rate') || '1.0';
    setVoiceModel(storedModel);
    setVoiceLang(storedLang);
    setVoiceRate(storedRate);

    // Fetch voice backend status
    fetch('/api/voice/config')
      .then(r => r.json())
      .then(data => setBackendConfig(data))
      .catch(() => {});
  }, []);

  const handleSave = (e) => {
    e.preventDefault();
    localStorage.setItem('nova_voice_model', voiceModel);
    localStorage.setItem('nova_voice_lang', voiceLang);
    localStorage.setItem('nova_voice_rate', voiceRate);

    setSaveSuccess(true);
    setTimeout(() => setSaveSuccess(false), 3000);
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-2xl font-bold text-white nova-text">Local AI Architecture Settings</h2>
        <p className="text-sm text-zinc-400 nova-text-muted">All reasoning, voice synthesis, speech recognition, and embeddings run 100% locally.</p>
      </div>

      {/* Local Engine Status Card */}
      <GlassCard>
        <div className="space-y-4">
          <div className="flex items-center justify-between border-b border-white/10 nova-border pb-3">
            <h3 className="text-sm font-bold uppercase tracking-wider text-purple-400">Engine Status (Offline / Local)</h3>
            <span className="text-[11px] px-2.5 py-0.5 rounded-full font-medium bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">
              ● 100% Local AI Active
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
            <div className="p-3 rounded-xl bg-white/[0.02] border border-white/5 nova-border space-y-1">
              <span className="text-zinc-400 nova-text-muted">Main Reasoning LLM:</span>
              <p className="text-white nova-text font-mono font-semibold">{backendConfig?.llm || 'ollama/llama3.2:3b'}</p>
            </div>
            <div className="p-3 rounded-xl bg-white/[0.02] border border-white/5 nova-border space-y-1">
              <span className="text-zinc-400 nova-text-muted">Local STT (Speech-to-Text):</span>
              <p className="text-white nova-text font-mono font-semibold">{backendConfig?.stt || 'faster-whisper (base.en)'}</p>
            </div>
            <div className="p-3 rounded-xl bg-white/[0.02] border border-white/5 nova-border space-y-1">
              <span className="text-zinc-400 nova-text-muted">Local TTS (Text-to-Speech):</span>
              <p className="text-white nova-text font-mono font-semibold">{backendConfig?.tts || 'pyttsx3 + espeak-ng'}</p>
            </div>
            <div className="p-3 rounded-xl bg-white/[0.02] border border-white/5 nova-border space-y-1">
              <span className="text-zinc-400 nova-text-muted">Web Search Engine:</span>
              <p className="text-white nova-text font-mono font-semibold">DuckDuckGo (DDGS — No API Key)</p>
            </div>
          </div>
        </div>
      </GlassCard>

      <GlassCard>
        <form onSubmit={handleSave} className="space-y-6">
          {/* Local Reasoning Model Selection */}
          <div className="space-y-2">
            <label className="block text-xs font-bold uppercase tracking-wider text-zinc-400 nova-text-muted">
              Local Orchestrator LLM
            </label>
            <select
              value={voiceModel}
              onChange={(e) => setVoiceModel(e.target.value)}
              className="nova-surface-alt w-full bg-zinc-900 border border-zinc-800 nova-border focus:border-violet-500 rounded-xl px-4 py-2.5 text-sm text-white nova-text outline-none transition-colors duration-200 font-mono"
            >
              <option value="llama3.2:3b">llama3.2:3b (Primary reasoning & voice model — Ollama)</option>
              <option value="qwen2.5-coder:1.5b">qwen2.5-coder:1.5b (Coding tasks agent — Ollama)</option>
            </select>
            <p className="text-[11px] text-zinc-500 nova-text-muted">
              Hosted in your local Ollama runtime. Zero external API calls.
            </p>
          </div>

          {/* Voice Language */}
          <div className="space-y-2">
            <label className="block text-xs font-bold uppercase tracking-wider text-zinc-400 nova-text-muted">Voice Assistant Language</label>
            <select
              value={voiceLang}
              onChange={(e) => setVoiceLang(e.target.value)}
              className="nova-surface-alt w-full bg-zinc-900 border border-zinc-800 nova-border focus:border-violet-500 rounded-xl px-4 py-2.5 text-sm text-white nova-text outline-none transition-colors duration-200"
            >
              <option value="en-IN">English (Indian / Global)</option>
              <option value="en-US">English (US)</option>
              <option value="en-GB">English (British)</option>
            </select>
          </div>

          {/* Speech Rate Slider */}
          <div className="space-y-2">
            <div className="flex justify-between items-center">
              <label className="block text-xs font-bold uppercase tracking-wider text-zinc-400 nova-text-muted">Local TTS Speed</label>
              <span className="text-sm font-bold text-violet-400">{voiceRate}x</span>
            </div>
            <input
              type="range"
              min="0.8"
              max="1.4"
              step="0.05"
              value={voiceRate}
              onChange={(e) => setVoiceRate(e.target.value)}
              className="w-full h-1.5 bg-zinc-800 nova-surface-alt rounded-lg appearance-none cursor-pointer accent-violet-500"
            />
            <div className="flex justify-between text-[10px] text-zinc-500 nova-text-muted">
              <span>0.8x (Relaxed)</span>
              <span>1.0x (Standard)</span>
              <span>1.4x (Brisk)</span>
            </div>
          </div>

          {/* Range Slider for Accept Threshold */}
          <div className="space-y-2 pt-2 border-t border-zinc-800/60 nova-border">
            <div className="flex justify-between items-center">
              <label className="block text-xs font-bold uppercase tracking-wider text-zinc-400 nova-text-muted">Min Accept Rating Target</label>
              <span className="text-sm font-bold text-violet-400">{minScore} / 10</span>
            </div>
            <input
              type="range"
              min="5.0"
              max="9.5"
              step="0.5"
              value={minScore}
              onChange={(e) => setMinScore(parseFloat(e.target.value))}
              className="w-full h-1.5 bg-zinc-800 nova-surface-alt rounded-lg appearance-none cursor-pointer accent-violet-500"
            />
            <div className="flex justify-between text-[10px] text-zinc-500 nova-text-muted">
              <span>5.0 (Lenient)</span>
              <span>7.5 (Standard)</span>
              <span>9.5 (Critical)</span>
            </div>
          </div>

          {/* Selection Select element */}
          <div className="space-y-2">
            <label className="block text-xs font-bold uppercase tracking-wider text-zinc-400 nova-text-muted">AI Report Verbosity</label>
            <select
              value={verbosity}
              onChange={(e) => setVerbosity(e.target.value)}
              className="nova-surface-alt w-full bg-zinc-900 border border-zinc-800 nova-border focus:border-violet-500 rounded-xl px-4 py-2.5 text-sm text-white nova-text outline-none transition-colors duration-200"
            >
              <option value="compact">Compact (Score + Recommendation Only)</option>
              <option value="detailed">Detailed (Standard Analysis Critiques)</option>
              <option value="exhaustive">Exhaustive (Expanded Structural Breakdowns)</option>
            </select>
          </div>

          {/* Form Actions */}
          <div className="flex items-center justify-between border-t border-zinc-800/60 nova-border pt-6">
            <div className="flex-1">
              {saveSuccess && (
                <span className="text-xs font-semibold text-emerald-400 flex items-center space-x-1.5 animate-fade-in">
                  <span>✓</span>
                  <span>Local configurations stored successfully.</span>
                </span>
              )}
            </div>
            <button
              type="submit"
              className="px-6 py-2.5 rounded-xl bg-violet-600 hover:bg-violet-500 font-semibold text-sm text-white shadow-lg shadow-violet-500/20 transition-all duration-200"
            >
              Save Changes
            </button>
          </div>
        </form>
      </GlassCard>
    </div>
  );
}
