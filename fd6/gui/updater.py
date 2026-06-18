"""In-app update check + opt-in self-update against the GitHub Releases API.

Flow:
  1. On launch (frozen builds only), a background QThread queries
     api.github.com/repos/<OWNER>/<REPO>/releases/latest.
  2. If the latest tag's version is newer than the running fd6.__version__, the
     GUI shows a "Update X available — update now?" prompt.
  3. If the user accepts, we download the release's .exe asset to a temp file,
     write a tiny .bat that waits for FD6 to exit, swaps the new exe in, and
     relaunches it — then quit the app so the swap can happen.

Everything is best-effort and fully guarded: no network, a private/missing
repo, a rate-limit, or any parse error simply means "no update offered" and the
app continues normally. Update checks are skipped entirely when running from
source (not frozen), since there's no single exe to replace.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

import fd6

# GitHub repo that publishes FD6 releases.
GITHUB_OWNER = "tokyubevoxelverse"
GITHUB_REPO = "ForzaDesigner6"
# Use the full releases LIST (not /releases/latest). /latest is eventually
# consistent and can return a stale release for a minute or two right after you
# publish — which is why "Check for updates" sometimes said "up to date" when a
# newer build was already live. The list lets us pick the highest version
# ourselves, and we cache-bust the request so no proxy hands us a stale copy.
RELEASES_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases?per_page=30"
RELEASES_PAGE = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"


def _parse_version(text: str) -> tuple[int, ...]:
    """Extract a comparable FD6 app version (X.Y.Z) from arbitrary tag/name text.

    CRITICAL: only THREE-component dotted numbers count as a version. FD6
    versions are X.Y.Z (e.g. 0.5.3, 0.4.7). FH6 *build numbers* like 354.221 /
    364.933 are TWO components and must NEVER be read as a version — an old
    release tagged `v354.221` parsed as (354, 221) once outranked (0, 5, 3) and
    auto-updated everyone DOWN to the original build. Requiring 3 components
    rejects those build numbers outright. When several 3-component groups exist
    (e.g. a name with both "0.5.3" and a "Build 1.2.3"), we take the SMALLEST
    major group, since the app version is the low-major one (0.x today).
    Returns () when no 3-component version is present (treated as "no version").
    """
    groups = re.findall(r"\d+\.\d+\.\d+", text or "")
    if not groups:
        return ()
    parsed = [tuple(int(p) for p in g.split(".")) for g in groups]
    # Prefer the lowest-major group (the app version), tie-break by highest value.
    parsed.sort(key=lambda v: (v[0], [-x for x in v]))
    return parsed[0]


def _is_newer(latest: str, current: str) -> bool:
    lv, cv = _parse_version(latest), _parse_version(current)
    if not lv:
        return False
    # Pad to equal length for a clean tuple compare (0.5 == 0.5.0).
    n = max(len(lv), len(cv))
    lv += (0,) * (n - len(lv))
    cv += (0,) * (n - len(cv))
    return lv > cv


class UpdateInfo:
    def __init__(self, version: str, tag: str, asset_url: str | None,
                 asset_name: str | None, notes: str) -> None:
        self.version = version
        self.tag = tag
        self.asset_url = asset_url
        self.asset_name = asset_name
        self.notes = notes


class UpdateChecker(QObject):
    """Background GitHub release check. Emits `update_available` only when a
    strictly-newer release with a downloadable .exe asset exists."""

    update_available = Signal(object)  # UpdateInfo
    no_update = Signal()
    failed = Signal(str)

    def run(self) -> None:
        try:
            req = urllib.request.Request(
                RELEASES_API,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "FD6-Updater",
                    # Defeat any intermediary/proxy caching so we always see the
                    # newest published release immediately.
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.load(resp)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return

        # /releases returns a list; normalize so a single-object response (or an
        # unexpected shape) still works.
        releases = data if isinstance(data, list) else [data]
        current = fd6.__version__

        # Pick the genuinely highest-version, non-draft, non-prerelease release —
        # don't trust list order or /latest's eventual consistency.
        best = None
        best_ver: tuple[int, ...] = ()
        for rel in releases:
            if not isinstance(rel, dict):
                continue
            if rel.get("draft") or rel.get("prerelease"):
                continue
            tag = str(rel.get("tag_name") or rel.get("name") or "")
            ver = _parse_version(tag)
            if ver and ver > best_ver:
                best_ver, best = ver, rel

        if best is None:
            self.no_update.emit()
            return

        tag = str(best.get("tag_name") or best.get("name") or "")
        if not _is_newer(tag, current):
            self.no_update.emit()
            return

        asset_url = asset_name = None
        for a in best.get("assets", []) or []:
            name = str(a.get("name", ""))
            if name.lower().endswith(".exe"):
                asset_url = a.get("browser_download_url")
                asset_name = name
                break
        info = UpdateInfo(
            version=".".join(str(p) for p in best_ver) or tag,
            tag=tag,
            asset_url=asset_url,
            asset_name=asset_name,
            notes=str(best.get("body") or "").strip(),
        )
        self.update_available.emit(info)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def current_exe_path() -> Path:
    return Path(sys.executable)


def download_and_apply(info: UpdateInfo, progress_cb=None) -> None:
    """Download the new exe and stage a swap-and-relaunch, then exit.

    A small .bat waits for THIS exe to exit (so Windows releases the file lock),
    moves the downloaded exe over it, and relaunches. We then quit the app.
    Raises on failure so the caller can show an error and continue running.
    """
    if not info.asset_url:
        raise RuntimeError("This release has no downloadable .exe asset.")
    exe = current_exe_path()
    tmp_dir = Path(tempfile.gettempdir())
    new_exe = tmp_dir / (info.asset_name or "FD6_update.exe")

    req = urllib.request.Request(info.asset_url, headers={"User-Agent": "FD6-Updater"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        read = 0
        with open(new_exe, "wb") as f:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                read += len(chunk)
                if progress_cb and total:
                    progress_cb(read, total)

    # Swap script: wait for the old process to release the exe, replace it,
    # verify the move succeeded, then relaunch.
    #
    # CRITICAL (the "Failed to load Python DLL ..._MEI######\python314.dll"
    # crash after auto-update): a PyInstaller one-file exe exports _MEIPASS2
    # pointing at its private temp extraction dir. If the relaunched child
    # inherits that variable, it tries to reuse the PARENT's extraction folder
    # instead of unpacking its own — but the parent deletes that folder as it
    # exits, so the child can't find python3xx.dll and dies. The .bat clears
    # _MEIPASS2 (and the related _PYI_* vars) before `start`, so the new exe
    # bootstraps cleanly. Manual launch worked precisely because it had no
    # inherited var.
    bat = tmp_dir / "fd6_update.bat"
    bat.write_text(
        "@echo off\r\n"
        "echo Updating Forza Designer 6...\r\n"
        ":wait\r\n"
        "timeout /t 1 /nobreak >nul\r\n"
        f'tasklist /fi "PID eq {os.getpid()}" 2>nul | find "{os.getpid()}" >nul\r\n'
        "if not errorlevel 1 goto wait\r\n"
        "rem one more beat so Windows fully releases the exe file lock\r\n"
        "timeout /t 1 /nobreak >nul\r\n"
        f'move /y "{new_exe}" "{exe}" >nul\r\n'
        f'if not exist "{exe}" goto fail\r\n'
        "set _MEIPASS2=\r\n"
        "set _PYI_APPLICATION_HOME_DIR=\r\n"
        "set _PYI_ARCHIVE_FILE=\r\n"
        "set _PYI_PARENT_PROCESS_LEVEL=\r\n"
        f'start "" "{exe}"\r\n'
        'del "%~f0"\r\n'
        "exit\r\n"
        ":fail\r\n"
        "echo Update failed to replace the program file.\r\n"
        "pause\r\n"
        'del "%~f0"\r\n',
        encoding="ascii",
    )
    # Launch the swap script with a CLEAN copy of the environment that has the
    # PyInstaller bootstrap vars stripped, so even the cmd-inherited values can't
    # leak into the relaunched exe.
    child_env = {k: v for k, v in os.environ.items()
                 if k not in ("_MEIPASS2", "_PYI_APPLICATION_HOME_DIR",
                              "_PYI_ARCHIVE_FILE", "_PYI_PARENT_PROCESS_LEVEL")}
    subprocess.Popen(
        ["cmd", "/c", str(bat)],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
        env=child_env,
    )
