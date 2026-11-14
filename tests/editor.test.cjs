const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '../editor.html'), 'utf8');
const catalog = JSON.parse(html.match(/<script id="catalog" type="application\/json">(.*?)<\/script>/s)[1]);
const context = vm.createContext({ TextEncoder, TextDecoder, Blob, crypto: require('node:crypto').webcrypto,
  window: { chrome: { webview: { addEventListener() {}, postMessage() {} } } } });
vm.runInContext(html.match(/<script>\s*('use strict';.*?)<\/script>/s)[1], context);
const api = vm.runInContext('({readSlot, updateSlot, editOptions, removalIssue, acquisitionFlags, zip, exportLayout, saveTime, formatSaveTime, newestSlot, saveBackEntries, replaceOpenedFiles})', context);
const editable = api.editOptions(catalog);
const item = name => catalog.inventory.find(row => row[1] === name)[0];
const registration = hash => catalog.registrations.find(([stocks]) => stocks.includes(hash));

function save(headerEnd, fields) {
  const strings = fields.filter(([, type]) => ['String32', 'String64'].includes(catalog.types[type]));
  const bytes = new Uint8Array(headerEnd + strings.length * 64 + 4);
  const view = new DataView(bytes.buffer);
  view.setUint32(0, 0x01020304, true);
  view.setUint32(4, 0x002D80EB, true);
  view.setUint32(8, headerEnd, true);
  let body = headerEnd;
  fields.forEach(([hash, type], i) => {
    view.setUint32(40 + i * 8, hash, true);
    if (['String32', 'String64'].includes(catalog.types[type])) {
      view.setUint32(44 + i * 8, body, true);
      body += 64;
    }
  });
  return bytes;
}
function fixture(names = ['Item_Boomerang']) {
  const p = save(0x175D8, catalog.fields);
  const captionHashes = [0xA9557547, 0x1E55ECC5, 0x74BD05D0, 0x19F26B6A, 0x943F8EC3,
    0xBD46F485, 0xDFD840D3, 0x9811A3F7, 0x23F3D75E, 0x27853BF7, 0x25F03CAA, 0x63696A32, 0x5EE50BED];
  const c = save(0x2A0, captionHashes.map(h => [h, 2]));
  const cv = new DataView(c.buffer);
  for (const hash of [0x1E55ECC5, 0x74BD05D0]) cv.setInt32(44 + captionHashes.indexOf(hash) * 8, 12, true);
  cv.setUint32(44 + captionHashes.indexOf(0x63696A32) * 8, 0x2A0, true);
  const offsets = new Map(catalog.fields.map(([h], i) => [h, 44 + i * 8]));
  const view = new DataView(p.buffer);
  const set = (h, v) => view.setInt32(offsets.get(h), v, true);
  const string = (h, text) => {
    const o = view.getUint32(offsets.get(h), true);
    p.fill(0, o, o + 64); p.set(new TextEncoder().encode(text), o);
  };
  string(0x3E42AFFA, 'Item_Wallet_Small');
  set(0xE0010A50, 200); set(0x1D74617E, 1);
  for (const flag of registration(item('Item_Wallet_Small')).slice(1, 3)) set(flag, 1);
  set(0x31AB5580, 12); set(0xFBE01DA1, 12);
  for (const name of names) {
    const hash = item(name); set(hash, 1);
    for (const flag of registration(hash).slice(1, 3)) set(flag, 1);
  }
  return { p, c, set, string, slot: () => api.readSlot(p, c) };
}
function changes(slot, extra = {}) {
  return { wallet: slot.w.id, rupees: slot.rupees, vitals: slot.vitals,
    amounts: slot.counts, bottles: 0, additions: [], removals: [], clearAcquisitions: [], flags: [], ...extra };
}
function edit(f, extra) {
  const slot = f.slot();
  return api.readSlot(...api.updateSlot(slot, changes(slot, extra), editable));
}
function changedHashes(before, after) {
  return catalog.fields.filter(([h]) => before.int(h) !== after.int(h)).map(([h]) => h).sort((a,b) => a-b);
}

test('removal preserves acquisition history and changes only the selected stock', () => {
  const f = fixture(); const h = item('Item_Boomerang'); const before = f.slot();
  const after = edit(f, { removals: [h] });
  assert.equal(after.p.int(h), 0);
  for (const flag of registration(h).slice(1,3)) assert.equal(after.p.int(flag), 1);
  assert.deepEqual(changedHashes(before.p, after.p), [h]);
  assert.deepEqual(after.c.bytes, before.c.bytes);
  assert.equal(f.slot().p.int(h), 1, 'source backup stays intact');
});

test('optional reset clears exactly the two mapped flags and stays cleared after another export', () => {
  const f = fixture(); const h = item('Item_Boomerang'); const before = f.slot();
  const after = edit(f, { removals: [h], clearAcquisitions: [h] });
  assert.deepEqual(changedHashes(before.p, after.p), [h, ...registration(h).slice(1,3)].sort((a,b)=>a-b));
  for (const flag of registration(h).slice(1,3)) assert.equal(after.p.int(flag), 0);
  const again = api.readSlot(...api.updateSlot(after, changes(after), editable));
  assert.equal(again.p.int(h), 0);
  for (const flag of registration(h).slice(1,3)) assert.equal(again.p.int(flag), 0);
});

test('adding an item still registers acquisition flags', () => {
  const f = fixture([]); const h = item('Item_Boomerang');
  const after = edit(f, { additions: [h] });
  for (const value of [h, ...registration(h).slice(1,3)]) assert.equal(after.p.int(value), 1);
});

test('reject flag-only resets, contradictory progress edits, and add/remove conflicts', () => {
  const f = fixture(); const h = item('Item_Boomerang'); const flag = registration(h)[1];
  assert.throws(() => edit(f, { clearAcquisitions: [h] }), /requires removing/);
  assert.throws(() => edit(f, { removals: [h], clearAcquisitions: [h], flags: [[flag, true]] }), /conflicts/);
  assert.throws(() => edit(f, { removals: [h], additions: [h] }), /cannot be added/);
});

test('reject removal of equipped weapons in either era and default clothes', () => {
  const h = item('Weapon_Sword_Kokiri');
  for (const field of [0xA95A3521, 0xA1F7EE2B]) {
    const f = fixture(['Weapon_Sword_Kokiri']); f.string(field, 'Weapon_Sword_Kokiri');
    assert.throws(() => edit(f, { removals: [h] }), /Unequip/);
  }
  const f = fixture(['Armor_Adult_Normal']);
  assert.throws(() => edit(f, { removals: [item('Armor_Adult_Normal')] }), /supported/);
});

test('reject unsupported stocks, non-boolean acquisition flags and shared flags still in use', () => {
  const f = fixture(); const h = item('Item_Boomerang'); const flag = registration(h)[1];
  assert.throws(() => edit(f, { removals: [item('Item_Wallet_Small')] }), /supported/);
  f.set(flag, 2);
  assert.throws(() => edit(f, { removals: [h], clearAcquisitions: [h] }), /safely/);
  const g = fixture(['Item_Boomerang', 'Item_Hammer']); const slot = g.slot();
  const shared = { ...editable, registrations: [...catalog.registrations, [[item('Item_Hammer')], flag, 0, 'Shared test']] };
  assert.throws(() => api.updateSlot(slot, changes(slot, {removals:[h], clearAcquisitions:[h]}), shared), /shared/);
});

test('ZIP and folder layout use one UTC timestamp before the UUID and instead of files', async () => {
  const uuid = '12345678-1234-4234-8234-123456789abc';
  const date = new Date('2026-11-09T17:42:16+08:00');
  const generated = api.exportLayout({id:'slot_00'}, [], date);
  assert.match(generated.name, /Patch-20261109_094216_[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/);
  for (const active of [{ id: 'slot_00' }, { id: 'loose', loose: true }]) {
    const prefix = active.loose ? '' : 'slot_00/';
    const edits = ['progress.sav', 'caption.sav', 'option.sav'].map(path => ({path: path === 'option.sav' ? path : prefix + path, after: new Uint8Array([1,2,3])}));
    const layout = api.exportLayout(active, edits, date, uuid);
    assert.equal(layout.name, `Ocarina-of-Time-${active.loose ? 'Save' : 'slot_00'}-Patch-20261109_094216_${uuid}`);
    layout.entries.push(['manifest.json', '{}']);
    const expected = edits.map(({path}) => '20261109_094216/' + path).concat('manifest.json');
    assert.deepEqual(Array.from(layout.entries, ([path]) => path), expected);
    const bytes = Buffer.from(await api.zip(layout.entries).arrayBuffer());
    const names = [];
    for (let offset = 0; bytes.readUInt32LE(offset) === 0x04034b50;) {
      const size = bytes.readUInt32LE(offset + 18);
      const length = bytes.readUInt16LE(offset + 26);
      const extra = bytes.readUInt16LE(offset + 28);
      names.push(bytes.toString('utf8', offset + 30, offset + 30 + length));
      offset += 30 + length + extra + size;
    }
    assert.deepEqual(names, expected);
  }
});

// Tests for the save time and Save Back additions by aut0mat3d/Claude (2026),
// vibe-coded with Claude (Anthropic); MIT License.

// Writes an in-game save time into a fixture's caption.sav.
function setSaveTime(f, [year, month, day, hour, minute, second], auto = 1) {
  const view = new DataView(f.c.buffer);
  const offsets = new Map();
  for (let o = 40; o < 0x2A0; o += 8) offsets.set(view.getUint32(o, true), o + 4);
  const values = [[0x9811A3F7, year], [0xDFD840D3, month], [0xBD46F485, day],
    [0x23F3D75E, hour], [0x27853BF7, minute], [0x5EE50BED, second], [0x25F03CAA, auto]];
  for (const [hash, value] of values) view.setInt32(offsets.get(hash), value, true);
}

test('save time is read from caption.sav to the second and shown as day.month.year', () => {
  const f = fixture(); setSaveTime(f, [2026, 11, 13, 0, 12, 41], 0);
  const time = api.saveTime(f.slot().c);
  assert.equal(time.valid, true);
  assert.equal(api.formatSaveTime(time), '13.11.2026 · 00:12:41 · manual save');
  assert.equal(api.saveTime(fixture().slot().c).valid, false, 'an all-zero caption has no valid time');
  setSaveTime(f, [2026, 11, 13, 0, 12, 60]);
  assert.equal(api.saveTime(f.slot().c).valid, false, 'seconds out of range');
});

test('a caption without the seconds field counts as second 0', () => {
  const f = fixture(); setSaveTime(f, [2026, 11, 13, 0, 12, 41]);
  const c = f.slot().c;
  c.fields.delete(0x5EE50BED);
  const time = api.saveTime(c);
  assert.equal(time.valid, true);
  assert.equal(time.second, 0);
});

test('the newest slot is chosen by in-game save time; ties keep the lower slot', () => {
  const at = (id, year, month, day, hour, minute, second) =>
    ({ id, time: { year, month, day, hour, minute, second, valid: true } });
  // Save times of a real backup: slot_00 and slot_02 share a minute.
  const slots = [at('slot_00', 2026, 11, 12, 23, 21, 25), at('slot_01', 2026, 11, 12, 23, 7, 15),
    at('slot_02', 2026, 11, 12, 23, 21, 55), { id: 'slot_03', time: null }, at('slot_05', 2026, 11, 13, 0, 12, 41)];
  assert.equal(api.newestSlot(slots).id, 'slot_05');
  assert.equal(api.newestSlot(slots.slice(0, 4)).id, 'slot_02', 'seconds decide within a minute');
  assert.equal(api.newestSlot([at('slot_00', 2026, 11, 12, 23, 21, 25), at('slot_01', 2026, 11, 12, 23, 21, 25)]).id,
    'slot_00', 'same second: lower slot');
  assert.equal(api.newestSlot([{ id: 'slot_04', time: null }]).id, 'slot_04');
  // Month before day: 03.11 is newer than 11.03.
  assert.equal(api.newestSlot([at('slot_00', 2026, 3, 11, 9, 0, 0), at('slot_01', 2026, 11, 3, 9, 0, 0)]).id, 'slot_01');
});

test('ZIP entries carry the save time, or the current time when the save has none', async () => {
  const entryTimes = async (...args) => {
    const bytes = Buffer.from(await api.zip([['a.sav', new Uint8Array([1])], ['b.sav', new Uint8Array([2])]], ...args).arrayBuffer());
    const local = [bytes.readUInt16LE(10), bytes.readUInt16LE(12)];
    const central = bytes.indexOf(Buffer.from([0x50, 0x4B, 0x01, 0x02]));
    assert.deepEqual([bytes.readUInt16LE(central + 12), bytes.readUInt16LE(central + 14)], local);
    const [time, date] = local;
    return [(date >> 9) + 1980, (date >> 5) & 15, date & 31, time >> 11, (time >> 5) & 63, (time & 31) * 2];
  };
  const f = fixture(); setSaveTime(f, [2026, 11, 13, 0, 12, 44]);
  assert.deepEqual(await entryTimes(api.saveTime(f.slot().c)), [2026, 11, 13, 0, 12, 44]);
  setSaveTime(f, [2026, 11, 13, 0, 12, 41]);
  assert.deepEqual(await entryTimes(api.saveTime(f.slot().c)), [2026, 11, 13, 0, 12, 40], 'MS-DOS time has 2 s steps');
  const now = new Date(2026, 10, 14, 15, 30, 17);
  assert.deepEqual(await entryTimes(api.saveTime(fixture().slot().c), now), [2026, 11, 14, 15, 30, 16]);
});

test('Save Back pairs each edited file with the opened file it replaces', async () => {
  const opened = path => ({ webkitRelativePath: path, arrayBuffer: async () => new ArrayBuffer(0) });
  const active = { id: 'slot_05', progress: opened('Backup/files/slot_05/progress.sav'),
    caption: opened('Backup/files/slot_05/caption.sav') };
  const backup = { slots: [active, { id: 'slot_00', progress: opened('Backup/files/slot_00/progress.sav'),
    caption: opened('Backup/files/slot_00/caption.sav') }],
    option: opened('Backup/files/option.sav'), manifest: opened('Backup/manifest.json') };
  const bytes = n => new Uint8Array([n]);
  const edits = [{ path: 'slot_05/progress.sav', after: bytes(1) }, { path: 'slot_05/caption.sav', after: bytes(2) },
    { path: 'option.sav', after: bytes(3) }];
  const entries = api.saveBackEntries(active, backup, edits, bytes(4));
  assert.deepEqual(entries.map(([path]) => path), ['Backup/files/slot_05/progress.sav',
    'Backup/files/slot_05/caption.sav', 'Backup/files/option.sav', 'Backup/manifest.json']);
  // Loose saves use their own paths.
  const loose = { id: 'My Save', loose: true, progress: opened('My Save/progress.sav'), caption: opened('My Save/caption.sav') };
  assert.deepEqual(api.saveBackEntries(loose, { slots: [loose] }, [{ path: 'progress.sav', after: bytes(1) }])
    .map(([path]) => path), ['My Save/progress.sav']);
  assert.throws(() => api.saveBackEntries(loose, { slots: [loose] }, [{ path: 'option.sav', after: bytes(1) }]),
    /No opened file/);

  api.replaceOpenedFiles(backup, entries);
  assert.deepEqual([...new Uint8Array(await active.progress.arrayBuffer())], [1], 'the written bytes are the new state');
  assert.deepEqual([...new Uint8Array(await backup.option.arrayBuffer())], [3]);
  assert.equal(backup.slots[1].progress.webkitRelativePath, 'Backup/files/slot_00/progress.sav');
  assert.deepEqual([...new Uint8Array(await backup.slots[1].progress.arrayBuffer())], [], 'other slots are untouched');
});

test('swim depth writes the float a save already carries, and leaves it alone when not given', () => {
  const f = fixture();
  const depth = catalog.fields.find(([, , name]) => name === 'PlayerStatus.DiveDepth')[0];
  f.set(depth, 0x40C00000);                       // 6.0f, the Silver Scale value
  const before = f.slot();
  const after = edit(f, { swimDepth: 9 });
  assert.equal(after.p.view.getFloat32(after.p.at(depth), true), 9);
  assert.deepEqual(changedHashes(before.p, after.p), [depth]);
  const untouched = edit(f, {});
  assert.equal(untouched.p.view.getFloat32(untouched.p.at(depth), true), 6);
  assert.throws(() => edit(f, { swimDepth: 41 }), /between 0 and 40/);
  assert.throws(() => edit(f, { swimDepth: Number.NaN }), /between 0 and 40/);
});

module.exports = { fixture };
