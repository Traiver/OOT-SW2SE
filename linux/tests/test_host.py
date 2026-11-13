"""Tests for the Linux host (linux/oot_sw2se.py) without real dialogs or browsers.

Run from the repository root:  python3 -m unittest discover -s linux/tests -v
"""
from __future__ import annotations

import base64
import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import oot_sw2se as host  # noqa: E402

NAME = "Ocarina-of-Time-slot_00-Patch-20261109_094216_11111111-1111-4111-8111-111111111111"
OTHER_NAME = NAME.replace("11111111-1111", "22222222-2222")
PATHS = ["20261109_094216/slot_00/progress.sav", "20261109_094216/slot_00/caption.sav",
         "20261109_094216/option.sav", "manifest.json"]
BYTES = bytes([0, 1, 2, 255])
ENTRIES = [{"relativePath": path, "contents": base64.b64encode(BYTES).decode()} for path in PATHS]


def write(path: str, data: bytes = b"data") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as file:
        file.write(data)


def save_pair(folder: str) -> None:
    write(os.path.join(folder, "progress.sav"), b"progress")
    write(os.path.join(folder, "caption.sav"), b"caption")


def paths(entries: list[dict[str, str]]) -> list[str]:
    return [entry["relativePath"] for entry in entries]


class TempDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory(prefix="oot-linux-tests-")
        self.root = self._temp.name

    def tearDown(self) -> None:
        self._temp.cleanup()


class PatchFolderTests(TempDirTest):
    """Same cases as tests/host_exports.py runs against the C# and Swift hosts."""

    def test_writes_nested_files_to_unique_folders(self) -> None:
        files = host.decode_patch_files(ENTRIES, NAME)
        first = host.write_patch_folder(self.root, files, NAME)
        second = host.write_patch_folder(self.root, files, OTHER_NAME)
        self.assertEqual(os.path.basename(first), NAME)
        self.assertEqual(os.path.basename(second), OTHER_NAME)
        for folder in (first, second):
            for path in PATHS:
                with open(os.path.join(folder, path), "rb") as file:
                    self.assertEqual(file.read(), BYTES)
        self.assertEqual(sorted(os.listdir(self.root)), sorted([NAME, OTHER_NAME]))

    def test_never_replaces_existing_folders(self) -> None:
        files = host.decode_patch_files(ENTRIES, NAME)
        host.write_patch_folder(self.root, files, NAME)
        with self.assertRaises(host.HostError):
            host.write_patch_folder(self.root, files, NAME)
        os.mkdir(os.path.join(self.root, OTHER_NAME))  # rename() would replace an empty folder
        with self.assertRaises(host.HostError):
            host.write_patch_folder(self.root, files, OTHER_NAME)
        self.assertEqual(os.listdir(os.path.join(self.root, OTHER_NAME)), [])
        self.assertFalse([name for name in os.listdir(self.root) if name.startswith(".oot-patch-")])

    def test_rejects_invalid_names(self) -> None:
        for bad in ["../escape", NAME + "/child", NAME + "\n", None, 5]:
            with self.assertRaises(host.HostError, msg=repr(bad)):
                host.decode_patch_files(ENTRIES, bad)

    def test_rejects_invalid_paths(self) -> None:
        for bad in ["../progress.sav", "/progress.sav", "files/../../caption.sav", "files\\progress.sav",
                    "20261109_094216/slot_06/progress.sav", "20261109_094217/progress.sav", "progress.sav\n",
                    "20261109_094216/progress.sav\n"]:
            with self.assertRaises(host.HostError, msg=repr(bad)):
                host.decode_patch_files([{"relativePath": bad, "contents": "AQ=="}, ENTRIES[1]], NAME)

    def test_rejects_duplicates_bad_lists_and_bad_contents(self) -> None:
        for entries in [[ENTRIES[0], ENTRIES[0]], ENTRIES[:1], ENTRIES + ENTRIES[:1], None, "x",
                        [{"relativePath": PATHS[0], "contents": "not base64!"}, ENTRIES[1]],
                        [{"relativePath": PATHS[0], "contents": ""}, ENTRIES[1]],
                        [{"relativePath": PATHS[0]}, ENTRIES[1]], ["x", ENTRIES[1]]]:
            with self.assertRaises(host.HostError, msg=repr(entries)[:80]):
                host.decode_patch_files(entries, NAME)

    def test_rejects_oversized_files(self) -> None:
        big = base64.b64encode(bytes(host.MAX_FILE_BYTES + 1)).decode()
        with self.assertRaises(host.HostError):
            host.decode_patch_files([{"relativePath": "20261109_094216/progress.sav", "contents": big},
                                     ENTRIES[1]], NAME)


class PatchZipTests(TempDirTest):
    def test_validates_zip(self) -> None:
        good = b"PK\x03\x04" + bytes(30)
        self.assertEqual(host.decode_patch_zip(base64.b64encode(good).decode()), good)
        for bad in [None, "", base64.b64encode(b"PK\x03\x04").decode(),
                    base64.b64encode(b"XX\x03\x04" + bytes(30)).decode(), "@@@@"]:
            with self.assertRaises(host.HostError, msg=repr(bad)):
                host.decode_patch_zip(bad)

    def test_atomic_write_replaces_file(self) -> None:
        path = os.path.join(self.root, "patch.zip")
        write(path, b"old")
        host.write_file_atomically(path, b"new")
        with open(path, "rb") as file:
            self.assertEqual(file.read(), b"new")
        self.assertEqual(os.listdir(self.root), ["patch.zip"])


class BackupReaderTests(TempDirTest):
    def backup(self) -> str:
        backup = os.path.join(self.root, "Backup")
        save_pair(os.path.join(backup, "files", "slot_00"))
        save_pair(os.path.join(backup, "files", "slot_02"))
        write(os.path.join(backup, "files", "option.sav"))
        write(os.path.join(backup, "manifest.json"), b"{}")
        return backup

    def test_backup_root(self) -> None:
        entries = host.BackupReader.read(self.backup())
        self.assertEqual(paths(entries), [
            "Backup/files/slot_00/progress.sav", "Backup/files/slot_00/caption.sav",
            "Backup/files/slot_02/progress.sav", "Backup/files/slot_02/caption.sav",
            "Backup/files/option.sav", "Backup/manifest.json"])
        self.assertEqual(base64.b64decode(entries[0]["contents"]), b"progress")


    def test_files_folder_finds_manifest(self) -> None:
        entries = host.BackupReader.read(os.path.join(self.backup(), "files"))
        self.assertIn("Backup/manifest.json", paths(entries))
        self.assertIn("Backup/files/option.sav", paths(entries))

    def test_slot_folder_is_one_slot_backup(self) -> None:
        backup = self.backup()
        os.rename(os.path.join(backup, "files", "slot_02"), os.path.join(backup, "files", "Slot_02"))
        entries = host.BackupReader.read(os.path.join(backup, "files", "Slot_02"))
        self.assertEqual(paths(entries), [
            "Backup/files/slot_02/progress.sav", "Backup/files/slot_02/caption.sav",
            "Backup/files/option.sav", "Backup/manifest.json"])

    def test_loose_save(self) -> None:
        folder = os.path.join(self.root, "My Save")
        save_pair(folder)
        write(os.path.join(folder, "option.sav"))
        self.assertEqual(paths(host.BackupReader.read(folder)),
                         ["My Save/progress.sav", "My Save/caption.sav", "My Save/option.sav"])

    def test_loose_save_with_unusable_name(self) -> None:
        folder = os.path.join(self.root, "a:b")
        save_pair(folder)
        self.assertEqual(paths(host.BackupReader.read(folder)), ["Save/progress.sav", "Save/caption.sav"])

    def test_empty_files_folder_does_not_hide_root_slots(self) -> None:
        save_pair(os.path.join(self.root, "slot_01"))
        os.mkdir(os.path.join(self.root, "files"))
        self.assertEqual(paths(host.BackupReader.read(self.root))[0], "Backup/files/slot_01/progress.sav")

    def test_no_saves(self) -> None:
        with self.assertRaisesRegex(host.HostError, "No folder containing"):
            host.BackupReader.read(self.root)

    def test_fifo_is_refused_without_blocking(self) -> None:
        folder = os.path.join(self.root, "slot_00")
        save_pair(folder)
        os.unlink(os.path.join(folder, "caption.sav"))
        os.mkfifo(os.path.join(folder, "caption.sav"))
        with self.assertRaises(host.HostError):  # not a save pair: no regular caption.sav
            host.BackupReader.read(folder)
        reader = host.BackupReader()
        with self.assertRaisesRegex(host.HostError, "not a regular file"):
            reader._read_file(os.path.join(folder, "caption.sav"), "caption.sav")

    def test_size_limits(self) -> None:
        folder = os.path.join(self.root, "slot_00")
        save_pair(folder)
        write(os.path.join(folder, "progress.sav"), bytes(host.MAX_FILE_BYTES + 1))
        with self.assertRaisesRegex(host.HostError, "exceed"):
            host.BackupReader.read(folder)

    def test_symlinked_files_are_followed(self) -> None:
        source = os.path.join(self.root, "real")
        save_pair(source)
        folder = os.path.join(self.root, "slot_03")
        os.mkdir(folder)
        for name in ("progress.sav", "caption.sav"):
            os.symlink(os.path.join(source, name), os.path.join(folder, name))
        self.assertEqual(paths(host.BackupReader.read(folder)),
                         ["Backup/files/slot_03/progress.sav", "Backup/files/slot_03/caption.sav"])


class PageTests(unittest.TestCase):
    def test_page_gets_shim_csp_and_version(self) -> None:
        page = host.build_page(host.resource("editor.html").decode(), "9.8.7").decode()
        self.assertNotIn("{{EDITOR_VERSION}}", page)
        self.assertIn("v9.8.7", page)
        self.assertIn("default-src 'none'; connect-src 'self'; script-src 'unsafe-inline'", page)
        self.assertEqual(page.count("Content-Security-Policy"), 1)
        # The shim runs after the policy and before the editor script.
        self.assertLess(page.index("Content-Security-Policy"), page.index("window.chrome.webview = {"))
        self.assertLess(page.index("window.chrome.webview = {"), page.index("const host = window.chrome.webview"))

    def test_unexpected_csp_is_refused(self) -> None:
        with self.assertRaises(host.HostError):
            host.build_page("<html>no policy</html>", "1.0.0")

    def test_version_from_program_cs(self) -> None:
        self.assertRegex(host.editor_version(), r"^[0-9]+\.[0-9]+\.[0-9]+$")

    def test_icons(self) -> None:
        images = host.ico_png_images(host.resource("editor.ico"))
        self.assertIn(256, images)

    def test_desktop_exec_quoting(self) -> None:
        self.assertEqual(host.desktop_exec_quote("/home/a/.local/bin/oot-sw2se"), "/home/a/.local/bin/oot-sw2se")
        self.assertEqual(host.desktop_exec_quote("/home/a b/x"), '"/home/a b/x"')
        self.assertEqual(host.desktop_exec_quote('/a$"%'), '"/a\\\\$\\\\"%%"')


class LifetimeTests(unittest.TestCase):
    def test_waits_for_launch(self) -> None:
        life = host.Lifetime(0, launch_timeout=120)
        self.assertIsNone(life.exit_reason(119))
        self.assertIn("did not open", life.exit_reason(120))
        self.assertIsNone(host.Lifetime(0, launch_timeout=None).exit_reason(10_000))

    def test_reload_keeps_running_and_close_exits(self) -> None:
        life = host.Lifetime(0, close_grace=10)
        life.page_served(1)
        life.alive("a", 1)
        life.closed("a", 5)  # reload: the new page says hello right away
        life.page_served(6)
        life.alive("b", 6)
        self.assertIsNone(life.exit_reason(30))
        life.closed("b", 40)
        self.assertIsNone(life.exit_reason(49))
        self.assertIn("closed", life.exit_reason(50))

    def test_other_tabs_keep_running(self) -> None:
        life = host.Lifetime(0, close_grace=10)
        life.alive("a", 1)
        life.alive("b", 1)
        life.closed("a", 2)
        self.assertIsNone(life.exit_reason(100))

    def test_stale_tabs_and_busy_requests(self) -> None:
        life = host.Lifetime(0, idle_timeout=600)
        life.alive("a", 0)
        with life.busy(clock=lambda: 900):
            self.assertIsNone(life.exit_reason(800))
        self.assertIn("stopped responding", life.exit_reason(900))


class FakeDialogs(host.Dialogs):
    def __init__(self) -> None:
        super().__init__()
        self.folder: str | None = None
        self.save_path: str | None = None
        self.calls: list[tuple] = []
        self.release = threading.Event()
        self.release.set()

    def pick_folder(self, title: str, start: str | None) -> str | None:
        self.calls.append(("folder", title, start))
        self.release.wait(10)
        return self.folder

    def save_file(self, title: str, start: str | None, file_name: str) -> str | None:
        self.calls.append(("save", title, start, file_name))
        return self.save_path


class ServerTests(TempDirTest):
    def setUp(self) -> None:
        super().setUp()
        self.dialogs = FakeDialogs()
        self.lifetime = host.Lifetime(0, launch_timeout=None)
        self.server = host.EditorServer(host.EditorHost(self.dialogs), self.lifetime, b"<page>")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.cookie = f"{self.server.cookie_name}={self.server.session}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def request(self, method: str, path: str, body: object = None, headers: dict | None = None,
                cookie: bool = True, api: bool = True) -> http.client.HTTPResponse:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        all_headers = {}
        if cookie:
            all_headers["Cookie"] = self.cookie
        if api:
            all_headers.update({"Origin": self.server.origin, "X-OOT-SW2SE": "1",
                                "Content-Type": "application/json"})
        all_headers.update(headers or {})
        data = json.dumps(body).encode() if body is not None and not isinstance(body, bytes) else body
        connection.request(method, path, body=data, headers=all_headers)
        response = connection.getresponse()
        response.body = response.read()  # type: ignore[attr-defined]
        connection.close()
        return response

    def call(self, message: dict) -> dict:
        response = self.request("POST", "/api/request", message)
        self.assertEqual(response.status, 200)
        return json.loads(response.body)  # type: ignore[attr-defined]

    def test_launch_sets_cookie_once(self) -> None:
        launch = self.server.launch_url[len(self.server.origin):]
        self.assertTrue(launch.startswith("/oot-sw2se?launch="), "stable path, token in the query")
        self.assertEqual(self.request("GET", "/", cookie=False, api=False).status, 403)
        self.assertEqual(self.request("GET", "/oot-sw2se?launch=wrong", cookie=False, api=False).status, 403)
        self.assertEqual(self.request("GET", "/oot-sw2se", cookie=False, api=False).status, 403)
        response = self.request("GET", launch, cookie=False, api=False)
        self.assertEqual(response.status, 303)
        self.assertEqual(response.getheader("Location"), "/")
        cookie = response.getheader("Set-Cookie")
        self.assertIn(self.cookie, cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertEqual(self.request("GET", launch, cookie=False, api=False).status, 403)
        page = self.request("GET", "/", api=False)
        self.assertEqual((page.status, page.body), (200, b"<page>"))  # type: ignore[attr-defined]

    def test_requests_need_host_cookie_origin_and_header(self) -> None:
        message = {"id": 1, "action": "openBackup"}
        self.assertEqual(self.request("POST", "/api/request", message, cookie=False).status, 403)
        self.assertEqual(self.request("POST", "/api/request", message,
                                      headers={"Origin": "http://evil.example"}).status, 403)
        self.assertEqual(self.request("POST", "/api/request", message, headers={"X-OOT-SW2SE": "0"}).status, 403)
        self.assertEqual(self.request("POST", "/api/request", message,
                                      headers={"Host": f"evil.example:{self.port}"}).status, 403)
        self.assertEqual(self.request("GET", "/", api=False, headers={"Host": "localhost"}).status, 403)
        self.assertEqual(self.request("POST", "/api/request", message,
                                      headers={"Content-Type": "text/plain"}).status, 415)
        self.assertEqual(self.request("POST", "/api/request", b"{nope").status, 400)
        self.assertEqual(self.dialogs.calls, [])

    def test_open_backup(self) -> None:
        self.assertEqual(self.call({"id": 1, "action": "openBackup"}), {"id": 1, "result": None, "error": None})
        folder = os.path.join(self.root, "slot_00")
        save_pair(folder)
        self.dialogs.folder = folder
        reply = self.call({"id": 2, "action": "openBackup"})
        self.assertIsNone(reply["error"])
        self.assertEqual(paths(reply["result"]),
                         ["Backup/files/slot_00/progress.sav", "Backup/files/slot_00/caption.sav"])
        self.call({"id": 3, "action": "openBackup"})
        self.assertEqual(self.dialogs.calls[-1][2], folder)  # starts in the last folder

    def test_errors_are_replied(self) -> None:
        self.dialogs.folder = self.root
        self.assertIn("No folder containing", self.call({"id": 4, "action": "openBackup"})["error"])
        self.assertEqual(self.call({"id": 5, "action": "nope"})["error"], "Unknown editor action.")

    def test_save_patch(self) -> None:
        zip_data = b"PK\x03\x04" + bytes(40)
        contents = base64.b64encode(zip_data).decode()
        self.dialogs.save_path = os.path.join(self.root, "patch")
        reply = self.call({"id": 6, "action": "savePatch", "name": "../x/Ocarina.zip", "contents": contents})
        self.assertEqual(reply, {"id": 6, "result": "patch.zip", "error": None})
        self.assertEqual(self.dialogs.calls[-1][3], "Ocarina.zip")
        with open(os.path.join(self.root, "patch.zip"), "rb") as file:
            self.assertEqual(file.read(), zip_data)
        # The added extension was not confirmed in the dialog: never replace.
        self.assertIn("already exists", self.call({"id": 7, "action": "savePatch", "name": "a.zip",
                                                   "contents": contents})["error"])
        self.assertIn("valid patch ZIP", self.call({"id": 8, "action": "savePatch", "name": "a.zip",
                                                    "contents": base64.b64encode(bytes(40)).decode()})["error"])

    def test_save_folder(self) -> None:
        self.dialogs.folder = self.root
        reply = self.call({"id": 9, "action": "saveFolder", "name": NAME, "files": ENTRIES})
        self.assertEqual(reply["result"], os.path.join(self.root, NAME))
        with open(os.path.join(self.root, NAME, PATHS[0]), "rb") as file:
            self.assertEqual(file.read(), BYTES)
        calls = len(self.dialogs.calls)
        self.assertEqual(self.call({"id": 10, "action": "saveFolder", "name": "../bad", "files": ENTRIES})["error"],
                         "Invalid patch folder name.")
        self.assertEqual(len(self.dialogs.calls), calls)  # validated before any dialog opens

    def test_one_dialog_at_a_time(self) -> None:
        self.dialogs.release.clear()
        results = []
        first = threading.Thread(target=lambda: results.append(self.call({"id": 11, "action": "openBackup"})))
        first.start()
        for _ in range(200):
            if self.dialogs.calls:
                break
            threading.Event().wait(0.01)
        self.assertEqual(self.call({"id": 12, "action": "openBackup"})["error"], "A file dialog is already open.")
        self.dialogs.release.set()
        first.join(10)
        self.assertEqual(results, [{"id": 11, "result": None, "error": None}])

    def test_window_bounds_are_kept_only_for_app_windows(self) -> None:
        bounds = {"x": 10, "y": 20, "width": 900, "height": 600, "maximized": False}
        self.request("POST", "/api/alive", {"tab": "a", "window": bounds})
        self.assertIsNone(self.server.window, "a tab of a normal browser is not remembered")
        self.server.track_window = True
        self.request("POST", "/api/alive", {"tab": "a", "window": bounds})
        self.assertEqual(self.server.window, bounds)
        self.request("POST", "/api/alive", {"tab": "a", "window": {"width": "big"}})
        self.assertEqual(self.server.window, bounds, "invalid bounds are ignored")
        closing = {**bounds, "width": 1000}
        self.request("POST", "/api/bye", json.dumps({"tab": "a", "window": closing}).encode(), api=False,
                     headers={"Content-Type": "text/plain;charset=UTF-8"})
        self.assertEqual(self.server.window, closing)

    def test_heartbeat_and_goodbye(self) -> None:
        self.assertEqual(self.request("POST", "/api/alive", {"tab": "abc-123"}).status, 204)
        self.assertEqual(self.request("POST", "/api/alive", {"tab": "../x"}).status, 400)
        self.assertEqual(list(self.lifetime._tabs), ["abc-123"])
        response = self.request("POST", "/api/bye", b"abc-123", api=False,
                                headers={"Content-Type": "text/plain;charset=UTF-8"})
        self.assertEqual(response.status, 204)
        self.assertEqual(self.lifetime._tabs, {})


class SettingsTests(TempDirTest):
    def test_round_trip_and_fallback(self) -> None:
        config = os.path.join(self.root, "config", "OOT-SW2SE")
        data = os.path.join(self.root, "data", "OOT-SW2SE")
        settings = host.Settings([config, data])
        self.assertEqual(settings.values, {})
        self.assertTrue(settings.update(lastBackupFolder=self.root))
        self.assertTrue(os.path.isfile(os.path.join(config, "settings.json")))
        self.assertEqual(host.Settings([config, data]).folder("lastBackupFolder"), self.root)
        # A config folder that can't be created falls back to the data folder.
        blocked = os.path.join(self.root, "file")
        write(blocked)
        settings = host.Settings([os.path.join(blocked, "OOT-SW2SE"), data])
        self.assertTrue(settings.update(lastExportFolder=self.root))
        self.assertTrue(os.path.isfile(os.path.join(data, "settings.json")))
        self.assertFalse(host.Settings([os.path.join(blocked, "x")]).update(a=1), "nothing writable")

    def test_bad_or_stale_values_are_ignored(self) -> None:
        folder = os.path.join(self.root, "config")
        write(os.path.join(folder, "settings.json"), b"{not json")
        self.assertEqual(host.Settings([folder]).values, {})
        write(os.path.join(folder, "settings.json"), json.dumps({"lastBackupFolder": "/does/not/exist"}).encode())
        self.assertIsNone(host.Settings([folder]).folder("lastBackupFolder"))

    def test_folders_are_remembered_across_runs(self) -> None:
        folder = os.path.join(self.root, "config")
        saves = os.path.join(self.root, "saves", "slot_00")
        save_pair(saves)
        dialogs = FakeDialogs()
        dialogs.folder = saves
        host.EditorHost(dialogs, host.Settings([folder])).open_backup()
        dialogs.folder = None
        later = host.EditorHost(dialogs, host.Settings([folder]))
        later.open_backup()
        self.assertEqual(dialogs.calls[-1][2], saves, "the next run starts in the last backup folder")
        later.save_patch({"name": "p.zip", "contents": base64.b64encode(b"PK\x03\x04" + bytes(30)).decode()})
        self.assertEqual(dialogs.calls[-1][2], saves, "exports start there too until something is exported")

    def test_window_bounds(self) -> None:
        good = {"x": -5, "y": 0, "width": 900.4, "height": 600, "maximized": True}
        self.assertEqual(host.window_bounds(good), {"x": -5, "y": 0, "width": 900, "height": 600, "maximized": True})
        for bad in [None, [], {"width": 900, "height": 600}, {**good, "width": 50}, {**good, "x": True},
                    {**good, "height": "600"}]:
            self.assertIsNone(host.window_bounds(bad), bad)
        normal = {"x": 1, "y": 2, "width": 900, "height": 600, "maximized": False}
        maximized = {"x": 0, "y": 0, "width": 2560, "height": 1400, "maximized": True}
        self.assertEqual(host.remembered_window(normal, maximized), {**normal, "maximized": True},
                         "maximizing keeps the size to return to")
        self.assertEqual(host.remembered_window(None, maximized), maximized)
        self.assertEqual(host.remembered_window(maximized, normal), normal)

    def test_window_classes_match_the_measured_vivaldi_app_id(self) -> None:
        self.assertIn("vivaldi-127.0.0.1__oot-sw2se-Default", host.window_classes())
        entry = host.window_desktop_entry("vivaldi-127.0.0.1__oot-sw2se-Default", "/x/oot-sw2se")
        self.assertIn("Icon=oot-sw2se\n", entry)
        self.assertIn("StartupWMClass=vivaldi-127.0.0.1__oot-sw2se-Default\n", entry)
        self.assertIn("NoDisplay=true\n", entry)


# A stand-in browser: loads the editor like a real one (launch URL, cookie,
# page, heartbeat), logs its arguments, then stays FAKE_STAY seconds. With
# FAKE_FAIL=<its name> it fails at once instead.
FAKE_BROWSER = r'''#!{python}
import http.cookiejar, json, os, sys, time, urllib.parse, urllib.request
name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(name + " " + " ".join(args) + "\n")
if os.environ.get("FAKE_FAIL") == name:
    sys.exit(1)
url = next((arg[len("--app="):] for arg in args if arg.startswith("--app=")), args[-1])
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
page = opener.open(url).read()
parts = urllib.parse.urlsplit(url)
origin = parts.scheme + "://" + parts.netloc
alive = {{"tab": "fake", "window": json.loads(os.environ.get("FAKE_WINDOW", "null"))}}
opener.open(urllib.request.Request(origin + "/api/alive", data=json.dumps(alive).encode(), headers={{
    "Content-Type": "application/json", "X-OOT-SW2SE": "1", "Origin": origin}}))
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write("loaded " + name + " " + str(b"window.chrome.webview" in page) + "\n")
time.sleep(float(os.environ.get("FAKE_STAY", "1")))
'''


class AppWindowTests(TempDirTest):
    def setUp(self) -> None:
        super().setUp()
        self.bin = os.path.join(self.root, "bin")
        os.mkdir(self.bin)
        self.log = os.path.join(self.root, "log")

    def fake(self, *names: str) -> None:
        for name in names:
            path = os.path.join(self.bin, name)
            with open(path, "w") as file:
                file.write(FAKE_BROWSER.format(python=sys.executable))
            os.chmod(path, 0o755)

    def env(self, **extra: str) -> dict:
        self.tmp = os.path.join(self.root, "tmp")
        os.makedirs(self.tmp, exist_ok=True)
        return {"PATH": self.bin, "HOME": self.root, "TMPDIR": self.tmp, "FAKE_LOG": self.log,
                "XDG_CONFIG_HOME": os.path.join(self.root, "config"), **extra}

    def read_log(self) -> list[str]:
        try:
            with open(self.log) as file:
                return file.read().splitlines()
        except FileNotFoundError:
            return []

    def test_finds_default_or_first_chromium_browser(self) -> None:
        self.fake("brave", "chromium", "firefox")
        with mock.patch.dict(os.environ, {"PATH": self.bin}, clear=True):
            with mock.patch.object(host, "default_browser_id", return_value=None):
                self.assertEqual(host.find_app_browser(), os.path.join(self.bin, "chromium"))
            with mock.patch.object(host, "default_browser_id", return_value="brave-browser.desktop"):
                self.assertEqual(host.find_app_browser(), os.path.join(self.bin, "brave"))
            os.environ["OOT_SW2SE_APP_BROWSER"] = "none"
            self.assertIsNone(host.find_app_browser())
            os.environ["OOT_SW2SE_APP_BROWSER"] = "brave"
            self.assertEqual(host.find_app_browser(), os.path.join(self.bin, "brave"))

    def test_no_chromium_browser(self) -> None:
        self.fake("firefox")
        with mock.patch.dict(os.environ, {"PATH": self.bin}, clear=True), \
                mock.patch.object(host, "default_browser_id", return_value="firefox.desktop"):
            self.assertIsNone(host.find_app_browser())

    def test_window_reopens_with_the_remembered_size_and_place(self) -> None:
        self.fake("chromium", "xdg-open")
        window = json.dumps({"x": 10, "y": 20, "width": 900, "height": 600, "maximized": False})
        process = self.run_main(FAKE_STAY="0.5", FAKE_WINDOW=window)
        process.communicate(timeout=30)
        settings = os.path.join(self.root, "config", "OOT-SW2SE", "settings.json")
        with open(settings) as file:
            self.assertEqual(json.load(file)["window"], json.loads(window))
        os.unlink(self.log)
        process = self.run_main(FAKE_STAY="0.5")
        process.communicate(timeout=30)
        first = self.read_log()[0]
        self.assertIn("--window-size=900,600", first)
        self.assertIn("--window-position=10,20", first)
        self.assertNotIn("--start-maximized", first)

    def test_window_command(self) -> None:
        default = host.AppWindow("chromium")
        maximized = host.AppWindow("chromium", window={"x": 5, "y": 6, "width": 800, "height": 500, "maximized": True})
        broken = host.AppWindow("chromium", window={"width": 20, "height": 20, "x": 0, "y": 0})
        try:
            self.assertIn("--window-size=1100,730", default.command("u"))
            self.assertFalse([arg for arg in default.command("u") if arg.startswith("--window-position")])
            self.assertIn("--start-maximized", maximized.command("u"))
            self.assertIn("--window-size=800,500", maximized.command("u"))
            self.assertIn("--window-size=1100,730", broken.command("u"), "implausible sizes are ignored")
        finally:
            for window in (default, maximized, broken):
                window.close()

    def test_window_uses_and_removes_a_temporary_profile(self) -> None:
        window = host.AppWindow("/usr/bin/chromium")
        command = window.command("http://127.0.0.1:1/launch/x")
        self.assertIn("--app=http://127.0.0.1:1/launch/x", command)
        self.assertIn("--user-data-dir=" + window.profile, command)
        self.assertIn("--password-store=basic", command)
        self.assertTrue(os.path.isdir(window.profile))
        window.close()
        self.assertFalse(os.path.exists(window.profile))

    def run_main(self, *args: str, **env: str) -> subprocess.Popen:
        return subprocess.Popen([sys.executable, "-I", host.__file__, *args], env=self.env(**env),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def test_closing_the_app_window_ends_the_editor(self) -> None:
        self.fake("chromium", "xdg-open")
        process = self.run_main(FAKE_STAY="1")
        output, _ = process.communicate(timeout=30)
        self.assertEqual(process.returncode, 0, output)
        self.assertIn("The editor window was closed.", output)
        log = self.read_log()
        self.assertTrue(log[0].startswith("chromium --app=http://127.0.0.1:"), log)
        self.assertIn("loaded chromium True", log)
        self.assertFalse([line for line in log if line.startswith("xdg-open")], "no tab was opened")
        self.assertEqual(os.listdir(self.tmp), [], "the temporary profile was removed")

    def test_failed_app_window_falls_back_to_a_tab(self) -> None:
        self.fake("chromium", "xdg-open")
        process = self.run_main(FAKE_FAIL="chromium", FAKE_STAY="0")
        try:
            for _ in range(200):
                if any(line.startswith("loaded xdg-open") for line in self.read_log()):
                    break
                threading.Event().wait(0.1)
        finally:
            process.terminate()
            output, _ = process.communicate(timeout=10)
        log = self.read_log()
        self.assertIn("loaded xdg-open True", log, output)
        app_url = log[0].split("--app=")[1].split()[0]
        tab_url = next(line for line in log if line.startswith("xdg-open ")).split()[1]
        self.assertNotEqual(app_url, tab_url, "the tab gets a fresh launch URL")

    def test_sigterm_closes_the_window_and_removes_the_profile(self) -> None:
        self.fake("chromium")
        process = self.run_main(FAKE_STAY="60")
        try:
            for _ in range(200):
                if any(line.startswith("loaded chromium") for line in self.read_log()):
                    break
                threading.Event().wait(0.1)
            self.assertEqual(len(os.listdir(self.tmp)), 1, "one temporary profile while the window is open")
            process.terminate()
            output, _ = process.communicate(timeout=15)
        finally:
            if process.poll() is None:
                process.kill()
        self.assertEqual(process.returncode, 0, output)
        self.assertEqual(os.listdir(self.tmp), [], "the temporary profile was removed")

    def test_tab_option_skips_the_app_window(self) -> None:
        self.fake("chromium", "xdg-open")
        process = self.run_main("--tab", FAKE_STAY="0")
        try:
            for _ in range(200):
                if any(line.startswith("loaded") for line in self.read_log()):
                    break
                threading.Event().wait(0.1)
        finally:
            process.terminate()
            process.communicate(timeout=10)
        self.assertIn("loaded xdg-open True", self.read_log())
        self.assertFalse([line for line in self.read_log() if line.startswith("chromium")])


if __name__ == "__main__":
    unittest.main()
