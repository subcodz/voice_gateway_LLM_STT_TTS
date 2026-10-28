"""LLM adapter supporting tiered Groq models and Gemini fallback.

Why this module exists:
Implements the intelligence layer of the gateway. It routes standard queries to a fast,
low-latency model (Groq fast tier), escalates complex or failed requests to a heavy model,
and falls back seamlessly to Gemini Flash if Groq hits 429 or timeout limits.
All outputs are strictly sanitized to ensure speech-ready plain text without markdown or emojis.
"""

import re
from typing import List, Optional
import httpx

from app.adapters.models import Msg


SYSTEM_PROMPT = (
    "You are a helpline agent for a fictional Kolkata power utility; "
    "answer in the caller's language (Hindi, Bengali or Hinglish/Benglish); "
    "at most two short sentences; plain text only, no markdown, no emoji, "
    "no symbols; never invent account data."
)


def sanitize_speech_text(text: str) -> str:
    """Strips markdown styling, bullet points, asterisks, emojis, and unwanted symbols.
    
    Ensures that TTS synthesis does not vocalize asterisks, hashes, or bullet marks.
    """
    # Remove markdown links [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # Remove markdown bold/italics
    text = re.sub(r'[*_~`#]', '', text)
    # Remove leading bullets or dashes
    text = re.sub(r'^\s*[-•*]\s+', '', text, flags=re.MULTILINE)
    # Remove emojis (surrogates and standard unicode emoji blocks)
    emoji_pattern = re.compile(
        "[\U00010000-\U0010ffff"
        "\u2600-\u26ff"
        "\u2700-\u27bf"
        "\ufe00-\ufe0f"
        "\u1f300-\u1f9ff]+",
        flags=re.UNICODE
    )
    text = emoji_pattern.sub('', text)
    # Normalize excessive whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


class LlmAdapter:
    def __init__(
        self,
        groq_api_key: str = "",
        gemini_api_key: str = "",
        groq_fast_model: str = "llama-3.1-8b-instant",
        groq_heavy_model: str = "llama-3.3-70b-versatile",
        gemini_model: str = "gemini-2.5-flash",
        client: Optional[httpx.AsyncClient] = None
    ):
        self.groq_api_key = groq_api_key
        self.gemini_api_key = gemini_api_key
        self.groq_fast_model = groq_fast_model
        self.groq_heavy_model = groq_heavy_model
        self.gemini_model = gemini_model
        self.client = client or httpx.AsyncClient(timeout=30.0)

    async def _call_groq(self, history: List[Msg], model: str) -> str:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for m in history:
            messages.append({"role": m.role, "content": m.content})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 150
        }
        r = await self.client.post(url, headers=headers, json=payload, timeout=20.0)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]

    async def _call_gemini_fallback(self, history: List[Msg]) -> str:
        """Fallback to Google Gemini REST API on Groq 429 or timeout."""
        if not self.gemini_api_key:
            raise RuntimeError("Gemini API key is not configured for fallback.")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent?key={self.gemini_api_key}"
        contents = []
        for m in history:
            role = "model" if m.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m.content}]})

        payload = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 150}
        }
        r = await self.client.post(url, json=payload, timeout=20.0)
        r.raise_for_status()
        data = r.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return "ধন্যবাদ, আমি আপনার অনুরোধ প্রক্রিয়া করছি।"
        return candidates[0]["content"]["parts"][0]["text"]

    async def reply(self, history: List[Msg], tier: str = "fast") -> str:
        """Requests conversational reply across Fast, Heavy, or Gemini Fallback tiers."""
        model = self.groq_fast_model if tier == "fast" else self.groq_heavy_model

        if self.groq_api_key:
            try:
                raw_text = await self._call_groq(history, model)
                return sanitize_speech_text(raw_text)
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                # If fast tier fails, try heavy tier before falling back to Gemini
                if tier == "fast":
                    try:
                        raw_text = await self._call_groq(history, self.groq_heavy_model)
                        return sanitize_speech_text(raw_text)
                    except Exception:
                        pass
                # Groq failed; attempt Gemini fallback
                if self.gemini_api_key:
                    raw_text = await self._call_gemini_fallback(history)
                    return sanitize_speech_text(raw_text)
                raise
        elif self.gemini_api_key:
            raw_text = await self._call_gemini_fallback(history)
            return sanitize_speech_text(raw_text)
        else:
            raise RuntimeError("No LLM API keys configured (neither GROQ_API_KEY nor GEMINI_API_KEY).")
