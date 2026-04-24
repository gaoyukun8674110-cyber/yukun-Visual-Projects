from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.config import DEFAULT_MODEL_FILENAME, Settings

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv"}


def _color(index: int) -> tuple[int, int, int]:
    palette = [(38, 255, 137), (36, 196, 255), (255, 78, 46), (255, 220, 54)]
    return palette[index % len(palette)]


def _draw_box(frame: np.ndarray, box: tuple[int, int, int, int], label: str, index: int = 0) -> None:
    x1, y1, x2, y2 = box
    color = _color(index)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
    cv2.rectangle(frame, (x1, max(0, y1 - 30)), (min(frame.shape[1], x1 + 220), y1), color, -1)
    cv2.putText(frame, label, (x1 + 8, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (15, 18, 14), 2)


def _demo_boxes(width: int, height: int) -> list[dict[str, Any]]:
    x1, y1 = int(width * 0.14), int(height * 0.18)
    x2, y2 = int(width * 0.62), int(height * 0.74)
    x3, y3 = int(width * 0.56), int(height * 0.28)
    x4, y4 = int(width * 0.88), int(height * 0.66)
    return [
        {"class": "demo-object", "confidence": 0.91, "xyxy": [x1, y1, x2, y2]},
        {"class": "demo-target", "confidence": 0.78, "xyxy": [x3, y3, x4, y4]},
    ]


def _demo_image(input_path: Path, output_path: Path) -> dict[str, Any]:
    frame = cv2.imread(str(input_path))
    if frame is None:
        raise ValueError(f"OpenCV cannot read image: {input_path}")
    height, width = frame.shape[:2]
    detections = _demo_boxes(width, height)
    for index, detection in enumerate(detections):
        _draw_box(frame, tuple(detection["xyxy"]), f"{detection['class']} {detection['confidence']:.2f}", index)
    cv2.imwrite(str(output_path), frame)
    return {"mode": "demo", "media_type": "image", "detections": detections}


def _demo_video(input_path: Path, output_path: Path) -> dict[str, Any]:
    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise ValueError(f"OpenCV cannot read video: {input_path}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 25
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    detections = _demo_boxes(width, height)
    frames = 0

    while True:
        ok, frame = capture.read()
        if not ok:
            break
        for index, detection in enumerate(detections):
            _draw_box(frame, tuple(detection["xyxy"]), f"{detection['class']} {detection['confidence']:.2f}", index)
        writer.write(frame)
        frames += 1

    capture.release()
    writer.release()
    return {"mode": "demo", "media_type": "video", "frames": frames, "detections": detections}


@lru_cache(maxsize=2)
def _load_model(model_path: str):
    resolved_path = Path(model_path)
    if not resolved_path.is_file():
        raise FileNotFoundError(
            f"YOLO model not found at {resolved_path}. "
            f"Place your trained model at 'models/{DEFAULT_MODEL_FILENAME}' before starting the worker."
        )

    from ultralytics import YOLO

    return YOLO(str(resolved_path))


def _extract_detections(result: Any) -> list[dict[str, Any]]:
    detections: list[dict[str, Any]] = []
    names = result.names or {}
    boxes = result.boxes
    if boxes is None:
        return detections

    xyxy = boxes.xyxy.cpu().tolist()
    confs = boxes.conf.cpu().tolist()
    classes = boxes.cls.cpu().tolist()
    for box, conf, class_id in zip(xyxy, confs, classes, strict=False):
        class_index = int(class_id)
        detections.append(
            {
                "class": names.get(class_index, str(class_index)),
                "confidence": round(float(conf), 4),
                "xyxy": [round(float(value), 2) for value in box],
            }
        )
    return detections


def _yolo_image(input_path: Path, output_path: Path, settings: Settings) -> dict[str, Any]:
    model = _load_model(str(settings.yolo_model_path))
    results = model.predict(source=str(input_path), conf=settings.yolo_confidence, verbose=False)
    first = results[0]
    annotated = first.plot()
    cv2.imwrite(str(output_path), annotated)
    return {"mode": "yolo", "media_type": "image", "detections": _extract_detections(first)}


def _yolo_video(input_path: Path, output_path: Path, settings: Settings) -> dict[str, Any]:
    model = _load_model(str(settings.yolo_model_path))
    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise ValueError(f"OpenCV cannot read video: {input_path}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 25
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    frames = 0
    sampled: list[dict[str, Any]] = []

    while True:
        ok, frame = capture.read()
        if not ok:
            break
        result = model.predict(source=frame, conf=settings.yolo_confidence, verbose=False)[0]
        writer.write(result.plot())
        if frames % max(1, int(fps)) == 0:
            sampled.append({"frame": frames, "detections": _extract_detections(result)})
        frames += 1

    capture.release()
    writer.release()
    return {"mode": "yolo", "media_type": "video", "frames": frames, "sampled": sampled}


def detect_media(input_path: Path, output_path: Path, settings: Settings) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = input_path.suffix.lower()

    if suffix in IMAGE_SUFFIXES:
        return _yolo_image(input_path, output_path, settings)
    if suffix in VIDEO_SUFFIXES:
        return _yolo_video(input_path, output_path, settings)
    raise ValueError(f"Unsupported media suffix: {suffix}")
