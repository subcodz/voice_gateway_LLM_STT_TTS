"""Single-flight request coalescing for concurrent uncached audio synthesis.

Why this module exists:
Prevents cache stampedes when multiple incoming calls request the same uncached phrase
simultaneously. A single leader performs upstream synthesis while concurrent followers
stream chunks directly from the leader's live memory buffer as they arrive, saving both
latency and expensive API characters.
"""

import asyncio
from typing import AsyncIterator, Callable, Dict, List, Optional


class FlightEntry:
    def __init__(self):
        self.chunks: List[bytes] = []
        self.event = asyncio.Event()
        self.is_done = False
        self.error: Optional[Exception] = None
        self.followers_count = 0


class SingleFlight:
    def __init__(self):
        self._flights: Dict[str, FlightEntry] = {}
        self._lock = asyncio.Lock()

    async def execute_or_follow(
        self,
        key: str,
        stream_fn: Callable[[], AsyncIterator[bytes]]
    ) -> AsyncIterator[bytes]:
        """Executes the stream as a leader if key is not in-flight; otherwise follows the leader.
        
        Followers stream chunks from the leader's buffer as they arrive. If leader fails,
        follower falls back to calling stream_fn directly.
        """
        async with self._lock:
            if key in self._flights:
                flight = self._flights[key]
                flight.followers_count += 1
                is_leader = False
            else:
                flight = FlightEntry()
                self._flights[key] = flight
                is_leader = True

        if is_leader:
            try:
                async for chunk in stream_fn():
                    flight.chunks.append(chunk)
                    flight.event.set()
                    flight.event.clear()
                    yield chunk
                flight.is_done = True
                flight.event.set()
            except Exception as e:
                flight.error = e
                flight.is_done = True
                flight.event.set()
                raise
            finally:
                async with self._lock:
                    self._flights.pop(key, None)
        else:
            # Follower path: read chunks from flight by offset
            offset = 0
            retried_directly = False
            try:
                while True:
                    while offset < len(flight.chunks):
                        chunk = flight.chunks[offset]
                        offset += 1
                        yield chunk

                    if flight.is_done:
                        if flight.error and not retried_directly:
                            # Leader failed; follower retries directly once
                            retried_directly = True
                            async for chunk in stream_fn():
                                yield chunk
                        break

                    # Wait for next chunk from leader
                    await flight.event.wait()
            except Exception:
                # If following fails for any reason, try direct stream fallback
                if not retried_directly:
                    async for chunk in stream_fn():
                        yield chunk
