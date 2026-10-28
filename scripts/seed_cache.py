"""Cache pre-seeding script for enterprise intent canonical responses.

Why this script exists:
Pre-synthesizes audio clips for all verified, non-personal FAQ replies in `data/intents.yaml`.
Seeding the cache beforehand guarantees that 70-80% of caller questions are served with
sub-50ms latency at zero live credit consumption. In accordance with project budget rules,
real API synthesis strictly requires an explicit `--live` flag and confirms character counts
before dispatching requests.
"""

import argparse
import asyncio
import os
import sys

# Reconfigure stdout for Indic scripts on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure repository root and backend directory are in sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(REPO_ROOT, ".env"))

from app.adapters.fake import FakeTtsAdapter
from app.adapters.gnani_tts import GnaniTtsAdapter
from app.adapters.models import TtsRequest
from app.budget import BudgetTracker
from app.cache.audio_store import AudioStore
from app.cache.keys import audio_key
from app.config import get_config
from app.routing.intents import IntentCatalog
from app.routing.splitter import split_into_clauses


async def seed_cache(live: bool = False, output_dir: str = "audio_cache"):
    cfg = get_config()
    catalog = IntentCatalog(os.path.join(REPO_ROOT, "data", "intents.yaml"))
    budget = BudgetTracker(db_path=cfg.db_path)
    audio_store = AudioStore(cache_dir=output_dir)

    # Collect all clauses to synthesize
    tasks = []
    for intent in catalog.intents.values():
        if intent.personal:
            continue  # Never seed or cache personalized responses!
        for lang, data in intent.languages.items():
            clauses = split_into_clauses(data.canonical_reply)
            voice = cfg.voice_map.get(lang, "Kirra")
            for clause in clauses:
                req = TtsRequest(
                    text=clause,
                    voice=voice,
                    model=cfg.gnani_tts_model,
                    language=lang,
                    sample_rate=cfg.gnani_sample_rate
                )
                key = audio_key(req, version_tag=cfg.version_tag)
                already_cached = audio_store.get(key) is not None
                tasks.append({
                    "intent": intent.id,
                    "lang": lang,
                    "voice": voice,
                    "text": clause,
                    "chars": len(clause),
                    "req": req,
                    "key": key,
                    "cached": already_cached
                })

    total_tasks = len(tasks)
    cached_count = sum(1 for t in tasks if t["cached"])
    needed_tasks = [t for t in tasks if not t["cached"]]
    needed_chars = sum(t["chars"] for t in needed_tasks)
    approx_credits = round(needed_chars / 300, 2)

    print("=" * 65)
    print(f"Gnani Voice Gateway - Cache Pre-Seeding Planner")
    print(f"Total Canonical Clauses : {total_tasks}")
    print(f"Already in Cache        : {cached_count}")
    print(f"Clauses to Synthesize   : {len(needed_tasks)}")
    print(f"Total Characters to Send: {needed_chars} chars (~{approx_credits} credits)")
    print("=" * 65)

    if not needed_tasks:
        print("\nAll canonical replies are already cached! No synthesis needed.")
        return

    if not live:
        print("\n[SAFETY NOTICE] Running in DRY-RUN / OFFLINE mode (0 credits spent).")
        print("To execute real synthesis with Gnani TTS, run:")
        print("  python scripts/seed_cache.py --live\n")
        adapter = FakeTtsAdapter(delay_ms=5)
    else:
        if not cfg.gnani_api_key or cfg.gnani_api_key.startswith("your_"):
            print("\n[ERROR] GNANI_API_KEY is not set or invalid in .env! Aborting.")
            return

        print(f"\n[LIVE MODE] Initializing Gnani TTS with key {cfg.gnani_api_key[:12]}...")
        adapter = GnaniTtsAdapter(
            api_key=cfg.gnani_api_key,
            base_url=cfg.gnani_base_url,
            budget_tracker=budget,
            default_bucket="seeding",
            kill_switch=cfg.kill_switch
        )

    # Execute synthesis for needed tasks
    success = 0
    for idx, item in enumerate(needed_tasks, start=1):
        print(f"[{idx}/{len(needed_tasks)}] [{item['lang']}|{item['voice']}] {item['text'][:45]}... ({item['chars']} chars)")
        try:
            res = await adapter.synthesize(item["req"], bucket="seeding")
            audio_store.put(item["key"], res.wav)

            # Also save a copy in data/seed/ for container boot loading
            seed_dir = os.path.join(REPO_ROOT, "data", "seed")
            os.makedirs(seed_dir, exist_ok=True)
            with open(os.path.join(seed_dir, f"{item['key']}.wav"), "wb") as f:
                f.write(res.wav)

            success += 1
        except Exception as exc:
            print(f"  --> Failed to synthesize: {exc}")

    print("\n" + "=" * 65)
    print(f"Seeding Complete! Successfully cached {success}/{len(needed_tasks)} audio clips.")
    status = budget.get_status().get("seeding", {})
    print(f"Seeding Bucket Balance: {status.get('chars_spent', 0)} / {status.get('cap_chars', 30000)} chars spent.")
    print("=" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed audio cache with canonical replies")
    parser.add_argument("--live", action="store_true", help="Execute real paid synthesis with Gnani TTS")
    parser.add_argument("--cache-dir", default="audio_cache", help="Target audio cache directory")
    args = parser.parse_args()

    asyncio.run(seed_cache(live=args.live, output_dir=args.cache_dir))
