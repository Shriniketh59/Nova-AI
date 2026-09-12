import { useState, useEffect, useRef } from 'react';

const SUPPORTED_LANGUAGES = [
  { code: 'auto', name: 'Auto', native: '🌐 Auto Detect' },
  { code: 'ta-IN', name: 'Tamil', native: 'தமிழ்' },
  { code: 'hi-IN', name: 'Hindi', native: 'हिन्दी' },
  { code: 'te-IN', name: 'Telugu', native: 'తెలుగు' },
  { code: 'ml-IN', name: 'Malayalam', native: 'മലയാളം' },
  { code: 'kn-IN', name: 'Kannada', native: 'ಕನ್ನಡ' },
  { code: 'en-IN', name: 'English', native: 'English' },
];

const PRESET_PROMPTS = [
  { label: '🗣️ Translate to Tamil', text: 'Translate "Hello, how can I help you today?" into Tamil' },
  { label: '🗣️ Translate to English', text: 'Translate "நன்றி, வணக்கம்" into English' },
  { label: '📅 Today’s Date', text: 'What is today’s date and status?' },
  { label: '✨ Quick Fun Fact', text: 'Tell me a quick interesting fun fact' },
];

export default function VoiceAssistantModal({ isOpen, onClose, activeChatId, onMessageAdded }) {
  const [status, setStatus] = useState('idle'); // 'idle' | 'listening' | 'thinking' | 'speaking'
  const [transcript, setTranscript] = useState('');
  const [replyText, setReplyText] = useState('');
  const [activeEngine, setActiveEngine] = useState('gemini');
  const [activeModel, setActiveModel] = useState('gemini-flash-lite-latest');
  const [isHandsFree, setIsHandsFree] = useState(true);
  const [voices, setVoices] = useState([]);
  const [speechRate, setSpeechRate] = useState(() => {
    return parseFloat(localStorage.getItem('nova_voice_rate') || '0.95');
  });
  const [selectedLang, setSelectedLang] = useState(() => {
    return localStorage.getItem('nova_voice_lang') || 'auto';
  });

  const recognitionRef = useRef(null);
  const isListeningRef = useRef(false);
  const isMountedRef = useRef(true);
  const lastReplyRef = useRef('');
  const lastLangRef = useRef('en-IN');

  // Unicode Script detector helper for phonetic voice selection
  const detectScriptLang = (str) => {
    if (!str) return selectedLang === 'auto' ? 'en-IN' : selectedLang;
    if (/[\u0B80-\u0BFF]/.test(str)) return 'ta-IN';
    if (/[\u0900-\u097F]/.test(str)) return 'hi-IN';
    if (/[\u0C00-\u0C7F]/.test(str)) return 'te-IN';
    if (/[\u0D00-\u0D7F]/.test(str)) return 'ml-IN';
    if (/[\u0C80-\u0CFF]/.test(str)) return 'kn-IN';
    return selectedLang === 'auto' ? 'en-IN' : selectedLang;
  };

  // Load available browser TTS voices
  useEffect(() => {
    isMountedRef.current = true;
    const updateVoices = () => {
      if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
        const available = window.speechSynthesis.getVoices();
        setVoices(available);
      }
    };

    updateVoices();
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.onvoiceschanged = updateVoices;
    }

    return () => {
      isMountedRef.current = false;
      stopListening();
      if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
        window.speechSynthesis.cancel();
      }
    };
  }, []);

  // Initialize Speech Recognition with selected language
  const initRecognition = (langCode = selectedLang) => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return null;

    const recognizer = new SpeechRecognition();
    recognizer.continuous = false;
    recognizer.interimResults = true;
    recognizer.lang = langCode === 'auto' ? 'en-IN' : langCode;

    recognizer.onstart = () => {
      isListeningRef.current = true;
      setStatus('listening');
    };

    recognizer.onresult = (event) => {
      let interim = '';
      let final = '';
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        if (event.results[i].isFinal) {
          final += event.results[i][0].transcript;
        } else {
          interim += event.results[i][0].transcript;
        }
      }
      const currentText = final || interim;
      setTranscript(currentText);

      if (final.trim()) {
        handleUserSpoke(final.trim());
      }
    };

    recognizer.onerror = (event) => {
      console.warn('Speech recognition error:', event.error);
      isListeningRef.current = false;
      if (status === 'listening') {
        setStatus('idle');
      }
    };

    recognizer.onend = () => {
      isListeningRef.current = false;
      if (status === 'listening') {
        setStatus('idle');
      }
    };

    return recognizer;
  };

  const startListening = () => {
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    setTranscript('');
    try {
      if (!recognitionRef.current) {
        recognitionRef.current = initRecognition(selectedLang);
      }
      if (recognitionRef.current && !isListeningRef.current) {
        recognitionRef.current.lang = selectedLang === 'auto' ? 'en-IN' : selectedLang;
        recognitionRef.current.start();
      }
    } catch (err) {
      console.warn('Could not start recognition:', err);
    }
  };

  const stopListening = () => {
    if (recognitionRef.current && isListeningRef.current) {
      try {
        recognitionRef.current.stop();
      } catch {
        // ignore
      }
      isListeningRef.current = false;
    }
  };

  // Language switch handler
  const handleLanguageChange = (langCode) => {
    setSelectedLang(langCode);
    localStorage.setItem('nova_voice_lang', langCode);

    stopListening();
    if (recognitionRef.current) {
      recognitionRef.current.lang = langCode === 'auto' ? 'en-IN' : langCode;
    }

    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    setStatus('idle');

    setTimeout(() => {
      startListening();
    }, 250);
  };

  // Start listening automatically when modal opens
  useEffect(() => {
    if (isOpen) {
      setTranscript('');
      setReplyText('');
      const timer = setTimeout(() => {
        startListening();
      }, 350);
      return () => clearTimeout(timer);
    } else {
      stopListening();
      if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
        window.speechSynthesis.cancel();
      }
      setStatus('idle');
    }
  }, [isOpen]);

  // Send speech to Gemini voice backend
  const handleUserSpoke = async (spokenText) => {
    stopListening();
    setStatus('thinking');

    try {
      const storedKey = localStorage.getItem('gemini_api_key') || '';
      const storedModel = localStorage.getItem('gemini_voice_model') || 'gemini-flash-lite-latest';

      const res = await fetch('/api/voice/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: spokenText,
          chatId: activeChatId || null,
          apiKey: storedKey || null,
          model: storedModel,
          language: selectedLang,
          langCode: selectedLang,
        }),
      });

      if (!res.ok) throw new Error('Voice service error');
      const data = await res.json();

      setActiveEngine(data.engine || 'gemini');
      setActiveModel(data.model || 'gemini-flash-lite-latest');
      setReplyText(data.reply);
      lastReplyRef.current = data.reply;
      lastLangRef.current = data.langCode || detectScriptLang(data.reply);

      if (onMessageAdded) {
        onMessageAdded({ role: 'user', content: spokenText });
        onMessageAdded({ role: 'ai', content: data.reply });
      }

      speakText(data.reply, lastLangRef.current);
    } catch (err) {
      console.error('Voice chat failed:', err);
      const fallbackMsg = "I couldn't reach the voice service. Please check your network or key.";
      setReplyText(fallbackMsg);
      speakText(fallbackMsg, 'en-IN');
    }
  };

  // Play assistant voice using SpeechSynthesis with crystal-clear native pronunciation
  const speakText = (text, langCodeHint) => {
    if (!('speechSynthesis' in window) || !text) {
      setStatus('idle');
      return;
    }

    window.speechSynthesis.cancel();

    // Clean text: strip any leftover bracketed phonetic clutter
    const cleanSpeechText = text
      .replace(/\([A-Za-z0-9\s,\.!?-]+\)/g, '')
      .replace(/[*#`_~]/g, '')
      .trim();

    const utterance = new SpeechSynthesisUtterance(cleanSpeechText);
    const targetLang = langCodeHint || detectScriptLang(cleanSpeechText);
    utterance.lang = targetLang;

    // Select the clearest native voice for this language
    if (voices.length > 0) {
      const prefix = targetLang.slice(0, 2).toLowerCase();
      // 1. Exact match e.g. 'ta-IN', 'hi-IN'
      let bestVoice = voices.find(v => v.lang.toLowerCase().replace('_', '-') === targetLang.toLowerCase());
      // 2. Prefix match e.g. starts with 'ta', 'hi', 'te', 'ml', 'kn'
      if (!bestVoice) {
        bestVoice = voices.find(v => v.lang.toLowerCase().startsWith(prefix));
      }
      // 3. High quality natural English voice if target is English
      if (!bestVoice && prefix === 'en') {
        bestVoice = voices.find(v => v.lang.startsWith('en') && (v.name.includes('Google') || v.name.includes('Natural') || v.name.includes('Samantha')));
      }
      if (bestVoice) {
        utterance.voice = bestVoice;
      }
    }

    // Pacing: Indian languages are clearer at 0.92-0.95x; English at 1.0x
    const isIndic = targetLang.startsWith('ta') || targetLang.startsWith('hi') || targetLang.startsWith('te') || targetLang.startsWith('ml') || targetLang.startsWith('kn');
    utterance.rate = isIndic ? Math.min(speechRate, 0.94) : speechRate;
    utterance.pitch = 1.0;

    utterance.onstart = () => {
      if (isMountedRef.current) setStatus('speaking');
    };

    utterance.onend = () => {
      if (!isMountedRef.current) return;
      setStatus('idle');
      if (isHandsFree) {
        setTimeout(() => {
          if (isMountedRef.current) startListening();
        }, 500);
      }
    };

    utterance.onerror = () => {
      if (isMountedRef.current) setStatus('idle');
    };

    window.speechSynthesis.speak(utterance);
  };

  const handleOrbClick = () => {
    if (status === 'speaking') {
      if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
        window.speechSynthesis.cancel();
      }
      setStatus('idle');
      startListening();
    } else if (status === 'listening') {
      stopListening();
      setStatus('idle');
    } else {
      startListening();
    }
  };

  const testAudioClarity = () => {
    const testSamples = {
      'auto': 'Hello! Nova voice is active and crystal clear.',
      'en-IN': 'Hello! Nova voice is active and crystal clear.',
      'ta-IN': 'வணக்கம்! நோவா வாய்ஸ் தெளிவாக பேசுகிறது.',
      'hi-IN': 'नमस्ते! नोवा वॉइस बिल्कुल स्पष्ट काम कर रही है।',
      'te-IN': 'నమస్కారం! నోవా వాయిస్ చాలా స్పష్టంగా ఉంది.',
      'ml-IN': 'നമസ്കാരം! നോവ വോയ്സ് വ്യക്തമായി പ്രവർത്തിക്കുന്നു.',
      'kn-IN': 'ನಮಸ್ಕಾರ! ನೋವಾ ವಾಯ್ಸ್ ಸ್ಪಷ್ಟವಾಗಿ ಕೆಲಸ ಮಾಡುತ್ತಿದೆ.',
    };
    const sample = testSamples[selectedLang] || testSamples['auto'];
    setReplyText(sample);
    speakText(sample, selectedLang === 'auto' ? 'en-IN' : selectedLang);
  };

  if (!isOpen) return null;

  const currentLangObj = SUPPORTED_LANGUAGES.find(l => l.code === selectedLang) || SUPPORTED_LANGUAGES[0];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/80 backdrop-blur-2xl animate-fade-in">
      {/* Background radial aura */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        <div className={`absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[550px] h-[550px] rounded-full blur-[140px] transition-all duration-700 ${
          status === 'listening' 
            ? 'bg-gradient-to-tr from-cyan-600/30 to-purple-600/35 scale-110'
            : status === 'speaking'
            ? 'bg-gradient-to-tr from-purple-600/40 via-indigo-500/35 to-pink-500/30 scale-125 animate-pulse'
            : status === 'thinking'
            ? 'bg-gradient-to-tr from-amber-500/25 to-purple-700/30 rotate-45 scale-100'
            : 'bg-gradient-to-tr from-purple-800/20 to-indigo-900/20 scale-90'
        }`} />
      </div>

      {/* Main Glass Card */}
      <div className="relative w-full max-w-xl bg-zinc-900/90 border border-white/10 rounded-3xl p-6 sm:p-8 shadow-2xl backdrop-blur-3xl flex flex-col items-center text-center overflow-hidden">
        
        {/* Header Bar */}
        <div className="w-full flex items-center justify-between pb-3 border-b border-white/5 text-zinc-400">
          <div className="flex items-center gap-2">
            <span className="flex h-2.5 w-2.5 relative">
              <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                status === 'listening' ? 'bg-cyan-400' : status === 'speaking' ? 'bg-purple-400' : 'bg-emerald-400'
              }`} />
              <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${
                status === 'listening' ? 'bg-cyan-500' : status === 'speaking' ? 'bg-purple-500' : 'bg-emerald-500'
              }`} />
            </span>
            <span className="text-xs font-semibold uppercase tracking-wider text-zinc-300">Nova Voice</span>
            <span className="text-[10px] px-2 py-0.5 rounded-full font-medium bg-purple-500/20 text-purple-300 border border-purple-500/30">
              {activeEngine === 'gemini' ? `✨ Gemini` : `⚡ Local AI`}
            </span>
            <span className="text-[10px] px-2 py-0.5 rounded-full font-medium bg-emerald-500/15 text-emerald-400 border border-emerald-500/25">
              {currentLangObj.native}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={testAudioClarity}
              className="text-[11px] px-2.5 py-1 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 transition-colors border border-white/5 flex items-center gap-1"
              title="Test clear audio playback"
            >
              <span>🔊</span>
              <span>Test Audio</span>
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-full hover:bg-white/10 text-zinc-400 hover:text-white transition-colors"
              title="Close voice mode"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Regularized Language Pill Bar */}
        <div className="w-full flex items-center justify-center gap-1.5 py-3 border-b border-white/5 overflow-x-auto no-scrollbar">
          {SUPPORTED_LANGUAGES.map((lang) => {
            const isSelected = selectedLang === lang.code;
            return (
              <button
                key={lang.code}
                onClick={() => handleLanguageChange(lang.code)}
                className={`px-3 py-1 rounded-full text-xs font-medium transition-all shrink-0 flex items-center gap-1 ${
                  isSelected
                    ? 'bg-gradient-to-r from-purple-600 to-indigo-600 text-white shadow-md shadow-purple-600/30 scale-105 border border-purple-400/50'
                    : 'bg-zinc-800/90 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700/80 border border-white/5'
                }`}
                title={`Switch voice mode to ${lang.name}`}
              >
                <span>{lang.native}</span>
              </button>
            );
          })}
        </div>

        {/* Dynamic Orb Visualizer */}
        <div className="my-6 relative flex items-center justify-center cursor-pointer group" onClick={handleOrbClick}>
          {/* Animated concentric rings */}
          <div className={`absolute rounded-full border border-purple-500/20 transition-all duration-700 ${
            status === 'speaking' ? 'w-56 h-56 animate-ping' : status === 'listening' ? 'w-52 h-52 animate-pulse' : 'w-44 h-44 opacity-20'
          }`} />
          <div className={`absolute rounded-full border border-cyan-400/20 transition-all duration-500 ${
            status === 'listening' ? 'w-48 h-48 animate-pulse delay-150' : status === 'speaking' ? 'w-48 h-48 scale-105' : 'w-40 h-40 opacity-20'
          }`} />

          {/* Central Glowing Core */}
          <div className={`w-36 h-36 rounded-full flex items-center justify-center shadow-2xl transition-all duration-500 transform ${
            status === 'listening'
              ? 'bg-gradient-to-tr from-cyan-500 via-indigo-600 to-purple-600 shadow-cyan-500/40 scale-110'
              : status === 'speaking'
              ? 'bg-gradient-to-tr from-purple-600 via-pink-600 to-indigo-500 shadow-purple-500/50 scale-115'
              : status === 'thinking'
              ? 'bg-gradient-to-tr from-amber-500 via-purple-600 to-indigo-700 shadow-purple-500/30 animate-spin scale-100'
              : 'bg-gradient-to-tr from-zinc-800 via-zinc-900 to-purple-950/40 border border-white/10 hover:border-purple-500/50 scale-100'
          }`}>
            {status === 'thinking' ? (
              <div className="w-8 h-8 border-3 border-white border-t-transparent rounded-full animate-spin" />
            ) : status === 'listening' ? (
              <svg className="w-12 h-12 text-white animate-bounce" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
              </svg>
            ) : status === 'speaking' ? (
              <div className="flex items-center gap-1.5 h-8">
                <span className="w-1.5 bg-white rounded-full animate-pulse h-5" />
                <span className="w-1.5 bg-white rounded-full animate-pulse h-8 delay-75" />
                <span className="w-1.5 bg-white rounded-full animate-pulse h-6 delay-150" />
                <span className="w-1.5 bg-white rounded-full animate-pulse h-3 delay-200" />
              </div>
            ) : (
              <svg className="w-10 h-10 text-zinc-400 group-hover:text-purple-300 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
              </svg>
            )}
          </div>
        </div>

        {/* Quick Action Presets (Ease-of-use shortcuts) */}
        <div className="w-full flex items-center justify-center gap-2 mb-3 overflow-x-auto no-scrollbar">
          {PRESET_PROMPTS.map((p, idx) => (
            <button
              key={idx}
              onClick={() => {
                setTranscript(p.text);
                handleUserSpoke(p.text);
              }}
              className="text-[11px] px-2.5 py-1 rounded-lg bg-zinc-800/80 hover:bg-purple-600/30 text-zinc-300 hover:text-white border border-white/5 transition-all shrink-0"
            >
              {p.label}
            </button>
          ))}
        </div>

        {/* Status indicator label */}
        <p className="text-sm font-medium text-zinc-300 mb-2 transition-all">
          {status === 'listening' && (selectedLang === 'auto' ? 'Listening in any language...' : `Listening in ${currentLangObj.native}...`)}
          {status === 'thinking' && 'Nova is thinking with Gemini...'}
          {status === 'speaking' && 'Speaking (tap to interrupt)...'}
          {status === 'idle' && 'Tap the orb or speak to start'}
        </p>

        {/* Live Spoken Transcript & Reply Display */}
        <div className="w-full min-h-[85px] max-h-[130px] overflow-y-auto px-4 py-3 rounded-2xl bg-zinc-950/70 border border-white/5 text-left text-sm space-y-2 relative">
          {transcript && (
            <div className="flex items-start gap-2 text-zinc-400">
              <span className="text-[11px] font-bold text-cyan-400 uppercase tracking-wide">You:</span>
              <span className="text-zinc-200">{transcript}</span>
            </div>
          )}
          {replyText && (
            <div className="flex items-start justify-between gap-2 text-purple-300">
              <div className="flex items-start gap-2">
                <span className="text-[11px] font-bold text-purple-400 uppercase tracking-wide">Nova:</span>
                <span className="text-zinc-100">{replyText}</span>
              </div>
              <button
                onClick={() => speakText(lastReplyRef.current, lastLangRef.current)}
                className="p-1 rounded-md bg-zinc-800/80 hover:bg-zinc-700 text-zinc-300 shrink-0"
                title="Replay spoken reply"
              >
                🔊
              </button>
            </div>
          )}
          {!transcript && !replyText && (
            <p className="text-xs text-zinc-500 italic text-center py-3">
              "Ask a question, speak in Tamil, Hindi, English, or ask to translate..."
            </p>
          )}
        </div>

        {/* Footer Controls: Clarity Speed & Hands-Free */}
        <div className="w-full flex items-center justify-between pt-3 mt-2 border-t border-white/5 text-xs text-zinc-400">
          {/* Clarity Speed Switcher */}
          <div className="flex items-center gap-1.5 bg-zinc-800/60 rounded-xl p-1 border border-white/5">
            <span className="text-[10px] text-zinc-400 px-1 font-semibold">Speed:</span>
            {[0.92, 1.0, 1.1].map((rate) => (
              <button
                key={rate}
                onClick={() => {
                  setSpeechRate(rate);
                  localStorage.setItem('nova_voice_rate', rate.toString());
                }}
                className={`px-2 py-0.5 rounded-lg text-[10px] font-medium transition-colors ${
                  Math.abs(speechRate - rate) < 0.04
                    ? 'bg-purple-600 text-white'
                    : 'text-zinc-400 hover:text-white'
                }`}
              >
                {rate === 0.92 ? '0.9x Clear' : `${rate}x`}
              </button>
            ))}
          </div>

          {/* Hands-Free Toggle & Mic */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => setIsHandsFree(!isHandsFree)}
              className={`text-[11px] px-2.5 py-1.5 rounded-xl border transition-colors ${
                isHandsFree
                  ? 'bg-purple-600/20 text-purple-300 border-purple-500/30'
                  : 'bg-white/5 text-zinc-400 border-white/10'
              }`}
            >
              {isHandsFree ? '✓ Continuous' : 'Push-to-talk'}
            </button>
            <button
              onClick={handleOrbClick}
              className={`px-3.5 py-1.5 rounded-xl font-medium transition-all ${
                status === 'listening'
                  ? 'bg-rose-600 hover:bg-rose-500 text-white'
                  : 'bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white shadow-lg shadow-purple-600/20'
              }`}
            >
              {status === 'listening' ? 'Stop' : 'Speak'}
            </button>
          </div>
        </div>

      </div>
    </div>
  );
}
