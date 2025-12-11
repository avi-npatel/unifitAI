import pytest

from unifit import exercises, routines
from unifit.routines import Profile, ProfileError, generate_routine, plates_per_side, select_exercises


def flat_loads(ids):
    """Stand-in for the model: 60% of each exercise's reference load."""
    return {i: exercises.BY_ID[i].ref_load_lb * 0.6 for i in ids}


def make(**overrides):
    base = dict(age=25, height_in=70, weight_lb=170, sex="male", experience=0)
    base.update(overrides)
    return Profile.from_dict(base)


# ---- validation ------------------------------------------------------------------------

def test_defaults_fill_optional_fields():
    p = make()
    assert (p.goal, p.days_per_week, p.equipment, p.session_minutes, p.focus) == ("hypertrophy", 3, "gym", 45, ())


def test_experience_accepts_names_and_numbers():
    assert make(experience="Advanced").experience == 2
    assert make(experience=1).experience == 1


def test_numeric_strings_are_accepted():
    p = make(age="31", height_in="68.5", weight_lb="150")
    assert (p.age, p.height_in, p.weight_lb) == (31, 68.5, 150.0)


@pytest.mark.parametrize("field,value", [
    ("age", 10), ("age", 25.5), ("age", "old"), ("age", True), ("age", float("nan")),
    ("height_in", 30), ("weight_lb", 20), ("weight_lb", 900),
    ("sex", "robot"), ("experience", 3), ("experience", "expert"), ("experience", True),
    ("goal", "bulk"), ("equipment", "kettlebell"), ("days_per_week", 7), ("days_per_week", 1),
    ("session_minutes", 5), ("focus", ["toes"]), ("focus", ["arms", "legs", "core"]), ("focus", "arms"),
])
def test_bad_values_are_rejected_with_a_field_message(field, value):
    data = dict(age=25, height_in=70, weight_lb=170, sex="male", experience=0)
    data[field] = value
    with pytest.raises(ProfileError) as caught:
        Profile.from_dict(data)
    assert field in caught.value.fields


def test_all_missing_required_fields_are_reported_together():
    with pytest.raises(ProfileError) as caught:
        Profile.from_dict({})
    assert set(caught.value.fields) == {"age", "height_in", "weight_lb", "sex", "experience"}


def test_duplicate_focus_is_collapsed():
    assert make(focus=["arms", "arms", "legs"]).focus == ("arms", "legs")


# ---- plates ----------------------------------------------------------------------------

@pytest.mark.parametrize("total,expected", [
    (45, []), (65, [10]), (95, [25]), (135, [45]), (185, [45, 25]),
    (225, [45, 45]), (115, [35]), (100, [25, 2.5]), (315, [45, 45, 45]),
])
def test_plates_per_side(total, expected):
    assert plates_per_side(total) == expected


def test_plates_always_add_back_up_to_the_load():
    for total in range(45, 405, 5):
        assert 45 + 2 * sum(plates_per_side(total)) == total


# ---- routines --------------------------------------------------------------------------

@pytest.mark.parametrize("days", [2, 3, 4, 5, 6])
def test_each_split_has_the_requested_number_of_days(days):
    plan = generate_routine(make(days_per_week=days), flat_loads)
    assert len(plan["days"]) == days
    assert [d["day"] for d in plan["days"]] == list(range(1, days + 1))
    trained = [w for w in plan["week"] if w["day"]]
    assert len(trained) == days
    assert [w["day"] for w in trained] == list(range(1, days + 1))


@pytest.mark.parametrize("equipment,allowed", [
    ("bodyweight", {"bodyweight"}),
    ("dumbbell", {"bodyweight", "dumbbell"}),
    ("gym", {"bodyweight", "dumbbell", "gym"}),
])
def test_exercises_never_need_more_equipment_than_the_person_has(equipment, allowed):
    for days in (2, 4, 6):
        plan = generate_routine(make(equipment=equipment, days_per_week=days, session_minutes=90), flat_loads)
        used = {e["equipment"] for d in plan["days"] for e in d["exercises"]}
        assert used <= allowed


def test_bodyweight_plan_has_no_weights_and_asks_for_no_model_calls():
    calls = []
    plan = generate_routine(make(equipment="bodyweight"), lambda ids: calls.append(ids) or {})
    assert calls == []
    for day in plan["days"]:
        for e in day["exercises"]:
            assert e["kind"] == "bodyweight" and e["load_lb"] is None


def test_no_exercise_repeats_within_a_day():
    plan = generate_routine(make(days_per_week=6, session_minutes=90, equipment="gym"), flat_loads)
    for day in plan["days"]:
        ids = [e["id"] for e in day["exercises"]]
        assert len(ids) == len(set(ids))


def test_longer_sessions_hold_more_exercises():
    short = generate_routine(make(session_minutes=20), flat_loads)["days"][0]["exercises"]
    long = generate_routine(make(session_minutes=90), flat_loads)["days"][0]["exercises"]
    assert 3 <= len(short) < len(long) <= 8


def test_estimated_time_roughly_respects_the_session_length():
    for minutes in (30, 45, 60, 90):
        plan = generate_routine(make(session_minutes=minutes, days_per_week=4), flat_loads)
        for day in plan["days"]:
            assert day["estimated_minutes"] <= minutes + 10


def test_compound_lifts_come_before_isolation_work():
    plan = generate_routine(make(days_per_week=4, session_minutes=75), flat_loads)
    for day in plan["days"]:
        flags = [e["compound"] for e in day["exercises"]]
        assert flags == sorted(flags, reverse=True)


def test_core_never_dominates_a_day():
    plan = generate_routine(make(days_per_week=4, session_minutes=90, equipment="bodyweight"), flat_loads)
    for day in plan["days"]:
        assert sum(e["muscle"] == "core" for e in day["exercises"]) <= 2


def test_focus_area_gets_extra_exercises():
    plain = generate_routine(make(days_per_week=4, session_minutes=60), flat_loads)
    focused = generate_routine(make(days_per_week=4, session_minutes=60, focus=["arms"]), flat_loads)

    def arm_count(plan):
        return sum(e["muscle"] == "arms" for d in plan["days"] for e in d["exercises"])

    assert arm_count(focused) > arm_count(plain)


def test_repeated_day_types_use_different_exercises():
    plan = generate_routine(make(days_per_week=3, session_minutes=45), flat_loads)
    sets = [{e["id"] for e in d["exercises"]} for d in plan["days"]]
    assert sets[0] != sets[1] != sets[2]


def test_goal_changes_the_prescription():
    def first_lift(goal):
        plan = generate_routine(make(goal=goal, equipment="gym"), flat_loads)
        return next(e for e in plan["days"][0]["exercises"] if e["id"] == "barbell_bench_press")

    strength, muscle, fat_loss = first_lift("strength"), first_lift("hypertrophy"), first_lift("fat_loss")
    assert strength["reps"] == "5" and strength["sets"] == 4
    assert muscle["reps"] == "8-12"
    assert fat_loss["reps"] == "12-15"
    assert strength["rest_seconds"] > muscle["rest_seconds"] > fat_loss["rest_seconds"]
    assert strength["load_lb"] >= muscle["load_lb"] >= fat_loss["load_lb"]


def test_loads_snap_to_real_equipment_and_respect_minimums():
    plan = generate_routine(make(equipment="gym", days_per_week=6, session_minutes=90), lambda ids: {i: 1.0 for i in ids})
    for day in plan["days"]:
        for e in day["exercises"]:
            if e["kind"] != "weighted":
                continue
            exercise = exercises.BY_ID[e["id"]]
            assert e["load_lb"] >= exercise.min_load_lb
            assert e["load_lb"] % exercise.step_lb == 0


def test_barbell_lifts_include_plates_and_nothing_else_does():
    plan = generate_routine(make(equipment="gym", session_minutes=90), flat_loads)
    for day in plan["days"]:
        for e in day["exercises"]:
            if e["load_style"] == "barbell":
                assert e["plates_per_side"] is not None
                assert 45 + 2 * sum(e["plates_per_side"]) == e["load_lb"]
            else:
                assert e["plates_per_side"] is None


def test_bodyweight_targets_grow_with_experience():
    def push_ups(level):
        plan = generate_routine(make(equipment="bodyweight", experience=level, days_per_week=2, session_minutes=90), flat_loads)
        return int(next(e for d in plan["days"] for e in d["exercises"] if e["id"] == "push_up")["reps"])

    assert push_ups(0) < push_ups(1) < push_ups(2)


def test_every_day_type_and_pool_can_be_built():
    """Every split day works for every equipment level and goal without running out of exercises."""
    for days, (_, template) in routines.SPLITS.items():
        for name, groups, variant in template:
            for equipment in exercises.EQUIPMENT_TIERS:
                for goal in routines.GOALS:
                    for minutes in (20, 90):
                        picked = select_exercises(groups, (), equipment, goal, minutes, variant)
                        assert 3 <= len(picked) <= 8, (name, equipment, goal, minutes)


def test_routine_carries_the_honesty_note():
    plan = generate_routine(make(), flat_loads)
    assert any("synthetic" in tip for tip in plan["tips"])
