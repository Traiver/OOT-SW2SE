# OOT SW2SE

Save editor for the Nintendo Switch 2 remake of The Legend of Zelda: Ocarina of Time.

Original editor by [Traiver](https://github.com/Traiver/OOT-SW2SE) and upstream contributors.

![OOT SW2SE showing the stats of a loaded save](editor-screenshot.jpg)

- Edit rupees, hearts, magic, the swim depth & more.
- Change item quantities, bottles, small keys, and bag or quiver capacity.
- Add missing items, including masks, with their acquisition flags set automatically.
- Remove supported owned single items, optionally clearing their mapped acquisition flags. Acquisition history is kept by default; story and quest progress are not reset. Unequip weapons and shields in both eras first. Default clothes, quantities, and capacity upgrades use their own controls rather than inventory removal.
- Export replacement files as a ZIP or to a new patch folder on Windows, macOS and Linux. Export names include a UTC timestamp followed by a UUID; replacement files sit inside a folder named with that same UTC timestamp (`yyyyMMdd_HHmmss`). Exports contain only replacement files, not a complete backup.
- Toggle progress flags and change the spoken dialogue language when `option.sav` is available.
- Open the most recently saved slot automatically, list every slot with its in-game save time, and give exported ZIP entries the slot's save time. See [Save time: newest slot and ZIP timestamps](#save-time-newest-slot-and-zip-timestamps).
- On Linux only: save edits straight back into the opened files, with an automatic backup of the replaced files, and more. See [Linux version](#linux-version).

## Linux version

[`linux/`](linux/) adds a Linux version. It shows the same, unchanged editor in a browser window and provides the native parts (file dialogs, file access) through a small Python host instead of WebView2 or WKWebView. See [`linux/README.md`](linux/README.md) for requirements, building and use.

Besides everything the Windows and macOS versions do, the Linux version has some features of its own. They are rebuilt here only for Linux; the Windows and macOS hosts don't have them:

| Linux-only feature | Summary | Details |
| ------------------ | ------- | ------- |
| **Save Back** | Writes the edits straight into the opened save files. The files it replaces are first stored in `~/.config/OOT-SW2SE/backups/<titleID>_slot<NN>_<YYMMDD>_<hhmmss>.zip`. Nothing is written if a file changed since it was opened. | [Save Back](linux/README.md#save-back) |
| **Remembered folders** | The open and export dialogs start in the folders used last, also after a restart (`~/.config/OOT-SW2SE/settings.json`). | [Settings](linux/README.md#settings) |
| **Remembered window** | The app window reopens with its last size, maximized state and, on X11, position. | [Browser window](linux/README.md#browser-window) |
| **App window with its own icon** | With a Chromium-based browser, the editor runs as an app window with its own task bar icon; otherwise in a browser tab. | [Browser window](linux/README.md#browser-window) |
| **Desktop integration** | `--install` adds the app to the application menu. | [Add it to the application menu](linux/README.md#add-it-to-the-application-menu) |

Save Back is the only one that touches `editor.html`: a **Save Back** button, hidden unless the host announces the feature in `window.chrome.webview.hostFeatures.saveBack`, and two helper functions (`saveBackEntries`, `replaceOpenedFiles`). On Windows and macOS the button stays hidden, so nothing changes there. A Windows or macOS host could offer Save Back by announcing the feature and answering the `saveBack` request like [`linux/oot_sw2se.py`](linux/oot_sw2se.py) does.

The Linux version, Save Back and the save-time features below were written by aut0mat3d/Claude in 2026, vibe-coded with Claude (Anthropic), and are released under the MIT License like the rest of the project.

## Save time: newest slot and ZIP timestamps

*Added by aut0mat3d/Claude (2026), vibe-coded with Claude (Anthropic); MIT License. Shared by all platforms.*

A backup holds up to six slots (`slot_00` … `slot_05`): autosaves and manual saves. When you continue in the game, it loads the most recently saved slot, which is often not `slot_00`. Before this change, the editor always opened `slot_00` first. Edits to that slot then had no visible effect in the game, because the game kept loading a newer slot. The exported ZIP also dated every file 1980-01-01 00:00, so you could not tell from the files which save a patch came from.

The editor now uses the save time that the game writes into each slot's `caption.sav`, to the second.

### What the user sees

- When a backup with several slots is opened, the editor opens the newest slot instead of `slot_00`.
- Every entry in the slot list shows its save time and save type, and the newest one is marked:

  ```text
  slot_00 · 12.11.2026 · 23:21:25 · autosave
  slot_01 · 12.11.2026 · 23:07:15 · autosave
  slot_02 · 12.11.2026 · 23:21:55 · autosave
  slot_03 · 12.11.2026 · 23:16:50 · autosave
  slot_04 · 12.11.2026 · 23:13:17 · autosave
  slot_05 · 13.11.2026 · 00:12:41 · manual save · newest   ← opened automatically
  ```

- The Overview shows the same time under **Saved**, now with seconds.
- Entries in an exported ZIP carry the slot's save time instead of 1980-01-01 00:00.
- You can still pick any slot from the list. Nothing is written to the backup.

### Where the time comes from

`caption.sav` stores the save time as separate integer fields. They hold the local date and time of the console (or emulator) at the moment of saving:

| Field hash   | Meaning                       | Note                         |
| ------------ | ----------------------------- | ---------------------------- |
| `0x9811A3F7` | Year                          |                              |
| `0xDFD840D3` | Month                         |                              |
| `0xBD46F485` | Day                           |                              |
| `0x23F3D75E` | Hour                          |                              |
| `0x27853BF7` | Minute                        |                              |
| `0x5EE50BED` | Second                        | Newly identified, see below  |
| `0x25F03CAA` | 1 = autosave, 0 = manual save |                              |

The editor already displayed all fields except the seconds. The seconds field and the day and month order were identified by comparing 18 slots saved by three Switch emulators with the file modification time of their `caption.sav`. In all 16 slots whose file time was still original, the stored date and time matched it within a few seconds: the file was written between 0.4 seconds before and 3.2 seconds after the stored time. The 0.4 seconds before are an emulator clock that runs slightly ahead; the longest gaps are manual saves, which also write a screenshot. A save time counts as valid only if all fields are in range (year 1980–2107, month 1–12, day 1–31, hour 0–23, minute and second 0–59). A `caption.sav` without the seconds field is read as second 0.

Because the complete time comes from the save itself, file times are not used at all. The result does not depend on the time zone, on how the backup was copied or extracted, or on the platform. The editor behaves the same on Windows, macOS and Linux, and would also work as a plain web page.

### Which slot is newest

1. Slots are compared by their in-game save time: date, hour, minute and second.
2. If two slots share the same second, the lower slot number wins.
3. Slots without a valid save time, or with an unreadable `caption.sav`, rank last. If no slot has a valid time, the editor opens the first slot, as before.

### ZIP timestamps

Each entry in an exported ZIP (`progress.sav`, `caption.sav`, and `option.sav` or `manifest.json` when included) gets the save time of the exported slot. If the slot has no valid save time, the editor uses the current local time. Before this change, every entry was dated 1980-01-01 00:00.

The ZIP stores this in the standard MS-DOS date and time fields. Like the save time, these hold a plain local date and time without a time zone, so an extracted file shows the same wall-clock time as the game, on any computer and in any time zone. MS-DOS time counts seconds in steps of two, so odd seconds are rounded down: 00:12:41 becomes 00:12:40. The editor never reads file times back, so this has no effect on which slot is newest.

Storing odd seconds exactly would need the ZIP "extended timestamp" field. That field holds UTC, so the editor would have to assume a time zone for the save time, and not every unpacking tool reads it. This was left out on purpose.

Folder export is unchanged. The native host writes those files with the export time, like any file copy.

### Limitations

- Tested with the unit tests and, in a browser, with copies of real emulator saves. Not yet verified with saves from a console or in the game on a console.
- The seconds field was identified from emulator saves only. Saves from a console are expected to use the same format, since the game writes it.

### Code

All logic is in `editor.html` and shared by every platform. No host changes are needed.

| Function                 | Purpose                                                                  |
| ------------------------ | ------------------------------------------------------------------------ |
| `saveTime(c)`            | Reads and validates the save time from a parsed `caption.sav`            |
| `newestSlot(slots)`      | Applies the rules above                                                  |
| `formatSaveTime(t)`      | Text for the slot list and Overview                                      |
| `dosDateTime(t, now)`    | Converts the save time to ZIP (MS-DOS) time and date                     |
| `openBackupFiles(files)` | Reads every slot's save time, labels the list and opens the newest slot  |

To go back to the previous behavior, open `backup.slots[0]` in `openBackupFiles` and call `zip(entries)` without a time. `tests/editor.test.cjs` covers field order, seconds, validation, tie handling and ZIP timestamps.

## Changes in this fork

2026-11-09 · 20:42 (UTC+8)

- Added removal of supported owned single items on Windows and macOS.
- Added an optional acquisition-flag reset when removing an item; acquisition history is preserved by default.
- Added folder export on both platforms alongside ZIP export, preserving relative paths in a new patch folder.
- Added regression tests for save editing and both native folder exporters.
- Built macOS v1.0.1 for Apple silicon and Intel; verified removal, acquisition-flag reset, and folder export through the app with a synthetic save.

2026-11-09 · 13:44 UTC

- Updated ZIP and folder names to include a UTC timestamp before the UUID, for example `Ocarina-of-Time-slot_00-Patch-20261109_094216_<uuid>.zip`.
- Replaced the exported `files/` directory with `20261109_094216/`, using the same timestamp as the outer name. Loose saves also use a timestamp folder. `manifest.json` stays at the export root.
- Updated both native folder exporters and built macOS v1.0.2.

2026-11-12 · 23:31 UTC

- Added a Linux version in `linux/`: a Python host (standard library only) that shows the unchanged editor in its own window of a Chromium-based browser when one is installed, otherwise in a new tab of the default web browser, and uses `kdialog` or `zenity` for file dialogs. `linux/build.sh` builds a single executable `.pyz` and optionally an AppImage. See [`linux/README.md`](linux/README.md).
- The editor now opens the most recently saved slot, shows each slot's save time (to the second, from the newly identified seconds field in `caption.sav`) in the slot list, and dates ZIP entries with the slot's save time instead of 1980-01-01. See [Save time: newest slot and ZIP timestamps](#save-time-newest-slot-and-zip-timestamps).
- Linux only: **Save Back** writes edits into the opened files after backing up the replaced files to `~/.config/OOT-SW2SE/backups/`. The open and export folders and the app window's size and position are remembered, and `--install` (also from the AppImage) adds a menu entry and a task bar icon for the app window. See [Linux version](#linux-version).
- Added regression tests for these features (`tests/editor.test.cjs`, `linux/tests/test_host.py`).
- Written by aut0mat3d/Claude, vibe-coded with Claude (Anthropic); MIT License.

To apply a patch to a full backup, copy the contents of the timestamp folder into the backup's `files/` directory and copy `manifest.json` to the backup root when included. For a standalone save, copy the files inside the timestamp folder into the save folder. Work on a copy of the backup.

Clearing acquisition flags does not rewind story events or quest progress. Windows UI and in-game behavior have not yet been verified.
