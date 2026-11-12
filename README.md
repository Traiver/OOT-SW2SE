# OOT SW2SE

Save editor for the Nintendo Switch 2 remake of The Legend of Zelda: Ocarina of Time.

Original editor by [Traiver](https://github.com/Traiver/OOT-SW2SE) and upstream contributors.

![OOT SW2SE showing the stats of a loaded save](editor-screenshot.jpg)

- Edit rupees, hearts, magic & more.
- Change item quantities, bottles, small keys, and bag or quiver capacity.
- Add missing items, including masks, with their acquisition flags set automatically.
- Remove supported owned single items, optionally clearing their mapped acquisition flags. Acquisition history is kept by default; story and quest progress are not reset. Unequip weapons and shields in both eras first. Default clothes, quantities, and capacity upgrades use their own controls rather than inventory removal.
- Export replacement files as a ZIP or to a new patch folder on Windows, macOS and Linux. Export names include a UTC timestamp followed by a UUID; replacement files sit inside a folder named with that same UTC timestamp (`yyyyMMdd_HHmmss`). Exports contain only replacement files, not a complete backup.
- Toggle progress flags and change the spoken dialogue language when `option.sav` is available.

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

- Added a Linux version in `linux/`: a Python host (standard library only) that opens the unchanged editor in the default web browser and uses `kdialog` or `zenity` for file dialogs. `linux/build.sh` builds a single executable `.pyz` and optionally an AppImage. See [`linux/README.md`](linux/README.md).
- Added regression tests for the Linux host (`linux/tests/test_host.py`).

To apply a patch to a full backup, copy the contents of the timestamp folder into the backup's `files/` directory and copy `manifest.json` to the backup root when included. For a standalone save, copy the files inside the timestamp folder into the save folder. Work on a copy of the backup.

Clearing acquisition flags does not rewind story events or quest progress. Windows UI and in-game behavior have not yet been verified.
