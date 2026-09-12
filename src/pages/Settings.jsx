import { useState, useEffect } from 'react';
import GlassCard from '../components/GlassCard';

export default function Settings() {
  const [minScore, setMinScore] = useState(8.0);
  const [verbosity, setVerbosity] = useState("detailed");
  const [apiKey, setApiKey] = useState("");
  const [voiceModel, setVoiceModel] = useState("gemini-3.6-flash");
  const [voiceLang, setVoiceLang] = useState("en-IN");
  const [voiceRate, setVoiceRate] = useState("1.05");
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [backendConfig, setBackendConfig] = useState(null);

  useEffect(() => {
    // Load from local storage
    const storedKey = localStorage.getItem('gemini_api_key') || '';
    const storedModel = localStorage.getItem('gemini_voice_model') || 'gemini-3.6-flash';
    const storedLang = localStorage.getItem('nova_voice_lang') || 'en-IN';
    const storedRate = localStorage.getItem('gemini_voice_rate') || '1.05';
    setApiKey(storedKey);
    setVoiceModel(storedModel);
    setVoiceLang(storedLang);
    setVoiceRate(storedRate);

    // Fetch voice backend status
    fetch('/api/voice/config')
      .then(r => r.json())
      .then(data => setBackendConfig(data))
      .catch(() => {});
  }, []);

  const handleSave = async (e) => {
    e.preventDefault();
    localStorage.setItem('gemini_api_key', apiKey.trim());
    localStorage.setItem('gemini_voice_model', voiceModel);
    localStorage.setItem('nova_voice_lang', voiceLang);
    localStorage.setItem('gemini_voice_rate', voiceRate);

    if (apiKey.trim()) {
      try {
        await fetch('/api/settings/gemini', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ apiKey: apiKey.trim() }),
        });
      } catch (err) {
        console.warn('Could not sync key to server:', err);
      }
    }

    setSaveSuccess(true);
    setTimeout(() => setSaveSuccess(false), 3000);
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-2xl font-bold text-white">System Settings</h2>
        <p className="text-sm text-zinc-400">Configure parameters for Gemini models, Voice Assistant, and reviewer guidelines.</p>
      </div>

      <GlassCard>
        <form onSubmit={handleSave} className="space-y-6">
          {/* Gemini API Key */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="block text-xs font-bold uppercase tracking-wider text-zinc-400">
                Google Gemini API Key
              </label>
              <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
                apiKey || backendConfig?.geminiConfigured
                  ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/20'
                  : 'bg-zinc-800 text-zinc-400 border border-white/5'
              }`}>
                {apiKey || backendConfig?.geminiConfigured ? '✓ Gemini Active' : 'Fallback to Local AI'}
              </span>
            </div>
            <input
              type="password"
              placeholder="AIzaSy..."
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              className="w-full bg-zinc-900 border border-zinc-800 focus:border-violet-500 rounded-xl px-4 py-2.5 text-sm text-white placeholder-zinc-500 outline-none transition-colors duration-200 font-mono"
            />
            <p className="text-[11px] text-zinc-500">
              Used for the conversational Gemini Voice Assistant and Gemini Multimodal RAG. Stored securely in your local session and backend.
            </p>
          </div>

          {/* Voice Model Selection */}
          <div className="space-y-2">
            <label className="block text-xs font-bold uppercase tracking-wider text-zinc-400">Voice Assistant Model</label>
            <select
              value={voiceModel}
              onChange={(e) => setVoiceModel(e.target.value)}
              className="w-full bg-zinc-900 border border-zinc-800 focus:border-violet-500 rounded-xl px-4 py-2.5 text-sm text-white outline-none transition-colors duration-200"
            >
              <option value="gemini-3.6-flash">Gemini 3.6 Flash (Recommended — Fastest & Full Multilingual)</option>
              <option value="gemini-3.7-flash">Gemini 3.7 Flash (Balanced Voice Reasoning)</option>
              <option value="gemini-flash-latest">Gemini Flash Latest</option>
              <option value="gemini-3.8-flash">Gemini 3.8 Flash (High-Intelligence Conversational)</option>
            </select>
          </div>

          {/* Default Voice Language */}
          <div className="space-y-2">
            <label className="block text-xs font-bold uppercase tracking-wider text-zinc-400">Default Voice Language</label>
            <select
              value={voiceLang}
              onChange={(e) => setVoiceLang(e.target.value)}
              className="w-full bg-zinc-900 border border-zinc-800 focus:border-violet-500 rounded-xl px-4 py-2.5 text-sm text-white outline-none transition-colors duration-200"
            >
              <option value="en-IN">English (Indian / Global)</option>
              <option value="ta-IN">தமிழ் (Tamil)</option>
              <option value="hi-IN">हिन्दी (Hindi)</option>
              <option value="te-IN">తెలుగు (Telugu)</option>
              <option value="ml-IN">മലയാളം (Malayalam)</option>
              <option value="kn-IN">ಕನ್ನಡ (Kannada)</option>
            </select>
            <p className="text-[11px] text-zinc-500">
              Primary language for speech recognition and conversational Gemini Voice Assistant.
            </p>
          </div>

          {/* Speech Rate Slider */}
          <div className="space-y-2">
            <div className="flex justify-between items-center">
              <label className="block text-xs font-bold uppercase tracking-wider text-zinc-400">Voice Speech Speed</label>
              <span className="text-sm font-bold text-violet-400">{voiceRate}x</span>
            </div>
            <input
              type="range"
              min="0.8"
              max="1.4"
              step="0.05"
              value={voiceRate}
              onChange={(e) => setVoiceRate(e.target.value)}
              className="w-full h-1.5 bg-zinc-800 rounded-lg appearance-none cursor-pointer accent-violet-500"
            />
            <div className="flex justify-between text-[10px] text-zinc-500">
              <span>0.8x (Relaxed)</span>
              <span>1.05x (Natural Conversational)</span>
              <span>1.4x (Brisk)</span>
            </div>
          </div>

          {/* Range Slider for Accept Threshold */}
          <div className="space-y-2 pt-2 border-t border-zinc-800/60">
            <div className="flex justify-between items-center">
              <label className="block text-xs font-bold uppercase tracking-wider text-zinc-400">Min Accept Rating Target</label>
              <span className="text-sm font-bold text-violet-400">{minScore} / 10</span>
            </div>
            <input
              type="range"
              min="5.0"
              max="9.5"
              step="0.5"
              value={minScore}
              onChange={(e) => setMinScore(parseFloat(e.target.value))}
              className="w-full h-1.5 bg-zinc-800 rounded-lg appearance-none cursor-pointer accent-violet-500"
            />
            <div className="flex justify-between text-[10px] text-zinc-500">
              <span>5.0 (Lenient)</span>
              <span>7.5 (Standard)</span>
              <span>9.5 (Critical)</span>
            </div>
          </div>

          {/* Selection Select element */}
          <div className="space-y-2">
            <label className="block text-xs font-bold uppercase tracking-wider text-zinc-400">AI Report Verbosity</label>
            <select
              value={verbosity}
              onChange={(e) => setVerbosity(e.target.value)}
              className="w-full bg-zinc-900 border border-zinc-800 focus:border-violet-500 rounded-xl px-4 py-2.5 text-sm text-white outline-none transition-colors duration-200"
            >
              <option value="compact">Compact (Score + Recommendation Only)</option>
              <option value="detailed">Detailed (Standard Analysis Critiques)</option>
              <option value="exhaustive">Exhaustive (Expanded Structural Breakdowns)</option>
            </select>
          </div>

          {/* Form Actions */}
          <div className="flex items-center justify-between border-t border-zinc-800/60 pt-6">
            <div className="flex-1">
              {saveSuccess && (
                <span className="text-xs font-semibold text-emerald-400 flex items-center space-x-1.5 animate-fade-in">
                  <span>✓</span>
                  <span>Configurations stored successfully.</span>
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
