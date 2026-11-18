const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const { execFileSync } = require('node:child_process');
const host = require('../web/browser-host.js');

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'editor.html'), 'utf8');
const context = vm.createContext({ TextEncoder, TextDecoder, Blob, crypto: require('node:crypto').webcrypto,
  window: { chrome: { webview: { addEventListener() {}, postMessage() {} } } } });
vm.runInContext(html.match(/<script>\s*('use strict';.*?)<\/script>/s)[1], context);
const editor = vm.runInContext('({ findBackupFiles, exportLayout, zip })', context);

const layout = (name, files) => host.backupLayout(name, new Set(files));
// What the editor makes of the paths the host sends.
const opened = entries => editor.findBackupFiles(entries.map(([relativePath]) => ({ webkitRelativePath: relativePath })));
const pair = folder => [folder + 'progress.sav', folder + 'caption.sav'];

test('a full backup sends every slot, option.sav and manifest.json under the desktop hosts\' paths', () => {
  const entries = layout('MyBackup', ['manifest.json', 'files/option.sav', 'files/account.sav', ...pair('files/slot_00/'),
    ...pair('files/slot_03/'), 'files/slot_04/progress.sav', 'files/unrelated.txt']);
  assert.deepEqual(entries, [
    ['Backup/files/slot_00/progress.sav', 'files/slot_00/progress.sav'],
    ['Backup/files/slot_00/caption.sav', 'files/slot_00/caption.sav'],
    ['Backup/files/slot_03/progress.sav', 'files/slot_03/progress.sav'],
    ['Backup/files/slot_03/caption.sav', 'files/slot_03/caption.sav'],
    ['Backup/files/option.sav', 'files/option.sav'],
    ['Backup/files/account.sav', 'files/account.sav'],
    ['Backup/manifest.json', 'manifest.json'],
  ]);
  const backup = opened(entries);
  assert.deepEqual(Array.from(backup.slots, slot => slot.id), ['slot_00', 'slot_03']);
  assert.ok(backup.option && backup.manifest);
});

test('slots directly in the picked folder, or the picked "files" folder, are read too', () => {
  const direct = layout('Backup', [...pair('slot_01/'), 'option.sav', 'manifest.json']);
  assert.deepEqual(direct.map(([to]) => to), ['Backup/files/slot_01/progress.sav', 'Backup/files/slot_01/caption.sav',
    'Backup/files/option.sav', 'Backup/manifest.json']);
  // The backup root around a picked "files" folder can't be read.
  const files = layout('Files', [...pair('slot_02/'), 'option.sav', 'manifest.json']);
  assert.deepEqual(files.map(([to]) => to), ['Backup/files/slot_02/progress.sav', 'Backup/files/slot_02/caption.sav',
    'Backup/files/option.sav']);
  // An empty or unrelated "files" folder doesn't hide slots at the root.
  assert.equal(layout('Backup', [...pair('slot_00/'), 'files/readme.txt'])[0][1], 'slot_00/progress.sav');
});

test('a picked slot folder or loose save opens as one save', () => {
  const slot = layout('SLOT_05', pair(''));
  assert.deepEqual(slot.map(([to]) => to), ['Backup/files/slot_05/progress.sav', 'Backup/files/slot_05/caption.sav']);
  assert.deepEqual(Array.from(opened(slot).slots, s => s.id), ['slot_05']);
  const loose = layout('My Save', [...pair(''), 'option.sav']);
  assert.deepEqual(loose.map(([to]) => to), ['My Save/progress.sav', 'My Save/caption.sav', 'My Save/option.sav']);
  const looseBackup = opened(loose);
  assert.ok(looseBackup.slots[0].loose && looseBackup.option);
  assert.equal(layout(' ', pair(''))[0][0], 'Save/progress.sav');
});

test('a PC port\'s game or data folder opens the save folder of the profile it uses', () => {
  const user = '5a3c9e1f0b7d24680000000000000001';
  const profile = base => [...pair(base + 'slot_00/'), ...pair(base + 'slot_03/'), base + 'option.sav', base + 'account.sav'];
  const expected = ['Backup/files/slot_00/progress.sav', 'Backup/files/slot_00/caption.sav',
    'Backup/files/slot_03/progress.sav', 'Backup/files/slot_03/caption.sav', 'Backup/files/option.sav', 'Backup/files/account.sav'];
  const cases = [
    ['longshot', [...profile('save/' + user + '/'), 'cache/0/x.bin']],          // Longshot's data folder
    ['save', profile(user + '/')],                                              // its save folder
    [user, profile('')],                                                        // the profile folder itself
    ['ReLink', [...profile('user/save/' + user + '/'), 'image.bin', 'romfs/a']], // Project ReLink's game folder
    ['user', profile('save/' + user + '/')],                                    // its user folder
  ];
  for (const [name, files] of cases) {
    const entries = layout(name, files);
    assert.deepEqual(entries.map(([to]) => to), expected, name);
    assert.equal(opened(entries).slots.length, 2, name);
  }
  // Several profiles: the one the ports open, else a list to pick from.
  const stray = '0123456789abcdef0123456789abcdef';
  assert.equal(layout('save', [...profile(stray + '/'), ...profile(user + '/')])[0][1], user + '/slot_00/progress.sav');
  assert.equal(layout('save', profile(stray + '/'))[0][1], stray + '/slot_00/progress.sav');
  assert.throws(() => layout('save', [...profile(stray + '/'), ...profile('fedcba9876543210fedcba9876543210/')]),
    /several profiles\. Open one of them: 0123456789abcdef0123456789abcdef, fedcba9876543210fedcba9876543210\./);
  // Saves in the picked folder itself keep the old rules.
  assert.equal(layout('Backup', [...pair('files/slot_01/'), ...profile('save/' + user + '/')])[0][0],
    'Backup/files/slot_01/progress.sav');
});

// A folder tree as the File System Access API shows it, built from a file list.
function fakeFolder(name, files) {
  const dir = (path) => ({
    kind: 'directory', name: path.split('/').filter(Boolean).at(-1) ?? name,
    async getDirectoryHandle(child) {
      if (!files.some(file => file.startsWith(path + child + '/'))) throw Object.assign(new Error('missing'), { name: 'NotFoundError' });
      return dir(path + child + '/');
    },
    async getFileHandle(child) {
      if (!files.includes(path + child)) throw Object.assign(new Error('missing'), { name: 'NotFoundError' });
      return { kind: 'file', getFile: async () => ({ size: 1, arrayBuffer: async () => new Uint8Array([7]).buffer }) };
    },
    async *entries() {
      const names = new Set(files.filter(file => file.startsWith(path)).map(file => file.slice(path.length).split('/')));
      for (const parts of names) yield [parts[0], parts.length > 1 ? dir(path + parts[0] + '/') : await this.getFileHandle(parts[0])];
    },
  });
  return dir('');
}

test('Switch emulators: Lichii, Fritchii and Eden save folders open from any folder on the way', async () => {
  const profile = 'E571F9CCBF8984318D5EE33D0A8D0868';
  const save = base => [...pair(base + 'slot_00/'), ...pair(base + 'slot_03/'), base + 'option.sav', base + 'account.sav'];
  const expected = ['Backup/files/slot_00/progress.sav', 'Backup/files/slot_00/caption.sav',
    'Backup/files/slot_03/progress.sav', 'Backup/files/slot_03/caption.sav', 'Backup/files/option.sav', 'Backup/files/account.sav'];
  const lichii = [...save(`nand/user/save/0000000000000000/${profile}/0400486024DEC000/`),
    `nand/user/save/0000000000000000/${profile}/0400C3F00006E000/Play/account.sav`, 'nand/system/save/8000000000000010/x'];
  const cases = [
    ['lichii', lichii], ['nand', lichii.map(file => file.slice('nand/'.length))],
    [profile, save('0400486024DEC000/')],
    ['eden', save('nand/user/save/account/0123/0400486024DEC000/0/')],
    ['Fritchii', [...save('user/nand/user/save/0000000000000000/AB12/0400486024DEC000/'), 'fritchii.exe']],
    ['longshot', [...save('save/5a3c9e1f0b7d24680000000000000001/'), 'cache/0/x']],
    ['ReLink', [...save('user/save/5a3c9e1f0b7d24680000000000000001/'), 'image.bin']],
  ];
  for (const [name, files] of cases) {
    // Folder upload field: every file is listed.
    assert.deepEqual(layout(name, files).map(([to]) => to), expected, name + ' (file list)');
    // Folder handles: only the files the layouts lead to are looked up.
    const { paths, open } = await host.probeFolder(fakeFolder(name, files));
    assert.deepEqual(host.backupLayout(name, paths).map(([to]) => to), expected, name + ' (folder handles)');
    assert.equal((await host.readBackup(name, paths, open)).length, 6);
  }
  const two = [...save('nand/user/save/0000000000000000/AAAA/0400486024DEC000/'), ...save('nand/user/save/0000000000000000/BBBB/0400486024DEC000/')];
  assert.throws(() => layout('lichii', two), /several profiles\. Open one of them: AAAA, BBBB\./);
});

test('folders without a complete save are refused', () => {
  for (const files of [[], ['progress.sav'], ['files/slot_00/progress.sav'], ['slot_06/progress.sav', 'slot_06/caption.sav']]) {
    assert.throws(() => layout('Backup', files), /No folder containing progress\.sav and caption\.sav/);
  }
  // Only these paths are ever looked up in a picked folder.
  for (const name of ['MyBackup', 'Files', 'slot_00']) {
    const all = new Set(host.CANDIDATES);
    for (const [, from] of layout(name, all)) assert.ok(host.CANDIDATES.includes(from), from);
  }
});

test('reading enforces the desktop hosts\' size limits and sends base64 contents', async () => {
  const file = bytes => ({ size: bytes.length, arrayBuffer: async () => bytes.buffer });
  const small = new Uint8Array([1, 2, 3]);
  const files = await host.readBackup('slot_00', new Set(pair('')), () => file(small));
  assert.deepEqual(files.map(f => [f.relativePath, f.contents]),
    [['Backup/files/slot_00/progress.sav', 'AQID'], ['Backup/files/slot_00/caption.sav', 'AQID']]);
  const big = new Uint8Array(2 * 1024 * 1024 + 1);
  await assert.rejects(host.readBackup('slot_00', new Set(pair('')), () => file(big)), /exceed the expected size/);
  const unreadable = { size: 3, arrayBuffer: async () => { throw new Error('NotReadableError'); } };
  await assert.rejects(host.readBackup('slot_00', new Set(pair('')), () => unreadable), /could not be read/);
});

test('folder exports accept exactly what the editor creates', () => {
  const edits = [{ path: 'slot_02/progress.sav', after: new Uint8Array([1]) },
    { path: 'slot_02/caption.sav', after: new Uint8Array([2]) }];
  const { name, entries } = editor.exportLayout({ id: 'slot_02' }, edits, new Date(Date.UTC(2026, 10, 9, 9, 42, 16)),
    '01234567-89ab-cdef-0123-456789abcdef');
  const files = entries.map(([relativePath, bytes]) => ({ relativePath, contents: Buffer.from(bytes).toString('base64') }));
  files.push({ relativePath: 'manifest.json', contents: Buffer.from('{}').toString('base64') });
  const decoded = host.decodePatchFiles(files, name);
  assert.deepEqual([...decoded.keys()], ['20261109_094216/slot_02/progress.sav', '20261109_094216/slot_02/caption.sav',
    'manifest.json']);

  const bad = (relativePath, contents = 'AQ==') => [{ relativePath, contents }, files[1]];
  for (const entry of [bad('../slot_02/progress.sav'), bad('20261109_094216/../slot_02/progress.sav'),
    bad('20261109_094216/slot_02/other.sav'), bad('/20261109_094216/slot_02/progress.sav'),
    bad('20260101_000000/slot_02/progress.sav'), bad('20261109_094216/slot_02/progress.sav', ''),
    bad('20261109_094216/slot_02/progress.sav', 'not base64!'), [files[1], files[1]]]) {
    assert.throws(() => host.decodePatchFiles(entry, name), /Invalid patch file/);
  }
  assert.throws(() => host.decodePatchFiles(files, 'Ocarina-of-Time-slot_02-Patch'), /Invalid patch folder name/);
  assert.throws(() => host.decodePatchFiles(files.slice(0, 1), name), /Invalid patch file list/);
  // 2 MiB per file, 8 MiB in all, like the desktop hosts.
  const sized = bytes => Buffer.alloc(bytes).toString('base64');
  assert.equal(host.decodePatchFiles([{ ...files[0], contents: sized(2 * 1024 * 1024) }, files[1]], name).size, 2);
  assert.throws(() => host.decodePatchFiles([{ ...files[0], contents: sized(2 * 1024 * 1024 + 3) }, files[1]], name),
    /too large/);
});

test('patch ZIPs are checked before they are offered as a download', async () => {
  const blob = editor.zip([['20261109_094216/progress.sav', new Uint8Array([1, 2])]]);
  const contents = Buffer.from(await blob.arrayBuffer()).toString('base64');
  assert.equal(host.decodePatchZip(contents).length, blob.size);
  for (const contents of ['', 'AQID', 'not base64!', Buffer.alloc(30).toString('base64')]) {
    assert.throws(() => host.decodePatchZip(contents), /patch ZIP/);
  }
  assert.equal(host.fileName('Ocarina-of-Time-slot_00-Patch-x.zip'), 'Ocarina-of-Time-slot_00-Patch-x.zip');
  assert.equal(host.fileName('../../evil/name.zip'), 'name.zip');
  for (const name of ['', '.zip', 'patch.exe', undefined]) assert.equal(host.fileName(name), 'Ocarina-of-Time-Patch.zip');
});

test('the build adds the browser host in front of the unchanged editor', async () => {
  const { buildPage, editorVersion } = await import('../web/build.mjs');
  const version = editorVersion(fs.readFileSync(path.join(root, 'Program.cs'), 'utf8'));
  assert.match(version, /^[0-9]+\.[0-9]+\.[0-9]+$/);
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'oot-sw2se-web-'));
  try {
    execFileSync(process.execPath, [path.join(root, 'web/build.mjs'), '--out', out], { stdio: 'pipe' });
    assert.deepEqual(fs.readdirSync(out).sort(), ['LICENSE.txt', 'favicon.ico', 'index.html']);
    const page = fs.readFileSync(path.join(out, 'index.html'), 'utf8');
    assert.equal(page, buildPage(html, fs.readFileSync(path.join(root, 'web/browser-host.js'), 'utf8'), version));
    assert.ok(page.includes('v' + version + '</span>') && !page.includes('{{EDITOR_VERSION}}'));
    // Same policy, host script first, then the editor; nothing else changed.
    const csp = html.match(/<meta http-equiv="Content-Security-Policy"[^>]*>/)[0];
    assert.ok(page.includes(csp));
    assert.ok(page.indexOf('window.chrome.webview = {') < page.indexOf("const desktop = (() => {"));
    const hostScript = '\n<script>' + fs.readFileSync(path.join(root, 'web/browser-host.js'), 'utf8') + '</script>';
    assert.equal(page, html.replace(csp, () => csp + hostScript).replaceAll('{{EDITOR_VERSION}}', version));
  } finally {
    fs.rmSync(out, { recursive: true, force: true });
  }
  assert.throws(() => buildPage(html.replace(/<meta http-equiv="Content-Security-Policy"[^>]*>/, ''), '', '1.0.0'),
    /Content-Security-Policy/);
  assert.throws(() => buildPage(html, '</script>', '1.0.0'), /must not close/);
});
