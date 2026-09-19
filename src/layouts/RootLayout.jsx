import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from '../components/Sidebar';

export default function RootLayout({ onLogout }) {
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  return (
    <div className="flex nova-surface bg-zinc-900 text-zinc-100 h-screen font-sans antialiased overflow-hidden">
      {/* Sidebar navigation */}
      <Sidebar
        onLogout={onLogout}
        mobileOpen={mobileSidebarOpen}
        onCloseMobile={() => setMobileSidebarOpen(false)}
      />

      {/* Main body area - full height, no padding because Chat handles it */}
      <main className="flex-1 flex flex-col h-screen overflow-hidden relative">
        {/* Mobile top bar with hamburger toggle — sidebar is a drawer below md */}
        <div className="md:hidden flex items-center gap-3 px-3 py-2.5 border-b border-white/5 nova-surface bg-[#0B0B0F] flex-shrink-0">
          <button
            type="button"
            onClick={() => setMobileSidebarOpen(true)}
            className="p-2 rounded-lg hover:bg-white/10 text-zinc-200"
            aria-label="Open sidebar"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <img src="/logo.png" alt="Nova AI" className="w-6 h-6 object-contain rounded-md" />
          <span className="font-semibold text-sm text-zinc-100">Nova AI</span>
        </div>
        <Outlet />
      </main>
    </div>
  );
}
