"""Push notifications through Firebase Cloud Messaging.

A device registers an FCM token plus when it wants reminders. Once a minute the scheduler
checks every device in its own timezone: on a training day it sends "today's workout", and
on a rest day it can send a short encouragement. Without Firebase credentials the sender
runs in dry-run mode, which records what would have been sent so the whole flow can be
demonstrated and tested without a Firebase project.
"""

import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Deque, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from .config import Config
from .store import Device, Store

log = logging.getLogger("unifit.notifications")

GRACE_MINUTES = 120  # a reminder is skipped if the server is more than this late sending it

TRAINING_TITLES = (
    "Today: {name}",
    "{name} day",
)
REST_MESSAGES = (
    ("Rest day", "Sleep and protein do the work today. Back at it tomorrow."),
    ("Rest day", "Recovery is part of the plan. A 20-minute walk counts."),
    ("Rest day", "Muscle gets built while you rest. Drink some water and stretch."),
    ("Rest day", "You showed up this week. Keep the streak going."),
    ("Rest day", "Take it easy. Your next session will feel better for it."),
)
TRAINING_BODIES = (
    "Your plan is ready. Open UniFit to see today's weights.",
    "Open UniFit for today's exercises and starting weights.",
    "Warm up, then work through today's list. Your weights are waiting.",
)


class InvalidToken(Exception):
    """The push service says this token is no longer valid."""


def training_message(day_name: str, on: date) -> Tuple[str, str]:
    index = on.toordinal()
    title = TRAINING_TITLES[index % len(TRAINING_TITLES)].format(name=day_name)
    return title, TRAINING_BODIES[index % len(TRAINING_BODIES)]


def rest_message(on: date) -> Tuple[str, str]:
    return REST_MESSAGES[on.toordinal() % len(REST_MESSAGES)]


class DryRunSender:
    """Records messages instead of sending them. Used when Firebase isn't configured."""
    mode = "dry-run"

    def __init__(self) -> None:
        self.sent: Deque[Dict[str, str]] = deque(maxlen=100)

    def send(self, token: str, title: str, body: str, link: Optional[str] = None) -> str:
        self.sent.append({"token": token, "title": title, "body": body})
        log.info("[dry-run] %s: %s", title, body)
        return "dry-run"


class FirebaseSender:
    """Sends through the Firebase Admin SDK using a service account."""
    mode = "firebase"

    def __init__(self, credentials_path: str) -> None:
        import firebase_admin
        from firebase_admin import credentials, messaging

        self._messaging = messaging
        self._app = firebase_admin.initialize_app(credentials.Certificate(credentials_path))

    def send(self, token: str, title: str, body: str, link: Optional[str] = None) -> str:
        messaging = self._messaging
        webpush = None
        if link and link.startswith("https://"):
            webpush = messaging.WebpushConfig(fcm_options=messaging.WebpushFCMOptions(link=link))
        message = messaging.Message(
            token=token,
            notification=messaging.Notification(title=title, body=body),
            webpush=webpush,
        )
        try:
            return messaging.send(message, app=self._app)
        except (messaging.UnregisteredError, messaging.SenderIdMismatchError) as exc:
            raise InvalidToken(str(exc)) from exc


def build_sender(config: Config):
    """Firebase when credentials are configured, otherwise dry-run."""
    if config.push_send_enabled:
        try:
            return FirebaseSender(config.firebase_credentials)
        except Exception:
            log.exception("Firebase credentials could not be loaded; falling back to dry-run.")
    return DryRunSender()


@dataclass(frozen=True)
class Delivery:
    token: str
    kind: str          # "training" or "rest"
    title: str
    body: str


class Scheduler:
    """Sends due reminders. Call tick() directly in tests; start() runs it on a timer."""

    def __init__(self, store: Store, sender, link: Optional[str] = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 interval_seconds: int = 60) -> None:
        self.store = store
        self.sender = sender
        self.link = link
        self.clock = clock
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def tick(self, now: Optional[datetime] = None) -> List[Delivery]:
        now = now or self.clock()
        deliveries: List[Delivery] = []
        for device in self.store.list_devices():
            try:
                delivery = self._process(device, now)
            except Exception:
                log.exception("Reminder for a device failed; will retry on the next tick.")
                continue
            if delivery:
                deliveries.append(delivery)
        return deliveries

    def _process(self, device: Device, now: datetime) -> Optional[Delivery]:
        local = now.astimezone(ZoneInfo(device.timezone))
        today = local.date().isoformat()
        if device.last_sent_on == today:
            return None

        hour, minute = (int(part) for part in device.reminder_time.split(":"))
        due = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if not (due <= local < due + timedelta(minutes=GRACE_MINUTES)):
            return None

        if local.weekday() in device.weekdays:
            name = device.day_names[device.weekdays.index(local.weekday())]
            kind, (title, body) = "training", training_message(name, local.date())
        elif device.motivation:
            kind, (title, body) = "rest", rest_message(local.date())
        else:
            self.store.mark_sent(device.token, today)  # nothing to send today
            return None

        try:
            self.sender.send(device.token, title, body, self.link)
        except InvalidToken:
            log.info("Removing a device whose push token is no longer valid.")
            self.store.delete_device(device.token)
            return None
        self.store.mark_sent(device.token, today)
        return Delivery(device.token, kind, title, body)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="unifit-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.tick()
