"""Multi-tier audio storage (L1 memory LRU + L2 atomic disk store) with byte limits.

Why this module exists:
Delivers sub-millisecond audio retrieval for cached clips. The L1 memory cache
serves hot responses instantly without disk I/O, while the L2 disk cache persists
clips across server restarts. Writes use temporary files and atomic rename operations
to guarantee that partial or interrupted clips never contaminate the cache.
"""

from collections import OrderedDict
import os
import shutil
import tempfile
import threading
import time
from typing import Optional


class AudioStore:
    def __init__(
        self,
        cache_dir: str = "audio_cache",
        l1_max_bytes: int = 64 * 1024 * 1024,   # 64 MB
        l2_max_bytes: int = 256 * 1024 * 1024  # 256 MB
    ):
        self.cache_dir = cache_dir
        self.l1_max_bytes = l1_max_bytes
        self.l2_max_bytes = l2_max_bytes
        self._lock = threading.Lock()

        # L1 In-Memory LRU: key -> bytes
        self._l1_cache: OrderedDict[str, bytes] = OrderedDict()
        self._l1_current_bytes: int = 0

        # L2 Disk Tracking: key -> (filepath, size, last_accessed)
        self._l2_meta: dict[str, dict] = {}
        self._l2_current_bytes: int = 0

        os.makedirs(self.cache_dir, exist_ok=True)
        self._scan_disk()

    def _scan_disk(self):
        """Scans the disk cache directory at startup to discover pre-seeded clips."""
        total = 0
        for entry in os.scandir(self.cache_dir):
            if entry.is_file() and entry.name.endswith(".wav"):
                key = entry.name[:-4]
                size = entry.stat().st_size
                mtime = entry.stat().st_mtime
                self._l2_meta[key] = {"path": entry.path, "size": size, "mtime": mtime}
                total += size
        self._l2_current_bytes = total
        self._evict_l2_if_needed()

    def get(self, key: str) -> Optional[bytes]:
        """Retrieves audio bytes from L1 memory or L2 disk. Returns None on cache miss."""
        with self._lock:
            # Check L1 memory cache first
            if key in self._l1_cache:
                self._l1_cache.move_to_end(key)
                return self._l1_cache[key]

            # Check L2 disk cache
            if key in self._l2_meta:
                meta = self._l2_meta[key]
                path = meta["path"]
                try:
                    with open(path, "rb") as f:
                        data = f.read()

                    # Update LRU metadata
                    meta["mtime"] = time.time()
                    try:
                        os.utime(path, None)
                    except OSError:
                        pass

                    # Promote to L1 memory cache
                    self._put_l1(key, data)
                    return data
                except (OSError, IOError):
                    # Graceful degradation on disk read error: treat as miss
                    self._l2_meta.pop(key, None)
                    return None

            return None

    def put(self, key: str, wav_bytes: bytes):
        """Atomically commits non-empty audio into L1 memory and L2 disk caches."""
        if not wav_bytes or len(wav_bytes) == 0:
            return

        with self._lock:
            # Store in L1 Memory
            self._put_l1(key, wav_bytes)

            # Store on L2 Disk atomically via temp file
            target_file = os.path.join(self.cache_dir, f"{key}.wav")
            try:
                temp_fd, temp_path = tempfile.mkstemp(dir=self.cache_dir, prefix="tmp_audio_")
                with os.fdopen(temp_fd, "wb") as f:
                    f.write(wav_bytes)
                    f.flush()
                    os.fsync(f.fileno())

                # Atomic rename replaces existing target safely
                os.replace(temp_path, target_file)

                file_size = len(wav_bytes)
                if key in self._l2_meta:
                    self._l2_current_bytes -= self._l2_meta[key]["size"]

                self._l2_meta[key] = {
                    "path": target_file,
                    "size": file_size,
                    "mtime": time.time()
                }
                self._l2_current_bytes += file_size
                self._evict_l2_if_needed()
            except (OSError, IOError):
                # Clean up temp file on failure; cache write errors must not crash execution
                if 'temp_path' in locals() and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass

    def _put_l1(self, key: str, data: bytes):
        size = len(data)
        if size > self.l1_max_bytes:
            return  # Skip L1 if item exceeds total L1 capacity

        if key in self._l1_cache:
            self._l1_current_bytes -= len(self._l1_cache[key])
            del self._l1_cache[key]

        while self._l1_current_bytes + size > self.l1_max_bytes and self._l1_cache:
            _, oldest_data = self._l1_cache.popitem(last=False)
            self._l1_current_bytes -= len(oldest_data)

        self._l1_cache[key] = data
        self._l1_current_bytes += size

    def _evict_l2_if_needed(self):
        """Evicts least recently used audio files from disk if capacity is exceeded."""
        if self._l2_current_bytes <= self.l2_max_bytes:
            return

        # Sort items by mtime ascending (oldest first)
        sorted_keys = sorted(self._l2_meta.items(), key=lambda item: item[1]["mtime"])
        for k, meta in sorted_keys:
            if self._l2_current_bytes <= self.l2_max_bytes:
                break
            try:
                if os.path.exists(meta["path"]):
                    os.remove(meta["path"])
                self._l2_current_bytes -= meta["size"]
                del self._l2_meta[k]
            except OSError:
                continue

    def clear(self):
        """Clears memory and disk caches."""
        with self._lock:
            self._l1_cache.clear()
            self._l1_current_bytes = 0
            for meta in self._l2_meta.values():
                try:
                    if os.path.exists(meta["path"]):
                        os.remove(meta["path"])
                except OSError:
                    pass
            self._l2_meta.clear()
            self._l2_current_bytes = 0
