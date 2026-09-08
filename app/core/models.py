from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
import json


@dataclass
class VideoInfo:
    path: str
    duration: float
    width: int
    height: int
    fps: float
    codec: str
    audio_codec: Optional[str] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str

    def to_dict(self):
        return asdict(self)


@dataclass
class Signal:
    timestamp: float
    value: float
    kind: str

    def to_dict(self):
        return asdict(self)


@dataclass
class CandidateEvent:
    event_id: str
    start: float
    end: float
    peak: float
    signals: Dict[str, float] = field(default_factory=dict)
    transcript: str = ""
    frames: List[str] = field(default_factory=list)
    ai_analysis: Dict[str, Any] = field(default_factory=dict)
    score: Optional[float] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class VideoAnalysis:
    video: Optional[VideoInfo] = None
    transcript: List[TranscriptSegment] = field(default_factory=list)
    signals: List[Signal] = field(default_factory=list)
    events: List[CandidateEvent] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {
            "video": self.video.to_dict() if self.video else None,
            "transcript": [x.to_dict() for x in self.transcript],
            "signals": [x.to_dict() for x in self.signals],
            "events": [x.to_dict() for x in self.events],
            "metadata": self.metadata,
        }

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
