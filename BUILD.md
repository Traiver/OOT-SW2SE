# Build OOT SW2SE

Use Windows x64 with .NET Framework 4.8 and the Microsoft Edge WebView2 Runtime. From PowerShell in this folder, run:

```powershell
.\build.ps1
```

The script verifies the pinned Microsoft WebView2 SDK package, builds the executable, and places it with the project license (`LICENSE.txt`) and the WebView2 license (`WebView2-LICENSE.txt`) in `dist`. The application works offline. The build downloads the SDK once, unless you pass a local copy with `-WebView2Package`.

`Program.cs` contains the native window and local file dialogs. `editor.html` contains the English editor interface, save parser, and patch generator.

The MIT license applies to the original editor software. WebView2 and third-party material, such as game imagery, retain their own terms.

## macOS

Use macOS 13 or later with the Xcode command-line tools (`xcode-select --install`). From Terminal in this folder, run:

```sh
macos/build.sh
```

The script builds a universal app for Apple silicon and Intel, signs it ad hoc for the Mac that built it, and places it in `macos/dist/OOT SW2SE.app` with the project license inside the app. It bundles the same `editor.html` unchanged and reads the version from `Program.cs`.

GitHub Actions also runs this script ([`.github/workflows/macos.yml`](.github/workflows/macos.yml)): download the app from a run in the Actions tab, or from a release, where it is attached as `OOT-SW2SE-<version>-macOS.zip`. These builds are ad hoc signed, not notarized, so macOS blocks the first launch until you choose **Open Anyway** in System Settings → Privacy & Security.

`macos/OOTSW2SE.swift` contains the native window and file dialogs. See [`macos/README.md`](macos/README.md) for usage notes and for running the app on another Mac.

## Linux

Use Python 3.8 or later; no other build tools are needed. From a terminal in this folder, run:

```sh
linux/build.sh
```

The script places `linux/dist/oot-sw2se.pyz`, a single executable file that bundles `linux/oot_sw2se.py` with the same `editor.html` unchanged, the icon and the project license, in `linux/dist`. It reads the version from `Program.cs`. With `--appimage` and [appimagetool](https://github.com/AppImage/appimagetool) installed, it also builds an AppImage. At runtime, the app shows the editor in its own window of a Chromium-based browser when one is installed, otherwise in a new tab of the default web browser, and uses `kdialog` or `zenity` for file dialogs.

GitHub Actions also runs this script ([`.github/workflows/linux.yml`](.github/workflows/linux.yml)) and attaches `OOT-SW2SE-<version>-linux.pyz` to releases. See [`linux/README.md`](linux/README.md) for usage notes, desktop integration and how the browser host works. The Linux version, including its Linux-only Save Back, was written by aut0mat3d/Claude, vibe-coded with Claude (Anthropic), under the MIT License.

## Checks

Run `node --test tests/editor.test.cjs` for synthetic save regression tests.
Run `python3 -m unittest discover -s linux/tests -v` for the Linux host's backup
reading, export, page and server checks.
On a Mac with Swift and Mono installed, run `python3 tests/host_exports.py` to
compile and exercise the actual Swift and C# folder export helpers, including
path validation and byte-for-byte output checks. These checks do not replace
in-game testing with a real save.
