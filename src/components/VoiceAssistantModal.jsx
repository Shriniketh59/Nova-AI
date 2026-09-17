import { useState, useEffect, useRef, useCallback } from 'react';

// Audio playback: play audio bytes returned by server TTS (neural MP3 or fallback WAV)
function playWavBytes(base64Data, onStart, onEnd, mimeType = 'audio/mpeg') {
  try {
    const binary = atob(base64Data);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const blob = new Blob([bytes], { type: mimeType || 'audio/mpeg' });
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.onplay = () => onStart && onStart();
    audio.onended = () => {
      URL.revokeObjectURL(url);
      onEnd && onEnd();
    };
    audio.onerror = () => {
      URL.revokeObjectURL(url);
      onEnd && onEnd();
    };
    audio.play().catch(() => onEnd && onEnd());
    return audio;
  } catch (err) {
    console.warn('Audio playback error:', err);
    onEnd && onEnd();
    return null;
  }
}

// Downsample Float32Array audio buffer to 16000Hz
function downsampleBuffer(buffer, sampleRate, outSampleRate = 16000) {
  if (outSampleRate >= sampleRate) return buffer;
  const ratio = sampleRate / outSampleRate;
  const newLength = Math.round(buffer.length / ratio);
  const result = new Float32Array(newLength);
  let offsetResult = 0;
  let offsetBuffer = 0;
  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
    let accum = 0, count = 0;
    for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
      accum += buffer[i];
      count++;
    }
    result[offsetResult] = count ? accum / count : 0;
    offsetResult++;
    offsetBuffer = nextOffsetBuffer;
  }
  return result;
}

// Convert Float32Array to 16-bit PCM little-endian ArrayBuffer
function floatTo16BitPCM(float32Array) {
  const buffer = new ArrayBuffer(float32Array.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < float32Array.length; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buffer;
}

function arrayBufferToBase64(buffer) {
  let binary = '';
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

const SIRI_VOICES = [
  { id: 'en-US-AvaNeural', name: 'Siri Natural (Ava)', desc: 'Warm, human & conversational', tag: 'Default' },
  { id: 'en-US-JennyNeural', name: 'Siri Crisp (Jenny)', desc: 'Studio clarity & crisp articulation', tag: 'Studio' },
  { id: 'en-US-AriaNeural', name: 'Siri Confident (Aria)', desc: 'Expressive & confident tone', tag: 'Pro' },
  { id: 'en-US-AndrewNeural', name: 'Siri Smooth (Andrew)', desc: 'Warm executive male voice', tag: 'Male' },
  { id: 'en-GB-SoniaNeural', name: 'Siri British (Sonia)', desc: 'Sophisticated UK English accent', tag: 'UK' },
];

export default function VoiceAssistantModal({ isOpen, onClose, activeChatId, onMessageAdded }) {
  const [status, setStatus] = useState('idle'); // 'connecting' | 'idle' | 'listening' | 'thinking' | 'speaking'
  const [statusDetail, setStatusDetail] = useState('');
  const [transcript, setTranscript] = useState('');
  const [replyText, setReplyText] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [micActive, setMicActive] = useState(false);
  const [inputVolume, setInputVolume] = useState(0);
  const [selectedVoice, setSelectedVoice] = useState(() => {
    return localStorage.getItem('nova_siri_voice') || 'en-US-AvaNeural';
  });
  const [isVoicePickerOpen, setIsVoicePickerOpen] = useState(false);

  const statusRef = useRef('idle');
  statusRef.current = status;

  const wsRef = useRef(null);
  const audioRef = useRef(null);
  const micStreamRef = useRef(null);
  const audioContextRef = useRef(null);
  const processorRef = useRef(null);
  const silenceTimerRef = useRef(null);
  const hasSpokenRef = useRef(false);
  const isComponentMountedRef = useRef(true);

  const stopAudio = useCallback(() => {
    if (audioRef.current) {
      try { audioRef.current.pause(); } catch {}
      audioRef.current = null;
    }
  }, []);

  const stopMic = useCallback(() => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
    hasSpokenRef.current = false;
    if (processorRef.current) {
      try { processorRef.current.disconnect(); } catch {}
      processorRef.current = null;
    }
    if (audioContextRef.current) {
      try { audioContextRef.current.close(); } catch {}
      audioContextRef.current = null;
    }
    if (micStreamRef.current) {
      try {
        micStreamRef.current.getTracks().forEach(t => t.stop());
      } catch {}
      micStreamRef.current = null;
    }
    setMicActive(false);
    setInputVolume(0);
  }, []);

  const startMic = useCallback(async () => {
    stopMic();
    if (!navigator.mediaDevices?.getUserMedia) {
      setErrorMessage('Microphone not supported on this browser.');
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      micStreamRef.current = stream;

      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const audioCtx = new AudioCtx();
      audioContextRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);

      // ScriptProcessorNode to capture 16kHz PCM chunks
      const processor = audioCtx.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;

      processor.onaudioprocess = (e) => {
        const ws = wsRef.current;
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        // Don't capture microphone while assistant is speaking (echo prevention)
        if (statusRef.current === 'speaking' || statusRef.current === 'thinking') return;

        const inputChannel = e.inputBuffer.getChannelData(0);

        // Calculate RMS for live voice visualizer and silence detector
        let sum = 0;
        for (let i = 0; i < inputChannel.length; i++) {
          sum += inputChannel[i] * inputChannel[i];
        }
        const rms = Math.sqrt(sum / inputChannel.length);

        if (rms > 0.02) {
          setInputVolume(Math.min(100, Math.round(rms * 500)));
          hasSpokenRef.current = true;
          if (silenceTimerRef.current) {
            clearTimeout(silenceTimerRef.current);
            silenceTimerRef.current = null;
          }
        } else {
          setInputVolume(0);
          if (hasSpokenRef.current && !silenceTimerRef.current) {
            silenceTimerRef.current = setTimeout(() => {
              if (hasSpokenRef.current && wsRef.current?.readyState === WebSocket.OPEN) {
                hasSpokenRef.current = false;
                wsRef.current.send(JSON.stringify({ type: 'audio_end' }));
                setStatus('thinking');
                setStatusDetail('Transcribing speech (faster-whisper)...');
              }
            }, 1200);
          }
        }

        // Downsample to 16000Hz for Whisper
        const downsampled = audioCtx.sampleRate !== 16000
          ? downsampleBuffer(inputChannel, audioCtx.sampleRate, 16000)
          : inputChannel;

        const pcmBuffer = floatTo16BitPCM(downsampled);
        const b64 = arrayBufferToBase64(pcmBuffer);
        ws.send(JSON.stringify({ type: 'audio_chunk', data: b64 }));
      };

      source.connect(processor);
      processor.connect(audioCtx.destination);
      setMicActive(true);
    } catch (err) {
      console.warn('Microphone start error:', err);
      setErrorMessage(`Microphone access error: ${err.message}`);
      setMicActive(false);
    }
  }, [stopMic]);

  const cleanup = useCallback(() => {
    stopAudio();
    stopMic();
    if (wsRef.current) {
      try { wsRef.current.close(); } catch {}
      wsRef.current = null;
    }
  }, [stopAudio, stopMic]);

  // Connect to local /ws/voice/local endpoint
  const connect = useCallback(() => {
    cleanup();
    if (!isComponentMountedRef.current) return;
    setErrorMessage('');
    setStatus('connecting');
    setStatusDetail('Connecting to local voice engine...');

    try {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const params = new URLSearchParams();
      if (activeChatId) params.set('chatId', activeChatId);
      if (selectedVoice) params.set('voice', selectedVoice);
      const queryStr = params.toString() ? `?${params.toString()}` : '';
      const ws = new WebSocket(`${proto}//${window.location.host}/ws/voice/local${queryStr}`);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!isComponentMountedRef.current) return;
        startMic();
      };

      ws.onmessage = (event) => {
        if (!isComponentMountedRef.current) return;
        let data;
        try { data = JSON.parse(event.data); } catch { return; }

        switch (data.type) {
          case 'ready':
          case 'listening':
            setStatus('listening');
            setStatusDetail('Listening — speak into your microphone...');
            break;
          case 'transcript':
            setTranscript(data.text || '');
            setReplyText('');
            if (onMessageAdded) onMessageAdded({ role: 'user', content: data.text });
            break;
          case 'thinking':
            setStatus('thinking');
            setStatusDetail('Nova is reasoning with Llama 3.2...');
            break;
          case 'token':
            setReplyText(prev => prev + (data.text || ''));
            break;
          case 'speaking':
            setStatus('speaking');
            setStatusDetail('Nova is speaking — tap orb to interrupt...');
            break;
          case 'tts_audio':
            stopAudio();
            audioRef.current = playWavBytes(
              data.data,
              () => {
                if (isComponentMountedRef.current) {
                  setStatus('speaking');
                  setStatusDetail('Nova is speaking — tap orb to interrupt...');
                }
              },
              () => {
                if (isComponentMountedRef.current) {
                  setStatus('listening');
                  setStatusDetail('Listening — speak into your microphone...');
                }
              },
              data.mimeType || 'audio/mpeg'
            );
            break;
          case 'done':
            if (replyText && onMessageAdded) {
              onMessageAdded({ role: 'ai', content: replyText });
            }
            break;
          case 'interrupted':
            stopAudio();
            setStatus('listening');
            setStatusDetail('Interrupted — listening again...');
            break;
          case 'error':
            setErrorMessage(data.message || 'Voice engine error');
            setStatus('idle');
            break;
          default:
            break;
        }
      };

      ws.onerror = () => {
        if (isComponentMountedRef.current) {
          setErrorMessage('Connection error. Make sure the server is running on port 5001.');
          setStatus('idle');
        }
      };

      ws.onclose = () => {
        if (isComponentMountedRef.current && statusRef.current !== 'idle') {
          setStatus('idle');
          setStatusDetail('Session ended. Click Start to reconnect.');
        }
      };
    } catch (err) {
      if (isComponentMountedRef.current) {
        setErrorMessage(`Could not connect: ${err.message}`);
        setStatus('idle');
      }
    }
  }, [activeChatId, selectedVoice, cleanup, stopAudio, startMic, onMessageAdded, replyText]);

  const handleVoiceChange = (voiceId) => {
    setSelectedVoice(voiceId);
    try {
      localStorage.setItem('nova_siri_voice', voiceId);
    } catch {}
    setIsVoicePickerOpen(false);
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'set_voice', voice: voiceId }));
    }
  };

  const sendText = (text) => {
    if (!text || !text.trim()) return;
    setTranscript(text);
    setReplyText('');
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'text', text }));
      setStatus('thinking');
      setStatusDetail('Nova is thinking...');
    } else {
      connect();
    }
  };

  const handleOrbClick = () => {
    if (status === 'speaking') {
      stopAudio();
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'stop' }));
      }
      setStatus('listening');
      setStatusDetail('Stopped. Listening...');
    } else if (status === 'listening') {
      // If user is speaking, manual tap finishes utterance
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'audio_end' }));
        setStatus('thinking');
        setStatusDetail('Transcribing speech...');
      }
    } else if (status === 'idle' || status === 'connecting') {
      connect();
    }
  };

  const handleStop = () => {
    stopAudio();
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'stop' }));
    }
    setStatus('listening');
    setStatusDetail('Stopped. Listening...');
  };

  useEffect(() => {
    isComponentMountedRef.current = true;
    if (isOpen) {
      setTranscript('');
      setReplyText('');
      setErrorMessage('');
      connect();
    } else {
      cleanup();
      setStatus('idle');
    }
    return () => {
      isComponentMountedRef.current = false;
      cleanup();
    };
  }, [isOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/85 backdrop-blur-2xl animate-fade-in">
      {/* Background radial aura */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        <div
          className={`absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[550px] h-[550px] rounded-full blur-[140px] transition-all duration-500 ${
            status === 'speaking'
              ? 'bg-gradient-to-tr from-purple-600/50 via-indigo-500/40 to-pink-500/35 scale-125 animate-pulse'
              : status === 'listening'
              ? 'bg-gradient-to-tr from-cyan-600/40 to-purple-600/35 scale-110'
              : status === 'thinking'
              ? 'bg-gradient-to-tr from-amber-500/30 to-purple-700/35 rotate-45 scale-100'
              : 'bg-gradient-to-tr from-purple-800/20 to-indigo-900/20 scale-90'
          }`}
        />
      </div>

      {/* Main Glass Card */}
      <div className="relative w-full max-w-xl bg-zinc-950/80 border border-white/10 rounded-3xl p-6 sm:p-8 shadow-2xl backdrop-blur-3xl flex flex-col items-center text-center overflow-hidden">
        {/* Ambient Top Glow */}
        <div className="absolute -top-24 left-1/2 -translate-x-1/2 w-96 h-48 bg-gradient-to-b from-purple-600/20 via-cyan-500/10 to-transparent blur-3xl pointer-events-none" />

        {/* Header */}
        <div className="w-full flex items-center justify-between pb-3 border-b border-white/5 text-zinc-400 z-20">
          <div className="flex items-center gap-2.5">
            <span className="flex h-2.5 w-2.5 relative">
              <span
                className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${
                  status === 'listening'
                    ? 'bg-cyan-400'
                    : status === 'speaking'
                    ? 'bg-purple-400'
                    : status === 'thinking'
                    ? 'bg-amber-400'
                    : 'bg-zinc-600'
                }`}
              />
              <span
                className={`relative inline-flex rounded-full h-2.5 w-2.5 ${
                  status === 'listening'
                    ? 'bg-cyan-400'
                    : status === 'speaking'
                    ? 'bg-purple-500'
                    : status === 'thinking'
                    ? 'bg-amber-400'
                    : 'bg-zinc-500'
                }`}
              />
            </span>
            <span className="text-xs font-semibold tracking-wider text-zinc-200">Nova Live Assistant</span>
          </div>

          <div className="flex items-center gap-2">
            {/* Siri Voice Selector Dropdown */}
            <div className="relative">
              <button
                type="button"
                onClick={() => setIsVoicePickerOpen(!isVoicePickerOpen)}
                className="text-[11px] px-2.5 py-1 rounded-full font-medium bg-purple-500/15 text-purple-300 border border-purple-500/30 hover:bg-purple-500/25 transition-all flex items-center gap-1.5 cursor-pointer shadow-sm"
                title="Select Siri Voice Persona"
              >
                <span>🎙️</span>
                <span>{SIRI_VOICES.find(v => v.id === selectedVoice)?.name || 'Siri Natural'}</span>
                <svg className={`w-3 h-3 transition-transform ${isVoicePickerOpen ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {/* Voice Dropdown Menu */}
              {isVoicePickerOpen && (
                <div className="absolute right-0 mt-2 w-64 bg-zinc-900/95 border border-white/10 rounded-2xl shadow-2xl backdrop-blur-2xl p-1.5 z-50 text-left animate-fade-in">
                  <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-400 border-b border-white/5 mb-1">
                    Siri English Voices
                  </div>
                  {SIRI_VOICES.map((v) => (
                    <button
                      key={v.id}
                      type="button"
                      onClick={() => handleVoiceChange(v.id)}
                      className={`w-full flex items-center justify-between px-3 py-2 rounded-xl text-left transition-colors ${
                        selectedVoice === v.id
                          ? 'bg-purple-600/30 text-white font-medium'
                          : 'text-zinc-300 hover:bg-white/5 hover:text-white'
                      }`}
                    >
                      <div className="flex flex-col">
                        <span className="text-xs">{v.name}</span>
                        <span className="text-[10px] text-zinc-400">{v.desc}</span>
                      </div>
                      {selectedVoice === v.id && (
                        <span className="text-purple-400 text-xs font-bold">✓</span>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <button
              onClick={onClose}
              className="p-1.5 rounded-full hover:bg-white/10 text-zinc-400 hover:text-white transition-colors"
              title="Close"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Siri-Style Interactive Orb Visualizer */}
        <div className="my-8 relative flex items-center justify-center cursor-pointer group" onClick={handleOrbClick}>
          {/* Outermost Soundwave Pulse Rings */}
          <div
            className={`absolute rounded-full border border-purple-400/20 transition-all duration-500 ${
              status === 'speaking'
                ? 'w-64 h-64 animate-ping opacity-40'
                : status === 'listening'
                ? inputVolume > 10 ? 'w-64 h-64 border-cyan-400/50 animate-ping' : 'w-56 h-56 animate-pulse opacity-30'
                : 'w-48 h-48 opacity-10'
            }`}
          />
          <div
            className={`absolute rounded-full border border-cyan-400/30 transition-all duration-300 ${
              status === 'listening'
                ? inputVolume > 10 ? 'w-56 h-56 border-cyan-300/60' : 'w-50 h-50 animate-pulse'
                : status === 'speaking'
                ? 'w-52 h-52 border-pink-400/30 animate-pulse'
                : 'w-42 h-42 opacity-15'
            }`}
          />

          {/* Core Orb */}
          <div
            className={`w-36 h-36 rounded-full flex flex-col items-center justify-center shadow-2xl transition-all duration-300 relative ${
              status === 'listening'
                ? inputVolume > 10
                  ? 'bg-gradient-to-tr from-cyan-400 via-blue-500 to-purple-500 shadow-cyan-500/60 scale-115'
                  : 'bg-gradient-to-tr from-cyan-500 via-indigo-600 to-purple-600 shadow-cyan-500/40 scale-105'
                : status === 'speaking'
                ? 'bg-gradient-to-tr from-fuchsia-600 via-pink-500 to-indigo-600 shadow-fuchsia-500/50 scale-110'
                : status === 'thinking' || status === 'connecting'
                ? 'bg-gradient-to-tr from-amber-500 via-purple-600 to-indigo-700 shadow-purple-500/30'
                : 'bg-gradient-to-tr from-zinc-800 via-zinc-900 to-purple-950/40 border border-white/10 hover:border-purple-500/50 group-hover:scale-105'
            }`}
          >
            {status === 'thinking' || status === 'connecting' ? (
              <div className="w-9 h-9 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            ) : status === 'listening' ? (
              inputVolume > 5 ? (
                <div className="flex flex-col items-center justify-center">
                  <div className="flex items-center gap-1 h-9 mb-1">
                    <span className="w-1 bg-cyan-300 rounded-full transition-all duration-75" style={{ height: `${Math.max(6, Math.min(26, inputVolume * 0.35))}px` }} />
                    <span className="w-1.5 bg-cyan-200 rounded-full transition-all duration-75" style={{ height: `${Math.max(10, Math.min(34, inputVolume * 0.65))}px` }} />
                    <span className="w-2 bg-white rounded-full transition-all duration-75" style={{ height: `${Math.max(14, Math.min(42, inputVolume * 0.9))}px` }} />
                    <span className="w-1.5 bg-cyan-200 rounded-full transition-all duration-75" style={{ height: `${Math.max(10, Math.min(34, inputVolume * 0.65))}px` }} />
                    <span className="w-1 bg-cyan-300 rounded-full transition-all duration-75" style={{ height: `${Math.max(6, Math.min(26, inputVolume * 0.35))}px` }} />
                  </div>
                  <span className="text-[10px] text-cyan-100 font-semibold uppercase tracking-widest">Listening</span>
                </div>
              ) : (
                <div className="flex flex-col items-center">
                  <svg className="w-10 h-10 text-white drop-shadow-md animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                  </svg>
                  <span className="text-[10px] text-cyan-200/90 font-medium tracking-wide mt-0.5">Speak now</span>
                </div>
              )
            ) : status === 'speaking' ? (
              <div className="flex items-center gap-1.5 h-10 px-4 py-1.5 rounded-full bg-black/20 backdrop-blur-sm">
                <span className="w-1.5 bg-white rounded-full animate-[pulse_0.6s_ease-in-out_infinite] h-4" />
                <span className="w-1.5 bg-white rounded-full animate-[pulse_0.5s_ease-in-out_infinite_0.1s] h-8" />
                <span className="w-1.5 bg-white rounded-full animate-[pulse_0.7s_ease-in-out_infinite_0.2s] h-6" />
                <span className="w-1.5 bg-white rounded-full animate-[pulse_0.4s_ease-in-out_infinite_0.3s] h-9" />
                <span className="w-1.5 bg-white rounded-full animate-[pulse_0.6s_ease-in-out_infinite_0.15s] h-7" />
                <span className="w-1.5 bg-white rounded-full animate-[pulse_0.5s_ease-in-out_infinite_0.25s] h-5" />
              </div>
            ) : (
              <svg className="w-10 h-10 text-zinc-400 group-hover:text-purple-300 transition-colors drop-shadow" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
              </svg>
            )}
          </div>
        </div>

        {/* Status label */}
        <div className="mb-3">
          <p className="text-sm font-medium text-zinc-200 tracking-wide">
            {statusDetail || (status === 'listening' ? 'Listening... Speak naturally' : 'Tap the orb to start conversation')}
          </p>
          {errorMessage && (
            <p className="text-xs text-rose-400 mt-1">{errorMessage}</p>
          )}
        </div>

        {/* Transcript + Spoken Reply Display */}
        <div className="w-full min-h-[110px] max-h-[175px] overflow-y-auto px-4 py-3.5 rounded-2xl bg-zinc-900/60 border border-white/5 text-left text-sm space-y-3 relative shadow-inner">
          {transcript && (
            <div className="flex items-start gap-2.5 text-zinc-300">
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-md bg-cyan-500/20 text-cyan-300 uppercase tracking-wider shrink-0 mt-0.5">
                You
              </span>
              <span className="leading-relaxed text-zinc-200">{transcript}</span>
            </div>
          )}
          {replyText && (
            <div className="flex items-start gap-2.5">
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-md bg-purple-500/20 text-purple-300 uppercase tracking-wider shrink-0 mt-0.5">
                Nova
              </span>
              <div className="leading-relaxed text-zinc-100 font-normal flex-1">
                <span>{replyText}</span>
                {status === 'speaking' && (
                  <span className="inline-block w-1.5 h-3.5 bg-purple-400 ml-1 rounded-sm animate-pulse" />
                )}
              </div>
            </div>
          )}
          {!transcript && !replyText && (
            <div className="flex flex-col items-center justify-center py-5 text-zinc-500 text-xs">
              <div className="flex items-center gap-1 mb-1.5 opacity-60">
                <span className="w-1 h-3 bg-purple-400/60 rounded-full animate-pulse" />
                <span className="w-1 h-5 bg-cyan-400/60 rounded-full animate-pulse delay-75" />
                <span className="w-1 h-4 bg-purple-400/60 rounded-full animate-pulse delay-150" />
              </div>
              <span className="text-zinc-300 font-medium">Ready for conversation</span>
              <span className="text-zinc-500 text-[11px] mt-0.5">Speak clearly in English • Powered by Siri Neural Voice</span>
            </div>
          )}
        </div>

        {/* Text fallback input */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const val = e.target.elements.voiceInput?.value?.trim();
            if (val) {
              sendText(val);
              e.target.reset();
            }
          }}
          className="w-full mt-3 flex gap-2"
        >
          <input
            name="voiceInput"
            type="text"
            placeholder="Type or speak a question..."
            className="flex-1 bg-zinc-900/70 border border-white/10 rounded-xl px-3.5 py-2.5 text-sm text-zinc-200 placeholder-zinc-500 outline-none focus:border-purple-500/50 transition-colors"
          />
          <button
            type="submit"
            className="px-4 py-2.5 rounded-xl bg-purple-600 hover:bg-purple-500 text-white text-sm font-medium transition-colors shadow-lg shadow-purple-600/20"
          >
            Ask
          </button>
        </form>

        {/* Footer controls */}
        <div className="w-full flex items-center justify-between pt-3 mt-3 border-t border-white/5 text-xs text-zinc-400">
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 text-[11px] text-zinc-400">
              <span className={`w-2 h-2 rounded-full ${micActive ? 'bg-emerald-400 animate-pulse' : 'bg-zinc-600'}`} />
              <span>{micActive ? 'Microphone Active' : 'Microphone Ready'}</span>
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={connect}
              className="text-[11px] px-2.5 py-1.5 rounded-xl border bg-zinc-800/60 text-zinc-300 border-white/10 hover:bg-zinc-700 transition-colors"
            >
              Reset
            </button>
            <button
              onClick={status === 'speaking' ? handleStop : handleOrbClick}
              className={`px-4 py-1.5 rounded-xl font-medium transition-all text-[11px] ${
                status === 'speaking'
                  ? 'bg-amber-600 hover:bg-amber-500 text-white shadow-lg shadow-amber-600/20'
                  : 'bg-gradient-to-r from-purple-600 via-indigo-600 to-cyan-600 hover:from-purple-500 hover:to-cyan-500 text-white shadow-lg shadow-purple-600/25'
              }`}
            >
              {status === 'speaking' ? 'Interrupt / Stop' : status === 'listening' ? 'Done Speaking' : 'Tap to Speak'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
