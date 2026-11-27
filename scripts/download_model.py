"""Descarga el modelo oficial de reconocimiento de gestos de MediaPipe."""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

# Permite ejecutar este script directamente desde cualquier directorio
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import MODEL_PATH, MODEL_URL, MODELS_DIR  # noqa: E402

MIN_EXPECTED_BYTES = 1_000_000  # El archivo .task pesa ~8.4 MB


def ensure_model_downloaded(force: bool = False) -> Path:
    """Verifica o descarga models/gesture_recognizer.task."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    if not force and MODEL_PATH.exists() and MODEL_PATH.stat().st_size >= MIN_EXPECTED_BYTES:
        print(f"[OK] Modelo encontrado en: {MODEL_PATH}")
        return MODEL_PATH

    print(f"[INFO] Descargando modelo de MediaPipe desde:\n       {MODEL_URL}")
    temp_path = MODEL_PATH.with_suffix(".task.tmp")

    def _progress(block_num: int, block_size: int, total_size: int) -> None:
        if total_size <= 0:
            return
        downloaded = min(block_num * block_size, total_size)
        pct = downloaded * 100.0 / total_size
        print(f"\r       Progreso: {pct:5.1f}% ({downloaded / 1e6:.2f} / {total_size / 1e6:.2f} MB)", end="")

    try:
        urllib.request.urlretrieve(MODEL_URL, temp_path, reporthook=_progress)
        print()
        size = temp_path.stat().st_size
        if size < MIN_EXPECTED_BYTES:
            raise RuntimeError(f"Descarga incompleta ({size} bytes). Intenta nuevamente.")
        temp_path.replace(MODEL_PATH)
        print(f"[OK] Modelo guardado correctamente ({size / 1e6:.2f} MB) en: {MODEL_PATH}")
        return MODEL_PATH
    except Exception:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    force_flag = "--force" in sys.argv
    ensure_model_downloaded(force=force_flag)
