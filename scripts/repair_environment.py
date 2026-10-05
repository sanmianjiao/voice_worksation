"""Repair this project's existing Python 3.10 environment after moving the folder.

Run using the BASE interpreter: py -3.10 scripts/repair_environment.py
Installed packages and model files are preserved; nothing is downloaded.
"""
import argparse
import importlib.metadata
import json
import subprocess
import sys
import urllib.parse
import urllib.request
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".venv"


def rewrite_entry_points(previous_root):
    from pip._vendor.distlib.scripts import ScriptMaker

    if Path(sys.prefix).resolve() != ENV.resolve():
        raise RuntimeError("Entry-point repair must run inside this project's environment.")
    scripts = ENV / "Scripts"
    maker = ScriptMaker(None, str(scripts))
    maker.executable = str(scripts / "python.exe")
    maker.clobber = True
    maker.variants = {""}
    rewritten = []
    for distribution in importlib.metadata.distributions():
        for entry in distribution.entry_points:
            if entry.group not in {"console_scripts", "gui_scripts"}:
                continue
            if Path(entry.name).name != entry.name:
                raise RuntimeError(f"Unexpected entry-point name: {entry.name}")
            maker.make(f"{entry.name} = {entry.value}",
                       options={"gui": entry.group == "gui_scripts"})
            rewritten.append(entry.name)
    # pip's versioned launcher can be present without its own metadata entry.
    maker.make("pip3.10 = pip._internal.cli.main:main")
    rewritten.append("pip3.10")

    # Some wheels (for example numba) install legacy script files rather than
    # advertising console entry points. Repair their interpreter line as well.
    legacy_scripts = []
    for script in scripts.iterdir():
        if not script.is_file() or script.suffix.lower() not in {"", ".py", ".pyw"}:
            continue
        payload = script.read_bytes()
        first, separator, remainder = payload.partition(b"\n")
        if not separator or not first.startswith(b"#!") or b"python" not in first.lower():
            continue
        interpreter = "pythonw.exe" if b"pythonw" in first.lower() else "python.exe"
        updated = f"#!{scripts / interpreter}".encode()
        if first.rstrip(b"\r") != updated:
            script.write_bytes(updated + b"\n" + remainder)
            legacy_scripts.append(script.name)

    # Preserve archive hashes while relocating local wheel provenance.
    repaired_metadata = []
    if previous_root:
        previous = Path(previous_root).resolve()
        for metadata in (ENV / "Lib" / "site-packages").glob("*.dist-info/direct_url.json"):
            record = json.loads(metadata.read_text(encoding="utf-8"))
            parsed = urllib.parse.urlparse(record.get("url", ""))
            if parsed.scheme != "file":
                continue
            old_file = Path(urllib.request.url2pathname(parsed.path)).resolve()
            try:
                relative = old_file.relative_to(previous)
            except ValueError:
                continue
            relocated = (ROOT / relative).resolve()
            if ROOT not in relocated.parents or not relocated.is_file():
                continue
            record["url"] = relocated.as_uri()
            metadata.write_text(json.dumps(record, indent=2), encoding="utf-8")
            repaired_metadata.append(metadata.parent.name)
    report = {"project_root": str(ROOT), "python": sys.executable,
              "entry_points_rebuilt": sorted(set(rewritten)),
              "legacy_scripts_repaired": legacy_scripts,
              "local_wheel_metadata_repaired": repaired_metadata}
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "logs" / "environment_relocation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous-root")
    parser.add_argument("--entry-points-only", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 10):
        raise SystemExit("Use Python 3.10: py -3.10 scripts/repair_environment.py")
    if ENV.resolve().parent != ROOT:
        raise SystemExit("Refusing to modify an environment outside this project.")
    if not (ENV / "Lib" / "site-packages" / "pip").is_dir():
        raise SystemExit("Existing environment missing; run setup.ps1 instead.")
    if args.entry_points_only:
        rewrite_entry_points(args.previous_root)
        return
    if Path(sys.prefix).resolve() == ENV.resolve():
        raise SystemExit("Run with BASE Python, not .venv: py -3.10 scripts/repair_environment.py")
    # Rebuild interpreter launchers and activation files WITHOUT clearing packages.
    venv.EnvBuilder(with_pip=False, clear=False).create(str(ENV))
    command = [str(ENV / "Scripts" / "python.exe"), str(Path(__file__).resolve()),
               "--entry-points-only"]
    if args.previous_root:
        command.extend(["--previous-root", args.previous_root])
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
