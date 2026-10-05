import os
import tempfile
from pathlib import Path
from unittest.mock import patch

# Test data never touches the user's voice profiles or generated outputs.
TEST_ROOT = tempfile.TemporaryDirectory(prefix="voice-studio-test-")
os.environ["VOICE_DATA_DIR"] = TEST_ROOT.name

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from studio import server
from studio.audio import (
    extract_reference,
    make_srt,
    probe,
    split_text,
    timestamp,
    waveform,
)

client = TestClient(server.app)
headers = {"X-Studio-Token": server.TOKEN}


def test_project_paths_follow_the_relocated_package():
    assert server.ROOT == Path(server.__file__).resolve().parents[1]
    assert (server.ROOT / "web" / "index.html").is_file()
    assert server.DATA == Path(TEST_ROOT.name).resolve()


@pytest.fixture
def reference(tmp_path):
    path = tmp_path / "source.wav"
    sr = 24000
    signal = .2 * np.sin(2 * np.pi * 220 * np.arange(sr * 10) / sr)
    sf.write(path, signal, sr)
    return path


def test_text_segmentation():
    assert split_text("你好。世界！\n再见？") == ["你好。", "世界！", "再见？"]
    long = "很长的文案，" * 50
    chunks = split_text(long, limit=40)
    assert all(len(chunk) <= 40 for chunk in chunks)
    assert "".join(chunks) == long
    with pytest.raises(ValueError):
        split_text(" \n ")


def test_srt_boundaries():
    assert timestamp(59.9996) == "00:01:00,000"
    assert timestamp(3601.25) == "01:00:01,250"
    assert "00:00:00,000 --> 00:00:02,500" in make_srt(
        [{"start": 0, "end": 2.5, "text": "测试"}])


def test_ffmpeg_extract_and_waveform(reference, tmp_path):
    info = probe(reference)
    assert info["duration"] == 10
    target = tmp_path / "clip.wav"
    result = extract_reference(reference, target, 2, 7)
    assert result["duration"] == 5
    assert len(waveform(reference, 80)) == 80
    for start, end in [(-1, 4), (0, 2), (8, 15), (0, 26)]:
        with pytest.raises(ValueError):
            extract_reference(reference, target, start, end)


def test_silence_rejected(tmp_path):
    source, target = tmp_path / "silent.wav", tmp_path / "clip.wav"
    sf.write(source, np.zeros(24000 * 5), 24000)
    with pytest.raises(ValueError, match="静音"):
        extract_reference(source, target, 0, 4)


def test_csrf_and_host_guard():
    assert client.post("/api/generate", json={}).status_code == 403
    assert client.get("/api/config", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/config").json()["token"] == server.TOKEN
    assert client.get("/api/config").headers["cache-control"] == "no-store"


def test_input_validation():
    for data in [
        {"profile_id": "x", "text": " ", "acknowledged": True},
        {"profile_id": "x", "text": "hello", "speed": 8},
        {"profile_id": "x", "text": "hello", "language": "invalid"},
    ]:
        assert client.post("/api/generate", headers=headers, json=data).status_code == 422
    assert client.post("/api/generate", headers=headers,
                       json={"profile_id": "x", "text": "hello"}).status_code == 400
    assert client.get("/api/profiles/..%5C..%5C/audio").status_code == 404


def test_upload_profile_edit(reference):
    with reference.open("rb") as file:
        result = client.post("/api/sources", headers=headers,
                             files={"file": ("my-reference.wav", file, "audio/wav")})
    assert result.status_code == 200, result.text
    source = result.json()
    assert client.get(f"/api/sources/{source['id']}").status_code == 200
    clip = client.post("/api/profiles", headers=headers, json={
        "source_id": source["id"], "start": 1, "end": 6, "name": "测试音色"})
    assert clip.status_code == 200, clip.text
    profile = clip.json()
    assert profile["duration"] == 5
    assert client.get(profile["url"]).status_code == 200
    edited = client.put(f"/api/profiles/{profile['id']}", headers=headers,
                        json={"name": "已校对", "transcript": "参考文字。"})
    assert edited.json()["transcript"] == "参考文字。"
    assert client.get("/api/profiles").json()
    bad_file = client.post("/api/sources", headers=headers,
                           files={"file": ("malicious.exe", b"anything")})
    assert bad_file.status_code == 400


def test_icl_requires_transcript(reference):
    with patch.object(server, "SAMPLE_PATH", reference):
        profile = client.post("/api/profiles", headers=headers, json={
            "source_id": "sample", "start": 0, "end": 5}).json()
    response = client.post("/api/generate", headers=headers, json={
        "profile_id": profile["id"], "text": "测试。", "mode": "icl", "acknowledged": True})
    assert response.status_code == 400
    assert "原文" in response.json()["detail"]


def test_bad_job_and_output():
    assert client.get("/api/jobs/missing").status_code == 404
    assert client.post("/api/jobs/missing/cancel", headers=headers).status_code == 409
    assert client.get("/api/outputs/missing/voice.wav").status_code == 404


def test_worker_errors_and_cancel():
    import time

    def fail(key):
        raise RuntimeError("intentional failure")
    key = server.submit("test", {}, fail)["id"]
    for _ in range(200):
        status = client.get(f"/api/jobs/{key}").json()
        if status["status"] == "failed":
            break
        time.sleep(.01)
    assert status["status"] == "failed"
    assert status["message"] == "intentional failure"


def test_ui_assets():
    assert client.get("/").status_code == 200
    assert "声刻" in client.get("/").text
    assert client.get("/app.js").status_code == 200
    assert client.get("/style.css").status_code == 200
    assert client.get("/.venv/pyvenv.cfg").status_code == 404


def test_full_export_with_mock_model(reference):
    """Exercise assembly, time-stretch, subtitles and downloads without inference."""
    import time
    import zipfile

    class MockModel:
        def create_voice_clone_prompt(self, **kwargs):
            return []

        def generate_voice_clone(self, **kwargs):
            sr = 24000
            return [.1 * np.sin(2 * np.pi * 180 * np.arange(sr) / sr)], sr

    with patch.object(server, "SAMPLE_PATH", reference):
        profile = client.post("/api/profiles", headers=headers, json={
            "source_id": "sample", "start": 0, "end": 5}).json()
    with patch.object(server.engine, "load", return_value=MockModel()):
        response = client.post("/api/generate", headers=headers, json={
            "profile_id": profile["id"], "text": "第一句。第二句！", "speed": 1.2,
            "gap": .3, "acknowledged": True})
        assert response.status_code == 200, response.text
        key = response.json()["id"]
        for _ in range(300):
            job = client.get(f"/api/jobs/{key}").json()
            if job["status"] in ("complete", "failed"):
                break
            time.sleep(.05)
        assert job["status"] == "complete", job
    result = job["result"]
    assert result["segments"] == 2
    assert 1.8 < result["duration"] < 2.2
    for url in result["files"].values():
        assert client.get(url).status_code == 200
    manifest = client.get(result["files"]["manifest"]).json()
    assert manifest["ai_generated"] is True
    segments = manifest["segments"]
    assert segments[1]["start"] - segments[0]["end"] == pytest.approx(.3)
    folder = server.DATA / "outputs" / key
    with zipfile.ZipFile(folder / "project.zip") as bundle:
        assert {"voice.wav", "voice.mp3", "subtitles.srt", "manifest.json", "segment_001.wav"} <= set(bundle.namelist())
    assert probe(folder / "voice.wav")["sample_rate"] == 48000
    assert client.get(f"/api/outputs/{key}/raw_001.wav").status_code == 404


def test_queue_cancel_before_start():
    import threading
    import time

    release = threading.Event()
    server.submit("test", {}, lambda key: release.wait(4))
    second = server.submit("test", {}, lambda key: {"unexpected": True})["id"]
    assert client.post(f"/api/jobs/{second}/cancel", headers=headers).status_code == 200
    release.set()
    for _ in range(100):
        job = client.get(f"/api/jobs/{second}").json()
        if job["status"] == "cancelled":
            break
        time.sleep(.01)
    assert job["status"] == "cancelled"
