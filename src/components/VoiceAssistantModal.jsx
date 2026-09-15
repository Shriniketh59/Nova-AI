import { useState, useEffect, useRef, useCallback } from 'react';

const PRESET_PROMPTS = [
  { label: '🏛️ CM of Karnataka', text: 'Who is the current Chief Minister of Karnataka?' },
  { label: '🏀 Tallest NBA Player', text: 'What is the tallest player in NBA history?' },
  { label: '🌌 Black Holes', text: 'What makes a black hole so fascinating?' },
  { label: '⚡ Fun Fact', text: 'Tell me a quick interesting fun fact' },
];

// Audio playback: play WAV bytes returned by server TTS
function playWavBytes(base64Wav, onStart, onEnd) {
  try {
    const binary = atob(base64Wav);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const blob = new Blob([bytes], { type: 'audio/wav' });
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

export default function VoiceAssistantModal({ isOpen, onClose, activeChatId, onMessageAdded }) {
  const [status, setStatus] = useState('idle'); // 'connecting' | 'idle' | 'listening' | 'thinking' | 'speaking'
  const [statusDetail, setStatusDetail] = useState('');
  const [transcript, setTranscript] = useState('');
  const [replyText, setReplyText] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [micActive, setMicActive] = useState(false);
  const [inputVolume, setInputVolume] = useState(0);

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
      const chatParam = activeChatId ? `?chatId=${encodeURIComponent(activeChatId)}` : '';
      const ws = new WebSocket(`${proto}//${window.location.host}/ws/voice/local${chatParam}`);
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
              }
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
  }, [activeChatId, cleanup, stopAudio, startMic, onMessageAdded, replyText]);

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
      <div className="relative w-full max-w-xl bg-zinc-900/90 border border-white/10 rounded-3xl p-6 sm:p-8 shadow-2xl backdrop-blur-3xl flex flex-col items-center text-center overflow-hidden">
        {/* Header */}
        <div className="w-full flex items-center justify-between pb-3 border-b border-white/5 text-zinc-400">
          <div className="flex items-center gap-2">
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
                    ? 'bg-cyan-500'
                    : status === 'speaking'
                    ? 'bg-purple-500'
                    : status === 'thinking'
                    ? 'bg-amber-500'
                    : 'bg-zinc-600'
                }`}
              />
            </span>
            <span className="text-xs font-semibold uppercase tracking-wider text-zinc-300">Nova Voice Assistant</span>
            <span className="text-[10px] px-2 py-0.5 rounded-full font-medium bg-emerald-500/15 text-emerald-400 border border-emerald-500/25">
              100% Local STT & TTS
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => sendText('Hello Nova! Give me a quick friendly greeting.')}
              className="text-[11px] px-2.5 py-1 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 transition-colors border border-white/5 flex items-center gap-1"
              title="Test local speech"
            >
              <span>🔊</span>
              <span>Test Audio</span>
            </button>
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

        {/* Orb & Audio Wave Visualizer */}
        <div className="my-6 relative flex items-center justify-center cursor-pointer group" onClick={handleOrbClick}>
          <div
            className={`absolute rounded-full border border-purple-500/30 transition-all duration-300 ${
              status === 'speaking'
                ? 'w-56 h-56 animate-ping'
                : status === 'listening'
                ? inputVolume > 10 ? 'w-60 h-60 border-cyan-400/60 animate-ping' : 'w-52 h-52 animate-pulse'
                : 'w-44 h-44 opacity-20'
            }`}
          />
          <div
            className={`absolute rounded-full border border-cyan-400/30 transition-all duration-300 ${
              status === 'listening'
                ? inputVolume > 10 ? 'w-52 h-52 border-cyan-300' : 'w-48 h-48 animate-pulse'
                : 'w-40 h-40 opacity-20'
            }`}
          />
          <div
            className={`w-36 h-36 rounded-full flex flex-col items-center justify-center shadow-2xl transition-all duration-300 ${
              status === 'listening'
                ? inputVolume > 10
                  ? 'bg-gradient-to-tr from-cyan-400 via-indigo-500 to-purple-500 shadow-cyan-400/50 scale-120'
                  : 'bg-gradient-to-tr from-cyan-500 via-indigo-600 to-purple-600 shadow-cyan-500/40 scale-110'
                : status === 'speaking'
                ? 'bg-gradient-to-tr from-purple-600 via-pink-600 to-indigo-500 shadow-purple-500/50 scale-115'
                : status === 'thinking' || status === 'connecting'
                ? 'bg-gradient-to-tr from-amber-500 via-purple-600 to-indigo-700 shadow-purple-500/30'
                : 'bg-gradient-to-tr from-zinc-800 via-zinc-900 to-purple-950/40 border border-white/10 hover:border-purple-500/50'
            }`}
          >
            {status === 'thinking' || status === 'connecting' ? (
              <div className="w-8 h-8 border-2 border-white border-t-transparent rounded-full animate-spin" />
            ) : status === 'listening' ? (
              <div className="flex flex-col items-center">
                <svg className="w-10 h-10 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                </svg>
                {inputVolume > 5 && (
                  <span className="text-[10px] text-cyan-100 font-bold uppercase tracking-wider mt-1">Speaking</span>
                )}
              </div>
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

        {/* Preset prompts */}
        <div className="w-full flex items-center justify-center gap-2 mb-3 overflow-x-auto no-scrollbar">
          {PRESET_PROMPTS.map((p, idx) => (
            <button
              key={idx}
              onClick={() => sendText(p.text)}
              className="text-[11px] px-2.5 py-1 rounded-lg bg-zinc-800/80 hover:bg-purple-600/30 text-zinc-300 hover:text-white border border-white/5 transition-all shrink-0"
            >
              {p.label}
            </button>
          ))}
        </div>

        {/* Status label */}
        <div className="mb-2">
          <p className="text-sm font-medium text-zinc-200">
            {statusDetail || (status === 'listening' ? 'Listening to microphone...' : 'Click the orb to start')}
          </p>
          {errorMessage && (
            <p className="text-xs text-rose-400 mt-1">{errorMessage}</p>
          )}
        </div>

        {/* Transcript + Reply display */}
        <div className="w-full min-h-[90px] max-h-[140px] overflow-y-auto px-4 py-3 rounded-2xl bg-zinc-950/70 border border-white/5 text-left text-sm space-y-2 relative">
          {transcript && (
            <div className="flex items-start gap-2 text-zinc-400">
              <span className="text-[11px] font-bold text-cyan-400 uppercase tracking-wide">You:</span>
              <span className="text-zinc-200">{transcript}</span>
            </div>
          )}
          {replyText && (
            <div className="flex items-start gap-2">
              <span className="text-[11px] font-bold text-purple-400 uppercase tracking-wide">Nova:</span>
              <span className="text-zinc-100">{replyText}</span>
            </div>
          )}
          {!transcript && !replyText && (
            <p className="text-xs text-zinc-500 italic text-center py-3">
              {micActive ? 'Microphone active — speak clearly into your mic' : 'Ask anything — fully local, no cloud APIs'}
            </p>
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
            placeholder="Or type a question..."
            className="flex-1 bg-zinc-800/60 border border-white/10 rounded-xl px-3 py-2 text-sm text-zinc-200 placeholder-zinc-500 outline-none focus:border-purple-500/50"
          />
          <button
            type="submit"
            className="px-3 py-2 rounded-xl bg-purple-600 hover:bg-purple-500 text-white text-sm font-medium transition-colors"
          >
            Ask
          </button>
        </form>

        {/* Footer controls */}
        <div className="w-full flex items-center justify-between pt-3 mt-2 border-t border-white/5 text-xs text-zinc-400">
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 text-[11px] text-zinc-400">
              <span className={`w-2 h-2 rounded-full ${micActive ? 'bg-emerald-400 animate-pulse' : 'bg-zinc-600'}`} />
              <span>{micActive ? 'Mic Active (16kHz PCM)' : 'Mic Standby'}</span>
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={connect}
              className="text-[11px] px-2.5 py-1.5 rounded-xl border bg-zinc-800/60 text-zinc-300 border-white/10 hover:bg-zinc-700 transition-colors"
            >
              Reconnect
            </button>
            <button
              onClick={status === 'speaking' ? handleStop : handleOrbClick}
              className={`px-3.5 py-1.5 rounded-xl font-medium transition-all text-[11px] ${
                status === 'speaking'
                  ? 'bg-amber-600 hover:bg-amber-500 text-white'
                  : 'bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 text-white shadow-lg shadow-purple-600/20'
              }`}
            >
              {status === 'speaking' ? 'Stop' : status === 'listening' ? 'Finish Utterance' : 'Start'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
