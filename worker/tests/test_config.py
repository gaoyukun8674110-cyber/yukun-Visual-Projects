from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKER_ROOT = PROJECT_ROOT / "worker"
if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))

try:
    import pydantic_settings  # type: ignore  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("pydantic_settings")

    class BaseSettings:
        pass

    class SettingsConfigDict(dict):
        pass

    stub.BaseSettings = BaseSettings
    stub.SettingsConfigDict = SettingsConfigDict
    sys.modules["pydantic_settings"] = stub

for module_name in ("cv2", "numpy"):
    if module_name not in sys.modules:
        try:
            __import__(module_name)
        except ModuleNotFoundError:
            stub = types.ModuleType(module_name)
            if module_name == "numpy":
                stub.ndarray = object
            sys.modules[module_name] = stub

try:
    import torch  # type: ignore  # noqa: F401
except ModuleNotFoundError:
    torch_stub = types.ModuleType("torch")

    class _CudaStub:
        @staticmethod
        def is_available() -> bool:
            return False

        @staticmethod
        def device_count() -> int:
            return 0

        @staticmethod
        def get_device_name(index: int) -> str:
            return f"cuda:{index}"

    torch_stub.cuda = _CudaStub()
    sys.modules["torch"] = torch_stub

from app.config import DEFAULT_MODEL_FILENAME, resolve_default_model_path
from app.inference import _load_model, _resolve_device, _video_progress_percent


class ResolveDefaultModelPathTests(unittest.TestCase):
    def test_prefers_local_project_models_directory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            config_file = project_root / "worker" / "app" / "config.py"
            config_file.parent.mkdir(parents=True)
            config_file.touch()

            model_path = project_root / "models" / DEFAULT_MODEL_FILENAME
            model_path.parent.mkdir(parents=True)
            model_path.write_bytes(b"")

            self.assertEqual(resolve_default_model_path(config_file), model_path)

    def test_prefers_container_models_directory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            app_root = Path(tmpdir) / "app"
            config_file = app_root / "app" / "config.py"
            config_file.parent.mkdir(parents=True)
            config_file.touch()

            model_path = app_root / "models" / DEFAULT_MODEL_FILENAME
            model_path.parent.mkdir(parents=True)
            model_path.write_bytes(b"")

            self.assertEqual(resolve_default_model_path(config_file), model_path)

    def test_returns_expected_best_pt_location_when_missing(self) -> None:
        with TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "project"
            config_file = project_root / "worker" / "app" / "config.py"
            config_file.parent.mkdir(parents=True)
            config_file.touch()

            expected_path = project_root / "models" / DEFAULT_MODEL_FILENAME
            expected_path.parent.mkdir(parents=True)

            self.assertEqual(resolve_default_model_path(config_file), expected_path)


class LoadModelTests(unittest.TestCase):
    def test_missing_model_raises_clear_error(self) -> None:
        with TemporaryDirectory() as tmpdir:
            missing_model = Path(tmpdir) / "models" / DEFAULT_MODEL_FILENAME

            with self.assertRaises(FileNotFoundError) as context:
                _load_model(str(missing_model))

        self.assertIn("models/best.pt", str(context.exception))
        self.assertIn(str(missing_model), str(context.exception))


class InferenceSettingsTests(unittest.TestCase):
    def test_explicit_yolo_device_is_used(self) -> None:
        settings = types.SimpleNamespace(yolo_device="cpu")

        self.assertEqual(_resolve_device(settings), "cpu")

    def test_video_progress_maps_frames_to_inference_range(self) -> None:
        self.assertEqual(_video_progress_percent(0, 100), 35)
        self.assertEqual(_video_progress_percent(50, 100), 65)
        self.assertEqual(_video_progress_percent(100, 100), 95)


if __name__ == "__main__":
    unittest.main()
