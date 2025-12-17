"""Flask app: JSON API for routines and reminders, plus the static front end."""

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Flask, Response, jsonify, request, send_from_directory

from . import exercises, model as model_module
from .config import ROOT, Config
from .notifications import (DryRunSender, InvalidToken, Scheduler, build_sender,
                            training_message)
from .routines import ProfileError, Profile, generate_routine
from .store import Device, Store

log = logging.getLogger("unifit")

FIREBASE_SDK_VERSION = "10.14.1"
TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
TEST_COOLDOWN_SECONDS = 5


def create_app(config: Optional[Config] = None, *, model=None, sender=None,
               clock: Optional[Callable[[], datetime]] = None,
               start_scheduler: bool = False) -> Flask:
    config = config or Config.from_env()
    clock = clock or (lambda: datetime.now(timezone.utc))

    app = Flask(__name__, static_folder=str(ROOT / "static"), static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

    weight_model = model or model_module.ensure_model(config.model_path)
    store = Store(config.db_path)
    sender = sender or build_sender(config)
    scheduler = Scheduler(store, sender, link=config.app_url, clock=clock)
    last_test_send = {}

    app.extensions["unifit"] = {
        "config": config, "model": weight_model, "store": store,
        "sender": sender, "scheduler": scheduler,
    }
    if start_scheduler:
        scheduler.start()

    # ---- helpers -----------------------------------------------------------------------

    def fail(message: str, status: int, **extra):
        return jsonify({"error": message, **extra}), status

    def json_body():
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else None

    @app.after_request
    def headers(response: Response) -> Response:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    # ---- pages -------------------------------------------------------------------------

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/firebase-messaging-sw.js")
    def service_worker():
        if not config.push_web_enabled:
            return Response("Push notifications are not configured.", status=404, mimetype="text/plain")
        script = (
            f'importScripts("https://www.gstatic.com/firebasejs/{FIREBASE_SDK_VERSION}/firebase-app-compat.js");\n'
            f'importScripts("https://www.gstatic.com/firebasejs/{FIREBASE_SDK_VERSION}/firebase-messaging-compat.js");\n'
            f"firebase.initializeApp({json.dumps(config.firebase_web)});\n"
            "// Initializing messaging lets the SDK show notifications that arrive while the app is closed.\n"
            "firebase.messaging();\n"
            'self.addEventListener("notificationclick", (event) => {\n'
            "  event.notification.close();\n"
            "  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {\n"
            "    for (const client of clients) { if ('focus' in client) { return client.focus(); } }\n"
            "    return self.clients.openWindow('/');\n"
            "  }));\n"
            "});\n"
        )
        response = Response(script, mimetype="application/javascript")
        response.headers["Cache-Control"] = "no-cache"
        return response

    # ---- API ---------------------------------------------------------------------------

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "model_loaded": weight_model is not None,
                        "push_mode": sender.mode})

    @app.get("/api/model-info")
    def model_info():
        info = dict(weight_model.metrics)
        info["exercises_with_weights"] = len(exercises.WEIGHTED)
        return jsonify(info)

    @app.get("/api/firebase-config")
    def firebase_config():
        if not config.push_web_enabled:
            return jsonify({"enabled": False, "mode": sender.mode})
        return jsonify({
            "enabled": True, "mode": sender.mode, "sdkVersion": FIREBASE_SDK_VERSION,
            "config": config.firebase_web, "vapidKey": config.vapid_key,
        })

    @app.post("/api/routine")
    def routine():
        body = json_body()
        if body is None:
            return fail("Send a JSON object with your measurements and preferences.", 400)
        try:
            profile = Profile.from_dict(body)
        except ProfileError as err:
            return fail("Some answers need fixing.", 400, fields=err.fields)

        def loads_for(ids):
            return weight_model.predict_loads(
                profile.height_in, profile.weight_lb, profile.age, profile.sex,
                profile.experience, ids)

        return jsonify(generate_routine(profile, loads_for))

    @app.post("/api/notifications/register")
    def register():
        body = json_body()
        if body is None:
            return fail("Send a JSON object.", 400)

        errors = {}
        token = body.get("token")
        if not isinstance(token, str) or not (1 <= len(token) <= 4096):
            errors["token"] = "A push token is required."

        tz_name = body.get("timezone")
        try:
            tz = ZoneInfo(tz_name) if isinstance(tz_name, str) and tz_name else None
        except (ZoneInfoNotFoundError, ValueError):
            tz = None
        if tz is None:
            errors["timezone"] = "Send an IANA timezone such as America/New_York."

        reminder_time = body.get("reminder_time")
        if not isinstance(reminder_time, str) or not TIME_PATTERN.match(reminder_time):
            errors["reminder_time"] = "Reminder time must look like 07:30."

        weekdays = body.get("weekdays")
        day_names = body.get("day_names")
        valid_days = (
            isinstance(weekdays, list) and 1 <= len(weekdays) <= 6
            and all(isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6 for d in weekdays)
            and len(set(weekdays)) == len(weekdays)
        )
        if not valid_days:
            errors["weekdays"] = "Send 1 to 6 different weekdays, Monday as 0 through Sunday as 6."
        valid_names = (
            isinstance(day_names, list) and valid_days and len(day_names) == len(weekdays)
            and all(isinstance(n, str) and 1 <= len(n) <= 40 for n in day_names)
        )
        if not valid_names:
            errors["day_names"] = "Send one workout name (up to 40 characters) for each weekday."

        motivation = body.get("motivation", True)
        if not isinstance(motivation, bool):
            errors["motivation"] = "Motivation must be true or false."

        if errors:
            return fail("Some fields need fixing.", 400, fields=errors)

        pairs = sorted(zip(weekdays, day_names))
        local_now = clock().astimezone(tz)
        hour, minute = (int(p) for p in reminder_time.split(":"))
        already_passed = (local_now.hour, local_now.minute) >= (hour, minute)
        # Registering after today's reminder time shouldn't trigger a late reminder.
        device = Device(
            token=token, timezone=tz_name, reminder_time=reminder_time,
            weekdays=tuple(p[0] for p in pairs), day_names=tuple(p[1] for p in pairs),
            motivation=motivation,
            last_sent_on=local_now.date().isoformat() if already_passed else None,
        )
        store.save_device(device)
        return jsonify({"registered": True, "mode": sender.mode})

    @app.delete("/api/notifications/register")
    def unregister():
        body = json_body() or {}
        token = body.get("token")
        if not isinstance(token, str) or not token:
            return fail("A push token is required.", 400)
        removed = store.delete_device(token)
        return jsonify({"registered": False, "removed": removed})

    @app.post("/api/notifications/test")
    def send_test():
        body = json_body() or {}
        token = body.get("token")
        if not isinstance(token, str) or not token:
            return fail("A push token is required.", 400)
        device = store.get_device(token)
        if device is None:
            return fail("Turn on reminders before sending a test.", 404)

        now = time.monotonic()
        if now - last_test_send.get(token, -1e9) < TEST_COOLDOWN_SECONDS:
            return fail("Wait a few seconds before sending another test.", 429)
        last_test_send[token] = now

        local = clock().astimezone(ZoneInfo(device.timezone))
        title, text = training_message(device.day_names[0], local.date())
        try:
            sender.send(token, f"{title} (test)", text, config.app_url)
        except InvalidToken:
            store.delete_device(token)
            return fail("Firebase no longer accepts this device. Turn reminders on again.", 410)
        except Exception:
            log.exception("Test notification failed")
            return fail("Couldn't reach Firebase. Check the server's credentials.", 502)
        return jsonify({"delivered": sender.mode == "firebase", "mode": sender.mode,
                        "message": {"title": f"{title} (test)", "body": text}})

    # ---- errors ------------------------------------------------------------------------

    @app.errorhandler(404)
    def not_found(_):
        if request.path.startswith("/api/"):
            return fail("Not found.", 404)
        return Response("Not found.", status=404, mimetype="text/plain")

    @app.errorhandler(405)
    def wrong_method(_):
        return fail("That method isn't allowed here.", 405)

    @app.errorhandler(413)
    def too_large(_):
        return fail("The request is too large.", 413)

    @app.errorhandler(500)
    def server_error(_):
        return fail("Something went wrong on the server.", 500)

    return app
