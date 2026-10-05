"""Friendly local launcher; opens a browser after the server is ready."""
import argparse
import json
import threading
import time
import urllib.request
import webbrowser


def is_studio(url):
    try:
        with urllib.request.urlopen(url + "/api/config", timeout=1) as response:
            return json.load(response).get("app_id") == "local-voice-studio"
    except (OSError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description="声刻 · 本地 AI 配音工作台")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    url = f"http://127.0.0.1:{args.port}"
    if is_studio(url):
        print(f"Voice Studio is already running: {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return
    if not args.no_browser:
        def open_when_ready():
            for _ in range(120):
                if is_studio(url):
                    webbrowser.open(url)
                    return
                time.sleep(.5)
        threading.Thread(target=open_when_ready, daemon=True).start()
    import uvicorn
    uvicorn.run("studio.server:app", host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
