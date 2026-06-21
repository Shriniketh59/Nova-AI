import { Outlet } from 'react-router-dom';
import Sidebar from '../components/Sidebar';

export default function RootLayout({ onLogout }) {
  return (
    <div className="flex bg-zinc-900 text-zinc-100 h-screen font-sans antialiased overflow-hidden">
      {/* Sidebar navigation */}
      <Sidebar onLogout={onLogout} />

      {/* Main body area - full height, no padding because Chat handles it */}
      <main className="flex-1 flex flex-col h-screen overflow-hidden relative">
        <Outlet />
      </main>
    </div>
  );
}
