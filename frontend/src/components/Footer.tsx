import React from 'react';

export const Footer: React.FC = () => {
  return (
    <footer className="border-t border-white/[0.09] py-8 text-xs text-zinc-400 mt-auto">
      <div className="max-w-[1120px] mx-auto px-6 flex flex-wrap justify-between items-center gap-4">
        <span>© 2026 CacheBuddy – Voice Gateway</span>
        <span>Built on Gnani speech APIs · Indic Voice Accelerator</span>
      </div>
    </footer>
  );
};

