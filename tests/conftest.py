import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unifit import model as model_module  # noqa: E402


@pytest.fixture(scope="session")
def trained_model():
    """A small model keeps the suite fast; the real one trains on 15,000 rows."""
    return model_module.train(n_rows=4000, seed=7)
