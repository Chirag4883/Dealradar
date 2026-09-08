"""SQLite outbox + process lock. No database transaction is held across HTTP."""
import fcntl
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from .models import money


@contextmanager
def locked(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with Path(str(path) + ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("another DealRadar run holds this state lock") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class State:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS delivery (
            id TEXT PRIMARY KEY, watch_id TEXT NOT NULL, channel TEXT NOT NULL,
            price TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','sent')),
            updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        """)

    def close(self):
        self.db.close()

    def reserve(self, watch, offer, notifier):
        raw = [watch, offer.provider, offer.identity, offer.currency, notifier.channel, notifier.destination]
        key = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
        row = self.db.execute("SELECT price,status FROM delivery WHERE id=?", (key,)).fetchone()
        if row and (row[1] == "pending" or offer.price >= money(row[0])):
            return None
        with self.db:
            self.db.execute("INSERT INTO delivery(id,watch_id,channel,price,status) VALUES(?,?,?,?,'pending') "
                "ON CONFLICT(id) DO UPDATE SET price=excluded.price,status='pending',updated=CURRENT_TIMESTAMP",
                (key, watch["id"], notifier.channel, str(offer.price)))
        return key

    def sent(self, key):
        with self.db:
            self.db.execute("UPDATE delivery SET status='sent',updated=CURRENT_TIMESTAMP WHERE id=?", (key,))

    def pending(self):
        return [dict(zip(("id", "watch_id", "channel", "price", "updated"), r)) for r in self.db.execute(
            "SELECT id,watch_id,channel,price,updated FROM delivery WHERE status='pending' ORDER BY updated,id")]

    def resolve(self, key, action):
        with self.db:
            if action == "retry":
                result = self.db.execute("DELETE FROM delivery WHERE id=? AND status='pending'", (key,))
            else:
                result = self.db.execute("UPDATE delivery SET status='sent' WHERE id=? AND status='pending'", (key,))
            if result.rowcount != 1:
                raise ValueError("pending delivery not found")
