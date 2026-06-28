import { useState, useEffect } from 'react';
import { NavLink, useNavigate, useParams } from 'react-router-dom';

export default function Sidebar({ onLogout }) {
  const [chatHistory, setChatHistory] = useState([]);
  const { chatId: activeChatId } = useParams();
  const navigate = useNavigate();

  const fetchChats = async () => {
    try {
      const res = await fetch('/api/chats');
      if (res.ok) {
        const data = await res.json();
        setChatHistory(data);
      }
    } catch (err) {
      console.error("Error fetching chats in sidebar:", err);
    }
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchChats();
  }, [activeChatId]);

  return (
    <aside className="w-64 bg-[#0B0B0F] border-r border-white/5 flex flex-col h-screen text-zinc-300 flex-shrink-0 hidden md:flex transition-all duration-300">
      {/* Top area: New Chat button */}
      <div className="p-3">
        <NavLink
          to="/"
          className="flex items-center space-x-3 w-full bg-white/5 hover:bg-white/10 text-zinc-100 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors duration-200"
        >
          <img src="/logo.png" alt="Nova AI" className="w-6 h-6 object-contain rounded-md" />
          <span>New chat</span>
          <svg className="w-4 h-4 ml-auto text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
        </NavLink>
      </div>

      {/* Scrollable history area */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1">
        {chatHistory.length > 0 ? (
          chatHistory.map((chat) => (
            <div
              key={chat.id}
              className={`group flex items-center justify-between w-full px-3 py-2.5 rounded-lg text-sm transition-colors ${
                chat.id === activeChatId
                  ? 'bg-white/10 text-white font-medium'
                  : 'text-zinc-400 hover:bg-white/5 hover:text-zinc-200'
              }`}
            >
              <button
                onClick={() => navigate(`/chat/${chat.id}`)}
                className="flex-1 text-left truncate pr-2 outline-none"
              >
                {chat.title}
              </button>

              <button
                onClick={async (e) => {
                  e.stopPropagation();
                  if (confirm(`Delete chat "${chat.title}"?`)) {
                    try {
                      const res = await fetch(`/api/chats/${chat.id}`, {
                        method: 'DELETE'
                      });
                      if (res.ok) {
                        fetchChats();
                        if (activeChatId === chat.id) {
                          navigate('/');
                        }
                      }
                    } catch (err) {
                      console.error("Error deleting chat:", err);
                    }
                  }
                }}
                className="opacity-0 group-hover:opacity-100 p-1 text-zinc-500 hover:text-rose-400 rounded transition-opacity"
                title="Delete Chat"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            </div>
          ))
        ) : (
          <div className="px-2 py-4 text-xs font-medium text-zinc-500 text-center">
            No previous chats
          </div>
        )}
      </div>

      {/* Bottom area: User & Settings */}
      <div className="p-3 flex flex-col space-y-1 mt-auto">
        <NavLink
          to="/settings"
          className="flex items-center space-x-3 w-full hover:bg-white/5 text-zinc-300 px-3 py-2.5 rounded-lg text-sm transition-colors"
        >
          <svg className="w-4 h-4 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          <span>Settings</span>
        </NavLink>

        <div className="flex items-center space-x-3 px-3 py-2 mt-1 rounded-lg hover:bg-white/5 cursor-pointer transition-colors" onClick={onLogout}>
          <div className="w-7 h-7 rounded-full bg-zinc-800 border border-white/10 flex items-center justify-center text-[10px] font-semibold text-white">
            JD
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-white truncate">Dr. John Doe</p>
          </div>
          <svg className="w-4 h-4 text-zinc-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
          </svg>
        </div>
      </div>
    </aside>
  );
}
