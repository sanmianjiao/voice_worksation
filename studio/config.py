import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("VOICE_DATA_DIR", ROOT / "data")).resolve()
MODELS = ROOT / "models"
MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
MODEL_PATH = Path(os.environ.get("VOICE_MODEL_PATH", MODELS / MODEL_ID.split("/")[-1]))
ASR_PATH = MODELS / "faster-whisper-small"
SAMPLE_PATH = Path(os.environ.get("VOICE_SAMPLE_PATH", ROOT / "data" / "sources" / "output.mp3"))
for directory in ("sources", "references", "outputs", "jobs", "profiles"):
    (DATA / directory).mkdir(parents=True, exist_ok=True)
