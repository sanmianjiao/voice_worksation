import json
import logging
import os
import secrets
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .audio import extract_reference, make_srt, probe, run_ffmpeg, split_text, waveform
from .config import ASR_PATH, DATA, MODEL_ID, MODEL_PATH, ROOT, SAMPLE_PATH
from .engine import engine

app = FastAPI(title="声刻 · 本地配音工作台")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
TOKEN = secrets.token_urlsafe(32)
pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voice-worker")
state_lock = threading.RLock()
jobs: dict[str, dict] = {}
cancellations: dict[str, threading.Event] = {}
logger = logging.getLogger("voice-studio")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    temporary = path.with_name(f"{path.stem}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


for job_file in (DATA / "jobs").glob("*.json"):
    try:
        record = read_json(job_file)
        if record["status"] in ("queued", "running"):
            record.update(status="failed", message="服务曾中断，请重新生成。")
            write_json(job_file, record)
        jobs[record["id"]] = record
    except (ValueError, KeyError):
        logger.warning("Unreadable job file: %s", job_file)


@app.middleware("http")
async def local_guard(request: Request, call_next):
    # Prevent another website from driving this local server through CSRF.
    if request.method not in ("GET", "HEAD", "OPTIONS") and not secrets.compare_digest(
        request.headers.get("x-studio-token", ""), TOKEN
    ):
        return JSONResponse({"detail": "本地会话已失效，请刷新页面。"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
    return response


@app.exception_handler(ValueError)
async def invalid_value(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=400)


def lookup(folder: str, key: str) -> dict:
    if not key.isalnum() or len(key) > 64:
        raise HTTPException(404, "记录不存在。")
    path = DATA / folder / f"{key}.json"
    if not path.is_file():
        raise HTTPException(404, "记录不存在。")
    return read_json(path)


def source_info(key):
    if key == "sample":
        if not SAMPLE_PATH.is_file():
            raise HTTPException(404, "找不到示例音频，请上传自己的素材。")
        return SAMPLE_PATH, {"id": "sample", "name": SAMPLE_PATH.name, **probe(SAMPLE_PATH)}
    record = lookup("sources", key)
    return DATA / "sources" / record["filename"], record


def patch_job(key, **updates):
    with state_lock:
        jobs[key].update(updates)
        write_json(DATA / "jobs" / f"{key}.json", jobs[key])


def submit(kind, params, work):
    with state_lock:
        if sum(j["status"] in ("queued", "running") for j in jobs.values()) >= 4:
            raise HTTPException(429, "队列已满，请等待当前任务完成。")
        key = uuid.uuid4().hex
        cancellations[key] = threading.Event()
        jobs[key] = {"id": key, "kind": kind, "status": "queued", "progress": 0,
                     "message": "等待处理", "created_at": datetime.now(timezone.utc).isoformat(),
                     "params": params}
        patch_job(key)

    def runner():
        try:
            if cancellations[key].is_set():
                patch_job(key, status="cancelled", message="已取消")
                return
            patch_job(key, status="running", message="开始处理")
            result = work(key)
            if cancellations[key].is_set():
                patch_job(key, status="cancelled", message="已取消")
            else:
                patch_job(key, status="complete", progress=100, message="处理完成", result=result)
        except Exception as exc:
            logger.exception("Job %s failed", key)
            message = str(exc)
            if "out of memory" in message.lower():
                message = "显存不足，请关闭游戏等占用显存的程序，释放模型后重试。"
            patch_job(key, status="failed", message=message[:1500])
        finally:
            with state_lock:
                cancellations.pop(key, None)
    pool.submit(runner)
    return {"id": key}


class ClipRequest(BaseModel):
    source_id: str = "sample"
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(gt=0, allow_inf_nan=False)
    name: str = Field(default="我的参考音色", min_length=1, max_length=60)


class ProfileUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    transcript: str = Field(default="", max_length=2000)


class GenerateRequest(BaseModel):
    profile_id: str
    text: str = Field(min_length=1, max_length=5000)
    mode: Literal["quick", "icl"] = "quick"
    language: Literal["Chinese", "English", "Auto"] = "Chinese"
    speed: float = Field(default=1, ge=.7, le=1.4, allow_inf_nan=False)
    gap: float = Field(default=.25, ge=0, le=2, allow_inf_nan=False)
    seed: int = Field(default=42, ge=0, le=2147483647)
    acknowledged: bool = False

    @field_validator("text")
    @classmethod
    def clean_text(cls, value):
        if not value.strip():
            raise ValueError("文案不能全部为空白。")
        return value.strip()


@app.get("/api/config")
def configuration():
    return {"app_id": "local-voice-studio", "token": TOKEN, "sample_available": SAMPLE_PATH.is_file(),
            "model": MODEL_ID, "model_ready": (MODEL_PATH / "model.safetensors").is_file(),
            "asr_ready": (ASR_PATH / "model.bin").is_file(),
            "model_loaded": engine.model is not None, "device": engine.device}


@app.get("/api/sources/{key}")
def get_source(key: str):
    path, info = source_info(key)
    cache = DATA / "sources" / f"{key}.wave.json"
    if cache.is_file() and cache.stat().st_mtime >= path.stat().st_mtime:
        peaks = read_json(cache)
    else:
        peaks = waveform(path)
        write_json(cache, peaks)
    return {**info, "waveform": peaks, "url": f"/api/sources/{key}/audio"}


@app.get("/api/sources/{key}/audio")
def source_audio(key: str):
    path, _ = source_info(key)
    return FileResponse(path)


@app.post("/api/sources")
async def upload_source(file: Annotated[UploadFile, File()]):
    extension = Path(file.filename or "").suffix.lower()
    if extension not in {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".mp4", ".aac", ".webm"}:
        raise HTTPException(400, "支持 MP3 / WAV / M4A / FLAC / OGG / MP4 / AAC / WEBM。")
    key = uuid.uuid4().hex
    target = DATA / "sources" / f"{key}{extension}"
    try:
        total = 0
        with target.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > 200 * 1024 * 1024:
                    raise HTTPException(413, "单个文件不能超过 200MB。")
                out.write(chunk)
        info = probe(target)
        record = {"id": key, "name": Path(file.filename).name,
                  "filename": target.name, **info}
        write_json(DATA / "sources" / f"{key}.json", record)
        return record
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@app.post("/api/profiles")
def create_profile(body: ClipRequest):
    path, source = source_info(body.source_id)
    key = uuid.uuid4().hex
    target = DATA / "references" / f"{key}.wav"
    info = extract_reference(path, target, body.start, body.end)
    record = {"id": key, "name": body.name, "source_id": source["id"],
              "start": body.start, "end": body.end, "transcript": "",
              "rights_status": "user_provided_not_verified", **info,
              "url": f"/api/profiles/{key}/audio"}
    write_json(DATA / "profiles" / f"{key}.json", record)
    return record


@app.get("/api/profiles")
def list_profiles():
    return sorted([read_json(p) for p in (DATA / "profiles").glob("*.json")],
                  key=lambda p: p["name"])


@app.put("/api/profiles/{key}")
def edit_profile(key: str, body: ProfileUpdate):
    # Serialize profile edits so a simultaneous ASR cannot overwrite a name change.
    with state_lock:
        record = lookup("profiles", key)
        record.update(body.model_dump())
        write_json(DATA / "profiles" / f"{key}.json", record)
    return record


@app.get("/api/profiles/{key}/audio")
def profile_audio(key: str):
    lookup("profiles", key)
    return FileResponse(DATA / "references" / f"{key}.wav", media_type="audio/wav")


@app.post("/api/profiles/{key}/transcribe")
def transcribe_profile(key: str):
    lookup("profiles", key)
    def work(job_id):
        patch_job(job_id, message="在 CPU 上识别参考录音，请稍候", progress=15)
        # Return draft only. The user's reviewed transcript is never overwritten.
        return engine.transcribe(DATA / "references" / f"{key}.wav")
    return submit("transcribe", {"profile_id": key}, work)


def synthesize(key: str, body: GenerateRequest, profile: dict):
    import torch

    started = time.monotonic()
    folder = DATA / "outputs" / key
    folder.mkdir(parents=True, exist_ok=True)
    chunks = split_text(body.text)
    segments, audio_parts = [], []
    cursor = 0
    with engine.lock:
        patch_job(key, message="加载音色模型（首次加载可能需要一两分钟）", progress=3)
        model = engine.load()
        torch.manual_seed(body.seed)
        patch_job(key, message="提取参考音色特征", progress=8)
        prompt = model.create_voice_clone_prompt(
            ref_audio=str(DATA / "references" / f"{profile['id']}.wav"),
            ref_text=profile["transcript"] if body.mode == "icl" else None,
            x_vector_only_mode=body.mode == "quick",
        )
        for index, text in enumerate(chunks):
            if cancellations[key].is_set():
                return {}
            patch_job(key, message=f"正在合成第 {index + 1} / {len(chunks)} 句",
                      progress=10 + int(index / len(chunks) * 80))
            with torch.inference_mode():
                waves, sr = model.generate_voice_clone(
                    text=text, language=body.language, voice_clone_prompt=prompt,
                    max_new_tokens=1200, do_sample=True,
                    temperature=.8, top_p=.9, repetition_penalty=1.05,
                )
            wave = np.asarray(waves[0], dtype=np.float32).reshape(-1)
            if not len(wave) or not np.isfinite(wave).all():
                raise RuntimeError("模型没有返回有效音频，请更换参考片段重试。")
            if len(wave) / sr >= 94:
                raise RuntimeError("本句可能达到生成长度上限；请缩短句子后重新生成，避免导出截断配音。")
            raw = folder / f"raw_{index + 1:03}.wav"
            segment_path = folder / f"segment_{index + 1:03}.wav"
            sf.write(raw, wave, sr, subtype="PCM_16")
            run_ffmpeg(["-i", str(raw), "-af", f"atempo={body.speed}",
                        "-ar", "48000", "-ac", "1", "-c:a", "pcm_s24le",
                        "-y", str(segment_path)])
            audio, output_sr = sf.read(segment_path, dtype="float32")
            length = len(audio) / output_sr
            segments.append({"text": text, "start": cursor, "end": cursor + length,
                             "file": segment_path.name})
            audio_parts.append(audio)
            cursor += length
            if index < len(chunks) - 1:
                silence = np.zeros(round(body.gap * output_sr), dtype=np.float32)
                audio_parts.append(silence)
                cursor += len(silence) / output_sr
            raw.unlink()
        del prompt
    if cancellations[key].is_set():
        return {}
    patch_job(key, message="导出配音、分句字幕和工程包", progress=93)
    combined = np.concatenate(audio_parts)
    peak = float(np.max(np.abs(combined)))
    if peak > .98:
        combined *= .98 / peak
    sf.write(folder / "voice.wav", combined, 48000, subtype="PCM_24")
    run_ffmpeg(["-i", str(folder / "voice.wav"), "-c:a", "libmp3lame", "-b:a", "192k",
                "-metadata", "comment=AI-generated voice; reference rights not verified",
                "-y", str(folder / "voice.mp3")])
    (folder / "subtitles.srt").write_text(make_srt(segments), encoding="utf-8-sig")
    (folder / "script.txt").write_text(body.text, encoding="utf-8")
    manifest = {"ai_generated": True, "model": MODEL_ID, "model_path": str(MODEL_PATH),
                "profile": profile, "settings": body.model_dump(), "segments": segments,
                "duration": cursor, "created_at": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "notice": "AI合成配音；非本人原声发言。参考音色授权需由使用者另行确认。字幕为生成片段级时间轴，非逐字对齐。"}
    write_json(folder / "manifest.json", manifest)
    with zipfile.ZipFile(folder / "project.zip", "w", zipfile.ZIP_DEFLATED) as bundle:
        for file in folder.iterdir():
            if file.suffix != ".zip":
                bundle.write(file, file.name)
    return {"duration": cursor, "elapsed_seconds": manifest["elapsed_seconds"],
            "segments": len(segments), "files": {
                ext: f"/api/outputs/{key}/{name}" for ext, name in
                {"wav": "voice.wav", "mp3": "voice.mp3", "srt": "subtitles.srt",
                 "zip": "project.zip", "manifest": "manifest.json"}.items()}}


@app.post("/api/generate")
def generate(body: GenerateRequest):
    if not body.acknowledged:
        raise HTTPException(400, "请先确认了解音色授权与 AI 合成标识要求。")
    profile = lookup("profiles", body.profile_id)
    if body.mode == "icl" and not profile["transcript"].strip():
        raise HTTPException(400, "完整克隆模式需要参考录音的准确原文。")
    return submit("generate", body.model_dump(), lambda key: synthesize(key, body, profile))


@app.get("/api/jobs")
def list_jobs():
    with state_lock:
        return sorted(jobs.values(), key=lambda j: j["created_at"], reverse=True)[:100]


@app.get("/api/jobs/{key}")
def job_status(key: str):
    with state_lock:
        if key not in jobs:
            raise HTTPException(404, "任务不存在。")
        return dict(jobs[key])


@app.post("/api/jobs/{key}/cancel")
def cancel_job(key: str):
    with state_lock:
        if key not in cancellations:
            raise HTTPException(409, "任务已经结束。")
        cancellations[key].set()
        patch_job(key, message="已请求取消，将在当前处理步骤结束后停止")
    return {"ok": True}


@app.post("/api/model/unload")
def unload():
    with state_lock:
        if any(j["status"] in ("running", "queued") for j in jobs.values()):
            raise HTTPException(409, "请等待任务结束后再释放模型。")
        engine.unload()
    return {"ok": True}


@app.get("/api/outputs/{key}/{filename}")
def output_file(key: str, filename: str):
    job = job_status(key)
    if job["status"] != "complete" or job["kind"] != "generate":
        raise HTTPException(404, "配音尚未完成。")
    allowed = {"voice.wav", "voice.mp3", "subtitles.srt", "project.zip", "manifest.json"}
    if filename not in allowed:
        raise HTTPException(404, "文件不存在。")
    target = DATA / "outputs" / key / filename
    if not target.is_file():
        raise HTTPException(404, "输出文件已被移动或删除。")
    return FileResponse(target, filename=f"AI配音_{key[:8]}_{filename}")


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="ui")
