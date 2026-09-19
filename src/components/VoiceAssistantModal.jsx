import { useState, useEffect, useRef, useCallback } from 'react';

// Play audio bytes returned by the local TTS engine (pyttsx3 -> WAV).
function playAudioBytes(base64Data, onStart, onEnd, mimeType = 'audio/wav') {
  try {
    const binary = atob(base64Data);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const blob = new Blob([bytes], { type: mimeType || 'audio/wav' });
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

// Downsample a Float32Array to 16kHz (what faster-whisper expects).
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
  for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

// The complete voice state machine. Deliberately small and explicit —
// a state is an icon plus a short label, nothing more.
const STATES = {
  IDLE:      { label: 'Idle',       hint: 'Start voice to begin',          dot: 'bg-zinc-500',    text: 'text-zinc-400' },
  LISTENING: { label: 'Listening',  hint: 'Speak now — pause when done',   dot: 'bg-emerald-400', text: 'text-emerald-300' },
  THINKING:  { label: 'Thinking',   hint: 'Processing your request',       dot: 'bg-amber-400',   text: 'text-amber-300' },
  SPEAKING:  { label: 'Speaking',   hint: 'Playing the reply',             dot: 'bg-sky-400',     text: 'text-sky-300' },
  STOPPED:   { label: 'Stopped',    hint: 'Voice session ended',           dot: 'bg-zinc-500',    text: 'text-zinc-400' },
  ERROR:     { label: 'Error',      hint: 'Something went wrong',          dot: 'bg-rose-500',    text: 'text-rose-300' },
};

function StateIcon({ state }) {
  const cls = 'w-4 h-4';
  if (state === 'THINKING') {
    return <span className={`${cls} inline-block border-2 border-zinc-600 border-t-amber-300 rounded-full animate-spin`} />;
  }
  if (state === 'SPEAKING') {
    return (
      <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M11 5L6 9H2v6h4l5 4V5z" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M15.5 8.5a5 5 0 010 7" />
      </svg>
    );
  }
  if (state === 'ERROR') {
    return (
      <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v4m0 4h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L14.7 3.9a2 2 0 00-3.4 0z" />
      </svg>
    );
  }
  return (
    <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 18.75a6 6 0 006-6v-1.5m-6 7.5a6 6 0 01-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 01-3-3V4.5a3 3 0 116 0v8.25a3 3 0 01-3 3z" />
    </svg>
  );
}

export default function VoiceAssistantModal({ isOpen, onClose, activeChatId, onMessageAdded }) {
  const [state, setState] = useState('IDLE');
  const [transcript, setTranscript] = useState('');
  const [replyText, setReplyText] = useState('');
  const [errorMessage, setErrorMessage] = useState('');

  // Mirrors of state for use inside long-lived callbacks (the audio worklet
  // and WebSocket handlers capture their closure once, so they cannot read
  // the latest state directly). Synced in an effect, never during render.
  const stateRef = useRef('IDLE');
  const replyRef = useRef('');

  const wsRef = useRef(null);
  const audioRef = useRef(null);
  const micStreamRef = useRef(null);
  const audioContextRef = useRef(null);
  const processorRef = useRef(null);
  const silenceTimerRef = useRef(null);
  const hasSpokenRef = useRef(false);
  const isMountedRef = useRef(true);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    replyRef.current = replyText;
  }, [replyText]);

  const stopAudio = useCallback(() => {
    if (audioRef.current) {
      try { audioRef.current.pause(); } catch { /* already stopped */ }
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
      try { processorRef.current.disconnect(); } catch { /* already disconnected */ }
      processorRef.current = null;
    }
    if (audioContextRef.current) {
      try { audioContextRef.current.close(); } catch { /* already closed */ }
      audioContextRef.current = null;
    }
    if (micStreamRef.current) {
      try { micStreamRef.current.getTracks().forEach((t) => t.stop()); } catch { /* already stopped */ }
      micStreamRef.current = null;
    }
  }, []);

  const startMic = useCallback(async () => {
    stopMic();
    if (!navigator.mediaDevices?.getUserMedia) {
      setErrorMessage('This browser does not provide microphone access.');
      setState('ERROR');
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      micStreamRef.current = stream;

      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const audioCtx = new AudioCtx();
      audioContextRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);
      const processor = audioCtx.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;

      processor.onaudioprocess = (e) => {
        const ws = wsRef.current;
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        // Don't capture while the assistant is talking (echo prevention).
        if (stateRef.current === 'SPEAKING' || stateRef.current === 'THINKING') return;

        const inputChannel = e.inputBuffer.getChannelData(0);

        let sum = 0;
        for (let i = 0; i < inputChannel.length; i++) sum += inputChannel[i] * inputChannel[i];
        const rms = Math.sqrt(sum / inputChannel.length);

        if (rms > 0.02) {
          hasSpokenRef.current = true;
          if (silenceTimerRef.current) {
            clearTimeout(silenceTimerRef.current);
            silenceTimerRef.current = null;
          }
        } else if (hasSpokenRef.current && !silenceTimerRef.current) {
          // End the utterance after a short pause.
          silenceTimerRef.current = setTimeout(() => {
            if (hasSpokenRef.current && wsRef.current?.readyState === WebSocket.OPEN) {
              hasSpokenRef.current = false;
              wsRef.current.send(JSON.stringify({ type: 'audio_end' }));
              setState('THINKING');
            }
          }, 1200);
        }

        const downsampled = audioCtx.sampleRate !== 16000
          ? downsampleBuffer(inputChannel, audioCtx.sampleRate, 16000)
          : inputChannel;
        ws.send(JSON.stringify({ type: 'audio_chunk', data: arrayBufferToBase64(floatTo16BitPCM(downsampled)) }));
      };

      source.connect(processor);
      processor.connect(audioCtx.destination);
    } catch (err) {
      setErrorMessage(`Microphone unavailable: ${err.message}`);
      setState('ERROR');
    }
  }, [stopMic]);

  const cleanup = useCallback(() => {
    stopAudio();
    stopMic();
    if (wsRef.current) {
      try { wsRef.current.close(); } catch { /* already closed */ }
      wsRef.current = null;
    }
  }, [stopAudio, stopMic]);

  const connect = useCallback(() => {
    cleanup();
    if (!isMountedRef.current) return;
    setErrorMessage('');
    setState('THINKING');

    try {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const params = new URLSearchParams();
      if (activeChatId) params.set('chatId', activeChatId);
      const queryStr = params.toString() ? `?${params.toString()}` : '';
      const ws = new WebSocket(`${proto}//${window.location.host}/ws/voice/local${queryStr}`);
      wsRef.current = ws;

      ws.onopen = () => {
        if (isMountedRef.current) startMic();
      };

      ws.onmessage = (event) => {
        if (!isMountedRef.current) return;
        let data;
        try { data = JSON.parse(event.data); } catch { return; }

        switch (data.type) {
          case 'ready':
          case 'listening':
            setState((prev) => (prev === 'ERROR' ? prev : 'LISTENING'));
            break;
          case 'transcript':
            setTranscript(data.text || '');
            setReplyText('');
            if (onMessageAdded) onMessageAdded({ role: 'user', content: data.text });
            break;
          case 'thinking':
            setState('THINKING');
            break;
          case 'token':
            setReplyText((prev) => prev + (data.text || ''));
            break;
          case 'speaking':
            setState('SPEAKING');
            break;
          case 'tts_audio':
            stopAudio();
            audioRef.current = playAudioBytes(
              data.data,
              () => isMountedRef.current && setState('SPEAKING'),
              () => isMountedRef.current && setState('LISTENING'),
              data.mimeType || 'audio/wav',
            );
            break;
          case 'done':
            if (replyRef.current && onMessageAdded) {
              onMessageAdded({ role: 'ai', content: replyRef.current });
            }
            break;
          case 'interrupted':
            stopAudio();
            setState('LISTENING');
            break;
          case 'error':
            setErrorMessage(data.message || 'Voice engine error');
            setState('ERROR');
            break;
          default:
            break;
        }
      };

      ws.onerror = () => {
        if (isMountedRef.current) {
          setErrorMessage('Could not reach the local voice service. Is the server running?');
          setState('ERROR');
        }
      };

      ws.onclose = () => {
        if (isMountedRef.current && stateRef.current !== 'ERROR') setState('STOPPED');
      };
    } catch (err) {
      if (isMountedRef.current) {
        setErrorMessage(`Could not connect: ${err.message}`);
        setState('ERROR');
      }
    }
  }, [activeChatId, cleanup, stopAudio, startMic, onMessageAdded]);

  const handleStop = () => {
    stopAudio();
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'stop' }));
    }
    cleanup();
    setState('STOPPED');
  };

  const sendText = (text) => {
    if (!text || !text.trim()) return;
    setTranscript(text);
    setReplyText('');
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'text', text }));
      setState('THINKING');
    } else {
      connect();
    }
  };

  useEffect(() => {
    isMountedRef.current = true;
    if (isOpen) {
      setTranscript('');
      setReplyText('');
      setErrorMessage('');
      connect();
    } else {
      cleanup();
      setState('IDLE');
    }
    return () => {
      isMountedRef.current = false;
      cleanup();
    };
  }, [isOpen]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!isOpen) return null;

  const meta = STATES[state] || STATES.IDLE;
  const isActive = state === 'LISTENING' || state === 'THINKING' || state === 'SPEAKING';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div className="nova-surface-alt w-full max-w-md bg-zinc-950 border border-white/10 nova-border rounded-2xl shadow-2xl flex flex-col">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-white/5 nova-border">
          <span className="text-sm font-medium text-zinc-200 nova-text">Voice</span>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-zinc-500 hover:text-white hover:bg-white/5 transition-colors"
            title="Close"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* State row — icon + short label. No orb, no waveform. */}
        <div className="px-5 py-4 flex items-center gap-3 border-b border-white/5 nova-border">
          <span className={`flex items-center justify-center ${meta.text}`}>
            <StateIcon state={state} />
          </span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className={`w-1.5 h-1.5 rounded-full ${meta.dot} ${isActive ? 'animate-pulse' : ''}`} />
              <span className={`text-sm font-medium ${meta.text}`}>{meta.label}</span>
            </div>
            <p className="text-xs text-zinc-500 nova-text-muted mt-0.5 truncate">
              {state === 'ERROR' ? errorMessage || meta.hint : meta.hint}
            </p>
          </div>
        </div>

        {/* Transcript + reply */}
        <div className="px-5 py-4 min-h-[120px] max-h-64 overflow-y-auto space-y-3 text-sm">
          {transcript && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 nova-text-muted mb-1">You</div>
              <p className="text-zinc-300 nova-text-muted leading-relaxed">{transcript}</p>
            </div>
          )}
          {replyText && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-zinc-500 nova-text-muted mb-1">Nova</div>
              <p className="text-zinc-100 nova-text leading-relaxed whitespace-pre-wrap">{replyText}</p>
            </div>
          )}
          {!transcript && !replyText && (
            <p className="text-zinc-500 nova-text-muted text-center py-8 text-xs">
              Speak, or type a message below.
            </p>
          )}
        </div>

        {/* Text input */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const val = e.target.elements.voiceInput?.value?.trim();
            if (val) {
              sendText(val);
              e.target.reset();
            }
          }}
          className="px-5 pb-3 flex gap-2"
        >
          <input
            name="voiceInput"
            type="text"
            placeholder="Type a message..."
            className="nova-surface-alt flex-1 bg-zinc-900 border border-white/10 nova-border rounded-lg px-3 py-2 text-sm text-zinc-200 nova-text placeholder-zinc-600 outline-none focus:border-white/25 transition-colors"
          />
          <button
            type="submit"
            className="px-3 py-2 rounded-lg bg-white text-black text-sm font-medium hover:bg-zinc-200 transition-colors"
          >
            Send
          </button>
        </form>

        {/* Footer controls */}
        <div className="px-5 py-3 border-t border-white/5 nova-border flex items-center justify-between">
          <span className="text-[11px] text-zinc-600 nova-text-muted">Runs locally on this machine</span>
          {isActive ? (
            <button
              type="button"
              onClick={handleStop}
              className="text-xs px-3 py-1.5 rounded-lg border border-white/10 nova-border text-zinc-300 hover:bg-white/5 transition-colors"
            >
              Stop
            </button>
          ) : (
            <button
              type="button"
              onClick={connect}
              className="text-xs px-3 py-1.5 rounded-lg bg-white text-black font-medium hover:bg-zinc-200 transition-colors"
            >
              Start voice
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
