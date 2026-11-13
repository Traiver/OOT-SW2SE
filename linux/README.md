# OOT SW2SE for Linux

The OOT SW2SE save editor for Linux. It shows the same
[`editor.html`](../editor.html) as the Windows and macOS versions, unchanged,
so the editor itself behaves identically. Only the host differs
([`oot_sw2se.py`](oot_sw2se.py)): instead of embedding a web view, it shows
the editor in an installed web browser and shows native folder and save
dialogs. With a Chromium-based browser, the editor gets its own app window;
otherwise it opens in a new tab of your default browser.

## Requirements

- Python 3.8 or later. Most desktop distributions include it.
- `kdialog` (KDE) or `zenity` (GNOME and most other desktops) for the file
  dialogs. Most desktops include one of them. The editor uses `kdialog` on KDE
  and LXQt, and `zenity` everywhere else, falling back to whichever is
  installed. Set `OOT_SW2SE_DIALOG=kdialog` or `OOT_SW2SE_DIALOG=zenity` to
  choose one.
- A current web browser. With a Chromium-based browser (Chromium, Google
  Chrome, Brave, Microsoft Edge or Vivaldi) the editor runs in its own window,
  like a regular app. Any other browser, such as Firefox, works too; the
  editor then opens in a new tab. See [Browser window](#browser-window).

The host uses only the Python standard library, so you don't need to install
anything with pip.

## Build

From the repository folder:

```sh
linux/build.sh
```

This writes `linux/dist/oot-sw2se.pyz`, a single executable file (a Python
[zipapp](https://docs.python.org/3/library/zipapp.html)) that contains the
editor, its icon and the license. The version shown in the editor is read from
`Program.cs`.

To build an AppImage as well, install
[appimagetool](https://github.com/AppImage/appimagetool) and run:

```sh
linux/build.sh --appimage    # or: APPIMAGETOOL=/path/to/appimagetool linux/build.sh --appimage
```

This also writes `linux/dist/OOT_SW2SE-<version>-<arch>.AppImage`. It runs the
same `.pyz` with the system's `python3`, so the requirements above still
apply.

You can also run the editor straight from a checkout, without building it:

```sh
python3 linux/oot_sw2se.py
```

## Use

1. Start `oot-sw2se.pyz` by double-clicking it or running
   `linux/dist/oot-sw2se.pyz` in a terminal. The editor opens in its own
   window, or in a new browser tab (see [Browser window](#browser-window)). A
   downloaded copy first needs `chmod +x oot-sw2se.pyz`, or start it with
   `python3 oot-sw2se.pyz`.
2. Click **Open Backup** and pick one of the following. The folder dialog
   starts in the folder you opened last time, so reopening the same save
   takes one click.
   - a backup folder (with `files/slot_00` … or `slot_00` … inside),
   - the `files` folder of a backup,
   - a single `slot_0X` folder,
   - any folder that holds `progress.sav` and `caption.sav`.
3. Edit, then choose **Save Patch ZIP** or **Export to Folder**. Folder export
   creates a new `Ocarina-of-Time-…-Patch-<UTC timestamp>_<uuid>` folder in your
   selected location; ZIP exports use the same name with `.zip` appended.
   Both contain a UTC timestamp folder such as `20261109_094216/` instead of
   `files/`. Copy that folder's contents into the `files/` directory of a **copy**
   of your full backup; copy `manifest.json` to the backup root when included.
   For a standalone save, copy the files inside the timestamp folder into the
   save folder. The patch contains only edited files, not a complete backup.

Closing the editor window ends the editor at once. In a browser tab, the
helper program exits about ten seconds after the tab is closed. Reloading the
page keeps it running, but discards unsaved edits.

Close the game or emulator first: a save file that changes while it is being
read is refused.

### Add it to the application menu

```sh
linux/dist/oot-sw2se.pyz --install
```

This copies the app to `~/.local/bin/oot-sw2se` and adds a menu entry and
icon for your user. It also adds hidden entries that give the editor's app
window its own icon and name in the task bar instead of the browser's (see
[Browser window](#browser-window)). `oot-sw2se --uninstall` removes all of
them again. For the
AppImage, use your desktop's AppImage integration (for example Gear Lever or
AppImageLauncher) instead.

### Options

| Option         | Effect                                                              |
| -------------- | ------------------------------------------------------------------- |
| `--tab`        | Open a tab of the default browser even if a Chromium-based browser is installed |
| `--no-browser` | Print the editor address instead of opening a browser               |
| `--install`    | Add the app to `~/.local/bin` and the application menu              |
| `--uninstall`  | Undo `--install`                                                    |
| `--verbose`    | Log every HTTP request and the browser's output                     |
| `--version`    | Print the version                                                   |

| Environment variable              | Effect                                                     |
| --------------------------------- | ---------------------------------------------------------- |
| `OOT_SW2SE_APP_BROWSER=<command>` | Use this Chromium-based browser for the window             |
| `OOT_SW2SE_APP_BROWSER=none`      | Never open a window; always use a tab (like `--tab`)       |
| `BROWSER=<command>`               | Browser for the tab, instead of the default browser        |
| `OOT_SW2SE_DIALOG=kdialog\|zenity` | File dialog program                                       |

To use any other browser, start with `--no-browser` and open the printed
address there.

### Browser window

When a Chromium-based browser is installed, the editor opens in a window of
its own, without tabs or an address bar, at the same size as on Windows and
macOS. The default browser is used when it is Chromium-based; otherwise the
first one found of `chromium`, `google-chrome-stable`, `brave-browser`,
`microsoft-edge-stable` and `vivaldi-stable` (and their usual alternative
names).

The window runs with a fresh, temporary browser profile, so it is a separate
process from any browser you have open. Your own browser profile, history and
extensions are not touched, and no password-store prompt (KWallet, GNOME
Keyring) appears. Closing the window ends the editor right away, and the
temporary profile is deleted. It is also deleted when the editor is ended with
Ctrl+C, by logging out or by closing its terminal.

The window's size and maximized state are remembered for the next start
(see [Settings](#settings)). Its position is remembered too, but only X11
lets an application place its own window. On Wayland the compositor decides;
on KDE Plasma the KWin script
[Remember Window Positions](https://github.com/rxappdev/RememberWindowPositions)
restores both size and position of the editor window.

Chromium names an app window after the address it opens: on Wayland this is
the app id, on X11 the window class. For the editor it is always
`<browser>-127.0.0.1__oot-sw2se-Default`, for example
`vivaldi-127.0.0.1__oot-sw2se-Default`. `--install` adds a hidden `.desktop`
file with that name for each supported browser, so the desktop shows the
editor's icon and name for the window, and pinning it to the task bar starts
the editor. Without `--install`, the task bar shows the browser's icon.

If no Chromium-based browser is found, or it fails to start, the editor opens
in a new tab of your default browser instead. Browsers installed only as
Flatpak or Snap are not detected; set `OOT_SW2SE_APP_BROWSER` to their
launcher command if they accept Chromium's `--app` option, or use the tab.

## Settings

The editor remembers a few things between runs in
`~/.config/OOT-SW2SE/settings.json` (`$XDG_CONFIG_HOME/OOT-SW2SE/`), or in
`~/.local/share/OOT-SW2SE/settings.json` if the config folder can't be
written:

| Key                | Value                                                              |
| ------------------ | ------------------------------------------------------------------ |
| `lastBackupFolder` | Folder opened last; the **Open Backup** dialog starts there         |
| `lastExportFolder` | Folder of the last ZIP or folder export; export dialogs start there |
| `window`           | Size, position and maximized state of the app window               |

Folders that no longer exist are ignored. The window size is only saved for
the app window, not for a tab of a normal browser. Delete the file to reset
everything; the editor works the same without it.

## How it works

The Windows and macOS hosts expose the WebView2 bridge
(`window.chrome.webview`) to the page and answer three requests: open a
backup, save a patch ZIP, write a patch folder. The Linux host does the same
over HTTP:

- It serves the editor from a server that listens only on `127.0.0.1`, on a
  random port.
- Before sending the page, it adds a small script that provides
  `window.chrome.webview` on top of `fetch()`, and it adds
  `connect-src 'self'` to the page's Content-Security-Policy so that script can
  reach the server. All other network access stays blocked.
- The browser opens a one-time launch address that sets a session cookie
  (`HttpOnly`, `SameSite=Strict`). Every request must carry this cookie, the
  page's own origin and a custom header. The server also checks the `Host`
  header. Other websites and other users on the same machine can't use the
  editor's file access.
- Backups are read with the same folder rules and size limits as the macOS
  host. Patches are validated and written like on the other platforms. ZIP
  files are written atomically, and patch folders never replace existing
  files or folders.

## Tests

```sh
python3 -m unittest discover -s linux/tests -v
```

These tests cover backup reading, patch validation and writing (the same
cases `tests/host_exports.py` runs against the Windows and macOS hosts), page
preparation, the server's access checks, the editor's lifetime, the settings
file, and choosing, starting, sizing and cleaning up the browser window (with a
stand-in browser). They
don't open real dialogs or a real browser, and they don't replace in-game
testing with a real save.

## License

MIT, like the rest of the project: see [`LICENSE`](../LICENSE). The build
places a copy inside the app (`LICENSE.txt`) and next to it in `dist`; keep
it with the app when you share it. Game imagery shown by the editor keeps its
own terms.
