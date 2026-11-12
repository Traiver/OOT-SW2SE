#!/usr/bin/env python3
"""Linux host for the OOT SW2SE save editor.

All editor logic (UI, save parser, patch ZIP generator) lives in
../editor.html. The Windows host (../Program.cs) shows it in WebView2 and the
macOS host (../macos/OOTSW2SE.swift) in WKWebView. This file is the Linux
counterpart: instead of embedding a web view, it serves the same editor.html,
unchanged, to the user's default browser from a private server on 127.0.0.1.

The page talks to its host through `window.chrome.webview` (the WebView2
bridge). The served page gets a small shim that provides that object on top
of fetch() to this server, which implements the host actions the page uses:
  - "openBackup": pick a backup/save folder and return its files as base64
  - "savePatch":  receive the patch ZIP as base64 and save it with a dialog
  - "saveFolder": receive the patch files and write them to a new folder
  - "workspace":  resizes the native window on Windows/macOS; ignored here
Folder and file dialogs are shown with kdialog or zenity, so they look native
on KDE and GNOME. Size limits and folder rules mirror the other two hosts so
all of them accept the same backups and write the same patches.

Only the Python 3 standard library is used. The server exits by itself a few
seconds after the last editor tab is closed.

Security model: the server listens on 127.0.0.1 only and checks the Host
header (against DNS rebinding). The browser is opened with a one-time launch
URL that sets an HttpOnly, SameSite=Strict session cookie. API requests need
that cookie, the page's own Origin and a custom header, so neither other
websites nor other local users can call the host.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
import hmac
import http.cookies
import http.server
import json
import os
import re
import secrets
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser

APP_NAME = "OOT SW2SE"
APP_ID = "oot-sw2se"

# Values shared with Program.cs and OOTSW2SE.swift so every host accepts the
# same input.
MAX_BACKUP_BYTES = 8 * 1024 * 1024  # all files read from one backup
MAX_FILE_BYTES = 2 * 1024 * 1024  # a single .sav or manifest file
SLOT_COUNT = 6  # slot_00 ... slot_05
# Largest request body accepted: a base64 patch plus JSON overhead.
MAX_REQUEST_BYTES = 3 * MAX_BACKUP_BYTES

HERE = os.path.dirname(os.path.abspath(__file__))


class HostError(Exception):
    """An error whose message is shown to the user by the editor page."""


def describe_os_error(error: OSError) -> str:
    """Formats an OSError as a short sentence for the user."""
    text = error.strerror or str(error)
    return f"{text}: {error.filename}" if error.filename else text


# MARK: - Resources

def _bundled(name: str) -> bytes | None:
    """Returns a file stored next to this module, also inside a zipapp.

    The path must start exactly like __file__: a zipapp started as
    ./oot-sw2se.pyz is known to its loader by that relative path, so an
    absolute path (HERE) would not be found inside the archive.
    """
    try:
        return __loader__.get_data(os.path.join(os.path.dirname(__file__), name))  # type: ignore[name-defined]
    except (OSError, AttributeError):
        return None


def _repository(name: str) -> bytes | None:
    """Returns a file from the repository root when run from a checkout."""
    try:
        with open(os.path.join(os.path.dirname(HERE), name), "rb") as file:
            return file.read()
    except OSError:
        return None


def resource(name: str) -> bytes:
    """Loads a resource from the built app or, failing that, the checkout."""
    data = _bundled(name)
    if data is None:
        data = _repository(name)
    if data is None:
        raise HostError(f"{name} is missing. Run linux/build.sh or start the editor from the repository.")
    return data


def editor_version() -> str:
    """The version shown in the editor.

    build.sh stores it in VERSION. From a checkout it is read from
    AssemblyVersion("x.y.z.w") in ../Program.cs, keeping the first three parts
    like the Windows and macOS builds.
    """
    bundled = _bundled("VERSION")
    if bundled is not None:
        text = bundled.decode("ascii").strip()
    else:
        program = resource("Program.cs").decode("utf-8", "replace")
        match = re.search(r'AssemblyVersion\("([0-9]+\.[0-9]+\.[0-9]+)', program)
        text = match.group(1) if match else ""
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", text):
        raise HostError("The editor version could not be determined.")
    return text


def ico_png_images(data: bytes) -> dict[int, bytes]:
    """Returns the PNG images of a .ico file by pixel size (BMP entries skipped)."""
    images: dict[int, bytes] = {}
    count = struct.unpack_from("<H", data, 4)[0]
    for index in range(count):
        width, _, _, _, _, _, size, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * index)
        image = data[offset:offset + size]
        if image.startswith(b"\x89PNG\r\n\x1a\n"):
            images[width or 256] = image
    return images


def write_icons(icon_root: str) -> dict[int, str]:
    """Writes the app icon into a hicolor theme tree (<root>/NxN/apps/)."""
    written = {}
    for size, image in sorted(ico_png_images(resource("editor.ico")).items()):
        folder = os.path.join(icon_root, f"{size}x{size}", "apps")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, APP_ID + ".png")
        with open(path, "wb") as file:
            file.write(image)
        written[size] = path
    if 256 not in written:
        raise HostError("editor.ico has no 256 px PNG image.")
    return written


def desktop_entry(exec_value: str) -> str:
    """The freedesktop.org .desktop file that starts the editor."""
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "GenericName=Save Editor\n"
        "Comment=Save editor for the Nintendo Switch 2 remake of Ocarina of Time\n"
        f"Exec={exec_value}\n"
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
        "Categories=Utility;\n"
        "Keywords=Zelda;Ocarina;Save;Editor;Switch;\n"
    )


def desktop_exec_quote(path: str) -> str:
    """Quotes a path for the Exec key of a .desktop file."""
    path = path.replace("%", "%%")
    if re.fullmatch(r"[A-Za-z0-9_./+-]+", path):
        return path
    quoted = '"' + re.sub(r'(["`$\\])', r"\\\1", path) + '"'
    # Exec is also a string value, whose own escaping doubles backslashes.
    return quoted.replace("\\", "\\\\")


# MARK: - Backup reading

BACKUP_PREFIX = "Backup/files/"


class BackupReader:
    """Reads the save files of a folder picked by the user.

    Port of BackupReader in OOTSW2SE.swift (itself based on
    EditorWindow.ReadBackup in Program.cs). Accepted layouts:
      1. A slot folder (slot_00 ... slot_05) picked directly. It is sent as a
         one-slot backup, with option.sav and manifest.json from around it,
         so the patch keeps backup paths and the voice language stays
         editable.
      2. Any other folder that directly holds progress.sav + caption.sav (one
         loose save), optionally with option.sav next to them.
      3. A backup folder with slot_00 ... slot_05 subfolders, either directly
         or inside a "files" subfolder, plus optional option.sav and
         manifest.json. Picking the "files" folder itself works too.
    """

    def __init__(self) -> None:
        self.files: list[dict[str, str]] = []
        self.total = 0

    @classmethod
    def read(cls, folder: str) -> list[dict[str, str]]:
        """Returns the files of `folder` as {relativePath, contents} entries."""
        reader = cls()
        reader._read(os.path.abspath(folder))
        return reader.files

    def _read(self, folder: str) -> None:
        name = os.path.basename(folder)
        slot = slot_name(name)
        if slot and has_save_pair(folder):
            self._read_pair(folder, BACKUP_PREFIX + slot + "/")
            self._read_extras(os.path.dirname(folder))
            return

        if has_save_pair(folder):
            # The page expects "<name>/progress.sav"; fall back to "Save" for
            # names that would break its path parsing.
            if not name.strip() or any(char in name for char in "/\\:"):
                name = "Save"
            self._read_pair(folder, name + "/")
            option = os.path.join(folder, "option.sav")
            if is_regular_file(option):
                self._read_file(option, name + "/option.sav")
            return

        # Prefer a "files" subfolder, but only if it really holds slots: an
        # empty or unrelated "files" folder must not hide slots at the root.
        nested = os.path.join(folder, "files")
        slots_folder = nested if os.path.isdir(nested) and slot_folders(nested) else folder
        slots = slot_folders(slots_folder)
        if not slots:
            raise HostError("No folder containing progress.sav and caption.sav was found.")
        for slot, slot_folder in slots:
            self._read_pair(slot_folder, BACKUP_PREFIX + slot + "/")
        self._read_extras(slots_folder)

    def _read_extras(self, slots_folder: str) -> None:
        """Adds option.sav next to the slots and manifest.json in the backup
        root, the parent of a folder named "files"."""
        option = os.path.join(slots_folder, "option.sav")
        if is_regular_file(option):
            self._read_file(option, BACKUP_PREFIX + "option.sav")
        root = os.path.dirname(slots_folder) if os.path.basename(slots_folder).lower() == "files" else slots_folder
        manifest = os.path.join(root, "manifest.json")
        if is_regular_file(manifest):
            self._read_file(manifest, "Backup/manifest.json")

    def _read_pair(self, folder: str, prefix: str) -> None:
        for name in ("progress.sav", "caption.sav"):
            self._read_file(os.path.join(folder, name), prefix + name)

    def _read_file(self, path: str, relative_path: str) -> None:
        """Reads one file, enforcing the size limits before loading it.

        Only regular files are opened (symlinks are followed): opening a FIFO
        or device could block forever. Linux has no equivalent of the
        FileShare.Read lock Program.cs relies on to refuse files another
        program is writing, so size, modification time and inode are compared
        before and after reading instead.
        """
        changed = HostError(f"{relative_path} changed while it was being read. "
                            "Close the game or emulator, then try again.")
        try:
            before = os.stat(path)
            if not stat.S_ISREG(before.st_mode):
                raise HostError(f"{relative_path} is not a regular file.")
            limit = min(MAX_FILE_BYTES, MAX_BACKUP_BYTES - self.total)
            if before.st_size > limit:
                raise HostError("The backup files exceed the expected size.")
            descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            with os.fdopen(descriptor, "rb") as file:
                opened = os.fstat(file.fileno())
                if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    raise changed
                # Read at most one byte past the limit, so a file that grew
                # after the size check is rejected without being loaded whole.
                data = file.read(limit + 1)
            after = os.stat(path)
        except OSError as error:
            raise HostError(f"{relative_path} could not be read: {describe_os_error(error)}") from error
        if len(data) > limit:
            raise HostError("The backup files exceed the expected size.")
        if len(data) < before.st_size:
            raise HostError("A backup file was truncated while reading it.")
        if (after.st_ino, after.st_size, after.st_mtime_ns) != (before.st_ino, before.st_size, before.st_mtime_ns):
            raise changed
        self.total += len(data)
        self.files.append({"relativePath": relative_path, "contents": base64.b64encode(data).decode("ascii")})


def slot_name(name: str) -> str | None:
    """The canonical lowercase slot name ("slot_03") for a slot folder name in
    any letter case, else None. The page only matches lowercase slot names."""
    lower = name.lower()
    return lower if re.fullmatch(r"slot_0[0-5]", lower) else None


def slot_folders(folder: str) -> list[tuple[str, str]]:
    """The slot subfolders of `folder` that hold a complete save, in order."""
    result = []
    for index in range(SLOT_COUNT):
        slot = f"slot_{index:02d}"
        path = os.path.join(folder, slot)
        if has_save_pair(path):
            result.append((slot, path))
    return result


def has_save_pair(folder: str) -> bool:
    """True when `folder` holds both files that make up one save slot."""
    return is_regular_file(os.path.join(folder, "progress.sav")) and \
        is_regular_file(os.path.join(folder, "caption.sav"))


def is_regular_file(path: str) -> bool:
    """True for an existing regular file, following symlinks."""
    try:
        return stat.S_ISREG(os.stat(path).st_mode)
    except OSError:
        return False


# MARK: - Patch export

PATCH_NAME = re.compile(
    r"Ocarina-of-Time-(?:Save|slot_0[0-5])-Patch-([0-9]{8}_[0-9]{6})_"
    r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def patch_timestamp(name: object) -> str:
    """The UTC timestamp inside a patch name; rejects anything else."""
    match = PATCH_NAME.fullmatch(name) if isinstance(name, str) else None
    if not match:
        raise HostError("Invalid patch folder name.")
    return match.group(1)


def decode_patch_files(entries: object, name: object) -> dict[str, bytes]:
    """Validates and decodes the files of a folder export.

    Same rules as PatchFolderWriter in Program.cs and OOTSW2SE.swift: only the
    known save paths below the timestamp folder (and manifest.json) are
    allowed, with the same size limits.
    """
    stamp = patch_timestamp(name)
    if not isinstance(entries, list) or not 2 <= len(entries) <= 4:
        raise HostError("Invalid patch file list.")
    allowed = re.compile(r"manifest\.json|" + stamp +
                         r"/(?:progress\.sav|caption\.sav|option\.sav|slot_0[0-5]/(?:progress|caption)\.sav)")
    files: dict[str, bytes] = {}
    total = 0
    for entry in entries:
        path = entry.get("relativePath") if isinstance(entry, dict) else None
        contents = entry.get("contents") if isinstance(entry, dict) else None
        if not isinstance(path, str) or not allowed.fullmatch(path) or path in files or \
                not isinstance(contents, str) or not contents or len(contents) > 2 * MAX_FILE_BYTES:
            raise HostError("Invalid patch file.")
        try:
            data = base64.b64decode(contents, validate=True)
        except (binascii.Error, ValueError):
            raise HostError("Invalid patch file.") from None
        if not data:
            raise HostError("Invalid patch file.")
        total += len(data)
        if len(data) > MAX_FILE_BYTES or total > MAX_BACKUP_BYTES:
            raise HostError("The patch files are too large.")
        files[path] = data
    return files


def write_patch_folder(parent: str, files: dict[str, bytes], name: str) -> str:
    """Writes `files` into a new folder `name` inside `parent`.

    The files are written into a hidden staging folder first, which is then
    renamed in one step, so a failed export leaves nothing half-written. An
    existing file or folder is never replaced.
    """
    patch_timestamp(name)
    staging = os.path.join(parent, ".oot-patch-" + uuid.uuid4().hex)
    destination = os.path.join(parent, name)
    os.mkdir(staging)
    try:
        for path, data in files.items():
            target = os.path.join(staging, path)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "xb") as file:
                file.write(data)
        # rename() would silently replace an empty folder of the same name.
        if os.path.lexists(destination):
            raise HostError(f"{name} already exists.")
        os.rename(staging, destination)
        return destination
    finally:
        if os.path.lexists(staging):
            shutil.rmtree(staging, ignore_errors=True)


def decode_patch_zip(contents: object) -> bytes:
    """Validates the patch ZIP sent by the page, like Program.cs."""
    if not isinstance(contents, str) or not contents or len(contents) > MAX_BACKUP_BYTES * 2:
        raise HostError("The patch ZIP is empty or too large.")
    try:
        data = base64.b64decode(contents, validate=True)
    except (binascii.Error, ValueError):
        raise HostError("The editor did not create a valid patch ZIP.") from None
    if len(data) < 22 or len(data) > MAX_BACKUP_BYTES or not data.startswith(b"PK\x03\x04"):
        raise HostError("The editor did not create a valid patch ZIP.")
    return data


def write_file_atomically(path: str, data: bytes) -> None:
    """Writes `data` to `path` through a temporary file in the same folder, so
    an existing file is only replaced once the new one is complete."""
    descriptor, temp = tempfile.mkstemp(prefix=".oot-patch-", suffix=".tmp", dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
            os.fchmod(file.fileno(), 0o644)
        os.replace(temp, path)
        temp = ""
    finally:
        if temp:
            with contextlib.suppress(OSError):
                os.unlink(temp)


# MARK: - File dialogs

class Dialogs:
    """Native folder and save dialogs through kdialog or zenity.

    KDE-like desktops prefer kdialog, everything else zenity; whichever is
    installed is used. Set OOT_SW2SE_DIALOG=kdialog or =zenity to force one.
    """

    TOOLS = ("kdialog", "zenity")

    def __init__(self) -> None:
        self._tool: tuple[str, str] | None = None
        self._zenity_major: int | None = None

    def tool(self) -> tuple[str, str]:
        """(name, path) of the dialog program, found on first use."""
        if self._tool is None:
            forced = os.environ.get("OOT_SW2SE_DIALOG", "").strip()
            if forced and forced not in self.TOOLS:
                raise HostError("OOT_SW2SE_DIALOG must be kdialog or zenity.")
            desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper().split(":")
            if forced:
                order = [forced]
            elif "KDE" in desktop or "LXQT" in desktop:
                order = ["kdialog", "zenity"]
            else:
                order = ["zenity", "kdialog"]
            for name in order:
                path = shutil.which(name)
                if path:
                    self._tool = (name, path)
                    break
            else:
                raise HostError("No file dialog program was found. Install zenity or kdialog, then try again.")
        return self._tool

    def pick_folder(self, title: str, start: str | None) -> str | None:
        """Asks for an existing folder. Returns None when canceled."""
        name, path = self.tool()
        start = start if start and os.path.isdir(start) else os.path.expanduser("~")
        if name == "kdialog":
            return self._run([path, "--title", title, "--getexistingdirectory", start])
        return self._run([path, "--file-selection", "--directory", "--title=" + title,
                          "--filename=" + os.path.join(start, "")])

    def save_file(self, title: str, start: str | None, file_name: str) -> str | None:
        """Asks where to save a ZIP file. Returns None when canceled.

        Both programs ask before replacing an existing file (zenity 3 only
        with --confirm-overwrite, which zenity 4 always does by itself).
        """
        name, path = self.tool()
        start = start if start and os.path.isdir(start) else os.path.expanduser("~")
        suggested = os.path.join(start, file_name)
        if name == "kdialog":
            return self._run([path, "--title", title, "--getsavefilename", suggested, "ZIP archive (*.zip)"])
        args = [path, "--file-selection", "--save", "--title=" + title, "--filename=" + suggested,
                "--file-filter=ZIP archive (*.zip) | *.zip"]
        if self._zenity_version(path) < 4:
            args.append("--confirm-overwrite")
        return self._run(args)

    def _zenity_version(self, path: str) -> int:
        if self._zenity_major is None:
            try:
                output = subprocess.run([path, "--version"], stdin=subprocess.DEVNULL, capture_output=True,
                                        text=True, timeout=10).stdout
                self._zenity_major = int(output.strip().split(".")[0])
            except (OSError, ValueError, subprocess.SubprocessError):
                self._zenity_major = 0
        return self._zenity_major

    @staticmethod
    def _run(args: list[str]) -> str | None:
        """Runs a dialog and returns the chosen path, or None when canceled."""
        try:
            process = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True)
        except OSError as error:
            raise HostError(f"The file dialog could not start: {describe_os_error(error)}") from error
        if process.returncode == 1:
            return None
        if process.returncode != 0:
            lines = [line for line in os.fsdecode(process.stderr).splitlines() if line.strip()]
            raise HostError("The file dialog failed" + (": " + lines[-1].strip() if lines else "."))
        chosen = os.fsdecode(process.stdout).rstrip("\n")
        return chosen or None


# MARK: - Host actions

class EditorHost:
    """Answers the page's requests, like HandleMessage in Program.cs."""

    def __init__(self, dialogs: Dialogs) -> None:
        self.dialogs = dialogs
        # Guards against overlapping dialogs, like dialogOpen in Program.cs.
        self._dialog = threading.Lock()
        self.last_folder: str | None = None
        self.last_export_folder: str | None = None

    def handle(self, message: dict) -> dict:
        """Runs one request and returns {result, error} for the page."""
        if not self._dialog.acquire(blocking=False):
            return {"result": None, "error": "A file dialog is already open."}
        try:
            action = message.get("action")
            if action == "openBackup":
                result = self.open_backup()
            elif action == "savePatch":
                result = self.save_patch(message)
            elif action == "saveFolder":
                result = self.save_folder(message)
            else:
                raise HostError("Unknown editor action.")
            return {"result": result, "error": None}
        except HostError as error:
            return {"result": None, "error": str(error)}
        except OSError as error:
            return {"result": None, "error": describe_os_error(error)}
        except Exception as error:  # Shown to the user, like Program.cs does.
            return {"result": None, "error": str(error) or type(error).__name__}
        finally:
            self._dialog.release()

    def open_backup(self) -> list[dict[str, str]] | None:
        folder = self.dialogs.pick_folder("Select a backup or save folder", self.last_folder)
        if folder is None:
            return None
        self.last_folder = folder
        return BackupReader.read(folder)

    def save_patch(self, message: dict) -> str | None:
        data = decode_patch_zip(message.get("contents"))
        name = os.path.basename(str(message.get("name") or "Ocarina-of-Time-Patch.zip"))
        path = self.dialogs.save_file("Save patch", self._export_start(), name)
        if path is None:
            return None
        if not path.lower().endswith(".zip"):
            # Like AddExtension in Program.cs. The dialog only confirmed
            # replacing the name without the extension, so never replace here.
            path += ".zip"
            if os.path.lexists(path):
                raise HostError(f"{os.path.basename(path)} already exists. Choose another name.")
        self.last_export_folder = os.path.dirname(path)
        write_file_atomically(path, data)
        return os.path.basename(path)

    def save_folder(self, message: dict) -> str | None:
        name = message.get("name")
        files = decode_patch_files(message.get("files"), name)
        parent = self.dialogs.pick_folder("Select where to create the patch folder", self._export_start())
        if parent is None:
            return None
        self.last_export_folder = parent
        return write_patch_folder(parent, files, name)  # type: ignore[arg-type]

    def _export_start(self) -> str | None:
        return self.last_export_folder or self.last_folder


# MARK: - Lifetime

class Lifetime:
    """Decides when the server should exit.

    Every editor tab sends a heartbeat with its own id and says goodbye when
    it is closed. The server exits once no tab is left (after a short grace
    period, so reloading the page doesn't end it), when tabs stop sending
    heartbeats (e.g. the browser was killed), or when the browser never
    opened the editor at all.
    """

    def __init__(self, now: float, launch_timeout: float | None = 120.0,
                 idle_timeout: float = 600.0, close_grace: float = 10.0) -> None:
        self._lock = threading.Lock()
        self._tabs: dict[str, float] = {}
        self._busy = 0
        self._started = False
        self._empty_since = now
        self.launch_timeout = launch_timeout
        self.idle_timeout = idle_timeout
        self.close_grace = close_grace

    def page_served(self, now: float) -> None:
        with self._lock:
            self._started = True
            if not self._tabs:
                self._empty_since = now

    def alive(self, tab: str, now: float) -> None:
        with self._lock:
            self._started = True
            if tab in self._tabs or len(self._tabs) < 64:
                self._tabs[tab] = now

    def closed(self, tab: str, now: float) -> None:
        with self._lock:
            self._tabs.pop(tab, None)
            if not self._tabs:
                self._empty_since = now

    @contextlib.contextmanager
    def busy(self, clock=time.monotonic):
        """Keeps the server alive while a request (e.g. a dialog) runs."""
        with self._lock:
            self._busy += 1
        try:
            yield
        finally:
            with self._lock:
                self._busy -= 1
                if not self._tabs:
                    self._empty_since = clock()

    def exit_reason(self, now: float) -> str | None:
        """Why the server should exit now, or None to keep running."""
        with self._lock:
            if self._busy:
                return None
            stale = [tab for tab, seen in self._tabs.items() if now - seen >= self.idle_timeout]
            for tab in stale:
                del self._tabs[tab]
            if self._tabs:
                return None
            if stale:
                return "The editor tab stopped responding."
            if not self._started:
                if self.launch_timeout is not None and now - self._empty_since >= self.launch_timeout:
                    return "The browser did not open the editor."
                return None
            if now - self._empty_since >= self.close_grace:
                return "The editor tab was closed."
            return None


# MARK: - Page

# Recreates the subset of the WebView2 `window.chrome.webview` API that
# editor.html uses (postMessage + addEventListener('message')) on top of
# fetch(), and keeps the server informed that this tab is still open.
BRIDGE_SHIM = r"""
(() => {
  'use strict';
  const listeners = new Set();
  const tab = crypto.randomUUID();
  const notify = data => {
    for (const listener of listeners) {
      try { listener({ data }); } catch (error) { console.error(error); }
    }
  };
  const post = (path, body) => fetch(path, {
    method: 'POST', cache: 'no-store', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-OOT-SW2SE': '1' },
    body: JSON.stringify(body),
  });
  window.chrome = window.chrome || {};
  window.chrome.webview = {
    postMessage(message) {
      // "workspace" resizes the native window on Windows and macOS. A browser
      // tab keeps its size, and the page lays itself out for any size.
      if (!message || message.action === 'workspace') return;
      const id = message.id;
      post('/api/request', message)
        .then(response => {
          if (!response.ok) throw new Error('The OOT SW2SE helper refused the request (HTTP ' + response.status + ').');
          return response.json();
        })
        .then(reply => notify({ id, result: reply.result ?? null, error: reply.error ?? null }))
        .catch(error => notify({ id, result: null, error: error instanceof TypeError
          ? 'The OOT SW2SE helper is not running anymore. Start OOT SW2SE again and reopen the backup.'
          : error.message }));
    },
    addEventListener(type, listener) {
      if (type === 'message') listeners.add(listener);
    },
    removeEventListener(type, listener) {
      if (type === 'message') listeners.delete(listener);
    },
  };
  const alive = () => post('/api/alive', { tab }).catch(() => {});
  alive();
  setInterval(alive, 20000);
  addEventListener('pageshow', event => { if (event.persisted) alive(); });
  addEventListener('pagehide', () => navigator.sendBeacon('/api/bye', tab));
})();
"""

CSP_META = re.compile(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">')


def build_page(html: str, version: str) -> bytes:
    """Prepares editor.html for the browser.

    The page itself is unchanged except for three things: the version
    placeholder is filled in (as the other hosts do), the bridge shim is
    added right after the Content-Security-Policy, and that policy also
    allows fetch() to this server ("connect-src 'self'"), which the shim
    needs. All other network access stays blocked.
    """
    policies = CSP_META.findall(html)
    if len(policies) != 1 or "default-src 'none';" not in policies[0] or "connect-src" in policies[0]:
        raise HostError("editor.html has an unexpected Content-Security-Policy; update linux/oot_sw2se.py.")
    policy = policies[0].replace("default-src 'none';", "default-src 'none'; connect-src 'self';", 1)
    meta = f'<meta http-equiv="Content-Security-Policy" content="{policy}">'
    if "</script" in BRIDGE_SHIM:
        raise AssertionError("The bridge shim must not close its script element.")
    html = CSP_META.sub(lambda _: meta + "\n<script>" + BRIDGE_SHIM + "</script>", html, count=1)
    return html.replace("{{EDITOR_VERSION}}", version).encode("utf-8")


FORBIDDEN_PAGE = (
    "<!doctype html><meta charset=utf-8><title>OOT SW2SE</title>"
    "<body style=\"font:16px system-ui,sans-serif;background:#101b18;color:#edf2e8;padding:2em\">"
    "<h1>OOT SW2SE</h1><p>This tab is not connected to the editor. "
    "Start OOT SW2SE again; it opens a new tab.</p>"
).encode("utf-8")


# MARK: - Server

class EditorServer(http.server.ThreadingHTTPServer):
    """HTTP server on 127.0.0.1 serving the editor and its host API."""

    daemon_threads = True

    def __init__(self, host: EditorHost, lifetime: Lifetime, page: bytes,
                 verbose: bool = False, clock=time.monotonic) -> None:
        super().__init__(("127.0.0.1", 0), RequestHandler)
        port = self.server_address[1]
        self.host = host
        self.lifetime = lifetime
        self.page = page
        self.verbose = verbose
        self.clock = clock
        self.authority = f"127.0.0.1:{port}"
        self.origin = "http://" + self.authority
        # Cookies are shared between ports of one host, so the name includes
        # the port to keep two running editors apart.
        self.cookie_name = f"oot_sw2se_{port}"
        self.session = secrets.token_urlsafe(32)
        self._launch_lock = threading.Lock()
        self._launch: str | None = secrets.token_urlsafe(32)
        self.launch_url = f"{self.origin}/launch/{self._launch}"

    def consume_launch(self, token: str) -> bool:
        """True once for the launch token; it can't be used a second time."""
        with self._launch_lock:
            if self._launch and _same(token, self._launch):
                self._launch = None
                return True
            return False


def _same(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode("utf-8", "replace"), expected.encode("utf-8"))


class RequestHandler(http.server.BaseHTTPRequestHandler):
    server: EditorServer
    server_version = "OOT-SW2SE"
    sys_version = ""

    def log_message(self, format: str, *args) -> None:  # noqa: A002 (base class name)
        if self.server.verbose:
            super().log_message(format, *args)

    def _send(self, status: int, body: bytes = b"", content_type: str = "text/plain; charset=utf-8",
              headers: tuple[tuple[str, str], ...] = ()) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self) -> bool:
        # A page from another site that a DNS-rebinding attack points at
        # 127.0.0.1 still sends its own host name here.
        return self.headers.get("Host") == self.server.authority

    def _session_ok(self) -> bool:
        cookie = http.cookies.SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie") or "")
        except http.cookies.CookieError:
            return False
        morsel = cookie.get(self.server.cookie_name)
        return morsel is not None and _same(morsel.value, self.server.session)

    def do_GET(self) -> None:  # noqa: N802 (base class name)
        if not self._host_ok():
            return self._send(403, b"Forbidden")
        path = self.path.split("?", 1)[0]
        if path.startswith("/launch/"):
            if self.server.consume_launch(path[len("/launch/"):]):
                cookie = f"{self.server.cookie_name}={self.server.session}; Path=/; HttpOnly; SameSite=Strict"
                return self._send(303, headers=(("Location", "/"), ("Set-Cookie", cookie)))
            if self._session_ok():
                return self._send(303, headers=(("Location", "/"),))
            return self._send(403, FORBIDDEN_PAGE, "text/html; charset=utf-8")
        if path == "/":
            if not self._session_ok():
                return self._send(403, FORBIDDEN_PAGE, "text/html; charset=utf-8")
            self.server.lifetime.page_served(self.server.clock())
            return self._send(200, self.server.page, "text/html; charset=utf-8")
        return self._send(404, b"Not found")

    def do_POST(self) -> None:  # noqa: N802 (base class name)
        if not self._host_ok() or not self._session_ok():
            return self._send(403, b"Forbidden")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._send(411, b"Length required")
        if not 0 <= length <= MAX_REQUEST_BYTES:
            return self._send(413, b"Request too large")
        body = self.rfile.read(length)
        path = self.path.split("?", 1)[0]
        now = self.server.clock()

        if path == "/api/bye":
            # Sent with navigator.sendBeacon, which can't add headers; the
            # SameSite=Strict cookie already proves it comes from the page.
            self.server.lifetime.closed(body.decode("utf-8", "replace").strip(), now)
            return self._send(204)

        # A cross-site page can't send this header without a CORS preflight,
        # which this server never approves.
        if self.headers.get("Origin") != self.server.origin or self.headers.get("X-OOT-SW2SE") != "1":
            return self._send(403, b"Forbidden")
        if self.headers.get_content_type() != "application/json":
            return self._send(415, b"JSON expected")
        try:
            message = json.loads(body)
        except ValueError:
            return self._send(400, b"Invalid JSON")
        if not isinstance(message, dict):
            return self._send(400, b"Invalid request")

        if path == "/api/alive":
            tab = message.get("tab")
            if not isinstance(tab, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", tab):
                return self._send(400, b"Invalid tab")
            self.server.lifetime.alive(tab, now)
            return self._send(204)
        if path == "/api/request":
            with self.server.lifetime.busy(self.server.clock):
                reply = self.server.host.handle(message)
            reply["id"] = message.get("id")
            return self._send(200, json.dumps(reply).encode("utf-8"), "application/json")
        return self._send(404, b"Not found")


# MARK: - Desktop integration

def _data_home() -> str:
    return os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def _installed_paths() -> tuple[str, str, str]:
    """(program, .desktop file, hicolor icon root) for a per-user install."""
    return (os.path.expanduser("~/.local/bin/" + APP_ID),
            os.path.join(_data_home(), "applications", APP_ID + ".desktop"),
            os.path.join(_data_home(), "icons", "hicolor"))


def install() -> int:
    """Copies the built app to ~/.local/bin and adds a menu entry and icon."""
    if os.environ.get("APPIMAGE"):
        print("The AppImage can't install itself; use an AppImage integration tool instead.", file=sys.stderr)
        return 1
    if not os.path.isfile(HERE):
        print("Only the built app can install itself. Run linux/build.sh, then "
              "linux/dist/oot-sw2se.pyz --install.", file=sys.stderr)
        return 1
    program, desktop_file, icon_root = _installed_paths()
    os.makedirs(os.path.dirname(program), exist_ok=True)
    if os.path.abspath(program) != HERE:
        with open(HERE, "rb") as file:
            data = file.read()
        write_file_atomically(program, data)
    os.chmod(program, 0o755)
    write_icons(icon_root)
    os.makedirs(os.path.dirname(desktop_file), exist_ok=True)
    write_file_atomically(desktop_file, desktop_entry(desktop_exec_quote(program)).encode("utf-8"))
    _refresh_desktop_database(os.path.dirname(desktop_file))
    print(f"Installed {APP_NAME} {editor_version()}:\n  {program}\n  {desktop_file}")
    return 0


def uninstall() -> int:
    """Removes what install() added."""
    program, desktop_file, icon_root = _installed_paths()
    removed = []
    paths = [program, desktop_file]
    with contextlib.suppress(OSError):
        paths += [os.path.join(icon_root, size, "apps", APP_ID + ".png") for size in os.listdir(icon_root)]
    for path in paths:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path)
            removed.append(path)
    _refresh_desktop_database(os.path.dirname(desktop_file))
    print("Removed:\n  " + "\n  ".join(removed) if removed else f"{APP_NAME} was not installed.")
    return 0


def _refresh_desktop_database(folder: str) -> None:
    tool = shutil.which("update-desktop-database")
    if tool and os.path.isdir(folder):
        subprocess.run([tool, "-q", folder], stdin=subprocess.DEVNULL, check=False)


# MARK: - Main

def open_browser(url: str) -> bool:
    """Opens `url` in the default browser without tying the browser's
    lifetime or console output to this process."""
    opener = None if os.environ.get("BROWSER") else shutil.which("xdg-open")
    if opener:
        try:
            subprocess.Popen([opener, url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return True
        except OSError:
            pass
    return webbrowser.open(url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog=APP_ID, description=f"{APP_NAME}: save editor for the Nintendo Switch 2 remake of Ocarina of Time. "
                                 "Opens the editor in your default web browser.")
    parser.add_argument("--no-browser", action="store_true",
                        help="print the editor URL instead of opening the default browser")
    parser.add_argument("--install", action="store_true",
                        help="copy the app to ~/.local/bin and add it to the application menu")
    parser.add_argument("--uninstall", action="store_true", help="undo --install")
    parser.add_argument("--verbose", action="store_true", help="log every HTTP request")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    args = parser.parse_args(argv)

    try:
        if args.version:
            print(f"{APP_NAME} {editor_version()}")
            return 0
        if args.install:
            return install()
        if args.uninstall:
            return uninstall()
        page = build_page(resource("editor.html").decode("utf-8"), editor_version())
    except HostError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    lifetime = Lifetime(time.monotonic(), launch_timeout=None if args.no_browser else 120.0)
    server = EditorServer(EditorHost(Dialogs()), lifetime, page, verbose=args.verbose)
    thread = threading.Thread(target=server.serve_forever, name="http", daemon=True)
    thread.start()
    print(f"{APP_NAME} is running. Open this address once, in your browser:\n  {server.launch_url}\n"
          "It stops a few seconds after the editor tab is closed (or press Ctrl+C).", flush=True)
    if not args.no_browser and not open_browser(server.launch_url):
        print("No web browser could be started; open the address above yourself.", file=sys.stderr)
        lifetime.launch_timeout = None
    try:
        while True:
            time.sleep(1)
            reason = lifetime.exit_reason(time.monotonic())
            if reason:
                print(reason + " Exiting.", flush=True)
                break
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
