import json
import shutil
import subprocess
from pathlib import Path


class FFmpeg:
    def __init__(self, executable=""):
        self.executable = executable or shutil.which("ffmpeg")

        if not self.executable:
            raise RuntimeError(
                "FFmpeg was not found. Set ffmpeg.executable in config.yaml "
                "or put ffmpeg in PATH."
            )

        self.ffprobe = self._find_ffprobe()

    def _find_ffprobe(self):
        configured = Path(self.executable)

        if configured.name.lower() == "ffmpeg.exe":
            probe = configured.with_name("ffprobe.exe")
            if probe.exists():
                return str(probe)

        found = shutil.which("ffprobe")
        if found:
            return found

        return "ffprobe"

    def run(self, args):
        command = [self.executable] + list(args)

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(
                "FFmpeg command failed:\n"
                + " ".join(command)
                + "\n\n"
                + result.stderr
            )

        return result

    def probe(self, path):
        command = [
            self.ffprobe,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(result.stderr)

        return json.loads(result.stdout)

    def video_info(self, path):
        data = self.probe(path)

        streams = data.get("streams", [])
        video = next(
            (s for s in streams if s.get("codec_type") == "video"),
            None,
        )
        audio = next(
            (s for s in streams if s.get("codec_type") == "audio"),
            None,
        )

        if not video:
            raise RuntimeError("No video stream found.")

        fps_text = video.get("r_frame_rate", "0/1")
        numerator, denominator = fps_text.split("/")
        fps = float(numerator) / float(denominator) if float(denominator) else 0

        duration = float(
            data.get("format", {}).get(
                "duration",
                video.get("duration", 0),
            )
        )

        from app.core.models import VideoInfo

        return VideoInfo(
            path=str(path),
            duration=duration,
            width=int(video.get("width", 0)),
            height=int(video.get("height", 0)),
            fps=fps,
            codec=video.get("codec_name", ""),
            audio_codec=audio.get("codec_name") if audio else None,
        )
