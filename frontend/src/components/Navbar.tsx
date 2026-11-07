import React from 'react';

interface NavbarProps {
  currentPath: string;
  onNavigate: (path: string) => void;
  statusBadge?: string;
}

export const Navbar: React.FC<NavbarProps> = ({ currentPath, onNavigate, statusBadge }) => {
  const isSession = currentPath === '/session';

  const scrollToSection = (e: React.MouseEvent<HTMLAnchorElement>, id: string) => {
    e.preventDefault();
    if (currentPath !== '/') {
      onNavigate('/');
      setTimeout(() => {
        const el = document.getElementById(id);
        el?.scrollIntoView({ behavior: 'smooth' });
      }, 60);
    } else {
      const el = document.getElementById(id);
      el?.scrollIntoView({ behavior: 'smooth' });
    }
  };

  return (
    <nav className="sticky top-0 z-50 bg-[#08080a]/80 backdrop-blur-md border-b border-white/[0.09]">
      <div className="max-w-[1120px] mx-auto px-6 h-[60px] flex items-center justify-between">
        <a
          href="/"
          onClick={(e) => {
            e.preventDefault();
            onNavigate('/');
          }}
          className="flex items-center gap-2.5 font-semibold tracking-tight text-white hover:opacity-90 transition-opacity"
        >
          <img src="/static/icon.svg" alt="CacheBuddy" className="w-7 h-7 object-contain block" />
          <span>CacheBuddy</span>
        </a>

        {!isSession ? (
          <div className="hidden md:flex items-center gap-2 text-sm text-zinc-400">
            <a
              href="#features"
              onClick={(e) => scrollToSection(e, 'features')}
              className="relative px-3.5 py-1.5 transition-colors group flex items-center justify-center hover:text-white"
            >
              <span className="absolute inset-0 bg-[#1D222B]/90 rounded-md -z-10 border border-neutral-600/75 inset-shadow-md inset-shadow-gray-600/60 opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none" />
              <span>Features</span>
            </a>
            <a
              href="#architecture"
              onClick={(e) => scrollToSection(e, 'architecture')}
              className="relative px-3.5 py-1.5 transition-colors group flex items-center justify-center hover:text-white"
            >
              <span className="absolute inset-0 bg-[#1D222B]/90 rounded-md -z-10 border border-neutral-600/75 inset-shadow-md inset-shadow-gray-600/60 opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none" />
              <span>Architecture</span>
            </a>
            <a
              href="#stack"
              onClick={(e) => scrollToSection(e, 'stack')}
              className="relative px-3.5 py-1.5 transition-colors group flex items-center justify-center hover:text-white"
            >
              <span className="absolute inset-0 bg-[#1D222B]/90 rounded-md -z-10 border border-neutral-600/75 inset-shadow-md inset-shadow-gray-600/60 opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none" />
              <span>Technology</span>
            </a>
          </div>
        ) : (
          <div className="hidden md:flex items-center gap-3">
            <span className="text-xs font-mono text-zinc-400">Mode:</span>
            <span className="text-xs font-mono px-2.5 py-1 rounded bg-zinc-800/80 border border-white/10 text-zinc-200">
              {statusBadge || 'connecting…'}
            </span>
          </div>
        )}

        <div className="flex items-center gap-3">
          <a
            href="https://github.com/subcodz/voice_gateway_LLM_STT_TTS"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="GitHub Repository"
            className="p-2 text-zinc-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors flex items-center justify-center"
          >
            <svg
              className="w-5 h-5 fill-current"
              viewBox="0 0 24 24"
              role="img"
              aria-hidden="true"
            >
              <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
              />
            </svg>
          </a>

          {isSession ? (
            <button
              onClick={() => onNavigate('/')}
              className="text-xs md:text-sm font-medium px-4 py-2 rounded-lg border border-white/20 bg-transparent text-white hover:bg-white/10 transition-colors"
            >
              Overview
            </button>
          ) : (
            <button
              onClick={() => onNavigate('/session')}
              className="text-xs md:text-sm font-medium px-4 py-2 rounded-lg bg-white text-black hover:bg-zinc-200 inset-shadow-md transition-colors font-medium"
            >
              Open live demo
            </button>
          )}
        </div>
      </div>
    </nav>
  );
};
