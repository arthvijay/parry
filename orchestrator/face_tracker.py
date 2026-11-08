"""Reading the learner's face from the webcam, for the date to see and the demo to show.

The client sends small JPEG frames; MediaPipe's Face Landmarker turns each into the 52
ARKit blendshapes (the same names as the avatars' AK_ shapes, so they drive the
player's avatar directly), the head's pitch, yaw and roll, and the face mesh. A subset
of the mesh comes back to the client as normalised points grouped by feature, which the
vision panel draws over the camera image.

MediaPipe is optional (``uv sync --group face``). Without it, or without its model file,
the tracker reports itself unavailable and the date carries on without a face.
Frames are analysed one at a time on a single worker thread; a frame that arrives while
the previous one is still being read is dropped, so the panel shows the newest face,
never a backlog.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("orchestrator")

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
             "face_landmarker/float16/1/face_landmarker.task")
MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
DEFAULT_MODEL = Path(__file__).resolve().parent.parent / "runs" / "models" / "face_landmarker.task"

# Contours from MediaPipe's canonical face mesh, drawn by the vision panel.
CONTOURS = {
    "oval": [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378,
             400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21,
             54, 103, 67, 109, 10],
    "lips": [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37,
             39, 40, 185, 61],
    "inner_lips": [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308, 415, 310, 311, 312, 13,
                   82, 81, 80, 191, 78],
    "left_eye": [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388,
                 466, 263],
    "right_eye": [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161,
                  246, 33],
    "left_brow": [276, 283, 282, 295, 285, 300, 293, 334, 296, 336],
    "right_brow": [46, 53, 52, 65, 55, 70, 63, 105, 66, 107],
    "nose": [168, 6, 197, 195, 5, 4, 1, 19, 94, 2],
    "left_iris": [474, 475, 476, 477, 474],
    "right_iris": [469, 470, 471, 472, 469],
}
# A sparse scatter of the full mesh, for the "being analysed" look.
MESH_STRIDE = 4


@dataclass
class FaceReading:
    found: bool
    blendshapes: dict[str, float] = field(default_factory=dict)
    pitch: float = 0.0
    yaw: float = 0.0
    roll: float = 0.0
    contours: dict[str, list[list[float]]] = field(default_factory=dict)
    mesh: list[list[float]] = field(default_factory=list)
    width: int = 0
    height: int = 0
    ms: float = 0.0

    def shape(self, name: str) -> float:
        return self.blendshapes.get(name, 0.0)

    def wire(self) -> dict:
        return {"found": self.found,
                "blendshapes": {k: round(v, 3) for k, v in self.blendshapes.items()},
                "head": {"pitch": round(self.pitch, 1), "yaw": round(self.yaw, 1),
                         "roll": round(self.roll, 1)},
                "contours": self.contours, "mesh": self.mesh,
                "frame": {"width": self.width, "height": self.height},
                "analysis_ms": round(self.ms, 1)}


def euler_from_matrix(m) -> tuple[float, float, float]:
    """Pitch, yaw, roll in degrees from MediaPipe's facial transformation matrix:
    pitch up positive, yaw toward the learner's left positive, roll clockwise positive."""
    r = [[float(m[i][j]) for j in range(3)] for i in range(3)]
    sy = math.sqrt(r[0][0] ** 2 + r[1][0] ** 2)
    if sy > 1e-6:
        pitch = math.atan2(r[2][1], r[2][2])
        yaw = math.atan2(-r[2][0], sy)
        roll = math.atan2(r[1][0], r[0][0])
    else:
        pitch, yaw, roll = math.atan2(-r[1][2], r[1][1]), math.atan2(-r[2][0], sy), 0.0
    return math.degrees(pitch), math.degrees(yaw), math.degrees(roll)


def ensure_model(path: Path) -> Path:
    """The Face Landmarker model, downloaded once and checked against its hash."""
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".part")
    with urllib.request.urlopen(MODEL_URL, timeout=30) as response:  # noqa: S310 (fixed URL)
        data = response.read()
    if hashlib.sha256(data).hexdigest() != MODEL_SHA256:
        raise ValueError("Face model download did not match its checksum")
    temp.write_bytes(data)
    temp.replace(path)
    return path


class FaceTracker:
    def __init__(self, model_path: Path | None = None):
        self.model_path = Path(os.getenv("FACE_MODEL_PATH") or model_path or DEFAULT_MODEL)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="face")
        self.landmarker = None
        self.error: str | None = None
        self.busy = False
        self._loading: asyncio.Future | None = None

    @property
    def available(self) -> bool:
        return self.error is None

    def _load(self):
        import mediapipe as mp  # noqa: F401  (optional dependency)
        from mediapipe.tasks.python import BaseOptions, vision
        path = ensure_model(self.model_path)
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(path)),
            running_mode=vision.RunningMode.IMAGE, num_faces=1,
            output_face_blendshapes=True, output_facial_transformation_matrixes=True,
            min_face_detection_confidence=0.5, min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5)
        self.landmarker = vision.FaceLandmarker.create_from_options(options)

    async def start(self) -> bool:
        """Load MediaPipe and the model off the event loop; safe to call repeatedly."""
        if self.landmarker is not None or self.error is not None:
            return self.available
        if self._loading is None:
            self._loading = asyncio.get_running_loop().run_in_executor(self.pool, self._load)
        try:
            await self._loading
        except Exception as error:  # noqa: BLE001
            self.error = f"{type(error).__name__}: {error}"[:200]
            log.warning("Face tracking unavailable: %s", self.error)
        return self.available

    def _analyse(self, jpeg: bytes) -> FaceReading:
        import time

        import cv2
        import mediapipe as mp
        import numpy as np
        started = time.perf_counter()
        image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return FaceReading(found=False)
        height, width = image.shape[:2]
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        result = self.landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        reading = FaceReading(found=bool(result.face_landmarks), width=width, height=height)
        if reading.found:
            points = result.face_landmarks[0]
            if result.face_blendshapes:
                reading.blendshapes = {c.category_name: float(c.score)
                                       for c in result.face_blendshapes[0]
                                       if c.category_name != "_neutral"}
            if result.facial_transformation_matrixes:
                reading.pitch, reading.yaw, reading.roll = euler_from_matrix(
                    result.facial_transformation_matrixes[0])

            def xy(i: int) -> list[float]:
                p = points[i]
                return [round(float(p.x), 4), round(float(p.y), 4)]

            reading.contours = {name: [xy(i) for i in idx if i < len(points)]
                                for name, idx in CONTOURS.items()}
            reading.mesh = [xy(i) for i in range(0, min(len(points), 468), MESH_STRIDE)]
        reading.ms = (time.perf_counter() - started) * 1000
        return reading

    def _selfie(self, jpeg: bytes) -> dict:
        """Colours for the avatar from a selfie: skin from both cheeks and the forehead,
        hair from just above the hairline, each the median of a small patch."""
        import cv2
        import mediapipe as mp
        import numpy as np
        image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return {"face_found": False, "reason": "not an image"}
        height, width = image.shape[:2]
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        result = self.landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        if not result.face_landmarks:
            return {"face_found": False, "reason": "no face in the photo"}
        points = result.face_landmarks[0]

        def patch(x: float, y: float, radius: int) -> np.ndarray | None:
            cx, cy = int(x * width), int(y * height)
            if not (0 <= cx < width and 0 <= cy < height):
                return None
            area = rgb[max(0, cy - radius):cy + radius, max(0, cx - radius):cx + radius]
            return area.reshape(-1, 3) if area.size else None

        face_h = abs(points[152].y - points[10].y)
        radius = max(3, int(face_h * height * 0.04))
        skin = [patch(points[i].x, points[i].y, radius) for i in (50, 280, 151)]
        skin = np.concatenate([p for p in skin if p is not None]) if any(
            p is not None for p in skin) else None
        top = points[10]
        hair = patch(top.x, top.y - face_h * 0.12, radius * 2)

        def hexcolor(pixels) -> str | None:
            if pixels is None or not len(pixels):
                return None
            r, g, b = (int(v) for v in np.median(pixels, axis=0))
            return f"#{r:02X}{g:02X}{b:02X}"

        skin_hex = hexcolor(skin)
        hair_hex = hexcolor(hair)
        # A hairline patch that matches the skin is a forehead or a bald head, not hair.
        if hair_hex and skin_hex:
            hs = np.array([int(hair_hex[i:i + 2], 16) for i in (1, 3, 5)])
            ss = np.array([int(skin_hex[i:i + 2], 16) for i in (1, 3, 5)])
            if np.abs(hs - ss).sum() < 60:
                hair_hex = None
        box = [min(p.x for p in points), min(p.y for p in points),
               max(p.x for p in points), max(p.y for p in points)]
        return {"face_found": True, "skin_hex": skin_hex, "hair_hex": hair_hex,
                "face_box": [round(v, 4) for v in box],
                "blendshapes": {c.category_name: round(float(c.score), 3)
                                for c in (result.face_blendshapes or [[]])[0]
                                if c.category_name != "_neutral"}}

    async def selfie(self, jpeg: bytes) -> dict:
        if not await self.start():
            return {"face_found": False, "reason": f"face tracking unavailable: {self.error}"}
        return await asyncio.get_running_loop().run_in_executor(self.pool, self._selfie, jpeg)

    async def analyse(self, jpeg: bytes) -> FaceReading | None:
        """One frame, or None if the tracker is unavailable or still on the last frame."""
        if self.busy or not await self.start():
            return None
        self.busy = True
        try:
            return await asyncio.get_running_loop().run_in_executor(self.pool, self._analyse, jpeg)
        except Exception as error:  # noqa: BLE001
            log.warning("Face frame failed: %s", type(error).__name__)
            return None
        finally:
            self.busy = False

    def close(self):
        if self.landmarker is not None:
            try:
                self.landmarker.close()
            except Exception:  # noqa: BLE001
                pass
        self.pool.shutdown(wait=False, cancel_futures=True)
