from __future__ import annotations

from functools import lru_cache
import logging
from pathlib import Path
import subprocess
from typing import Any, Callable

import cv2
import numpy as np
import torch

from app.config import DEFAULT_MODEL_FILENAME, Settings

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv"}
logger = logging.getLogger("worker.inference")
ProgressCallback = Callable[[int], None]


def _color(index: int) -> tuple[int, int, int]:
    palette = [(38, 255, 137), (36, 196, 255), (255, 78, 46), (255, 220, 54)]
    return palette[index % len(palette)]


def _draw_box(frame: np.ndarray, box: tuple[int, int, int, int], label: str, index: int = 0) -> None:
    x1, y1, x2, y2 = box
    color = _color(index)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
    cv2.rectangle(frame, (x1, max(0, y1 - 30)), (min(frame.shape[1], x1 + 220), y1), color, -1)
    cv2.putText(frame, label, (x1 + 8, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (15, 18, 14), 2)


def _video_progress_percent(frames_done: int, total_frames: int) -> int:
    return min(95, 35 + int(60 * frames_done / total_frames))


def _notify_progress(progress_cb: ProgressCallback | None, progress: int) -> None:
    if progress_cb is not None:
        progress_cb(progress)


def _demo_boxes(width: int, height: int) -> list[dict[str, Any]]:
    x1, y1 = int(width * 0.14), int(height * 0.18)
    x2, y2 = int(width * 0.62), int(height * 0.74)
    x3, y3 = int(width * 0.56), int(height * 0.28)
    x4, y4 = int(width * 0.88), int(height * 0.66)
    return [
        {"class": "demo-object", "confidence": 0.91, "xyxy": [x1, y1, x2, y2]},
        {"class": "demo-target", "confidence": 0.78, "xyxy": [x3, y3, x4, y4]},
    ]


def _demo_image(input_path: Path, output_path: Path, progress_cb: ProgressCallback | None = None) -> dict[str, Any]:
    frame = cv2.imread(str(input_path))
    if frame is None:
        raise ValueError(f"OpenCV cannot read image: {input_path}")
    height, width = frame.shape[:2]
    detections = _demo_boxes(width, height)
    for index, detection in enumerate(detections):
        _draw_box(frame, tuple(detection["xyxy"]), f"{detection['class']} {detection['confidence']:.2f}", index)
    cv2.imwrite(str(output_path), frame)
    _notify_progress(progress_cb, 70)
    return {"mode": "demo", "media_type": "image", "detections": detections}


def _resolve_device(settings: Settings) -> str:
    configured = settings.yolo_device.strip()
    if configured and configured.lower() != "auto":
        return configured
    return "0" if torch.cuda.is_available() else "cpu"


def describe_torch_device(settings: Settings) -> dict[str, Any]:
    cuda_available = torch.cuda.is_available()
    device_count = torch.cuda.device_count() if cuda_available else 0
    device_names = [torch.cuda.get_device_name(index) for index in range(device_count)]
    return {
        "configured": settings.yolo_device,
        "resolved": _resolve_device(settings),
        "cuda_available": cuda_available,
        "device_count": device_count,
        "device_names": device_names,
    }


def _transcode_browser_mp4(input_path: Path, output_path: Path) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vf",
        "pad=ceil(iw/2)*2:ceil(ih/2)*2",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is required to create browser-playable result videos") from exc
    except subprocess.CalledProcessError as exc:
        logger.error("ffmpeg transcode failed: %s", exc.stderr)
        raise RuntimeError("ffmpeg failed to transcode result video") from exc


def _demo_video(input_path: Path, output_path: Path, progress_cb: ProgressCallback | None = None) -> dict[str, Any]:
    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise ValueError(f"OpenCV cannot read video: {input_path}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 25
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    step = max(1, total // 50) if total else 1
    tmp_path = output_path.with_name(f"{output_path.stem}.opencv-tmp.mp4")
    writer = cv2.VideoWriter(str(tmp_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        capture.release()
        raise RuntimeError(f"OpenCV cannot write video: {tmp_path}")
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
        if total and frames % step == 0:
            _notify_progress(progress_cb, _video_progress_percent(frames, total))

    capture.release()
    writer.release()
    _notify_progress(progress_cb, 95)
    _transcode_browser_mp4(tmp_path, output_path)
    _notify_progress(progress_cb, 98)
    tmp_path.unlink(missing_ok=True)
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


def _yolo_image(
    input_path: Path,
    output_path: Path,
    settings: Settings,
    progress_cb: ProgressCallback | None = None,
) -> dict[str, Any]:
    model = _load_model(str(settings.yolo_model_path))
    device = _resolve_device(settings)
    results = model.predict(source=str(input_path), conf=settings.yolo_confidence, device=device, verbose=False)
    first = results[0]
    annotated = first.plot()
    cv2.imwrite(str(output_path), annotated)
    _notify_progress(progress_cb, 70)
    return {"mode": "yolo", "media_type": "image", "detections": _extract_detections(first)}


def _yolo_video(
    input_path: Path,
    output_path: Path,
    settings: Settings,
    progress_cb: ProgressCallback | None = None,
) -> dict[str, Any]:
    model = _load_model(str(settings.yolo_model_path))
    device = _resolve_device(settings)
    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise ValueError(f"OpenCV cannot read video: {input_path}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 25
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    step = max(1, total // 50) if total else 1
    tmp_path = output_path.with_name(f"{output_path.stem}.opencv-tmp.mp4")
    writer = cv2.VideoWriter(str(tmp_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        capture.release()
        raise RuntimeError(f"OpenCV cannot write video: {tmp_path}")
    frames = 0
    sampled: list[dict[str, Any]] = []

    while True:
        ok, frame = capture.read()
        if not ok:
            break
        result = model.predict(source=frame, conf=settings.yolo_confidence, device=device, verbose=False)[0]
        writer.write(result.plot())
        if frames % max(1, int(fps)) == 0:
            sampled.append({"frame": frames, "detections": _extract_detections(result)})
        frames += 1
        if total and frames % step == 0:
            _notify_progress(progress_cb, _video_progress_percent(frames, total))

    capture.release()
    writer.release()
    _notify_progress(progress_cb, 95)
    _transcode_browser_mp4(tmp_path, output_path)
    _notify_progress(progress_cb, 98)
    tmp_path.unlink(missing_ok=True)
    return {"mode": "yolo", "media_type": "video", "frames": frames, "sampled": sampled}


def detect_media(
    input_path: Path,
    output_path: Path,
    settings: Settings,
    progress_cb: ProgressCallback | None = None,
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = input_path.suffix.lower()

    if suffix in IMAGE_SUFFIXES:
        return _yolo_image(input_path, output_path, settings, progress_cb)
    if suffix in VIDEO_SUFFIXES:
        return _yolo_video(input_path, output_path, settings, progress_cb)
    raise ValueError(f"Unsupported media suffix: {suffix}")
