"""Audio stream teeing mechanism for simultaneous streaming and cache population.

Why this module exists:
Achieves minimal Time-To-First-Audio (TTFA) by forwarding incoming audio chunks to the
client WebSocket as fast as they arrive, while buffering them in memory in parallel.
Once the stream finishes cleanly, it runs WAV header repair and commits the full clip
to the audio cache store.
"""

import asyncio
from typing import AsyncIterator, Callable, Optional
from app.audio import fix_wav_header
from app.cache.audio_store import AudioStore


async def tee_stream(
    stream: AsyncIterator[bytes],
    cache_store: AudioStore,
    key: str,
    finish_on_disconnect: bool = True,
    on_commit: Optional[Callable[[str, bytes], None]] = None
) -> AsyncIterator[bytes]:
    """Forwards audio chunks to the caller while accumulating them.
    
    On clean completion, repairs the WAV header and commits the audio to cache_store.
    If the caller disconnects (CancelledError), either finishes synthesis in background
    (if finish_on_disconnect is True) or abandons it.
    """
    accumulated = []
    completed = False

    try:
        async for chunk in stream:
            accumulated.append(chunk)
            yield chunk
        full_audio = b"".join(accumulated)
        if full_audio:
            repaired = fix_wav_header(full_audio)
            await asyncio.to_thread(cache_store.put, key, repaired)
            if on_commit:
                on_commit(key, repaired)
    except asyncio.CancelledError:
        if finish_on_disconnect:
            # Drain remaining chunks in background task to warm cache for followers
            async def _drain_and_cache(remainder_stream, buffered):
                try:
                    async for c in remainder_stream:
                        buffered.append(c)
                    full = b"".join(buffered)
                    if full:
                        repaired = fix_wav_header(full)
                        cache_store.put(key, repaired)
                        if on_commit:
                            on_commit(key, repaired)
                except Exception:
                    pass

            asyncio.create_task(_drain_and_cache(stream, accumulated))
        raise
