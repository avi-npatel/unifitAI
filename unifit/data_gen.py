"""Synthetic training data.

Real lifting logs with height, weight, age and working weights are hard to find, so the
dataset is generated from a strength model with noise. This is the same approach the
original hackathon project took (10,000 rows, heights from 48 to 80 inches). Because the
rows come from a formula, a model trained on them can only learn that formula. It is a
sensible starting-weight heuristic, not a measurement of real people.

Strength model, per row:
  load = ref_load * (weight / 170) ** 0.67   body size (strength scales with mass^(2/3))
                  * sex_factor[muscle group]
                  * age_factor
                  * experience_factor
                  * lognormal noise
  then rounded to 2.5 lb and floored at the lightest weight that exercise can be loaded with.
"""

from typing import Dict

import numpy as np
import pandas as pd

from .exercises import WEIGHTED, Exercise

FEATURES = ["height_in", "weight_lb", "age", "sex", "experience", "exercise"]
TARGET = "target_weight_lb"
COLUMNS = FEATURES + [TARGET]

REFERENCE_WEIGHT_LB = 170.0
SIZE_EXPONENT = 0.67
EXPERIENCE_FACTOR = (1.0, 1.45, 1.9)  # beginner, intermediate, advanced
SEX_FACTOR: Dict[str, Dict[str, float]] = {
    "male": {"upper": 1.0, "lower": 1.0},
    "female": {"upper": 0.62, "lower": 0.78},
}
LOWER_GROUPS = {"legs", "core"}

HEIGHT_RANGE = (48.0, 80.0)
AGE_RANGE = (16, 75)
BMI_RANGE = (17.0, 42.0)


def age_factor(age):
    """Flat to 30, then a gradual decline of 0.8 percentage points per year, floored at 0.55."""
    return np.clip(1.0 - 0.008 * (np.asarray(age, dtype=float) - 30.0), 0.55, 1.0).clip(max=1.0)


def sex_factor(sex: str, group: str) -> float:
    return SEX_FACTOR[sex]["lower" if group in LOWER_GROUPS else "upper"]


def round_to_half_step(values):
    return np.round(np.asarray(values, dtype=float) / 2.5) * 2.5


def expected_load(exercise: Exercise, weight_lb: float, age: float, sex: str, experience: int) -> float:
    """The noise-free working weight for one person and exercise, before rounding."""
    size = (weight_lb / REFERENCE_WEIGHT_LB) ** SIZE_EXPONENT
    raw = (exercise.ref_load_lb * size * sex_factor(sex, exercise.group)
           * float(age_factor(age)) * EXPERIENCE_FACTOR[experience])
    return max(float(round_to_half_step(raw)), exercise.min_load_lb)


def generate(n_rows: int = 15_000, seed: int = 42, noise: float = 0.09) -> pd.DataFrame:
    """Build the dataset. `noise` is the sigma of the multiplicative lognormal noise."""
    rng = np.random.default_rng(seed)

    sex = rng.choice(["male", "female"], size=n_rows)
    is_male = sex == "male"
    height = rng.normal(np.where(is_male, 69.5, 64.0), 2.8, size=n_rows)
    height = np.clip(height, *HEIGHT_RANGE).round(1)

    bmi = np.clip(rng.normal(26.0, 4.5, size=n_rows), *BMI_RANGE)
    weight = (bmi * height ** 2 / 703.0).round(1)  # BMI = 703 * lb / in^2

    age = np.clip(rng.normal(34, 12, size=n_rows), *AGE_RANGE).round().astype(int)
    experience = rng.choice([0, 1, 2], size=n_rows, p=[0.45, 0.40, 0.15])

    ids = np.array([e.id for e in WEIGHTED])
    exercise = rng.choice(ids, size=n_rows)

    ref = {e.id: e for e in WEIGHTED}
    ref_load = np.array([ref[i].ref_load_lb for i in exercise])
    minimum = np.array([ref[i].min_load_lb for i in exercise])
    lower = np.array([ref[i].group in LOWER_GROUPS for i in exercise])

    upper_f = np.where(is_male, SEX_FACTOR["male"]["upper"], SEX_FACTOR["female"]["upper"])
    lower_f = np.where(is_male, SEX_FACTOR["male"]["lower"], SEX_FACTOR["female"]["lower"])
    sex_f = np.where(lower, lower_f, upper_f)

    load = (ref_load * (weight / REFERENCE_WEIGHT_LB) ** SIZE_EXPONENT * sex_f
            * age_factor(age) * np.array(EXPERIENCE_FACTOR)[experience])
    if noise > 0:
        load = load * rng.lognormal(mean=0.0, sigma=noise, size=n_rows)
    load = np.maximum(round_to_half_step(load), minimum)

    return pd.DataFrame({
        "height_in": height,
        "weight_lb": weight,
        "age": age,
        "sex": sex,
        "experience": experience,
        "exercise": exercise,
        TARGET: load,
    })[COLUMNS]
