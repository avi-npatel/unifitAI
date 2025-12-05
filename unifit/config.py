"""Settings read from environment variables (and an optional .env file)."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent

FIREBASE_WEB_KEYS = {
    "apiKey": "FIREBASE_API_KEY",
    "authDomain": "FIREBASE_AUTH_DOMAIN",
    "projectId": "FIREBASE_PROJECT_ID",
    "storageBucket": "FIREBASE_STORAGE_BUCKET",
    "messagingSenderId": "FIREBASE_MESSAGING_SENDER_ID",
    "appId": "FIREBASE_APP_ID",
}
# The browser cannot register for push without these.
FIREBASE_WEB_REQUIRED = ("apiKey", "projectId", "messagingSenderId", "appId")


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines into os.environ without overriding real variables."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Config:
    db_path: Path
    model_path: Path
    dataset_path: Path
    firebase_credentials: Optional[str]
    firebase_web: dict
    vapid_key: Optional[str]
    app_url: Optional[str]

    @property
    def push_web_enabled(self) -> bool:
        """True when the browser has everything it needs to request a push token."""
        return bool(self.vapid_key) and all(self.firebase_web.get(k) for k in FIREBASE_WEB_REQUIRED)

    @property
    def push_send_enabled(self) -> bool:
        """True when the server can send through Firebase Cloud Messaging."""
        return bool(self.firebase_credentials)

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv(ROOT / ".env")
        env = os.environ
        web = {name: env.get(var) for name, var in FIREBASE_WEB_KEYS.items() if env.get(var)}
        return cls(
            db_path=Path(env.get("UNIFIT_DB", ROOT / "data" / "unifit.db")),
            model_path=Path(env.get("UNIFIT_MODEL", ROOT / "data" / "model.joblib")),
            dataset_path=Path(env.get("UNIFIT_DATASET", ROOT / "data" / "synthetic_workouts.csv")),
            firebase_credentials=env.get("FIREBASE_CREDENTIALS") or None,
            firebase_web=web,
            vapid_key=env.get("FIREBASE_VAPID_KEY") or None,
            app_url=env.get("UNIFIT_APP_URL") or None,
        )
