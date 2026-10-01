"""The server at a glance, for the Dashboard's cake boards (pages.py): the server's RAM and disk, how
much of its RAM Someless Mail takes, and whether it's healthy. Read as the kernel tells them, with
nothing to install: in the container, /proc/meminfo is the whole server's (the VPS), and the
container's own cgroup is Someless Mail's (the panel, the webmail and the mail engine together).
On a machine that isn't Linux (a Windows one, for development) the RAM is asked of Windows, and the
app's RAM is this process's alone. A figure that can't be told is None."""
import ctypes
import shutil
import sys
from pathlib import Path

from flask import current_app

from . import engine
from .engine import EngineError, EngineUnavailable

CGROUP = Path("/sys/fs/cgroup")
GB = 1024 ** 3
MB = 1024 ** 2
UNKNOWN = "Can't tell here"


def size_text(size):
    """Bytes as people say them: 3 GB, 7.8 GB, 330 MB."""
    if size >= GB:
        return f"{size / GB:.1f}".removesuffix(".0") + " GB"
    return f"{round(size / MB)} MB"


def percent(part, whole):
    return round(part * 100 / whole, 1) if whole else None


# --- the server's RAM -----------------------------------------------------------------------------

def parse_meminfo(text):
    """(total, used) in bytes from /proc/meminfo: used is what isn't available (the cache the kernel
    would give back counts as free, as `free` shows it)."""
    values = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        if rest.strip():
            values[name] = int(rest.split()[0]) * 1024
    total, available = values.get("MemTotal"), values.get("MemAvailable", values.get("MemFree"))
    return (total, total - available) if total and available is not None else None


def memory():
    """(total, used) of the server's RAM, or None."""
    if sys.platform == "win32":
        return _windows_memory()
    try:
        return parse_meminfo(Path("/proc/meminfo").read_text())
    except OSError:
        return None


def _windows_memory():
    class Status(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                    ("available", ctypes.c_ulonglong), ("page_total", ctypes.c_ulonglong),
                    ("page_available", ctypes.c_ulonglong), ("virtual_total", ctypes.c_ulonglong),
                    ("virtual_available", ctypes.c_ulonglong), ("extended", ctypes.c_ulonglong)]
    status = Status(length=ctypes.sizeof(Status))
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return status.total, status.total - status.available


# --- the disk ---------------------------------------------------------------------------------------

def disk():
    """(total, used) of the disk the mail is kept on, or None."""
    try:
        usage = shutil.disk_usage(current_app.config["DATA_DIR"])
    except OSError:
        return None
    return usage.total, usage.used


# --- Someless Mail's own RAM -------------------------------------------------------------------------

def _number(path):
    try:
        return int(path.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _stat(path, name):
    try:
        for line in path.read_text().splitlines():
            key, _, value = line.partition(" ")
            if key == name:
                return int(value)
    except (OSError, ValueError):
        return None
    return 0


def cgroup_memory(root=CGROUP):
    """What the container takes, as `docker stats` counts it: its memory without the file cache it
    can drop. cgroup v2 (memory.current), or v1 (memory/memory.usage_in_bytes); None outside one."""
    root = Path(root)
    current = _number(root / "memory.current")
    if current is not None:
        return current - (_stat(root / "memory.stat", "inactive_file") or 0)
    usage = _number(root / "memory" / "memory.usage_in_bytes")
    if usage is not None:
        return usage - (_stat(root / "memory" / "memory.stat", "total_inactive_file") or 0)
    return None


def app_memory():
    """Someless Mail's RAM in bytes: its container's, else this process's own, or None."""
    if sys.platform == "win32":
        return _windows_process_memory()
    found = cgroup_memory()
    if found is not None:
        return found
    rss = _stat(Path("/proc/self/status"), "VmRSS:")
    return rss * 1024 if rss else None


def _windows_process_memory():
    size_t = ctypes.c_size_t

    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("page_faults", ctypes.c_ulong), ("peak_working_set", size_t),
                    ("working_set", size_t), ("peak_paged_pool", size_t), ("paged_pool", size_t),
                    ("peak_nonpaged_pool", size_t), ("nonpaged_pool", size_t), ("pagefile", size_t),
                    ("peak_pagefile", size_t)]
    counters = Counters(cb=ctypes.sizeof(Counters))
    current = ctypes.windll.kernel32.GetCurrentProcess
    current.restype = ctypes.c_void_p   # (a handle: 64 bits wide, not an int)
    ask = ctypes.windll.psapi.GetProcessMemoryInfo
    ask.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    if not ask(current(), ctypes.byref(counters), counters.cb):
        return None
    return counters.working_set


# --- health -------------------------------------------------------------------------------------------

def health():
    """{"state": ok, warning, down or off; "title"; "detail"}: whether the mail engine runs, answers
    and is in line with the panel."""
    if not engine.enabled():
        return {"state": "off", "title": "No mail engine here", "detail": "It runs in the Docker container."}
    if engine.preparing():
        return {"state": "warning", "title": "Starting up", "detail": "The mail engine is getting ready."}
    try:
        engine.client().get("SystemSettings")
    except (EngineUnavailable, EngineError):
        return {"state": "down", "title": "Mail engine not answering",
                "detail": "It restarts by itself. If this stays, restart the container."}
    problem = engine.state()["sync_error"]
    if problem:
        return {"state": "warning", "title": "Catching up", "detail": f"Behind on a change: {problem}"}
    return {"state": "ok", "title": "Healthy", "detail": "Mail engine running, up to date."}


# --- the boards ---------------------------------------------------------------------------------------

def cards():
    """What the four boards say, in order: {key: {count, label, ...}} (the page, and its refresh)."""
    ram, space, mine = memory(), disk(), app_memory()
    found = {}
    for key, measured, what in (("ram", ram, "RAM"), ("disk", space, "Disk")):
        if measured:
            total, used = measured
            found[key] = {"count": size_text(used), "label": f"{what} used of {size_text(total)}", "used": percent(used, total)}
        else:
            found[key] = {"count": UNKNOWN, "label": what, "used": None}
    if ram and mine is not None:
        found["app-ram"] = {"count": f"{percent(mine, ram[0])}%", "label": f"Someless Mail's RAM: {size_text(mine)}"}
    else:
        found["app-ram"] = {"count": UNKNOWN, "label": "Someless Mail's RAM"}
    found["health"] = health()
    return found
