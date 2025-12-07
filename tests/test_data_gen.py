from unifit import data_gen
from unifit.exercises import BY_ID, WEIGHTED


def test_default_size_and_columns():
    frame = data_gen.generate()
    assert len(frame) == 15_000
    assert list(frame.columns) == data_gen.COLUMNS
    assert len(data_gen.COLUMNS) == 7


def test_same_seed_gives_same_data():
    a = data_gen.generate(n_rows=500, seed=3)
    b = data_gen.generate(n_rows=500, seed=3)
    assert a.equals(b)
    assert not a.equals(data_gen.generate(n_rows=500, seed=4))


def test_ranges_match_the_original_project():
    frame = data_gen.generate()
    assert frame.height_in.between(48, 80).all()
    assert frame.age.between(16, 75).all()
    assert set(frame.sex) == {"male", "female"}
    assert set(frame.experience) == {0, 1, 2}
    assert frame.weight_lb.between(60, 330).all()


def test_every_weighted_exercise_appears():
    frame = data_gen.generate()
    assert set(frame.exercise) == {e.id for e in WEIGHTED}


def test_targets_respect_minimum_loads_and_rounding():
    frame = data_gen.generate()
    minimums = frame.exercise.map(lambda i: BY_ID[i].min_load_lb)
    assert (frame.target_weight_lb >= minimums).all()
    assert (frame.target_weight_lb % 2.5 == 0).all()


def test_noise_free_rows_match_the_scalar_formula():
    frame = data_gen.generate(n_rows=300, seed=1, noise=0.0)
    for row in frame.itertuples():
        expected = data_gen.expected_load(
            BY_ID[row.exercise], row.weight_lb, row.age, row.sex, int(row.experience))
        assert row.target_weight_lb == expected


def test_strength_ordering_makes_physical_sense():
    squat = BY_ID["barbell_back_squat"]
    base = data_gen.expected_load(squat, 170, 25, "male", 0)
    assert data_gen.expected_load(squat, 170, 25, "male", 2) > data_gen.expected_load(squat, 170, 25, "male", 1) > base
    assert data_gen.expected_load(squat, 220, 25, "male", 0) > base          # heavier lifter
    assert data_gen.expected_load(squat, 170, 60, "male", 0) < base          # older lifter
    assert data_gen.expected_load(squat, 170, 25, "female", 0) < base        # sex factor
    bench = BY_ID["barbell_bench_press"]
    female_gap_upper = data_gen.expected_load(bench, 170, 25, "female", 1) / data_gen.expected_load(bench, 170, 25, "male", 1)
    female_gap_lower = data_gen.expected_load(squat, 170, 25, "female", 1) / data_gen.expected_load(squat, 170, 25, "male", 1)
    assert female_gap_upper < female_gap_lower


def test_age_factor_is_flat_then_declines():
    assert float(data_gen.age_factor(20)) == 1.0
    assert float(data_gen.age_factor(30)) == 1.0
    assert 0.55 <= float(data_gen.age_factor(90)) < float(data_gen.age_factor(50)) < 1.0
