"""Random forest that predicts a working weight for one person and one exercise."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from . import data_gen
from .data_gen import FEATURES, TARGET

log = logging.getLogger("unifit.model")

NUMERIC = ["height_in", "weight_lb", "age", "experience"]
CATEGORICAL = ["sex", "exercise"]


def build_pipeline(seed: int = 42) -> Pipeline:
    encode = ColumnTransformer(
        [("categories", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL)],
        remainder="passthrough",
    )
    forest = RandomForestRegressor(
        n_estimators=200, min_samples_leaf=3, n_jobs=-1, random_state=seed)
    return Pipeline([("encode", encode), ("forest", forest)])


def evaluate(pipeline: Pipeline, test: pd.DataFrame) -> Dict[str, float]:
    predicted = pipeline.predict(test[FEATURES])
    actual = test[TARGET].to_numpy()
    return {
        "r2": float(r2_score(actual, predicted)),
        "mae_lb": float(mean_absolute_error(actual, predicted)),
        # Share of held-out rows where the prediction is within 10% of the generated weight.
        "within_10_percent": float(np.mean(np.abs(predicted - actual) <= 0.10 * actual)),
    }


@dataclass
class WeightModel:
    pipeline: Pipeline
    metrics: Dict[str, object]

    def predict_loads(self, height_in: float, weight_lb: float, age: int, sex: str,
                      experience: int, exercise_ids: Iterable[str]) -> Dict[str, float]:
        """Predicted working weight in pounds for each exercise id.

        The model only saw male and female rows, so "other" averages both predictions.
        """
        ids = list(exercise_ids)
        if not ids:
            return {}
        sexes = ["male", "female"] if sex == "other" else [sex]
        frames = []
        for s in sexes:
            frames.append(pd.DataFrame({
                "height_in": height_in, "weight_lb": weight_lb, "age": age,
                "sex": s, "experience": experience, "exercise": ids,
            })[FEATURES])
        predictions = np.mean([self.pipeline.predict(f) for f in frames], axis=0)
        return {i: max(0.0, float(p)) for i, p in zip(ids, predictions)}


def train(n_rows: int = 15_000, seed: int = 42, test_size: float = 0.2,
          frame: Optional[pd.DataFrame] = None) -> WeightModel:
    """Generate data (unless given), hold out a test split, fit, and measure."""
    if frame is None:
        frame = data_gen.generate(n_rows=n_rows, seed=seed)
    train_set, test_set = train_test_split(frame, test_size=test_size, random_state=seed)

    pipeline = build_pipeline(seed)
    pipeline.fit(train_set[FEATURES], train_set[TARGET])

    metrics = evaluate(pipeline, test_set)
    metrics.update({
        "algorithm": "RandomForestRegressor",
        "rows_total": int(len(frame)),
        "rows_train": int(len(train_set)),
        "rows_test": int(len(test_set)),
        "features": FEATURES,
        "data": "synthetic",
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sklearn_version": sklearn.__version__,
    })
    return WeightModel(pipeline, metrics)


def save(model: WeightModel, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipeline": model.pipeline, "metrics": model.metrics}, path)


def load(path: Path) -> Optional[WeightModel]:
    """Load a saved model, or return None if it is missing or from another scikit-learn."""
    if not path.is_file():
        return None
    try:
        blob = joblib.load(path)
        if blob["metrics"].get("sklearn_version") != sklearn.__version__:
            log.info("Saved model was built with another scikit-learn; retraining.")
            return None
        return WeightModel(blob["pipeline"], blob["metrics"])
    except Exception:  # corrupt or incompatible file: retrain instead of crashing
        log.warning("Could not read %s; retraining.", path, exc_info=True)
        return None


def ensure_model(path: Path) -> WeightModel:
    """Load the saved model, training and saving one first if needed."""
    model = load(path)
    if model is None:
        log.info("Training a new model (about 10 seconds)...")
        model = train()
        save(model, path)
    return model
