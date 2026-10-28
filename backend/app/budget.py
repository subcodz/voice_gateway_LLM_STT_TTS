"""Budget tracker for enforcing hard character and credit limits across API buckets.

Why this module exists:
To protect limited hackathon API credits from accidental exhaustion, this tracker enforces
pre-reservation of characters before real synthesis or transcription calls. All allocations
and expenditures are persisted in SQLite, ensuring that any call exceeding its bucket cap
or triggered while the kill switch is active is strictly rejected.
"""

import sqlite3
import threading
from typing import Optional


class BudgetExceededError(Exception):
    """Raised when an operation would exceed its allocated character/credit budget."""
    pass


class KillSwitchActiveError(Exception):
    """Raised when the emergency kill switch is activated."""
    pass


class BudgetTracker:
    # Default bucket allocations (credits * 300 chars/credit)
    DEFAULT_CAPS = {
        "probe": 3 * 300,            # 900 chars
        "dev_listening": 400 * 300,  # 120,000 chars
        "seeding": 100 * 300,        # 30,000 chars
        "stt_testing": 60 * 300,     # 18,000 chars
        "benchmark": 800 * 300,      # 240,000 chars
        "public_demo": 1500 * 300,   # 450,000 chars
        "reserve": 2137 * 300        # 641,100 chars
    }

    def __init__(self, db_path: str = "metrics.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._lock:
            with self._get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS budget (
                        bucket TEXT PRIMARY KEY,
                        chars_spent INTEGER NOT NULL DEFAULT 0,
                        cap_chars INTEGER NOT NULL
                    )
                """)
                # Populate default buckets if not present
                for bucket, cap in self.DEFAULT_CAPS.items():
                    conn.execute("""
                        INSERT OR IGNORE INTO budget (bucket, chars_spent, cap_chars)
                        VALUES (?, 0, ?)
                    """, (bucket, cap))
                conn.commit()

    def reserve(self, bucket: str, chars: int, kill_switch: bool = False):
        """Pre-reserves characters in the specified bucket before an API call.
        
        Raises KillSwitchActiveError if kill_switch is active.
        Raises BudgetExceededError if the expenditure would exceed cap_chars.
        """
        if kill_switch:
            raise KillSwitchActiveError("Global kill switch is ACTIVE. Live API calls are suspended.")

        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute("SELECT chars_spent, cap_chars FROM budget WHERE bucket = ?", (bucket,))
                row = cur.fetchone()
                if not row:
                    # If unregistered bucket, initialize with 0 cap
                    conn.execute("INSERT INTO budget (bucket, chars_spent, cap_chars) VALUES (?, 0, 0)", (bucket,))
                    chars_spent, cap_chars = 0, 0
                else:
                    chars_spent = row["chars_spent"]
                    cap_chars = row["cap_chars"]

                if chars_spent + chars > cap_chars:
                    raise BudgetExceededError(
                        f"Budget exceeded for bucket '{bucket}': requesting {chars} chars, "
                        f"spent {chars_spent}/{cap_chars} chars."
                    )

                conn.execute(
                    "UPDATE budget SET chars_spent = chars_spent + ? WHERE bucket = ?",
                    (chars, bucket)
                )
                conn.commit()

    def refund(self, bucket: str, chars: int):
        """Refunds reserved characters if an API call failed before consuming them."""
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE budget SET chars_spent = MAX(0, chars_spent - ?) WHERE bucket = ?",
                    (chars, bucket)
                )
                conn.commit()

    def get_status(self) -> dict[str, dict[str, int]]:
        """Returns the current spend and cap for all buckets."""
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute("SELECT bucket, chars_spent, cap_chars FROM budget")
                return {
                    row["bucket"]: {
                        "chars_spent": row["chars_spent"],
                        "cap_chars": row["cap_chars"],
                        "credits_spent": round(row["chars_spent"] / 300, 2),
                        "credits_cap": round(row["cap_chars"] / 300, 2),
                    }
                    for row in cur.fetchall()
                }
