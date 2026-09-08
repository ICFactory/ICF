from pathlib import Path

from app.core.config import load_config
from app.pipeline.ingest import Ingestor


class Pipeline:
    def __init__(self, config_path="config.yaml"):
        self.config = load_config(config_path)

    def inspect(self, input_path):
        ingestor = Ingestor(self.config)
        return ingestor.inspect(input_path)

    def prepare_workspace(self):
        for key in ("input_dir", "output_dir", "temp_dir"):
            self.config.path_value(key).mkdir(
                parents=True,
                exist_ok=True,
            )

    def run(self, input_path):
        self.prepare_workspace()

        print("\nICF PIPELINE")
        print("=" * 60)
        print("Input:", input_path)

        analysis = self.inspect(input_path)

        video = analysis.video

        print(f"Duration : {video.duration:.2f}s")
        print(f"Resolution: {video.width}x{video.height}")
        print(f"FPS      : {video.fps:.2f}")
        print(f"Codec    : {video.codec}")
        print(f"Audio    : {video.audio_codec or 'none'}")

        analysis.metadata["stage"] = "ready_for_analysis"

        output = (
            self.config.path_value("output_dir")
            / "analysis"
            / "ingest.json"
        )

        output.parent.mkdir(parents=True, exist_ok=True)
        analysis.save(output)

        print("\nAnalysis manifest:")
        print(output)
        print("\nSTATUS: INGESTION READY")

        return analysis
