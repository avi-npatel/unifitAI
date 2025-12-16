from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from unifit.notifications import (GRACE_MINUTES, DryRunSender, InvalidToken, Scheduler,
                                  rest_message, training_message)
from unifit.store import Device, Store

NY = ZoneInfo("America/New_York")
# 2026-10-05 is a Monday.
MONDAY = date(2026, 10, 5)


def at(hour, minute, day=5, tz=NY):
    return datetime(2026, 10, day, hour, minute, tzinfo=tz)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "unifit.db")


def device(token="tok", **overrides):
    base = dict(token=token, timezone="America/New_York", reminder_time="07:30",
                weekdays=(0, 2, 4), day_names=("Push", "Pull", "Legs"), motivation=True)
    base.update(overrides)
    return Device(**base)


class RecordingSender(DryRunSender):
    def __init__(self):
        super().__init__()
        self.calls = []

    def send(self, token, title, body, link=None):
        self.calls.append((token, title, body, link))
        return super().send(token, title, body, link)


def test_training_day_sends_the_named_workout(store):
    store.save_device(device())
    sender = RecordingSender()
    sent = Scheduler(store, sender).tick(at(7, 30))
    assert len(sent) == 1 and sent[0].kind == "training"
    assert "Push" in sent[0].title
    assert sender.calls[0][0] == "tok"


def test_each_training_weekday_maps_to_its_own_workout(store):
    store.save_device(device())
    sender = RecordingSender()
    scheduler = Scheduler(store, sender)
    scheduler.tick(at(7, 30, day=5))   # Monday
    store.mark_sent("tok", "2000-01-01")
    scheduler.tick(at(7, 30, day=7))   # Wednesday
    store.mark_sent("tok", "2000-01-01")
    scheduler.tick(at(7, 30, day=9))   # Friday
    titles = [call[1] for call in sender.calls]
    assert "Push" in titles[0] and "Pull" in titles[1] and "Legs" in titles[2]


def test_rest_day_sends_encouragement_when_enabled(store):
    store.save_device(device())
    sent = Scheduler(store, RecordingSender()).tick(at(7, 30, day=6))  # Tuesday
    assert [s.kind for s in sent] == ["rest"]


def test_rest_day_is_silent_when_motivation_is_off(store):
    store.save_device(device(motivation=False))
    sender = RecordingSender()
    assert Scheduler(store, sender).tick(at(7, 30, day=6)) == []
    assert sender.calls == []


def test_nothing_is_sent_before_the_reminder_time(store):
    store.save_device(device())
    assert Scheduler(store, RecordingSender()).tick(at(7, 29)) == []


def test_late_ticks_inside_the_grace_window_still_send(store):
    assert GRACE_MINUTES == 120
    store.save_device(device())
    assert len(Scheduler(store, RecordingSender()).tick(at(9, 29))) == 1  # 119 minutes late


def test_a_server_that_wakes_up_too_late_skips_the_reminder(store):
    store.save_device(device())
    assert Scheduler(store, RecordingSender()).tick(at(9, 31)) == []


def test_only_one_notification_per_local_day(store):
    store.save_device(device())
    scheduler = Scheduler(store, RecordingSender())
    assert len(scheduler.tick(at(7, 30))) == 1
    assert scheduler.tick(at(7, 31)) == []
    assert scheduler.tick(at(8, 15)) == []
    assert store.get_device("tok").last_sent_on == "2026-10-05"
    assert len(scheduler.tick(at(7, 30, day=7))) == 1  # next training day works again


def test_reminders_follow_each_devices_own_timezone(store):
    store.save_device(device("ny", timezone="America/New_York"))
    store.save_device(device("la", timezone="America/Los_Angeles"))
    scheduler = Scheduler(store, RecordingSender())
    now = at(7, 30).astimezone(timezone.utc)          # 07:30 in New York, 04:30 in Los Angeles
    assert [d.token for d in scheduler.tick(now)] == ["ny"]
    later = at(7, 30, tz=ZoneInfo("America/Los_Angeles")).astimezone(timezone.utc)
    assert [d.token for d in scheduler.tick(later)] == ["la"]


def test_day_of_week_uses_local_time_not_utc(store):
    # Monday 23:30 in Los Angeles is already Tuesday in UTC.
    store.save_device(device(timezone="America/Los_Angeles", reminder_time="23:30"))
    now = at(23, 30, tz=ZoneInfo("America/Los_Angeles")).astimezone(timezone.utc)
    sent = Scheduler(store, RecordingSender()).tick(now)
    assert sent[0].kind == "training"


def test_invalid_tokens_are_removed(store):
    class Rejecting(DryRunSender):
        def send(self, *args, **kwargs):
            raise InvalidToken("unregistered")

    store.save_device(device())
    assert Scheduler(store, Rejecting()).tick(at(7, 30)) == []
    assert store.count() == 0


def test_a_failed_send_is_retried_on_the_next_tick(store):
    class Flaky(DryRunSender):
        attempts = 0

        def send(self, *args, **kwargs):
            Flaky.attempts += 1
            if Flaky.attempts == 1:
                raise RuntimeError("network down")
            return super().send(*args, **kwargs)

    store.save_device(device())
    scheduler = Scheduler(store, Flaky())
    assert scheduler.tick(at(7, 30)) == []
    assert store.get_device("tok").last_sent_on is None
    assert len(scheduler.tick(at(7, 31))) == 1


def test_one_bad_device_does_not_block_the_others(store):
    store.save_device(device("broken", timezone="Not/AZone"))
    store.save_device(device("good"))
    sent = Scheduler(store, RecordingSender()).tick(at(7, 30))
    assert [d.token for d in sent] == ["good"]


def test_link_is_passed_to_the_sender(store):
    store.save_device(device())
    sender = RecordingSender()
    Scheduler(store, sender, link="https://unifit.example").tick(at(7, 30))
    assert sender.calls[0][3] == "https://unifit.example"


def test_messages_are_deterministic_per_date():
    assert training_message("Push", MONDAY) == training_message("Push", MONDAY)
    assert rest_message(MONDAY) == rest_message(MONDAY)
    assert len({rest_message(date.fromordinal(MONDAY.toordinal() + i)) for i in range(5)}) == 5


def test_dry_run_sender_records_messages():
    sender = DryRunSender()
    sender.send("t", "Title", "Body")
    assert list(sender.sent) == [{"token": "t", "title": "Title", "body": "Body"}]


def test_store_round_trip_and_upsert(store):
    store.save_device(device())
    store.save_device(device(reminder_time="18:00", motivation=False))
    saved = store.get_device("tok")
    assert saved.reminder_time == "18:00" and saved.motivation is False
    assert saved.weekdays == (0, 2, 4) and saved.day_names == ("Push", "Pull", "Legs")
    assert store.count() == 1
    assert store.delete_device("tok") is True and store.delete_device("tok") is False
