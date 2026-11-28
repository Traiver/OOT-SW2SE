# OOT SW2SE on the web

The web version runs the OOT SW2SE save editor in a web browser, with nothing
to install. It is the same [`editor.html`](../editor.html) as on Windows,
macOS and Linux, unchanged. Only the host differs
([`browser-host.js`](browser-host.js)): instead of a native window, the
browser's own file pickers open the save and save the patch.

Nothing is uploaded. The page reads the save files in the browser, and
patches are saved as downloads or written into a folder you pick. The page
can't send anything anywhere: its Content-Security-Policy, the same as on the
other platforms, blocks all network access.

## Use

1. Open the page (see [Run it](#run-it)).
2. Click **Open Backup** and pick a folder, the same as on the other
   platforms:
   - a backup folder (with `files/slot_00` … or `slot_00` … inside),
   - the `files` folder of a backup,
   - a single `slot_0X` folder,
   - any folder that holds `progress.sav` and `caption.sav`,
   - the data or game folder of a PC port (Longshot, Project ReLink) or a
     Switch emulator (Lichii, Fritchii, Eden), or any folder on the way to
     the save: the editor opens the save folder inside it.
3. Edit, then choose **Save Patch ZIP** (saved to your downloads) or
   **Export to Folder**. Apply the patch as described in the
   [main README](../README.md#changes-in-this-fork).

The browser asks for permission before the page can read the folder.
Firefox and Safari call this an upload; the files still stay on your
computer.

### Differences from the desktop versions

| | Chrome, Edge and other Chromium-based browsers | Firefox, Safari |
| --- | --- | --- |
| Open Backup | Folder picker; starts in the folder opened last time | Folder upload field |
| Save Patch ZIP | Saved to your downloads | Saved to your downloads |
| Export to Folder | Writes a new patch folder in a folder you pick | Not shown: these browsers can't write folders |

- When you pick a single `slot_0X` folder, the page can't see the folder
  around it, so `option.sav` (voice language) and `manifest.json` are not
  included. Pick the whole backup to edit them.
- **Save Back** (Linux only) is not offered; patches never change the
  opened files.
- Phones and tablets: their browsers can't pick folders, so the web
  version can't open a backup there.
- Firefox doesn't show the editor's icon in the tab: the page's
  Content-Security-Policy only allows `blob:` images, and Firefox applies it
  to the icon as well.

## Run it

### As a container

GitHub Actions publishes an image to the GitHub Container Registry
([`.github/workflows/web.yml`](../.github/workflows/web.yml)): `:latest` and
`:<version>` for releases, `:edge` for the main branch. Until the first
release is published only `:edge` exists, so the commands below use it; use
`:latest` instead once there is a release.

```sh
docker run --rm -p 8080:8080 ghcr.io/traiver/oot-sw2se:edge
```

With Docker Compose, [`compose.yaml`](compose.yaml) runs the same image
locked down and restarts it with Docker (`OOT_SW2SE_TAG` picks the tag,
`edge` by default; `OOT_SW2SE_PORT` the port, 8080 by default):

```sh
docker compose -f web/compose.yaml up -d
```

Then open <http://localhost:8080> (with Compose and `OOT_SW2SE_PORT` set,
the port you chose: `http://localhost:<port>`). The image holds only
[static-web-server](https://static-web-server.net), its settings
([`sws.toml`](sws.toml)) and the page. It runs as an unprivileged user, needs
no write access and no capabilities, so it also runs locked down:

```sh
docker run --rm -p 8080:8080 --read-only --cap-drop ALL --security-opt no-new-privileges \
  ghcr.io/traiver/oot-sw2se:edge
```

`GET /health` answers `200` for health checks. Serve it over HTTPS (behind a
reverse proxy) when it isn't on `localhost`: browsers only allow the folder
pickers and the checksums the editor uses on secure pages.

### As files

Releases include `OOT-SW2SE-<version>-web.zip` with `index.html`,
`favicon.ico` and `LICENSE.txt`. Put them on any web server, or open
`index.html` straight from disk.

## Build

With [Node.js](https://nodejs.org) 20 or later, from the repository folder:

```sh
node web/build.mjs
```

This writes `web/dist/index.html`: `editor.html` with `browser-host.js` added
in front of the editor's script and the version from `Program.cs`. It also
copies `editor.ico` as `favicon.ico` and the license as `LICENSE.txt`.

To build the container image instead, which also runs the tests:

```sh
docker build -f web/Dockerfile -t oot-sw2se-web .
docker run --rm -p 8080:8080 oot-sw2se-web
```

[`Dockerfile`](Dockerfile) builds in stages: Node.js builds and tests the page,
then the image gets only the server binary and the page.
`docker build -f web/Dockerfile --target site --output web/dist .` exports
only the page.

## How it works

The Windows and macOS hosts expose the WebView2 bridge
(`window.chrome.webview`) to the page and answer three requests: open a
backup, save a patch ZIP, write a patch folder. `browser-host.js` provides the
same bridge and answers the same requests in the browser:

- **Open a backup:** with `showDirectoryPicker()` where the browser has it,
  otherwise an `<input type="file" webkitdirectory>` field. The folder rules
  (including the PC ports' save folders), file names and size limits are
  those of the desktop hosts, so the editor gets the same files under the
  same names.
- **Save a patch ZIP:** checked like on the desktop, then saved as a download.
- **Write a patch folder:** checked like on the desktop (only the known save
  paths, same size limits), then written with the File System Access API into
  a new folder. An existing file or folder is never replaced; if writing
  fails, the new folder is removed again.

## Tests

```sh
node --test tests/web-host.test.cjs
```

These tests check the folder rules against the editor's own
`findBackupFiles`, the patch checks against the editor's own exports, the
size limits, and that the build changes nothing in the editor but the version
and the added host. They don't open a real browser.
