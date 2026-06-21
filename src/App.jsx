import { useState } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import RootLayout from './layouts/RootLayout';
import Chat from './pages/Chat';
import Settings from './pages/Settings';
import Login from './pages/Login';

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(() => {
    return localStorage.getItem('nova_auth') === 'true';
  });

  const login = () => {
    localStorage.setItem('nova_auth', 'true');
    setIsAuthenticated(true);
  };

  const logout = () => {
    localStorage.removeItem('nova_auth');
    setIsAuthenticated(false);
  };

  return (
    <BrowserRouter>
      <Routes>
        <Route 
          path="/login" 
          element={<Login onLogin={login} isAuthenticated={isAuthenticated} />} 
        />
        <Route 
          path="/" 
          element={isAuthenticated ? <RootLayout onLogout={logout} /> : <Navigate to="/login" replace />}
        >
          <Route index element={<Chat />} />
          <Route path="chat/:chatId" element={<Chat />} />
          <Route path="settings" element={<Settings />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
