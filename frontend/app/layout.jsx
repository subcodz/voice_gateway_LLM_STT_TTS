import './globals.css';

export const metadata = {
  title: 'Gnani Voice Gateway | Audio Caching & Semantic Acceleration',
  description: 'Enterprise voice gateway layer removing repeated STT, LLM, and TTS work via semantic caching and exact audio reuse.',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body className="dark-theme">{children}</body>
    </html>
  );
}
