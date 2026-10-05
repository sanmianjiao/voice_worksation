"""Resumable range download from PyTorch's official index, with SHA256 verification.

Optional fallback for proxies that stall on a multi-gigabyte single request.
Run with Python 3.10+; it downloads, but does not install, the Windows cp310 wheel.
"""
import concurrent.futures
import hashlib
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "https://download.pytorch.org/whl/cu128/torch-2.8.0%2Bcu128-cp310-cp310-win_amd64.whl"
NAME = "torch-2.8.0+cu128-cp310-cp310-win_amd64.whl"
CHUNK = 16 * 1024 * 1024


def main():
    index = urllib.request.urlopen("https://download.pytorch.org/whl/cu128/torch/", timeout=60).read().decode()
    links = re.findall(r'href="([^"]+)"', index)
    selected = next(link for link in links if NAME in urllib.parse.unquote(link))
    expected_hash = selected.split("#sha256=")[1]
    directory = ROOT / ".downloads"
    directory.mkdir(exist_ok=True)
    target = directory / NAME
    if target.is_file() and digest(target) == expected_hash:
        print(f"Already verified: {target}", flush=True)
        return
    with urllib.request.urlopen(urllib.request.Request(URL, headers={"Range": "bytes=0-0"}), timeout=60) as response:
        size = int(response.headers["Content-Range"].split("/")[-1])

    def get_chunk(index):
        first, last = index * CHUNK, min((index + 1) * CHUNK, size) - 1
        path = directory / f"torch.part{index:04}"
        if path.is_file() and path.stat().st_size == last - first + 1:
            return path
        for attempt in range(5):
            try:
                request = urllib.request.Request(
                    URL, headers={"Range": f"bytes={first}-{last}"})
                with urllib.request.urlopen(request, timeout=90) as response:
                    if response.status != 206 or response.headers.get("Content-Range") != f"bytes {first}-{last}/{size}":
                        raise RuntimeError("The server did not honor the requested range")
                    payload = response.read()
                if len(payload) != last - first + 1:
                    raise RuntimeError("Incomplete range")
                path.write_bytes(payload)
                return path
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(min(2 ** attempt, 8))

    count = (size + CHUNK - 1) // CHUNK
    print(f"Downloading {size / 1024 ** 3:.2f} GiB in {count} verified ranges", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        for completed, _ in enumerate(executor.map(get_chunk, range(count)), 1):
            if completed % 8 == 0 or completed == count:
                print(f"{completed}/{count} ranges complete", flush=True)
    with target.open("wb") as output:
        for i in range(count):
            output.write((directory / f"torch.part{i:04}").read_bytes())
    if digest(target) != expected_hash:
        raise RuntimeError("SHA256 mismatch; do not install this download")
    # Remove only this downloader's validated, now-redundant part files.
    for i in range(count):
        (directory / f"torch.part{i:04}").unlink()
    print(f"SHA256 verified: {expected_hash}\n{target}", flush=True)


def digest(path):
    hasher = hashlib.sha256()
    with path.open("rb") as file:
        while block := file.read(8 * 1024 * 1024):
            hasher.update(block)
    return hasher.hexdigest()


if __name__ == "__main__":
    main()
