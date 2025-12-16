"""FirebaseSender with the Firebase SDK mocked out: no network and no credentials needed."""

import pytest
from firebase_admin import messaging

from unifit.config import Config
from unifit.notifications import DryRunSender, FirebaseSender, InvalidToken, build_sender


@pytest.fixture
def firebase(monkeypatch):
    sent = []

    class FakeApp:
        pass

    monkeypatch.setattr("firebase_admin.credentials.Certificate", lambda path: ("cert", path))
    monkeypatch.setattr("firebase_admin.initialize_app", lambda cred: FakeApp())

    def fake_send(message, app=None):
        sent.append(message)
        return "projects/demo/messages/1"

    monkeypatch.setattr(messaging, "send", fake_send)
    return sent


def test_builds_a_notification_message(firebase):
    sender = FirebaseSender("key.json")
    assert sender.send("device-token", "Today: Push", "Open UniFit.", "https://unifit.example") == "projects/demo/messages/1"
    message = firebase[0]
    assert message.token == "device-token"
    assert message.notification.title == "Today: Push" and message.notification.body == "Open UniFit."
    assert message.webpush.fcm_options.link == "https://unifit.example"


def test_link_is_only_attached_for_https_urls(firebase):
    sender = FirebaseSender("key.json")
    sender.send("t", "a", "b", "http://localhost:5000")
    sender.send("t", "a", "b", None)
    assert all(m.webpush is None for m in firebase)


@pytest.mark.parametrize("error", [
    messaging.UnregisteredError("gone"),
    messaging.SenderIdMismatchError("wrong project"),
])
def test_dead_tokens_become_invalid_token(monkeypatch, firebase, error):
    def reject(message, app=None):
        raise error

    monkeypatch.setattr(messaging, "send", reject)
    with pytest.raises(InvalidToken):
        FirebaseSender("key.json").send("t", "a", "b")


def test_other_errors_are_not_swallowed(monkeypatch, firebase):
    def fail(message, app=None):
        raise messaging.QuotaExceededError("slow down")

    monkeypatch.setattr(messaging, "send", fail)
    with pytest.raises(messaging.QuotaExceededError):
        FirebaseSender("key.json").send("t", "a", "b")


def make_config(tmp_path, credentials):
    return Config(tmp_path / "a.db", tmp_path / "m.joblib", tmp_path / "d.csv", credentials, {}, None, None)


def test_build_sender_uses_firebase_only_when_credentials_exist(tmp_path, firebase):
    assert isinstance(build_sender(make_config(tmp_path, None)), DryRunSender)
    assert isinstance(build_sender(make_config(tmp_path, "key.json")), FirebaseSender)


def test_build_sender_falls_back_when_credentials_are_unreadable(tmp_path):
    sender = build_sender(make_config(tmp_path, str(tmp_path / "missing.json")))
    assert isinstance(sender, DryRunSender)
