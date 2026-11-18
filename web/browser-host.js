// Browser host for the web version of OOT SW2SE.
//
// editor.html talks to its host through the WebView2 bridge
// (window.chrome.webview): it asks it to open a backup, save a patch ZIP and
// write a patch folder. This script provides the same bridge with browser APIs
// only, so the unchanged editor runs as a plain web page. Nothing is uploaded:
// the save files are read in the browser, and patches are saved as downloads
// or written into a folder the user picks.
//
// web/build.mjs places this script in front of the editor's own script. Folder
// rules, size limits and patch validation mirror the desktop hosts
// (Program.cs, macos/OOTSW2SE.swift, linux/oot_sw2se.py).
(() => {
  'use strict';
  const MAX_FILE_BYTES = 2 * 1024 * 1024; // a single .sav or manifest file
  const MAX_BACKUP_BYTES = 8 * 1024 * 1024; // all files read from one backup
  const SLOTS = ['slot_00', 'slot_01', 'slot_02', 'slot_03', 'slot_04', 'slot_05'];
  const PREFIX = 'Backup/files/';

  class HostError extends Error {}

  // Every path, relative to the picked folder, that backupLayout() may read.
  // The folder-handle reader only looks these up instead of listing the folder.
  const CANDIDATES = ['progress.sav', 'caption.sav', 'option.sav', 'account.sav', 'manifest.json',
    'files/option.sav', 'files/account.sav', ...SLOTS.flatMap(slot => ['', 'files/'].flatMap(base =>
      [base + slot + '/progress.sav', base + slot + '/caption.sav']))];

  // PC ports (Longshot, Project ReLink) and Switch emulators (Lichii,
  // Fritchii, Eden) keep the same save files as the Switch, in these layouts
  // relative to their data or game folder; "<id>" is a profile folder. The
  // picked folder may be any folder on the way to the save. GAME_USER is the
  // profile both ports open. Same rules as PortSaves in the desktop hosts.
  const TITLE_ID = '0400486024DEC000';
  const SAVE_LAYOUTS = [
    ['save', '<id>'],                                                      // Longshot; Project ReLink on Linux
    ['user', 'save', '<id>'],                                              // Project ReLink's game folder
    ['nand', 'user', 'save', '0000000000000000', '<id>', TITLE_ID],        // Lichii, Fritchii, Eden
    ['nand', 'user', 'save', 'account', '<id>', TITLE_ID, '0'],            // their newer layout
    ['user', 'nand', 'user', 'save', '0000000000000000', '<id>', TITLE_ID], // installed portable
    ['user', 'nand', 'user', 'save', 'account', '<id>', TITLE_ID, '0'],
  ];
  const GAME_USER = '5a3c9e1f0b7d24680000000000000001';
  // The files of a save folder `folder` (ending in "/") the layout reads.
  const profileCandidates = folder => [folder + 'option.sav', folder + 'account.sav',
    ...SLOTS.flatMap(slot => [folder + slot + '/progress.sav', folder + slot + '/caption.sav'])];

  // Every save folder the layouts reach in `paths` (the files that exist,
  // relative to the picked folder), as [folder ending in "/", profile].
  function layoutMatches(paths) {
    const tree = new Map();
    for (const path of paths) {
      const parts = path.split('/');
      for (let i = 0; i < parts.length - 1; i++) {
        const parent = parts.slice(0, i).map(part => part + '/').join('');
        if (!tree.has(parent)) tree.set(parent, new Set());
        tree.get(parent).add(parts[i]);
      }
    }
    const holdsSlots = folder => SLOTS.some(slot => paths.has(folder + slot + '/progress.sav') && paths.has(folder + slot + '/caption.sav'));
    const found = new Map();
    function walk(folder, parts, profile) {
      if (!parts.length) {
        if (!found.has(folder) && holdsSlots(folder)) found.set(folder, profile ?? folder.split('/').at(-2));
        return;
      }
      const [head, ...rest] = parts;
      const names = [...(tree.get(folder) ?? [])].sort();
      for (const name of head === '<id>' ? names : names.filter(name => name === head)) {
        walk(folder + name + '/', rest, head === '<id>' ? name : profile);
      }
    }
    for (const layout of SAVE_LAYOUTS) {
      for (let start = 0; start < layout.length; start++) walk('', layout.slice(start), null);
    }
    return [...found];
  }

  // The save folder of a port or emulator in the picked folder, ending in "/",
  // or '' when there is none.
  function portProfile(paths) {
    const matches = layoutMatches(paths);
    if (!matches.length) return '';
    if (matches.length === 1) return matches[0][0];
    const game = matches.find(([, profile]) => profile.toLowerCase() === GAME_USER);
    if (game) return game[0];
    throw new HostError('This folder holds the saves of several profiles. Open one of them: ' +
      [...new Set(matches.map(([, profile]) => profile))].sort().join(', ') + '.');
  }

  // With folder handles nothing is listed up front: this looks up the files
  // backupLayout() may read, following the layouts down from `folder`, and
  // returns their paths with a way to open each.
  async function probeFolder(folder) {
    const handles = new Map();
    const fileAt = async path => {
      const parts = path.split('/');
      let dir = folder;
      for (const part of parts.slice(0, -1)) dir = await dir.getDirectoryHandle(part);
      return dir.getFileHandle(parts.at(-1));
    };
    const probe = paths => Promise.all(paths.map(path => fileAt(path).then(handle => handles.set(path, handle), () => {})));
    await probe(CANDIDATES);
    const seen = new Set();
    async function walk(dir, prefix, parts) {
      if (!parts.length) {
        if (!seen.has(prefix)) {
          seen.add(prefix);
          await probe(profileCandidates(prefix));
        }
        return;
      }
      const [head, ...rest] = parts;
      if (head !== '<id>') {
        const child = await dir.getDirectoryHandle(head).catch(() => null);
        if (child) await walk(child, prefix + head + '/', rest);
        return;
      }
      for await (const [name, entry] of dir.entries()) {
        if (entry.kind === 'directory') await walk(entry, prefix + name + '/', rest);
      }
    }
    for (const layout of SAVE_LAYOUTS) {
      for (let start = 0; start < layout.length; start++) await walk(folder, '', layout.slice(start));
    }
    return { paths: new Set(handles.keys()), open: path => handles.get(path).getFile() };
  }

  // Decides which files of the picked folder `root` the editor gets, and under
  // which name, like BackupReader in the desktop hosts. `paths` holds the
  // files that exist, relative to the picked folder. Returns
  // [editor path, path in the picked folder] pairs. Accepted layouts:
  //   1. A slot folder (slot_00 … slot_05) picked directly. Unlike the desktop
  //      hosts, a page can't look at the folder around it, so option.sav and
  //      manifest.json are not included.
  //   2. Any other folder that directly holds progress.sav and caption.sav,
  //      with option.sav when it is there.
  //   3. A backup folder with slot_00 … slot_05 directly or inside "files",
  //      plus option.sav and account.sav next to the slots and manifest.json
  //      in the backup root. Picking the "files" folder itself works too.
  //   4. A PC port's or Switch emulator's data or game folder, or any folder
  //      on the way to the save: the save folder inside it is read like 3
  //      (see SAVE_LAYOUTS).
  function backupLayout(root, paths) {
    const has = path => paths.has(path);
    const pair = folder => has(folder + 'progress.sav') && has(folder + 'caption.sav');
    const read = (folder, prefix) => ['progress.sav', 'caption.sav'].map(name => [prefix + name, folder + name]);
    if (/^slot_0[0-5]$/i.test(root) && pair('')) return read('', PREFIX + root.toLowerCase() + '/');
    if (pair('')) {
      // The editor expects "<name>/progress.sav".
      const name = !root.trim() || /[/\\:]/.test(root) ? 'Save' : root;
      const files = read('', name + '/');
      for (const extra of ['option.sav', 'account.sav']) if (has(extra)) files.push([name + '/' + extra, extra]);
      return files;
    }
    // Prefer a "files" subfolder, but only if it really holds slots.
    const holdsSlots = folder => SLOTS.some(slot => pair(folder + slot + '/'));
    const at = holdsSlots('') || holdsSlots('files/') ? '' : portProfile(paths);
    const nested = at + (holdsSlots(at + 'files/') ? 'files/' : '');
    const slots = SLOTS.filter(slot => pair(nested + slot + '/'));
    if (!slots.length) throw new HostError('No folder containing progress.sav and caption.sav was found.');
    const files = slots.flatMap(slot => read(nested + slot + '/', PREFIX + slot + '/'));
    for (const extra of ['option.sav', 'account.sav']) {
      if (has(nested + extra)) files.push([PREFIX + extra, nested + extra]);
    }
    // manifest.json sits in the backup root, the folder around "files". When
    // the "files" folder itself was picked, that root can't be read.
    if (!at && (nested || root.toLowerCase() !== 'files') && has('manifest.json')) {
      files.push(['Backup/manifest.json', 'manifest.json']);
    }
    return files;
  }

  function base64(bytes) {
    let binary = '';
    for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
    return btoa(binary);
  }

  function fromBase64(text) {
    if (typeof text !== 'string' || !text || text.length % 4 || !/^[A-Za-z0-9+/]*={0,2}$/.test(text)) return null;
    return Uint8Array.from(atob(text), char => char.charCodeAt(0));
  }

  // Reads the files chosen by backupLayout(). `open(path)` returns a File for
  // a path in the picked folder. Returns the {relativePath, contents} list the
  // desktop hosts send.
  async function readBackup(root, paths, open) {
    const result = [];
    let total = 0;
    for (const [relativePath, path] of backupLayout(root, paths)) {
      const file = await open(path);
      total += file.size;
      if (file.size > MAX_FILE_BYTES || total > MAX_BACKUP_BYTES) {
        throw new HostError('The backup files exceed the expected size.');
      }
      let data;
      try {
        data = new Uint8Array(await file.arrayBuffer());
      } catch {
        // Browsers refuse to read a file that changed after it was picked.
        throw new HostError(relativePath + ' could not be read. If the game or an emulator saved it ' +
          'since you picked the folder, close it, then open the backup again.');
      }
      if (data.length !== file.size) throw new HostError('A backup file was truncated while reading it.');
      result.push({ relativePath, contents: base64(data) });
    }
    return result;
  }

  const PATCH_NAME = /^Ocarina-of-Time-(?:Save|slot_0[0-5])-Patch-([0-9]{8}_[0-9]{6})_[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$/;

  // Validates and decodes the files of a folder export, with the same rules
  // as the desktop hosts: only the known save paths below the timestamp folder
  // (and manifest.json) are allowed, with the same size limits.
  function decodePatchFiles(entries, name) {
    const match = typeof name === 'string' ? PATCH_NAME.exec(name) : null;
    if (!match) throw new HostError('Invalid patch folder name.');
    if (!Array.isArray(entries) || entries.length < 2 || entries.length > 4) {
      throw new HostError('Invalid patch file list.');
    }
    const allowed = new RegExp('^(?:manifest\\.json|' + match[1] +
      '/(?:progress\\.sav|caption\\.sav|option\\.sav|slot_0[0-5]/(?:progress|caption)\\.sav))$');
    const files = new Map();
    let total = 0;
    for (const entry of entries) {
      const path = entry?.relativePath;
      const contents = entry?.contents;
      if (typeof path !== 'string' || !allowed.test(path) || files.has(path) ||
          typeof contents !== 'string' || contents.length > 2 * MAX_FILE_BYTES) {
        throw new HostError('Invalid patch file.');
      }
      const data = fromBase64(contents);
      if (!data?.length) throw new HostError('Invalid patch file.');
      total += data.length;
      if (data.length > MAX_FILE_BYTES || total > MAX_BACKUP_BYTES) throw new HostError('The patch files are too large.');
      files.set(path, data);
    }
    return files;
  }

  // Validates the patch ZIP the editor created, like the desktop hosts.
  function decodePatchZip(contents) {
    if (typeof contents !== 'string' || !contents || contents.length > MAX_BACKUP_BYTES * 2) {
      throw new HostError('The patch ZIP is empty or too large.');
    }
    const data = fromBase64(contents);
    if (!data || data.length < 22 || data.length > MAX_BACKUP_BYTES ||
        data[0] !== 0x50 || data[1] !== 0x4B || data[2] !== 0x03 || data[3] !== 0x04) {
      throw new HostError('The editor did not create a valid patch ZIP.');
    }
    return data;
  }

  // Keeps only the last path part; an empty or odd name gets a default.
  function fileName(name) {
    const base = String(name ?? '').split(/[/\\]/).pop();
    return /^[^\0-\x1F<>:"|?*]+\.zip$/i.test(base) && !base.startsWith('.') ? base : 'Ocarina-of-Time-Patch.zip';
  }

  if (typeof module === 'object' && module.exports) {
    module.exports = { backupLayout, readBackup, decodePatchFiles, decodePatchZip, fileName, probeFolder, CANDIDATES,
      SAVE_LAYOUTS, HostError };
    return;
  }

  const aborted = error => error?.name === 'AbortError';
  // Chromium-based browsers can open and write folders through handles; the
  // pickers start in the folder used last time (one memory per id).
  const folderAccess = typeof window.showDirectoryPicker === 'function';

  async function openBackupFromHandle() {
    let folder;
    try {
      folder = await window.showDirectoryPicker({ id: 'oot-sw2se-backup', mode: 'read' });
    } catch (error) {
      if (aborted(error)) return null;
      throw error;
    }
    const { paths, open } = await probeFolder(folder);
    return readBackup(folder.name, paths, open);
  }

  // Other browsers: a folder upload field. The files still stay in the browser.
  let folderInput;
  function openBackupFromInput() {
    return new Promise((resolve, reject) => {
      folderInput?.remove();
      const input = folderInput = document.createElement('input');
      input.type = 'file';
      input.webkitdirectory = true;
      input.hidden = true;
      input.addEventListener('cancel', () => { input.remove(); resolve(null); });
      input.addEventListener('change', () => {
        input.remove();
        const files = new Map();
        let root = '';
        for (const file of input.files) {
          const [first, ...rest] = file.webkitRelativePath.split('/');
          root = first;
          files.set(rest.join('/'), file);
        }
        readBackup(root, new Set(files.keys()), path => files.get(path)).then(resolve, reject);
      });
      document.body.append(input);
      input.click();
    });
  }

  function savePatch(message) {
    const data = decodePatchZip(message.contents);
    const name = fileName(message.name);
    const url = URL.createObjectURL(new Blob([data], { type: 'application/zip' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = name;
    link.hidden = true;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    return name;
  }

  async function saveFolder(message) {
    if (!folderAccess) {
      throw new HostError('This browser cannot write folders. Use Save Patch ZIP instead.');
    }
    const name = message.name;
    const files = decodePatchFiles(message.files, name);
    let parent;
    try {
      parent = await window.showDirectoryPicker({ id: 'oot-sw2se-export', mode: 'readwrite', startIn: 'downloads' });
    } catch (error) {
      if (aborted(error)) return null;
      throw error;
    }
    // Never write into a folder or over a file that is already there.
    try {
      await parent.getDirectoryHandle(name);
      throw new HostError(name + ' already exists.');
    } catch (error) {
      // TypeMismatchError: a file of that name is there.
      if (error.name === 'TypeMismatchError') throw new HostError(name + ' already exists.');
      if (error.name !== 'NotFoundError') throw error;
    }
    const destination = await parent.getDirectoryHandle(name, { create: true });
    try {
      for (const [path, data] of files) {
        const parts = path.split('/');
        let dir = destination;
        for (const part of parts.slice(0, -1)) dir = await dir.getDirectoryHandle(part, { create: true });
        const writable = await (await dir.getFileHandle(parts.at(-1), { create: true })).createWritable();
        await writable.write(data);
        await writable.close();
      }
    } catch (error) {
      // Leave nothing half-written behind.
      await parent.removeEntry(name, { recursive: true }).catch(() => {});
      throw error;
    }
    return parent.name + '/' + name;
  }

  const handlers = {
    openBackup: () => folderAccess ? openBackupFromHandle() : openBackupFromInput(),
    savePatch,
    saveFolder,
  };
  const listeners = new Set();
  const notify = data => {
    for (const listener of listeners) {
      try { listener({ data }); } catch (error) { console.error(error); }
    }
  };

  window.chrome = window.chrome || {};
  window.chrome.webview = {
    // Save Back is not offered: a page cannot replace the files it opened
    // in every browser, and exported patches never touch the originals.
    hostFeatures: {},
    postMessage(message) {
      // "workspace" resizes the native window on Windows and macOS. A browser
      // tab keeps its size, and the page lays itself out for any size.
      if (!message || message.action === 'workspace') return;
      const id = message.id;
      let reply;
      try {
        // Called right away, not after an await: file pickers need the click
        // that started the request.
        const handler = Object.hasOwn(handlers, message.action) ? handlers[message.action] : null;
        if (!handler) throw new HostError('Unknown request.');
        reply = Promise.resolve(handler(message));
      } catch (error) {
        reply = Promise.reject(error);
      }
      reply.then(result => notify({ id, result: result ?? null, error: null }),
        error => notify({ id, result: null, error: error?.message || String(error) }));
    },
    addEventListener(type, listener) {
      if (type === 'message') listeners.add(listener);
    },
    removeEventListener(type, listener) {
      if (type === 'message') listeners.delete(listener);
    },
  };

  if (!folderAccess) {
    // Only Save Patch ZIP works without folder access.
    document.addEventListener('DOMContentLoaded', () => {
      const button = document.getElementById('export-folder');
      if (button) button.hidden = true;
    });
  }
})();
