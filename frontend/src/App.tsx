import React, { useState, useEffect } from 'react';
import { Navbar } from './components/Navbar';
import { Footer } from './components/Footer';
import { LandingPage } from './pages/LandingPage';
import { SessionPage } from './pages/SessionPage';

export const App: React.FC = () => {
  const [currentPath, setCurrentPath] = useState<string>(
    window.location.pathname === '/session' ? '/session' : '/'
  );
  const [modeBadge, setModeBadge] = useState<string>('connecting…');

  useEffect(() => {
    const onPopState = () => {
      setCurrentPath(window.location.pathname === '/session' ? '/session' : '/');
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  const navigate = (path: string) => {
    window.history.pushState({}, '', path);
    setCurrentPath(path);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  return (
    <div className="flex flex-col min-h-screen bg-[#08080a] text-[#fafafa]">
      <Navbar currentPath={currentPath} onNavigate={navigate} statusBadge={modeBadge} />

      <main className="flex-1 flex flex-col">
        {currentPath === '/session' ? (
          <SessionPage setModeBadge={setModeBadge} />
        ) : (
          <LandingPage onNavigate={navigate} />
        )}
      </main>

      {currentPath !== '/session' && <Footer />}
    </div>
  );
};

export default App;

