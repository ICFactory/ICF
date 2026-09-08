from pathlib import Path

from app.core.models import VideoAnalysis
from app.media.ffmpeg import FFmpeg


SUPPORTED_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
    ".m4v",
}


class Ingestor:
    def __init__(self, config):
        self.config = config
        self.ffmpeg = FFmpeg(
            config.get("ffmpeg", "executable", default="")
        )

    def inspect(self, input_path):
        input_path = Path(input_path)

        if not input_path.exists():
            raise FileNotFoundError(input_path)

        if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported video format: {input_path.suffix}"
            )

        info = self.ffmpeg.video_info(input_path)

        analysis = VideoAnalysis(video=info)

        analysis.metadata.update({
            "input_file": str(input_path.resolve()),
            "stage": "ingested",
        })

        return analysis
