import { useState, useRef, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import MessageContent from '../components/MessageContent';
import ConfidenceBadge from '../components/ConfidenceBadge';
import SourceCard from '../components/SourceCard';
import DocumentCard from '../components/DocumentCard';
import ImageAnalysisPanel from '../components/ImageAnalysisPanel';

// Cheap heuristic, no LLM call — keeps the fast path actually fast. Routes
// comparisons/analysis/long multi-part questions to the deep critical-thinking
// pipeline; greetings and short factual asks stay on the quick single-shot path.
const COMPLEXITY_KEYWORDS = /\b(compare|comparison|vs\.?|versus|difference between|pros and cons|analyze|analyse|evaluate|recommend|which is better|explain in detail|step by step plan|trade-?offs?)\b/i;

// Coding asks must never fall into the 1-3min deep pipeline even if they're
// long/multi-sentence — mirrors server/src/services/taskRouter.js's
// isCodingQuestion so client and server agree on routing before either
// makes a network call. Backend has its own copy as the source of truth;
// this is just the client-side fast/deep fork.
const CODE_DOMAIN_RE = /\b(leetcode|dsa|data structure|hackerrank|codeforces|merge sort|quick sort|binary search|two sum|fibonacci)\b/i;
const CODE_VERBS_RE = /\b(write|give|generate|create|implement|build|code|fix|debug|refactor|optimi[sz]e)\b/i;
const CODE_NOUNS_RE = /\b(code|function|algorithm|script|program|snippet|class|component|endpoint|api|query|regex)\b/i;
const CODE_LANGS_RE = /(java|python|javascript|typescript|c\+\+|c#|go|golang|rust|ruby|php|sql|html|css|kotlin|swift|react|node\.?js|express)/i;

function isCodingPrompt(text) {
  if (CODE_DOMAIN_RE.test(text)) return true;
  return CODE_VERBS_RE.test(text) && (CODE_NOUNS_RE.test(text) || CODE_LANGS_RE.test(text));
}

function isComplexPrompt(text) {
  const trimmed = text.trim();
  if (isCodingPrompt(trimmed)) return false;
  if (COMPLEXITY_KEYWORDS.test(trimmed)) return true;
  const wordCount = trimmed.split(/\s+/).filter(Boolean).length;
  if (wordCount > 25) return true;
  const questionMarks = (trimmed.match(/\?/g) || []).length;
  if (questionMarks > 1) return true;
  return false;
}

export default function Chat() {
  const { chatId } = useParams();
  const navigate = useNavigate();

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [attachment, setAttachment] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  
  const messagesEndRef = useRef(null);
  const fileInputRef = useRef(null);
  // Set right before navigate() when a chat is created from a send-in-progress.
  // Skips the next chatId-driven reload so it doesn't wipe the in-flight
  // streaming placeholder with an empty messages list from the backend.
  const skipNextLoadRef = useRef(false);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Load messages when chatId changes
  useEffect(() => {
    if (skipNextLoadRef.current) {
      skipNextLoadRef.current = false;
      return;
    }
    const loadChatMessages = async () => {
      if (!chatId) {
        setMessages([]);
        return;
      }
      try {
        const res = await fetch(`/api/chats/${chatId}/messages`);
        if (res.ok) {
          const data = await res.json();
          // Map backend messages format if needed
          setMessages(data);
        }
      } catch (err) {
        console.error("Error loading chat messages:", err);
      }
    };
    loadChatMessages();
  }, [chatId]);

  const handleFileChange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    setIsUploading(true);

    try {
      // 1. Upload to backend RAG pipeline
      const formData = new FormData();
      formData.append('file', file);

      const res = await fetch('/api/upload', {
        method: 'POST',
        body: formData
      });

      const uploadData = await res.json();

      if (!res.ok) {
        throw new Error(uploadData.error || 'Upload failed');
      }

      const fileRecord = uploadData.file;

      // 2. Set attachment with backend reference
      const reader = new FileReader();
      reader.onload = (event) => {
        setAttachment({
          id: fileRecord.id,
          url: fileRecord.type.startsWith('image/') ? event.target.result : null,
          name: file.name,
          type: file.type
        });
        setIsUploading(false);
      };
      reader.readAsDataURL(file);
    } catch (err) {
      console.error("Upload error:", err);
      alert(err.message || "Failed to upload and index document for RAG.");
      setIsUploading(false);
    }
    e.target.value = null; // Reset input
  };

  const removeAttachment = () => {
    setAttachment(null);
  };

  const handleSend = async (e) => {
    e.preventDefault();
    if (!input.trim() && !attachment) return;

    let activeId = chatId;

    // 1. Create a chat session if none exists (on root page "/")
    if (!activeId) {
      try {
        const res = await fetch('/api/chats', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: input.substring(0, 40) || 'New Chat' })
        });
        if (res.ok) {
          const newChat = await res.json();
          activeId = newChat.id;
          // Programmatically navigate to this chat. Replace state so back button is clean.
          skipNextLoadRef.current = true;
          navigate(`/chat/${activeId}`, { replace: true });
        } else {
          throw new Error('Failed to create chat');
        }
      } catch (err) {
        console.error("Error creating chat session:", err);
        alert("Failed to create chat session on backend.");
        return;
      }
    }

    // Attachment-only sends (no typed text) used to crash with "Failed to
    // retrieve response from server" — backend rejects an empty query string.
    // Default to a sensible prompt instead of sending "".
    const userInput = input.trim() || (attachment ? `Please analyze this document: ${attachment.name}` : input);
    const userAttachment = attachment;

    // Add user message to local state immediately
    const userMessage = { role: 'user', content: userInput, attachment: userAttachment };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setAttachment(null);

    // Add placeholder message for AI streaming response
    setMessages(prev => [...prev, { role: 'ai', content: '', isStreaming: true, isThinking: true, stageLabel: 'Thinking...' }]);

    // Two-tier routing: cheap client-side heuristic (no LLM call, stays free
    // for the fast path) decides whether this prompt needs the full
    // plan->research->reason->review pipeline (1-3min) or the old single-shot
    // endpoint. Comparisons/analysis/long multi-part questions go deep;
    // greetings and short factual asks stay fast. Fast-path budget matches
    // the server's OLLAMA_TIMEOUT_MS (180s) — rag_api can now auto-continue
    // generation across several Ollama round-trips to avoid truncating
    // long/code answers, so the old 65s client timeout fired on healthy responses.
    const useDeepPipeline = isComplexPrompt(userInput);
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), useDeepPipeline ? 240000 : 185000);

    try {
      // 2. Fetch the streaming response — deep pipeline or fast single-shot
      const response = await fetch(useDeepPipeline ? '/api/agent/chat' : `/api/chats/${activeId}/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(useDeepPipeline
          ? { chatId: activeId, message: userInput }
          : { query: userInput, fileId: userAttachment?.id || null }),
        signal: controller.signal
      });

      if (!response.ok) {
        throw new Error('Failed to retrieve response from server.');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let accumulatedText = '';

      while (true) {
        const { value, done } = await reader.read();
        clearTimeout(timeoutId);
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const dataStr = line.slice(6).trim();
            if (dataStr === '[DONE]') {
              break;
            }
            let data;
            try {
              data = JSON.parse(dataStr);
            } catch {
              // Ignore partial chunk JSON parsing errors
              continue;
            }
            if (data.error) {
              throw new Error(data.error);
            }
            {
              // Stage-progress events ({stage, stageLabel}) arrive while the
              // pipeline is still working — update the "Thinking..." label
              // instead of leaving it static for minutes. The final event
              // carries the complete answer (no incremental tokens — the
              // answer doesn't exist until reasoning+review finish).
              if (data.stage) {
                setMessages(prev => {
                  const updated = [...prev];
                  if (updated[updated.length - 1]) {
                    updated[updated.length - 1] = { ...updated[updated.length - 1], stageLabel: data.stageLabel };
                  }
                  return updated;
                });
                continue;
              }
              if (data.text) accumulatedText = data.text;
              setMessages(prev => {
                const updated = [...prev];
                if (updated[updated.length - 1]) {
                  updated[updated.length - 1] = {
                    role: 'ai',
                    content: accumulatedText,
                    isStreaming: true,
                    isThinking: !accumulatedText,
                    sources: data.sources && data.sources.length > 0 ? data.sources : updated[updated.length - 1].sources,
                    confidence: data.confidence || updated[updated.length - 1].confidence,
                    contradictions: data.contradictions || updated[updated.length - 1].contradictions,
                    document: data.document || updated[updated.length - 1].document
                  };
                }
                return updated;
              });
            }
          }
        }
      }

      // Finalize streaming state
      setMessages(prev => {
        const updated = [...prev];
        if (updated[updated.length - 1]) {
          updated[updated.length - 1].isStreaming = false;
        }
        return updated;
      });

    } catch (error) {
      console.error('Chat request failed:', error);
      const message = error.name === 'AbortError'
        ? 'Response timed out. Please try again.'
        : (error.message || 'Unknown error');
      setMessages(prev => {
        const updated = [...prev];
        if (updated[updated.length - 1]) {
          updated[updated.length - 1] = {
            role: 'ai',
            content: `❌ ${message}`
          };
        }
        return updated;
      });
    } finally {
      // Always clear the timer and ensure no message is left stuck on
      // "Thinking..." — covers success, error, and timeout/abort paths.
      clearTimeout(timeoutId);
      setMessages(prev => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last && (last.isThinking || last.isStreaming)) {
          updated[updated.length - 1] = { ...last, isThinking: false, isStreaming: false };
        }
        return updated;
      });
    }
  };

  const QuickActionButton = ({ icon: Icon, label }) => (
    <button className="flex items-center space-x-2 px-4 py-2.5 rounded-full border border-white/10 hover:bg-white/5 text-sm text-zinc-300 font-medium transition-all duration-200">
      <Icon className="w-4 h-4 text-purple-400" />
      <span>{label}</span>
    </button>
  );

  return (
    <div className="flex flex-col h-full bg-[#0B0B0F] text-zinc-100">
      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center max-w-2xl mx-auto w-full space-y-8 animate-fade-in">
            <div className="w-16 h-16 flex items-center justify-center">
              <img src="/logo.png" alt="Nova AI" className="w-full h-full object-contain" />
            </div>
            <h2 className="text-2xl font-semibold text-white tracking-tight">How can I help you today?</h2>
            
            <div className="flex flex-wrap justify-center gap-3 w-full">
              <QuickActionButton 
                icon={(props) => (
                  <svg {...props} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                  </svg>
                )} 
                label="Code" 
              />
              <QuickActionButton 
                icon={(props) => (
                  <svg {...props} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                )} 
                label="Image" 
              />
              <QuickActionButton 
                icon={(props) => (
                  <svg {...props} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                  </svg>
                )} 
                label="Video" 
              />
              <QuickActionButton 
                icon={(props) => (
                  <svg {...props} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 20H5a2 2 0 01-2-2V6a2 2 0 012-2h10a2 2 0 012 2v1m2 13a2 2 0 01-2-2V7m2 13a2 2 0 002-2V9.5a2.5 2.5 0 00-2.5-2.5H15" />
                  </svg>
                )} 
                label="Research" 
              />
              <QuickActionButton 
                icon={(props) => (
                  <svg {...props} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                )} 
                label="Documents" 
              />
            </div>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto w-full space-y-6 pb-20">
            {messages.map((msg, idx) => (
              <div key={idx} className={`flex gap-4 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
                {/* Avatar */}
                <div className={`w-8 h-8 flex-shrink-0 rounded-md flex items-center justify-center font-bold text-[10px]
                  ${msg.role === 'user' ? 'bg-zinc-800 text-white' : ''}`}>
                  {msg.role === 'user' ? 'YOU' : <img src="/logo.png" alt="Nova AI" className="w-full h-full object-contain rounded-md" />}
                </div>
                
                {/* Message Bubble */}
                <div className={`max-w-[80%] rounded-2xl px-5 py-3.5 shadow-sm ${
                  msg.role === 'user' 
                    ? 'bg-zinc-800/80 border border-white/5 text-zinc-100' 
                    : 'bg-transparent text-zinc-100'
                }`}>
                  {msg.attachment && (
                    <div className="mb-3">
                      {msg.attachment.type?.startsWith('image/') || msg.attachment.url ? (
                        <img 
                          src={msg.attachment.url || '/logo.png'} 
                          alt="Uploaded attachment" 
                          className="max-w-xs rounded-lg border border-white/10" 
                        />
                      ) : (
                        <div className="flex items-center space-x-3 p-3 bg-white/5 border border-white/10 rounded-lg max-w-xs">
                          <svg className="w-6 h-6 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                          </svg>
                          <span className="text-sm font-medium truncate">{msg.attachment.name || 'Document'}</span>
                        </div>
                      )}
                    </div>
                  )}
                  {msg.isThinking ? (
                    <div className="flex items-center gap-2 py-1">
                      <img src="/logo.png" alt="" className="w-6 h-6 object-contain animate-nova-thinking" />
                      <span className="text-sm text-zinc-400 animate-pulse">
                        {msg.stageLabel || 'Thinking...'}
                      </span>
                    </div>
                  ) : (
                    <>
                      {msg.document ? (
                        <DocumentCard {...msg.document} />
                      ) : msg.imageAnalysis ? (
                        <ImageAnalysisPanel {...msg.imageAnalysis} confidence={msg.confidence} />
                      ) : (
                        msg.content && <MessageContent content={msg.content} />
                      )}
                      {msg.sources && msg.sources.length > 0 && (
                        <div className="mt-3 pt-3 border-t border-white/10">
                          <div className="flex items-center justify-between mb-2">
                            <p className="text-xs font-medium text-zinc-500">Sources</p>
                            {/* Confidence now comes from the Review stage's LLM critique of the
                                final answer against all gathered evidence, not just doc-match score. */}
                            <ConfidenceBadge confidence={msg.confidence} />
                          </div>
                          {msg.contradictions && msg.contradictions.length > 0 && (
                            <p className="text-[11px] text-amber-400/90 mb-2">
                              ⚠ Sources disagree: {msg.contradictions.map(c => `${c.sourceA} vs ${c.sourceB}`).join(', ')}
                            </p>
                          )}
                          <div className="flex flex-wrap gap-2">
                            {msg.sources.map((s, i) => <SourceCard key={i} source={s} />)}
                          </div>
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input Area */}
      <div className="p-4 bg-gradient-to-t from-[#0B0B0F] via-[#0B0B0F] to-transparent">
        <div className="max-w-3xl mx-auto relative">
          
          {/* Attachment Preview Container */}
          {attachment && (
            <div className="mb-3 p-2 bg-zinc-800/80 border border-white/10 rounded-xl inline-flex items-start gap-3 shadow-lg backdrop-blur-md">
              <div className="relative group">
                {attachment.type?.startsWith('image/') ? (
                  <img src={attachment.url} alt="Preview" className="w-14 h-14 object-cover rounded-lg border border-white/10" />
                ) : (
                  <div className="w-14 h-14 bg-zinc-700 rounded-lg flex items-center justify-center border border-white/10">
                    <svg className="w-6 h-6 text-zinc-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
                    </svg>
                  </div>
                )}
                <button 
                  onClick={removeAttachment}
                  className="absolute -top-2 -right-2 bg-zinc-700 hover:bg-zinc-600 rounded-full p-1 text-zinc-200 transition-colors shadow-md border border-white/10"
                >
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <div className="flex flex-col justify-center h-14 pr-2">
                <span className="text-xs font-medium text-zinc-200 truncate max-w-[150px]">{attachment.name}</span>
                <span className="text-[10px] text-zinc-400">{attachment.type?.startsWith('image/') ? 'Image' : 'Document'}</span>
              </div>
            </div>
          )}

          {isUploading && (
            <div className="mb-3 p-2.5 bg-zinc-800/80 border border-white/10 rounded-xl inline-flex items-center gap-3 shadow-lg backdrop-blur-md">
              <div className="w-5 h-5 border-2 border-purple-500 border-t-transparent rounded-full animate-spin"></div>
              <span className="text-xs text-zinc-300">Uploading and indexing document for RAG...</span>
            </div>
          )}

          <form onSubmit={handleSend} className="relative flex items-end bg-zinc-800/50 border border-white/10 rounded-2xl shadow-lg backdrop-blur-md transition-all focus-within:border-white/20 focus-within:bg-zinc-800/80">
            <input 
              type="file" 
              accept="image/*,.pdf,.doc,.docx,.txt" 
              ref={fileInputRef}
              onChange={handleFileChange}
              className="hidden"
            />
            
            {/* Attachment Button */}
            <button 
              type="button" 
              disabled={isUploading}
              onClick={() => fileInputRef.current?.click()}
              className="p-3 text-zinc-400 hover:text-white transition-colors m-1 rounded-xl hover:bg-white/5 disabled:opacity-30"
              title="Upload file"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
              </svg>
            </button>
            
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSend(e);
                }
              }}
              placeholder={attachment ? "Ask about this file..." : "Message Nova AI..."}
              className="w-full bg-transparent border-0 pl-1 pr-2 py-4 text-[15px] text-white placeholder-zinc-500 outline-none resize-none max-h-32 min-h-[56px]"
              rows={1}
            />

            <div className="flex items-center p-2 m-1">
              {/* Voice Placeholder */}
              <button 
                type="button" 
                className="p-2 text-zinc-400 hover:text-white transition-colors rounded-xl hover:bg-white/5 mr-1"
                title="Voice input"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                </svg>
              </button>
              
              {/* Send Button */}
              <button 
                type="submit"
                disabled={(!input.trim() && !attachment) || isUploading}
                className="p-2 rounded-xl bg-white text-black disabled:opacity-30 disabled:bg-zinc-700 disabled:text-zinc-500 transition-colors"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 10l7-7m0 0l7 7m-7-7v18" />
                </svg>
              </button>
            </div>
          </form>
          <div className="text-center mt-3">
            <span className="text-[11px] text-zinc-500">Nova AI can make mistakes. Consider verifying important information.</span>
          </div>
        </div>
      </div>
    </div>
  );
}
