"""SQLite storage for push-notification registrations."""

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    token         TEXT PRIMARY KEY,
    timezone      TEXT NOT NULL,
    reminder_time TEXT NOT NULL,
    weekdays      TEXT NOT NULL,
    day_names     TEXT NOT NULL,
    motivation    INTEGER NOT NULL DEFAULT 1,
    last_sent_on  TEXT,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


@dataclass(frozen=True)
class Device:
    token: str
    timezone: str                 # IANA name, for example America/New_York
    reminder_time: str            # "HH:MM", 24 hour, in the device's timezone
    weekdays: Tuple[int, ...]     # training weekdays, Monday is 0
    day_names: Tuple[str, ...]    # workout name for each training weekday
    motivation: bool = True       # also send an encouragement note on rest days
    last_sent_on: Optional[str] = None  # local date of the last notification, ISO format


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _device(row: sqlite3.Row) -> Device:
        return Device(
            token=row["token"],
            timezone=row["timezone"],
            reminder_time=row["reminder_time"],
            weekdays=tuple(json.loads(row["weekdays"])),
            day_names=tuple(json.loads(row["day_names"])),
            motivation=bool(row["motivation"]),
            last_sent_on=row["last_sent_on"],
        )

    def save_device(self, device: Device) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """INSERT INTO devices
                   (token, timezone, reminder_time, weekdays, day_names, motivation, last_sent_on)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(token) DO UPDATE SET
                     timezone=excluded.timezone, reminder_time=excluded.reminder_time,
                     weekdays=excluded.weekdays, day_names=excluded.day_names,
                     motivation=excluded.motivation, last_sent_on=excluded.last_sent_on""",
                (device.token, device.timezone, device.reminder_time,
                 json.dumps(list(device.weekdays)), json.dumps(list(device.day_names)),
                 int(device.motivation), device.last_sent_on))

    def get_device(self, token: str) -> Optional[Device]:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM devices WHERE token = ?", (token,)).fetchone()
        return self._device(row) if row else None

    def list_devices(self) -> List[Device]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM devices").fetchall()
        return [self._device(r) for r in rows]

    def delete_device(self, token: str) -> bool:
        with closing(self._connect()) as conn, conn:
            cursor = conn.execute("DELETE FROM devices WHERE token = ?", (token,))
            return cursor.rowcount > 0

    def mark_sent(self, token: str, local_date: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE devices SET last_sent_on = ? WHERE token = ?", (local_date, token))

    def count(self) -> int:
        with closing(self._connect()) as conn:
            return conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
