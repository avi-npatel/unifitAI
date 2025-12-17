from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from unifit.app import create_app
from unifit.config import Config
from unifit.notifications import DryRunSender, InvalidToken

PROFILE = {"age": 24, "height_in": 70, "weight_lb": 170, "sex": "male", "experience": "beginner",
           "goal": "hypertrophy", "days_per_week": 4, "equipment": "gym", "session_minutes": 60}

# 2026-10-05 is a Monday; 06:00 New York is before a 07:30 reminder.
NOW = datetime(2026, 10, 5, 6, 0, tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)

REGISTRATION = {"token": "tok-123", "timezone": "America/New_York", "reminder_time": "07:30",
                "weekdays": [0, 2, 4], "day_names": ["Push", "Pull", "Legs"], "motivation": True}


def make_config(tmp_path, **overrides):
    values = dict(db_path=tmp_path / "unifit.db", model_path=tmp_path / "model.joblib",
                  dataset_path=tmp_path / "data.csv", firebase_credentials=None,
                  firebase_web={}, vapid_key=None, app_url=None)
    values.update(overrides)
    return Config(**values)


@pytest.fixture
def sender():
    return DryRunSender()


@pytest.fixture
def client(tmp_path, trained_model, sender):
    app = create_app(make_config(tmp_path), model=trained_model, sender=sender, clock=lambda: NOW)
    return app.test_client()


def test_health(client):
    body = client.get("/api/health").get_json()
    assert body == {"status": "ok", "model_loaded": True, "push_mode": "dry-run"}


def test_model_info_reports_real_training_metrics(client, trained_model):
    body = client.get("/api/model-info").get_json()
    assert body["r2"] == trained_model.metrics["r2"]
    assert body["rows_train"] + body["rows_test"] == body["rows_total"]
    assert body["data"] == "synthetic"


def test_routine_end_to_end(client):
    response = client.post("/api/routine", json=PROFILE)
    assert response.status_code == 200
    plan = response.get_json()
    assert plan["summary"]["days_per_week"] == 4
    assert len(plan["days"]) == 4
    first = plan["days"][0]["exercises"][0]
    assert first["load_lb"] > 0 and first["sets"] >= 3
    assert response.headers["Cache-Control"] == "no-store"


def test_routine_loads_scale_with_the_person(client):
    def bench(**changes):
        plan = client.post("/api/routine", json={**PROFILE, "days_per_week": 2, "session_minutes": 90, **changes}).get_json()
        for day in plan["days"]:
            for e in day["exercises"]:
                if e["id"] == "barbell_bench_press":
                    return e["load_lb"]

    assert bench(experience="advanced", weight_lb=200) > bench(experience="beginner", weight_lb=140)


def test_routine_rejects_bad_input_with_field_messages(client):
    response = client.post("/api/routine", json={**PROFILE, "age": 3, "sex": "x"})
    assert response.status_code == 400
    fields = response.get_json()["fields"]
    assert set(fields) == {"age", "sex"}


@pytest.mark.parametrize("payload", ["not json", "[1, 2]", "42", ""])
def test_routine_rejects_non_object_bodies(client, payload):
    response = client.post("/api/routine", data=payload, content_type="application/json")
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_oversized_body_is_rejected(client):
    response = client.post("/api/routine", data="x" * 70_000, content_type="application/json")
    assert response.status_code == 413


def test_unknown_api_path_returns_json_404(client):
    response = client.get("/api/nope")
    assert response.status_code == 404 and response.get_json()["error"]


def test_front_end_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"UniFit" in response.data
    assert client.get("/static/css/styles.css").status_code == 200
    assert client.get("/static/js/app.js").status_code == 200


# ---- Firebase configuration --------------------------------------------------------------

FIREBASE_WEB = {"apiKey": "key", "projectId": "proj", "messagingSenderId": "123", "appId": "1:123:web:abc",
                "authDomain": "proj.firebaseapp.com"}


def test_firebase_disabled_without_configuration(client):
    assert client.get("/api/firebase-config").get_json() == {"enabled": False, "mode": "dry-run"}
    assert client.get("/firebase-messaging-sw.js").status_code == 404


def test_firebase_config_and_service_worker_when_configured(tmp_path, trained_model, sender):
    config = make_config(tmp_path, firebase_web=FIREBASE_WEB, vapid_key="vapid-key")
    client = create_app(config, model=trained_model, sender=sender, clock=lambda: NOW).test_client()

    body = client.get("/api/firebase-config").get_json()
    assert body["enabled"] is True
    assert body["config"]["projectId"] == "proj" and body["vapidKey"] == "vapid-key"

    worker = client.get("/firebase-messaging-sw.js")
    assert worker.status_code == 200
    assert worker.mimetype == "application/javascript"
    text = worker.get_data(as_text=True)
    assert "firebase.initializeApp(" in text and '"projectId": "proj"' in text
    assert "vapid" not in text.lower()          # the VAPID key is only needed in the page


def test_firebase_stays_disabled_when_a_required_value_is_missing(tmp_path, trained_model, sender):
    partial = {k: v for k, v in FIREBASE_WEB.items() if k != "appId"}
    config = make_config(tmp_path, firebase_web=partial, vapid_key="vapid-key")
    client = create_app(config, model=trained_model, sender=sender).test_client()
    assert client.get("/api/firebase-config").get_json()["enabled"] is False


# ---- notification registration ---------------------------------------------------------

def test_register_test_and_unregister(client, sender):
    assert client.post("/api/notifications/register", json=REGISTRATION).get_json() == {
        "registered": True, "mode": "dry-run"}

    result = client.post("/api/notifications/test", json={"token": "tok-123"})
    assert result.status_code == 200
    body = result.get_json()
    assert body["mode"] == "dry-run" and body["delivered"] is False
    assert body["message"]["title"].endswith("(test)") and "Push" in body["message"]["title"]
    assert len(sender.sent) == 1

    removed = client.delete("/api/notifications/register", json={"token": "tok-123"}).get_json()
    assert removed == {"registered": False, "removed": True}
    assert client.post("/api/notifications/test", json={"token": "tok-123"}).status_code == 404


def test_test_endpoint_is_rate_limited_per_token(client):
    client.post("/api/notifications/register", json=REGISTRATION)
    assert client.post("/api/notifications/test", json={"token": "tok-123"}).status_code == 200
    assert client.post("/api/notifications/test", json={"token": "tok-123"}).status_code == 429


@pytest.mark.parametrize("change", [
    {"token": ""}, {"token": 5}, {"timezone": "Mars/Base"}, {"timezone": None},
    {"reminder_time": "7:30"}, {"reminder_time": "25:00"}, {"reminder_time": None},
    {"weekdays": []}, {"weekdays": [0, 0]}, {"weekdays": [7]}, {"weekdays": [True]},
    {"weekdays": [0, 1, 2, 3, 4, 5, 6]}, {"day_names": ["Push"]}, {"day_names": ["", "", ""]},
    {"day_names": ["x" * 41, "a", "b"]}, {"motivation": "yes"},
])
def test_registration_validation(client, change):
    response = client.post("/api/notifications/register", json={**REGISTRATION, **change})
    assert response.status_code == 400
    assert response.get_json()["fields"]


def test_registering_after_todays_reminder_time_does_not_send_late(tmp_path, trained_model, sender):
    late = datetime(2026, 10, 5, 12, 0, tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
    app = create_app(make_config(tmp_path), model=trained_model, sender=sender, clock=lambda: late)
    app.test_client().post("/api/notifications/register", json=REGISTRATION)
    store = app.extensions["unifit"]["store"]
    assert store.get_device("tok-123").last_sent_on == "2026-10-05"
    assert app.extensions["unifit"]["scheduler"].tick(late) == []


def test_registering_before_the_reminder_time_keeps_todays_reminder(client, tmp_path):
    client.post("/api/notifications/register", json=REGISTRATION)
    app_state = client.application.extensions["unifit"]
    assert app_state["store"].get_device("tok-123").last_sent_on is None
    sent = app_state["scheduler"].tick(datetime(2026, 10, 5, 7, 30, tzinfo=ZoneInfo("America/New_York")))
    assert len(sent) == 1


def test_registration_sorts_weekdays_with_their_names(client):
    client.post("/api/notifications/register", json={**REGISTRATION, "weekdays": [4, 0, 2], "day_names": ["Legs", "Push", "Pull"]})
    device = client.application.extensions["unifit"]["store"].get_device("tok-123")
    assert device.weekdays == (0, 2, 4) and device.day_names == ("Push", "Pull", "Legs")


def test_re_registering_updates_instead_of_duplicating(client):
    client.post("/api/notifications/register", json=REGISTRATION)
    client.post("/api/notifications/register", json={**REGISTRATION, "reminder_time": "18:00"})
    store = client.application.extensions["unifit"]["store"]
    assert store.count() == 1 and store.get_device("tok-123").reminder_time == "18:00"


def test_test_endpoint_reports_a_rejected_token(tmp_path, trained_model):
    class Rejecting(DryRunSender):
        def send(self, *args, **kwargs):
            raise InvalidToken("gone")

    app = create_app(make_config(tmp_path), model=trained_model, sender=Rejecting(), clock=lambda: NOW)
    client = app.test_client()
    client.post("/api/notifications/register", json=REGISTRATION)
    assert client.post("/api/notifications/test", json={"token": "tok-123"}).status_code == 410
    assert app.extensions["unifit"]["store"].count() == 0


def test_test_endpoint_reports_a_firebase_outage(tmp_path, trained_model):
    class Down(DryRunSender):
        def send(self, *args, **kwargs):
            raise RuntimeError("unreachable")

    client = create_app(make_config(tmp_path), model=trained_model, sender=Down(), clock=lambda: NOW).test_client()
    client.post("/api/notifications/register", json=REGISTRATION)
    assert client.post("/api/notifications/test", json={"token": "tok-123"}).status_code == 502
