import pytest

from unifit import model as model_module


def test_metrics_are_reported_and_sensible(trained_model):
    m = trained_model.metrics
    assert m["rows_train"] + m["rows_test"] == m["rows_total"] == 4000
    assert m["rows_test"] == 800
    assert m["r2"] > 0.9
    assert 0 < m["mae_lb"] < 15
    assert 0.4 < m["within_10_percent"] <= 1.0
    assert m["data"] == "synthetic"


def test_predictions_follow_experience_and_size(trained_model):
    def squat(experience, weight=170, sex="male", age=25):
        return trained_model.predict_loads(70, weight, age, sex, experience, ["barbell_back_squat"])["barbell_back_squat"]

    assert squat(2) > squat(1) > squat(0)
    assert squat(1, weight=230) > squat(1, weight=140)
    assert squat(1, sex="female") < squat(1, sex="male")


def test_other_sex_sits_between_male_and_female(trained_model):
    args = (68, 160, 30)
    male = trained_model.predict_loads(*args, "male", 1, ["barbell_bench_press"])["barbell_bench_press"]
    female = trained_model.predict_loads(*args, "female", 1, ["barbell_bench_press"])["barbell_bench_press"]
    other = trained_model.predict_loads(*args, "other", 1, ["barbell_bench_press"])["barbell_bench_press"]
    assert female <= other <= male
    assert other == pytest.approx((male + female) / 2)


def test_empty_request_returns_empty(trained_model):
    assert trained_model.predict_loads(70, 170, 25, "male", 0, []) == {}


def test_save_and_load_round_trip(trained_model, tmp_path):
    path = tmp_path / "model.joblib"
    model_module.save(trained_model, path)
    loaded = model_module.load(path)
    ids = ["deadlift", "db_curl"]
    # Forest predictions sum trees across threads, so the last float bits can differ between calls.
    assert loaded.predict_loads(70, 170, 25, "male", 1, ids) == pytest.approx(
        trained_model.predict_loads(70, 170, 25, "male", 1, ids))


def test_load_ignores_missing_and_corrupt_files(tmp_path):
    assert model_module.load(tmp_path / "nope.joblib") is None
    bad = tmp_path / "bad.joblib"
    bad.write_bytes(b"not a model")
    assert model_module.load(bad) is None


def test_load_rejects_model_from_another_sklearn_version(trained_model, tmp_path):
    stale = model_module.WeightModel(trained_model.pipeline, {**trained_model.metrics, "sklearn_version": "0.0.1"})
    path = tmp_path / "stale.joblib"
    model_module.save(stale, path)
    assert model_module.load(path) is None
