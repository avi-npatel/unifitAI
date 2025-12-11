"""Turns a person's measurements and preferences into a weekly routine.

The model supplies starting weights. This module decides everything else: how many days,
what each day trains, which exercises fit the available equipment and time, and the sets,
reps and rest for the chosen goal.
"""

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .exercises import (BARBELL, BY_ID, EQUIPMENT_TIERS, GROUPS, PER_HAND, SINGLE, STACK,
                        Exercise, available)

GOALS = ("strength", "hypertrophy", "fat_loss")
SEXES = ("male", "female", "other")
EXPERIENCE_NAMES = {"beginner": 0, "intermediate": 1, "advanced": 2}

# Abs recover quickly and fill out a day without needing many exercises.
GROUP_CAP = {"core": 2}

WARMUP_MINUTES = 5
SECONDS_PER_SET = 40
BAR_WEIGHT_LB = 45
PLATES_LB = (45, 35, 25, 10, 5, 2.5)
GOAL_LOAD_FACTOR = {"strength": 1.12, "hypertrophy": 1.0, "fat_loss": 0.85}

PUSH = ("chest", "shoulders", "arms")
PULL = ("back", "arms", "core")
LEGS = ("legs", "core")
UPPER = ("chest", "back", "shoulders", "arms")
FULL = ("legs", "chest", "back", "shoulders", "core", "arms")

# (name, muscle groups, variant). A repeated day type uses a different variant so the
# second session picks different exercises.
SPLITS: Dict[int, Tuple[str, List[Tuple[str, Tuple[str, ...], int]]]] = {
    2: ("Full body", [("Full body A", FULL, 0), ("Full body B", FULL, 1)]),
    3: ("Full body", [("Full body A", FULL, 0), ("Full body B", FULL, 1), ("Full body C", FULL, 2)]),
    4: ("Upper / lower", [("Upper A", UPPER, 0), ("Lower A", LEGS, 0),
                          ("Upper B", UPPER, 1), ("Lower B", LEGS, 1)]),
    5: ("Push / pull / legs, upper / lower", [("Push", PUSH, 0), ("Pull", PULL, 0), ("Legs", LEGS, 0),
                                              ("Upper", UPPER, 1), ("Lower", LEGS, 1)]),
    6: ("Push / pull / legs, twice a week", [("Push A", PUSH, 0), ("Pull A", PULL, 0), ("Legs A", LEGS, 0),
                                             ("Push B", PUSH, 1), ("Pull B", PULL, 1), ("Legs B", LEGS, 1)]),
}
# Monday is 0, matching datetime.weekday().
WEEKDAYS = {2: (0, 3), 3: (0, 2, 4), 4: (0, 1, 3, 4), 5: (0, 1, 2, 4, 5), 6: (0, 1, 2, 3, 4, 5)}

# (sets, reps, rest seconds, load factor) for compound and isolation work by goal.
Scheme = Tuple[int, str, int, float]
SCHEMES: Dict[str, Dict[str, Scheme]] = {
    "strength":    {"compound": (4, "5", 150, 1.12),     "isolation": (3, "10", 75, 1.0)},
    "hypertrophy": {"compound": (3, "8-12", 90, 1.0),    "isolation": (3, "10-15", 60, 1.0)},
    "fat_loss":    {"compound": (3, "12-15", 45, 0.85),  "isolation": (3, "15-20", 30, 0.85)},
}
BODYWEIGHT_REST = {"strength": 90, "hypertrophy": 60, "fat_loss": 30}

TIPS = {
    "strength": "Rest the full time between heavy sets. When all four sets of a lift feel solid, add 5 lb next week.",
    "hypertrophy": "Stop each set with one or two good reps left. When you reach the top of the rep range on every set, add 5 lb.",
    "fat_loss": "Keep rests short and the pace steady. Walk for 10 minutes after each session if you have the energy.",
}
GENERAL_NOTE = ("Starting weights are estimates from a model trained on synthetic data. "
                "If a weight feels wrong on your first set, move it up or down until the last reps are hard but your form holds.")


class ProfileError(ValueError):
    """Invalid input. `fields` maps each bad field to a message a person can act on."""

    def __init__(self, fields: Mapping[str, str]):
        super().__init__("; ".join(fields.values()))
        self.fields = dict(fields)


@dataclass(frozen=True)
class Profile:
    age: int
    height_in: float
    weight_lb: float
    sex: str
    experience: int
    goal: str = "hypertrophy"
    days_per_week: int = 3
    equipment: str = "gym"
    session_minutes: int = 45
    focus: Tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "Profile":
        errors: Dict[str, str] = {}

        def number(field, low, high, label, whole=False, default=None):
            raw = data.get(field, default)
            if raw is None or raw == "" or isinstance(raw, bool):
                errors[field] = f"Enter your {label}."
                return None
            try:
                value = float(raw)
            except (TypeError, ValueError):
                errors[field] = f"Enter your {label} as a number."
                return None
            if value != value or not (low <= value <= high):  # NaN fails the range test too
                errors[field] = f"Your {label} should be between {low:g} and {high:g}."
                return None
            if whole and value != int(value):
                errors[field] = f"Enter your {label} as a whole number."
                return None
            return int(value) if whole else value

        def choice(field, options, label, default=None):
            raw = data.get(field, default)
            if not isinstance(raw, str) or raw not in options:
                errors[field] = f"Choose {label}: {', '.join(options)}."
                return None
            return raw

        age = number("age", 14, 90, "age", whole=True)
        height = number("height_in", 48, 84, "height in inches")
        weight = number("weight_lb", 70, 500, "weight in pounds")
        sex = choice("sex", SEXES, "a sex")
        goal = choice("goal", GOALS, "a goal", default="hypertrophy")
        equipment = choice("equipment", EQUIPMENT_TIERS, "your equipment", default="gym")
        days = number("days_per_week", 2, 6, "training days per week", whole=True, default=3)
        minutes = number("session_minutes", 20, 90, "session length in minutes", whole=True, default=45)

        raw_exp = data.get("experience")
        experience = None
        if isinstance(raw_exp, str) and raw_exp.lower() in EXPERIENCE_NAMES:
            experience = EXPERIENCE_NAMES[raw_exp.lower()]
        elif not isinstance(raw_exp, bool) and raw_exp in (0, 1, 2):
            experience = int(raw_exp)
        else:
            errors["experience"] = "Choose beginner, intermediate, or advanced."

        raw_focus = data.get("focus", []) or []
        focus: List[str] = []
        if not isinstance(raw_focus, (list, tuple)) or any(g not in GROUPS for g in raw_focus):
            errors["focus"] = f"Focus areas must come from: {', '.join(GROUPS)}."
        else:
            focus = list(dict.fromkeys(raw_focus))
            if len(focus) > 2:
                errors["focus"] = "Pick up to two focus areas."

        if errors:
            raise ProfileError(errors)
        return cls(age=age, height_in=height, weight_lb=weight, sex=sex, experience=experience,
                   goal=goal, days_per_week=days, equipment=equipment, session_minutes=minutes,
                   focus=tuple(focus))

    def as_dict(self) -> Dict[str, object]:
        return {
            "age": self.age, "height_in": self.height_in, "weight_lb": self.weight_lb,
            "sex": self.sex, "experience": self.experience, "goal": self.goal,
            "days_per_week": self.days_per_week, "equipment": self.equipment,
            "session_minutes": self.session_minutes, "focus": list(self.focus),
        }


def plates_per_side(total_lb: float, bar_lb: float = BAR_WEIGHT_LB,
                    plates: Sequence[float] = PLATES_LB) -> List[float]:
    """Plates to load on each side of a barbell, largest first."""
    remaining = max(0.0, (total_lb - bar_lb) / 2)
    result: List[float] = []
    for plate in plates:
        while remaining + 1e-9 >= plate:
            result.append(plate)
            remaining -= plate
    return result


def _pool(group: str, equipment: str, variant: int) -> List[Exercise]:
    pool = available(group, equipment)
    if pool and variant:
        shift = variant % len(pool)
        pool = pool[shift:] + pool[:shift]
    return pool


def _scheme(goal: str, exercise: Exercise) -> Scheme:
    return SCHEMES[goal]["compound" if exercise.compound else "isolation"]


def _exercise_minutes(goal: str, exercise: Exercise) -> float:
    if exercise.weighted:
        sets, _, rest, _ = _scheme(goal, exercise)
    else:
        sets, rest = 3, BODYWEIGHT_REST[goal]
    return sets * (SECONDS_PER_SET + rest) / 60


def select_exercises(groups: Sequence[str], focus: Sequence[str], equipment: str,
                     goal: str, session_minutes: int, variant: int = 0) -> List[Exercise]:
    """Pick exercises that cover the day's muscle groups and fit in the time budget."""
    groups = list(groups)
    if variant and len(groups) > 2:
        # Keep the first group (the big lower-body or pressing lift) and rotate the rest,
        # so a second full-body day leads with different upper-body work.
        rest = groups[1:]
        shift = variant % len(rest)
        groups = [groups[0]] + rest[shift:] + rest[:shift]

    pools = {g: _pool(g, equipment, variant) for g in groups}
    limits = {g: min(len(pools[g]), GROUP_CAP.get(g, len(pools[g])) + (1 if g in focus and g in GROUP_CAP else 0))
              for g in groups}
    order: List[str] = []
    for g in groups:
        order.append(g)
        if g in focus:
            order.append(g)  # focus groups get a second pick per round

    pointer = {g: 0 for g in groups}
    candidates: List[Exercise] = []
    while len(candidates) < 8:
        progressed = False
        for g in order:
            if len(candidates) >= 8:
                break
            if pointer[g] < limits[g]:
                candidates.append(pools[g][pointer[g]])
                pointer[g] += 1
                progressed = True
        if not progressed:
            break

    budget = session_minutes - WARMUP_MINUTES
    chosen: List[Exercise] = []
    spent = 0.0
    for exercise in candidates:
        cost = _exercise_minutes(goal, exercise)
        if len(chosen) >= 3 and spent + cost > budget:
            break
        chosen.append(exercise)
        spent += cost

    # Heavy compound lifts first, while you are fresh.
    return sorted(chosen, key=lambda e: (not e.compound, e.priority))


def _round_step(value: float, step: float) -> float:
    return round(value / step) * step


def _load_note(exercise: Exercise) -> str:
    return {
        BARBELL: "total, including the 45 lb bar",
        STACK: "machine or cable setting",
        PER_HAND: "per hand",
        SINGLE: "one dumbbell, both hands",
    }[exercise.load_style]


def _prescribe(profile: Profile, exercise: Exercise, predicted: Optional[float]) -> Dict[str, object]:
    goal = profile.goal
    row: Dict[str, object] = {
        "id": exercise.id, "name": exercise.name, "muscle": exercise.group,
        "equipment": exercise.equipment, "compound": exercise.compound, "cue": exercise.cue,
    }
    if exercise.weighted:
        sets, reps, rest, factor = _scheme(goal, exercise)
        load = _round_step(predicted * factor, exercise.step_lb)
        load = max(load, exercise.min_load_lb)
        row.update({
            "kind": "weighted", "sets": sets, "reps": reps, "rest_seconds": rest,
            "load_lb": load, "load_style": exercise.load_style, "load_note": _load_note(exercise),
            "plates_per_side": plates_per_side(load) if exercise.load_style == BARBELL else None,
        })
    else:
        target = exercise.reps[profile.experience]
        row.update({
            "kind": "bodyweight", "sets": 3, "reps": str(target), "unit": exercise.unit,
            "rest_seconds": BODYWEIGHT_REST[goal],
            "load_lb": None, "load_style": None, "load_note": None, "plates_per_side": None,
        })
    return row


def _round_minutes(minutes: float) -> int:
    return int(round(minutes / 5.0) * 5)


def generate_routine(profile: Profile, loads_for) -> Dict[str, object]:
    """Build the full weekly plan.

    `loads_for(exercise_ids)` returns {exercise_id: predicted_working_weight_lb}. Passing a
    function keeps this module free of any model dependency, which makes it easy to test.
    """
    split_name, template = SPLITS[profile.days_per_week]
    days = []
    for index, (name, groups, variant) in enumerate(template):
        exercises = select_exercises(
            groups, profile.focus, profile.equipment, profile.goal,
            profile.session_minutes, variant)
        weighted_ids = [e.id for e in exercises if e.weighted]
        predictions = loads_for(weighted_ids) if weighted_ids else {}
        rows = [_prescribe(profile, e, predictions.get(e.id)) for e in exercises]
        minutes = WARMUP_MINUTES + sum(_exercise_minutes(profile.goal, e) for e in exercises)
        days.append({
            "day": index + 1, "name": name, "muscles": list(groups),
            "estimated_minutes": _round_minutes(minutes), "exercises": rows,
        })

    weekdays = WEEKDAYS[profile.days_per_week]
    week = [{"weekday": d, "day": weekdays.index(d) + 1 if d in weekdays else None} for d in range(7)]
    return {
        "profile": profile.as_dict(),
        "summary": {
            "split": split_name,
            "days_per_week": profile.days_per_week,
            "goal": profile.goal,
            "equipment": profile.equipment,
            "total_exercises": sum(len(d["exercises"]) for d in days),
        },
        "week": week,
        "days": days,
        "tips": [TIPS[profile.goal], GENERAL_NOTE],
    }
