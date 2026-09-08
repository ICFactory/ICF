from pathlib import Path
import os
import yaml


DEFAULT_CONFIG = {
    "project": {
        "name": "ICF",
        "version": "0.2.0",
    },
    "paths": {
        "input_dir": "input",
        "output_dir": "output",
        "temp_dir": "temp",
    },
    "ffmpeg": {
        "executable": "",
        "width": 1080,
        "height": 1920,
        "video_codec": "libx264",
        "crf": 20,
        "preset": "medium",
        "audio_codec": "aac",
        "audio_bitrate": "128k",
    },
    "analysis": {
        "sample_interval": 1.5,
        "max_candidates": 100,
        "event_padding_before": 3.0,
        "event_padding_after": 4.0,
    },
    "transcription": {
        "enabled": True,
        "model": "small",
        "device": "cpu",
        "compute_type": "int8",
    },
    "ai": {
        "vision_provider": "none",
        "reasoning_provider": "none",
    },
    "shorts": {
        "min_duration": 15,
        "max_duration": 59,
        "target_count": 6,
    },
}


class Config:
    def __init__(self, path="config.yaml"):
        self.path = Path(path)
        self.data = DEFAULT_CONFIG.copy()

        if self.path.exists():
            with open(self.path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            self.data = self._merge(DEFAULT_CONFIG, loaded)

    @staticmethod
    def _merge(base, override):
        result = dict(base)

        for key, value in override.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = Config._merge(result[key], value)
            else:
                result[key] = value

        return result

    def get(self, *keys, default=None):
        value = self.data

        for key in keys:
            if not isinstance(value, dict) or key not in value:
                return default
            value = value[key]

        return value

    def path_value(self, name):
        return Path(self.get("paths", name))


def load_config(path="config.yaml"):
    return Config(path)
