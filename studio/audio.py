import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf


def run_ffmpeg(args: list[str], timeout: int = 180) -> bytes:
    executable = shutil.which("ffmpeg")
    if not executable:
        raise RuntimeError("未找到 FFmpeg，请安装并加入 PATH。")
    result = subprocess.run(
        [executable, "-hide_banner", "-loglevel", "error", "-nostdin",
         "-protocol_whitelist", "file,pipe", *args],
        capture_output=True, timeout=timeout, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise ValueError("音频处理失败：" + result.stderr.decode("utf-8", errors="replace")[-1200:])
    return result.stdout


def probe(path: Path) -> dict:
    exe = shutil.which("ffprobe")
    if not exe:
        raise RuntimeError("未找到 ffprobe，请安装 FFmpeg 并加入 PATH。")
    result = subprocess.run(
        [exe, "-v", "error", "-protocol_whitelist", "file,pipe", "-show_entries",
         "format=duration:stream=codec_type,sample_rate,channels", "-of", "json", str(path)],
        capture_output=True, timeout=30, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise ValueError("无法读取音频文件。")
    data = json.loads(result.stdout)
    stream = next((s for s in data["streams"] if s.get("codec_type") == "audio"), None)
    if not stream:
        raise ValueError("文件中没有音轨。")
    duration = float(data["format"]["duration"])
    if not 0 < duration <= 10800:
        raise ValueError("音频须大于 0 秒且不超过 3 小时。")
    return {"duration": duration, "sample_rate": int(stream["sample_rate"]),
            "channels": int(stream["channels"])}


def waveform(path: Path, count: int = 700) -> list[float]:
    raw = run_ffmpeg(["-i", str(path), "-vn", "-ac", "1", "-ar", "1000",
                      "-f", "f32le", "pipe:1"])
    samples = np.frombuffer(raw, dtype="<f4")
    if not samples.size:
        return []
    return [round(float(np.max(np.abs(part))), 4) if len(part) else 0
            for part in np.array_split(samples, count)]


def extract_reference(source: Path, target: Path, start: float, end: float) -> dict:
    info = probe(source)
    if start < 0 or end > info["duration"] + .05 or not 3 <= end - start <= 25:
        raise ValueError("请选择文件范围内 3–25 秒的单人清晰语音。")
    run_ffmpeg(["-ss", str(start), "-i", str(source), "-t", str(end - start),
                "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", "-y", str(target)])
    audio, sr = sf.read(target, dtype="float32")
    rms = float(np.sqrt(np.mean(audio ** 2)))
    peak = float(np.max(np.abs(audio)))
    if rms < .0005:
        target.unlink(missing_ok=True)
        raise ValueError("选中片段几乎静音，请换一个有人说话的片段。")
    warnings = []
    if np.mean(np.abs(audio) >= .99) > .005:
        warnings.append("录音可能存在削波失真，建议换一段。")
    if rms < .015:
        warnings.append("音量偏低，建议选取更清晰的录音。")
    return {"duration": len(audio) / sr, "peak": peak, "rms": rms,
            "warnings": warnings, "sample_rate": sr}


def split_text(text: str, limit: int = 100) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise ValueError("请输入配音文案。")
    sentences = re.findall(r"[^。！？!?\n]+[。！？!?]*|[。！？!?]+", text)
    chunks = []
    for sentence in sentences:
        sentence = sentence.strip()
        while len(sentence) > limit:
            cut = max(sentence.rfind(char, 0, limit) for char in "，,；;：: ")
            cut = cut + 1 if cut >= limit // 3 else limit
            chunks.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            chunks.append(sentence)
    return chunks


def timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def make_srt(segments: list[dict]) -> str:
    return "\n\n".join(
        f"{i}\n{timestamp(s['start'])} --> {timestamp(s['end'])}\n{s['text']}"
        for i, s in enumerate(segments, 1)
    ) + "\n"
