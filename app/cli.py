import argparse

from app.pipeline.pipeline import Pipeline


def main():
    parser = argparse.ArgumentParser(
        description="Intelligent Content Factory"
    )

    parser.add_argument(
        "input",
        help="Path to the source video",
    )

    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Configuration file",
    )

    args = parser.parse_args()

    pipeline = Pipeline(args.config)
    pipeline.run(args.input)


if __name__ == "__main__":
    main()
