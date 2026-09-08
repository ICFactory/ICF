from pathlib import Path
import cv2


class FrameExtractor:
    def __init__(self, video_path):
        self.video_path = str(video_path)

    def extract(self, timestamp, output_path, quality=90):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cap = cv2.VideoCapture(self.video_path)

        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {self.video_path}")

        cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
        ok, frame = cap.read()
        cap.release()

        if not ok:
            raise RuntimeError(
                f"Could not extract frame at {timestamp:.3f}s"
            )

        cv2.imwrite(
            str(output_path),
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, quality],
        )

        return str(output_path)
