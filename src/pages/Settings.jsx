import { useState } from 'react';
import GlassCard from '../components/GlassCard';

export default function Settings() {
  const [minScore, setMinScore] = useState(8.0);
  const [verbosity, setVerbosity] = useState("detailed");
  const [apiKey, setApiKey] = useState("••••••••••••••••••••••••••••");
  const [saveSuccess, setSaveSuccess] = useState(false);

  const handleSave = (e) => {
    e.preventDefault();
    setSaveSuccess(true);
    setTimeout(() => setSaveSuccess(false), 3000);
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-2xl font-bold text-white">System Settings</h2>
        <p className="text-sm text-zinc-400">Configure parameters for Gemini models and reviewer guidelines.</p>
      </div>

      <GlassCard>
        <form onSubmit={handleSave} className="space-y-6">
          {/* API Key */}
          <div className="space-y-2">
            <label className="block text-xs font-bold uppercase tracking-wider text-zinc-400">Gemini API Token</label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              className="w-full bg-zinc-900 border border-zinc-800 focus:border-violet-500 rounded-xl px-4 py-2.5 text-sm text-white placeholder-zinc-500 outline-none transition-colors duration-200"
            />
            <p className="text-[11px] text-zinc-550">Your API token remains locally in your secure workspace.</p>
          </div>

          {/* Range Slider for Accept Threshold */}
          <div className="space-y-2">
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
