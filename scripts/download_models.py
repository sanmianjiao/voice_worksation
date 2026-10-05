"""Download public weights only; reference audio is never uploaded."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studio.config import ASR_PATH, MODEL_ID, MODEL_PATH


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--asr", action="store_true", help="Also download optional Chinese transcription model")
    parser.add_argument("--provider", choices=["huggingface", "modelscope"], default="huggingface")
    args = parser.parse_args()
    if args.provider == "modelscope":
        from modelscope import snapshot_download
        snapshot_download(MODEL_ID, local_dir=str(MODEL_PATH))
    else:
        from huggingface_hub import snapshot_download
        snapshot_download(MODEL_ID, local_dir=MODEL_PATH, max_workers=4,
                          ignore_patterns=["*.md", ".gitattributes"])
    print(f"TTS model ready: {MODEL_PATH}", flush=True)
    if args.asr:
        from huggingface_hub import snapshot_download
        snapshot_download("Systran/faster-whisper-small", local_dir=ASR_PATH,
                          allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"],
                          max_workers=4)
        print(f"ASR model ready: {ASR_PATH}", flush=True)


if __name__ == "__main__":
    main()
