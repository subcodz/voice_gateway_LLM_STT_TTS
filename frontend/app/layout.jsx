import './globals.css';

export const metadata = {
  title: 'Gnani Voice Gateway | Audio Caching & Semantic Acceleration',
  description: 'Enterprise voice gateway layer removing repeated STT, LLM, and TTS work via semantic caching and exact audio reuse.',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Noto+Sans+Bengali:wght@400;500;600;700&family=Noto+Sans+Devanagari:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="dark-theme">{children}</body>
    </html>
  );
}
