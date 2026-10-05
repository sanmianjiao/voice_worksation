"""Explicit, one-shot Windows sleep request; never called by the studio itself.

Example: python scripts/sleep_pc.py --delay 60
Create data/cancel_sleep.flag during the countdown to cancel.
"""
import argparse
import ctypes
import json
import os
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=int, default=60)
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("This helper is Windows-only")
    if not 0 <= args.delay <= 600:
        raise SystemExit("Delay must be 0–600 seconds")
    folder = ROOT / "data"
    folder.mkdir(exist_ok=True)
    log = folder / "sleep_status.json"
    cancel = folder / "cancel_sleep.flag"
    def status(state, **extra):
        log.write_text(json.dumps({"status": state, "time": datetime.now().astimezone().isoformat(),
                                   **extra}, ensure_ascii=False, indent=2), encoding="utf-8")
    status("scheduled", delay_seconds=args.delay)
    for _ in range(args.delay):
        if cancel.exists():
            status("cancelled", reason="cancel_sleep.flag exists")
            return
        time.sleep(1)
    if cancel.exists():
        status("cancelled", reason="cancel_sleep.flag exists")
        return
    # Enable only the privilege Windows requires for SetSuspendState.
    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]
    class LUID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]
    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [("PrivilegeCount", wintypes.DWORD),
                    ("Privileges", LUID_AND_ATTRIBUTES * 1)]
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    power = ctypes.WinDLL("powrprof", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(LUID)]
    advapi.AdjustTokenPrivileges.argtypes = [
        wintypes.HANDLE, wintypes.BOOL, ctypes.POINTER(TOKEN_PRIVILEGES),
        wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
    token = wintypes.HANDLE()
    try:
        if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x20 | 0x08, ctypes.byref(token)):
            raise ctypes.WinError(ctypes.get_last_error())
        privileges = TOKEN_PRIVILEGES()
        privileges.PrivilegeCount = 1
        if not advapi.LookupPrivilegeValueW(None, "SeShutdownPrivilege",
                                            ctypes.byref(privileges.Privileges[0].Luid)):
            raise ctypes.WinError(ctypes.get_last_error())
        privileges.Privileges[0].Attributes = 0x2
        ctypes.set_last_error(0)
        if not advapi.AdjustTokenPrivileges(token, False, ctypes.byref(privileges), 0, None, None):
            raise ctypes.WinError(ctypes.get_last_error())
        if ctypes.get_last_error() == 1300:
            raise RuntimeError("Current Windows account lacks the sleep privilege")
        power.SetSuspendState.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_ubyte]
        power.SetSuspendState.restype = ctypes.c_ubyte
        status("sleep_requested", hibernate=False, force=False, disable_wake_events=False)
        result = power.SetSuspendState(0, 0, 0)
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
        # On a normal sleep, this statement executes after resume.
        status("sleep_call_returned_success")
    except Exception as exc:
        status("failed", error=str(exc))
        raise
    finally:
        if token.value:
            kernel.CloseHandle(token)


if __name__ == "__main__":
    main()
