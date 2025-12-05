"""The exercise catalog.

Each exercise belongs to one muscle group and needs one equipment tier. Tiers nest:
a gym has dumbbells, and every tier allows bodyweight work.

Weighted exercises carry `ref_load_lb`, the working weight for a beginner man aged 30
or under who weighs 170 lb. The data generator scales it for body size, sex, age and
experience, and the model learns those relationships back from the generated rows.
Bodyweight exercises carry rep targets by experience level instead.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

GROUPS = ("chest", "back", "shoulders", "arms", "legs", "core")
EQUIPMENT_TIERS = ("bodyweight", "dumbbell", "gym")  # each tier includes the ones before it

# Load styles describe how the number on screen should be read.
BARBELL = "barbell"      # total weight on the bar, including the 45 lb bar
STACK = "stack"          # machine or cable stack setting
PER_HAND = "per_hand"    # one dumbbell in each hand
SINGLE = "single"        # one dumbbell held with both hands


@dataclass(frozen=True)
class Exercise:
    id: str
    name: str
    group: str
    equipment: str
    compound: bool
    cue: str
    priority: int = 50
    ref_load_lb: Optional[float] = None
    min_load_lb: float = 0.0
    step_lb: float = 5.0
    load_style: str = ""
    reps: Optional[Tuple[int, int, int]] = None  # beginner, intermediate, advanced
    unit: str = "reps"

    @property
    def weighted(self) -> bool:
        return self.ref_load_lb is not None


def _w(id, name, group, equipment, compound, cue, priority, ref, minimum, style, step=5.0):
    return Exercise(id, name, group, equipment, compound, cue, priority,
                    ref_load_lb=ref, min_load_lb=minimum, step_lb=step, load_style=style)


def _b(id, name, group, compound, cue, priority, reps, unit="reps"):
    return Exercise(id, name, group, "bodyweight", compound, cue, priority, reps=reps, unit=unit)


CATALOG: List[Exercise] = [
    # Chest
    _w("barbell_bench_press", "Barbell bench press", "chest", "gym", True,
       "Shoulder blades pinched, feet planted, lower to mid-chest.", 10, 85, 45, BARBELL),
    _w("db_bench_press", "Dumbbell bench press", "chest", "dumbbell", True,
       "Elbows about 45 degrees from your torso, press up and slightly in.", 20, 30, 10, PER_HAND),
    _w("db_fly", "Dumbbell fly", "chest", "dumbbell", False,
       "Soft elbows, open until you feel a stretch across the chest, then hug the arc back.", 22, 15, 5, PER_HAND),
    _w("machine_chest_press", "Machine chest press", "chest", "gym", True,
       "Set the handles at mid-chest height and push without shrugging.", 30, 80, 30, STACK),
    _b("push_up", "Push-up", "chest", True,
       "Body in one line from head to heels, chest to the floor.", 80, (8, 15, 25)),
    _b("wide_push_up", "Wide push-up", "chest", True,
       "Hands wider than shoulders, keep ribs down.", 85, (6, 12, 20)),
    _b("decline_push_up", "Decline push-up", "chest", True,
       "Feet on a chair or bench, same straight body line.", 86, (5, 10, 18)),

    # Back
    _w("barbell_row", "Barbell row", "back", "gym", True,
       "Hinge to a flat back and pull the bar to your lower ribs.", 10, 75, 45, BARBELL),
    _w("lat_pulldown", "Lat pulldown", "back", "gym", True,
       "Pull the bar to your upper chest and lead with the elbows.", 15, 80, 30, STACK),
    _w("db_row", "One-arm dumbbell row", "back", "dumbbell", True,
       "Hand on a bench, pull the dumbbell to your hip, no twisting.", 20, 35, 10, PER_HAND),
    _w("seated_cable_row", "Seated cable row", "back", "gym", True,
       "Sit tall, pull the handle to your belly, pause, return slowly.", 25, 70, 30, STACK),
    _b("superman", "Superman", "back", False,
       "Lie face down, lift arms and legs together, hold one second at the top.", 80, (10, 15, 20)),
    _b("reverse_snow_angel", "Reverse snow angel", "back", False,
       "Face down, sweep straight arms from your sides to overhead with palms down.", 85, (10, 15, 20)),

    # Shoulders
    _w("overhead_press", "Barbell overhead press", "shoulders", "gym", True,
       "Squeeze glutes, press straight up, head moves through at the top.", 10, 55, 45, BARBELL),
    _w("db_shoulder_press", "Dumbbell shoulder press", "shoulders", "dumbbell", True,
       "Start with palms forward at ear height, press until arms are straight.", 20, 22, 10, PER_HAND),
    _w("db_lateral_raise", "Dumbbell lateral raise", "shoulders", "dumbbell", False,
       "Lift out to the sides to shoulder height, lead with the elbows.", 30, 10, 5, PER_HAND),
    _w("cable_face_pull", "Cable face pull", "shoulders", "gym", False,
       "Pull the rope toward your forehead with elbows high.", 35, 30, 10, STACK),
    _b("pike_push_up", "Pike push-up", "shoulders", True,
       "Hips high in an upside-down V, lower the top of your head toward the floor.", 80, (5, 10, 15)),
    _b("plank_shoulder_tap", "Plank shoulder tap", "shoulders", False,
       "From a plank, tap each shoulder while keeping your hips still.", 85, (10, 20, 30)),

    # Arms
    _w("db_curl", "Dumbbell curl", "arms", "dumbbell", False,
       "Elbows stay at your sides, curl up and lower for a slow count of three.", 15, 15, 5, PER_HAND),
    _w("cable_triceps_pushdown", "Cable triceps pushdown", "arms", "gym", False,
       "Pin your elbows to your ribs and straighten fully.", 20, 40, 15, STACK),
    _w("cable_biceps_curl", "Cable biceps curl", "arms", "gym", False,
       "Stand close to the stack, curl without leaning back.", 25, 30, 10, STACK),
    _w("db_triceps_extension", "Overhead triceps extension", "arms", "dumbbell", False,
       "Hold one dumbbell with both hands overhead, bend at the elbows only.", 30, 20, 5, SINGLE),
    _b("chair_dip", "Chair dip", "arms", False,
       "Hands on a sturdy chair, lower until your elbows reach 90 degrees.", 80, (6, 12, 20)),
    _b("diamond_push_up", "Diamond push-up", "arms", True,
       "Hands close under your chest, elbows brush your ribs.", 85, (4, 8, 15)),

    # Legs
    _w("barbell_back_squat", "Barbell back squat", "legs", "gym", True,
       "Brace, sit between your hips, knees track over toes, drive up through mid-foot.", 10, 95, 45, BARBELL),
    _w("deadlift", "Deadlift", "legs", "gym", True,
       "Bar over mid-foot, flat back, push the floor away.", 11, 115, 65, BARBELL),
    _w("leg_press", "Leg press", "legs", "gym", True,
       "Feet shoulder width, lower until knees reach 90 degrees, don't lock out hard.", 20, 180, 90, STACK, 10.0),
    _w("goblet_squat", "Goblet squat", "legs", "dumbbell", True,
       "Hold one dumbbell at your chest, elbows inside your knees at the bottom.", 21, 35, 10, SINGLE),
    _w("db_romanian_deadlift", "Dumbbell Romanian deadlift", "legs", "dumbbell", True,
       "Push hips back with soft knees, dumbbells slide down your thighs.", 22, 30, 10, PER_HAND),
    _w("leg_curl", "Leg curl", "legs", "gym", False,
       "Curl heels toward glutes and lower under control.", 25, 60, 20, STACK),
    _w("db_lunge", "Dumbbell reverse lunge", "legs", "dumbbell", True,
       "Step back, drop the back knee toward the floor, push through the front heel.", 31, 20, 5, PER_HAND),
    _b("split_squat", "Split squat", "legs", True,
       "Long stance, lower straight down, back knee hovers over the floor. Reps are per leg.", 80, (6, 10, 14)),
    _b("reverse_lunge", "Reverse lunge", "legs", True,
       "Step back and lower until both knees bend to 90 degrees. Reps are per leg.", 81, (8, 12, 16)),
    _b("glute_bridge", "Glute bridge", "legs", False,
       "Feet flat, drive hips up and squeeze for one second at the top.", 82, (12, 20, 30)),
    _b("bodyweight_squat", "Bodyweight squat", "legs", True,
       "Sit back and down, chest up, stand tall at the top.", 83, (12, 20, 30)),

    # Core
    _w("cable_crunch", "Cable crunch", "core", "gym", False,
       "Kneel under the rope and curl your ribs toward your hips.", 20, 50, 20, STACK),
    _b("plank", "Plank", "core", False,
       "Forearms down, ribs tucked, squeeze glutes. Hold for the time listed.", 30, (20, 40, 75), "sec"),
    _b("dead_bug", "Dead bug", "core", False,
       "Press your lower back into the floor and lower opposite arm and leg slowly. Reps are per side.", 35, (8, 12, 16)),
    _b("mountain_climber", "Mountain climber", "core", False,
       "From a plank, drive knees toward your chest at a steady pace. Reps are per side.", 40, (20, 40, 60)),
    _b("bicycle_crunch", "Bicycle crunch", "core", False,
       "Rotate your ribcage toward the opposite knee, no neck pulling.", 45, (12, 20, 30)),
]

BY_ID: Dict[str, Exercise] = {e.id: e for e in CATALOG}
WEIGHTED: List[Exercise] = [e for e in CATALOG if e.weighted]


def available(group: str, equipment: str) -> List[Exercise]:
    """Exercises for a muscle group that someone with this equipment can do, best first."""
    level = EQUIPMENT_TIERS.index(equipment)
    pool = [e for e in CATALOG
            if e.group == group and EQUIPMENT_TIERS.index(e.equipment) <= level]
    return sorted(pool, key=lambda e: (e.priority, e.id))
