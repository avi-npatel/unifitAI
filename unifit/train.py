"""Train the model from the command line:  python -m unifit.train"""

import argparse
import json

from . import data_gen, model as model_module
from .config import Config


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the synthetic dataset and train the model.")
    parser.add_argument("--rows", type=int, default=15_000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    config = Config.from_env()
    frame = data_gen.generate(n_rows=args.rows, seed=args.seed)
    config.dataset_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(config.dataset_path, index=False)

    trained = model_module.train(seed=args.seed, frame=frame)
    model_module.save(trained, config.model_path)

    print(f"Dataset: {len(frame):,} rows -> {config.dataset_path}")
    print(f"Model:   {config.model_path}")
    print(json.dumps(trained.metrics, indent=2))


if __name__ == "__main__":
    main()
