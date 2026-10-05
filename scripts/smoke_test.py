"""Real local GPU integration test. No speaker authorization is inferred."""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studio import server
from studio.config import DATA


def wait_for_job(key):
    last_message = None
    while True:
        status = server.job_status(key)
        if status["message"] != last_message:
            print(status["message"], flush=True)
            last_message = status["message"]
        if status["status"] == "complete":
            return status
        if status["status"] in ("failed", "cancelled"):
            raise RuntimeError(status["message"])
        time.sleep(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=float, default=20)
    parser.add_argument("--end", type=float, default=32)
    parser.add_argument("--mode", choices=["quick", "icl"], default="quick")
    parser.add_argument("--profile", help="Reuse an existing profile ID")
    args = parser.parse_args()
    import torch
    print(f"PyTorch {torch.__version__}; CUDA available={torch.cuda.is_available()}", flush=True)
    if torch.cuda.is_available():
        print(torch.cuda.get_device_name(0), flush=True)
    if args.profile:
        profile = server.lookup("profiles", args.profile)
    else:
        profile = server.create_profile(server.ClipRequest(
            source_id="sample", start=args.start, end=args.end, name="参考男声 · 测试片段"))
    print("PROFILE_ID=" + profile["id"], flush=True)
    if args.mode == "icl" and not profile["transcript"]:
        print("Transcribing the reference (draft; not manually verified)", flush=True)
        draft = server.engine.transcribe(DATA / "references" / f"{profile['id']}.wav")
        print(draft["text"], flush=True)
        profile = server.edit_profile(profile["id"], server.ProfileUpdate(
            name=profile["name"], transcript=draft["text"]))
    text = "这是一段人工智能合成的配音测试，不是本人录音。欢迎来到今天的视频。"
    body = server.GenerateRequest(profile_id=profile["id"], text=text, mode=args.mode,
                                  acknowledged=True)
    job = server.generate(body)
    result = wait_for_job(job["id"])
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    print(f"OUTPUT={DATA / 'outputs' / job['id'] / 'voice.wav'}", flush=True)
    server.engine.unload()
    server.pool.shutdown(wait=True)


if __name__ == "__main__":
    main()
