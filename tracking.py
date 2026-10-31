"""
Evidence of effect: one row per session event, so we can see whether students
use the tool and whether they improve. No message content is stored.
"""

import csv
import os
from datetime import datetime, timezone

import config

EVENTS_LOG = os.path.join(config.LOG_DIR, "sessions.csv")
FIELDS = ["timestamp", "session_id", "event", "language", "student_turns",
          "deal_reached", "price_per_kg", "score"]


def log_event(session_id, event, language, student_turns=0,
              deal_reached="", price_per_kg="", score=""):
    os.makedirs(config.LOG_DIR, exist_ok=True)
    new_file = not os.path.exists(EVENTS_LOG)
    with open(EVENTS_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new_file:
            w.writeheader()
        w.writerow({
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "session_id": session_id,
            "event": event,                    # "started" or "completed"
            "language": language,
            "student_turns": student_turns,
            "deal_reached": deal_reached,
            "price_per_kg": price_per_kg,
            "score": score,
        })
