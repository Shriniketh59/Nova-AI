import { useEffect, useMemo, useState } from 'react';
import { NavLink, useNavigate, useParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';
import { relativeTime } from '../utils/time';
import { csrfHeaders } from '../utils/csrf';

export default function Sidebar({ onLogout, mobileOpen = false, onCloseMobile }) {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const [chatHistory, setChatHistory] = useState([]);
  const [search, setSearch] = useState('');
  const { chatId: activeChatId } = useParams();
  const navigate = useNavigate();

  const handleLogout = async () => {
    if (onLogout) {
      await onLogout();
    } else {
      await logout();
      navigate('/login');
    }
  };

  const displayName = user?.name || (user?.email ? user.email.split('@')[0] : 'User');
  const initials = displayName
    .split(' ')
    .map((p) => p[0])
    .join('')
    .slice(0, 2)
    .toUpperCase() || 'U';

  const fetchChats = async () => {
    try {
      const res = await fetch('/api/chats', { credentials: 'include' });
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

  const filteredChats = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return chatHistory;
    return chatHistory.filter((c) => (c.title || '').toLowerCase().includes(q));
  }, [chatHistory, search]);

  const goToChat = (id) => {
    navigate(`/chat/${id}`);
    onCloseMobile?.();
  };

  const sidebarContent = (
    <>
      {/* Top area: New Chat button */}
      <div className="p-3">
        <NavLink
          to="/"
          onClick={() => onCloseMobile?.()}
          className="flex items-center space-x-3 w-full bg-white/5 hover:bg-white/10 text-zinc-100 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors duration-200"
        >
          <img src="/logo.png" alt="Nova AI" className="w-6 h-6 object-contain rounded-md" />
          <span>New chat</span>
          <svg className="w-4 h-4 ml-auto text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
        </NavLink>
      </div>

      {/* Search / filter */}
      <div className="px-3 pb-2">
        <div className="relative">
          <svg className="w-4 h-4 text-zinc-500 absolute left-2.5 top-1/2 -translate-y-1/2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M17 10a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search chats..."
            className="w-full bg-white/5 border border-white/10 rounded-lg pl-8 pr-2.5 py-1.5 text-xs text-zinc-200 placeholder-zinc-500 outline-none focus:border-purple-500/40 focus:bg-white/[0.08] transition-colors"
          />
        </div>
      </div>

      {/* Scrollable history area */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1">
        {filteredChats.length > 0 ? (
          filteredChats.map((chat) => (
            <div
              key={chat.id}
              className={`group flex items-center justify-between w-full px-3 py-2.5 rounded-lg text-sm transition-colors ${
                chat.id === activeChatId
                  ? 'bg-white/10 text-white font-medium'
                  : 'text-zinc-400 hover:bg-white/5 hover:text-zinc-200'
              }`}
            >
              <button
                onClick={() => goToChat(chat.id)}
                className="flex-1 min-w-0 text-left outline-none"
              >
                <span className="block truncate">{chat.title}</span>
                {(chat.updated_at || chat.created_at) && (
                  <span className="block text-[10px] text-zinc-500 mt-0.5">
                    {relativeTime(chat.updated_at || chat.created_at)}
                  </span>
                )}
              </button>

              <button
                onClick={async (e) => {
                  e.stopPropagation();
                  if (confirm(`Delete chat "${chat.title}"?`)) {
                    try {
                      const res = await fetch(`/api/chats/${chat.id}`, {
                        method: 'DELETE',
                        headers: csrfHeaders(),
                        credentials: 'include',
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
                className="opacity-0 group-hover:opacity-100 p-1 text-zinc-500 hover:text-rose-400 rounded transition-opacity flex-shrink-0"
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
            {search ? 'No matching chats' : 'No previous chats'}
          </div>
        )}
      </div>

      {/* Bottom area: User & Settings */}
      <div className="p-3 flex flex-col space-y-1 mt-auto">
        <NavLink
          to="/coach"
          onClick={() => onCloseMobile?.()}
          className="flex items-center space-x-3 w-full hover:bg-white/5 text-zinc-300 px-3 py-2.5 rounded-lg text-sm transition-colors"
        >
          <svg className="w-4 h-4 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 17L4.5 12l5.25-5m4.5 0L19.5 12l-5.25 5" />
          </svg>
          <span>Interview Coach</span>
        </NavLink>

        <NavLink
          to="/settings"
          onClick={() => onCloseMobile?.()}
          className="flex items-center space-x-3 w-full hover:bg-white/5 text-zinc-300 px-3 py-2.5 rounded-lg text-sm transition-colors"
        >
          <svg className="w-4 h-4 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          <span>Settings</span>
        </NavLink>

        <button
          type="button"
          onClick={toggleTheme}
          className="flex items-center space-x-3 w-full hover:bg-white/5 text-zinc-300 px-3 py-2.5 rounded-lg text-sm transition-colors"
        >
          {theme === 'dark' ? (
            <svg className="w-4 h-4 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
            </svg>
          ) : (
            <svg className="w-4 h-4 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
            </svg>
          )}
          <span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>
        </button>

        <div
          className="flex items-center space-x-3 px-3 py-2 mt-1 rounded-lg hover:bg-white/5 cursor-pointer transition-colors group"
          onClick={handleLogout}
          title="Sign out"
        >
          {user?.profile_image ? (
            <img src={user.profile_image} alt={displayName} className="w-7 h-7 rounded-full object-cover border border-white/10" />
          ) : (
            <div className="w-7 h-7 rounded-full bg-gradient-to-tr from-violet-600 to-fuchsia-600 border border-white/10 flex items-center justify-center text-[10px] font-bold text-white shadow-sm">
              {initials}
            </div>
          )}
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-white truncate">{displayName}</p>
            <p className="text-[10px] text-zinc-500 truncate">{user?.email || ''}</p>
          </div>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              handleLogout();
            }}
            className="text-zinc-500 group-hover:text-rose-400 transition-colors p-1"
            title="Sign out"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
          </button>
        </div>
      </div>
    </>
  );

  return (
    <>
      {/* Desktop: persistent sidebar */}
      <aside className="w-64 nova-surface bg-[#0B0B0F] border-r border-white/5 flex-col h-screen text-zinc-300 flex-shrink-0 hidden md:flex transition-all duration-300">
        {sidebarContent}
      </aside>

      {/* Mobile: drawer + overlay */}
      {mobileOpen && (
        <div className="md:hidden fixed inset-0 z-40 flex">
          <div
            className="fixed inset-0 bg-black/60 backdrop-blur-sm"
            onClick={onCloseMobile}
            aria-hidden="true"
          />
          <aside className="relative z-50 w-72 max-w-[85vw] nova-surface bg-[#0B0B0F] border-r border-white/5 flex flex-col h-full text-zinc-300 shadow-2xl animate-fade-in">
            <div className="flex items-center justify-end px-2 pt-2">
              <button
                type="button"
                onClick={onCloseMobile}
                className="p-2 rounded-lg hover:bg-white/10 text-zinc-300"
                aria-label="Close sidebar"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            {sidebarContent}
          </aside>
        </div>
      )}
    </>
  );
}
