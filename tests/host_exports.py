"""Exercise the actual C# and Swift export helpers without native file dialogs."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='oot-export-tests-') as temp:
    work = Path(temp)
    swift = (root / 'macos/OOTSW2SE.swift').read_text()
    helper = swift.split('enum PatchFolderWriter {', 1)[1].split('// MARK: - Editor window', 1)[0]
    source = '''import Foundation
struct HostError: LocalizedError { let message: String; init(_ message: String) { self.message = message }; var errorDescription: String? { message } }
enum HostLimits { static let maxFileBytes = 2 * 1024 * 1024; static let maxBackupBytes = 8 * 1024 * 1024 }
enum PatchFolderWriter {''' + helper + r'''
let parent = URL(fileURLWithPath: CommandLine.arguments[1])
let bytes = Data([0, 1, 2, 255])
let name = "Ocarina-of-Time-slot_00-Patch-20261109_094216_11111111-1111-4111-8111-111111111111"
let otherName = name.replacingOccurrences(of: "11111111-1111", with: "22222222-2222")
let paths = ["20261109_094216/slot_00/progress.sav", "20261109_094216/slot_00/caption.sav", "20261109_094216/option.sav", "manifest.json"]
let entries = paths.map { ["relativePath": $0, "contents": bytes.base64EncodedString()] }
let files = try PatchFolderWriter.decode(entries, name: name)
let first = try PatchFolderWriter.write(parent: parent, files: files, name: name)
let second = try PatchFolderWriter.write(parent: parent, files: files, name: otherName)
precondition(first.lastPathComponent == name && second.lastPathComponent == otherName)
do { _ = try PatchFolderWriter.write(parent: parent, files: files, name: name); fatalError("Overwrote destination") } catch {}
for bad in ["../escape", name + "/child", name + "\n"] {
    do { _ = try PatchFolderWriter.decode(entries, name: bad); fatalError("Accepted invalid name") } catch {}
}
for folder in [first, second] { for path in paths { precondition(try Data(contentsOf: folder.appendingPathComponent(path)) == bytes) } }
for bad in ["../progress.sav", "/progress.sav", "files/../../caption.sav", "files\\progress.sav", "20261109_094216/slot_06/progress.sav", "20261109_094217/progress.sav", "progress.sav\n"] {
    do { _ = try PatchFolderWriter.decode([["relativePath": bad, "contents": "AQ=="], entries[1]], name: name); fatalError("Accepted invalid path") }
    catch {}
}
do { _ = try PatchFolderWriter.decode([entries[0], entries[0]], name: name); fatalError("Accepted duplicate") } catch {}
do { _ = try PatchFolderWriter.decode([["relativePath":"20261109_094216/progress.sav", "contents":Data(repeating: 1, count: HostLimits.maxFileBytes + 1).base64EncodedString()], entries[1]], name: name); fatalError("Accepted oversized file") } catch {}
print("PASS Swift: nested export bytes, unique destinations, invalid paths, duplicates and size limits")
'''
    # A throwing expression cannot be evaluated inside precondition's autoclosure.
    source = source.replace('precondition(try Data(contentsOf: folder.appendingPathComponent(path)) == bytes)', 'let actual = try Data(contentsOf: folder.appendingPathComponent(path)); precondition(actual == bytes)')
    (work / 'main.swift').write_text(source)
    subprocess.run(['swiftc', '-swift-version', '6', '-module-cache-path', str(work / 'cache'), str(work / 'main.swift'), '-o', str(work / 'swift-test')], check=True)
    (work / 'swift-output').mkdir()
    subprocess.run([str(work / 'swift-test'), str(work / 'swift-output')], check=True)

    cs = (root / 'Program.cs').read_text()
    helper = cs.split('internal static class PatchFolderWriter', 1)[1].split('internal static class FolderPicker', 1)[0]
    source = '''using System; using System.IO; using System.Collections.Generic;
internal static class PatchFolderWriter''' + helper + r'''
class Test {
  static void Main(string[] args) {
    var bytes = new byte[] {0,1,2,255};
    var name = "Ocarina-of-Time-slot_00-Patch-20261109_094216_11111111-1111-4111-8111-111111111111";
    var otherName = name.Replace("11111111-1111", "22222222-2222");
    var paths = new[] {"20261109_094216/slot_00/progress.sav", "20261109_094216/slot_00/caption.sav", "20261109_094216/option.sav", "manifest.json"};
    var entries = Array.ConvertAll(paths, p => new PatchFolderWriter.Entry { relativePath=p, contents=Convert.ToBase64String(bytes) });
    var files = PatchFolderWriter.Decode(entries, name);
    var first = PatchFolderWriter.Write(args[0], files, name);
    var second = PatchFolderWriter.Write(args[0], files, otherName);
    if (Path.GetFileName(first) != name || Path.GetFileName(second) != otherName) throw new Exception("Incorrect name");
    bool overwritten = true;
    try { PatchFolderWriter.Write(args[0], files, name); } catch (IOException) { overwritten=false; }
    if (overwritten) throw new Exception("Overwrote destination");
    foreach (var badName in new[] {"../escape", name + "/child", name + "\n"}) {
      try { PatchFolderWriter.Decode(entries, badName); } catch (IOException) { continue; }
      throw new Exception("Accepted invalid name");
    }
    foreach (var folder in new[] {first,second}) foreach (var path in paths)
      if (Convert.ToBase64String(File.ReadAllBytes(Path.Combine(folder,path))) != Convert.ToBase64String(bytes)) throw new Exception("Bytes differ");
    foreach (var bad in new[] {"../progress.sav", "/progress.sav", "files/../../caption.sav", "files\\progress.sav", "20261109_094216/slot_06/progress.sav", "20261109_094217/progress.sav", "progress.sav\n"}) {
      try { PatchFolderWriter.Decode(new[] {new PatchFolderWriter.Entry { relativePath=bad, contents="AQ==" }, entries[1]}, name); }
      catch (IOException) { continue; }
      throw new Exception("Accepted invalid path");
    }
    bool rejected = false;
    try { PatchFolderWriter.Decode(new[] {entries[0],entries[0]}, name); } catch (IOException) { rejected=true; }
    if (!rejected) throw new Exception("Accepted duplicate");
    rejected = false;
    try { PatchFolderWriter.Decode(new[] {new PatchFolderWriter.Entry { relativePath="20261109_094216/progress.sav", contents=Convert.ToBase64String(new byte[2*1024*1024+1]) }, entries[1]}, name); } catch (IOException) { rejected=true; }
    if (!rejected) throw new Exception("Accepted oversized file");
    Console.WriteLine("PASS C#: nested export bytes, unique destinations, invalid paths, duplicates and size limits");
  }
}
'''
    (work / 'Test.cs').write_text(source)
    subprocess.run(['mcs', '-out:' + str(work / 'cs-test.exe'), str(work / 'Test.cs')], check=True)
    (work / 'cs-output').mkdir()
    subprocess.run(['mono', str(work / 'cs-test.exe'), str(work / 'cs-output')], check=True)

    # PortSaves: the save folder of a PC port (Longshot, Project ReLink) inside a picked game or data folder.
    def save_slot(folder):
        folder.mkdir(parents=True, exist_ok=True)
        for name in ('progress.sav', 'caption.sav'):
            (folder / name).write_bytes(b'save')

    game_user = '5a3c9e1f0b7d24680000000000000001'
    several = 'several profiles. Open one of them: 0123456789abcdef0123456789abcdef, fedcba9876543210fedcba9876543210.'
    ports = work / 'ports'
    save_slot(ports / 'longshot/save' / game_user / 'slot_00')
    (ports / 'longshot/cache/0').mkdir(parents=True)
    save_slot(ports / 'ReLink/user/save' / game_user / 'slot_03')
    (ports / 'ReLink/romfs').mkdir(parents=True)
    save_slot(ports / 'several/save/0123456789abcdef0123456789abcdef/slot_00')
    save_slot(ports / 'several/save' / game_user / 'slot_01')
    save_slot(ports / 'stray/save/0123456789abcdef0123456789abcdef/slot_00')
    save_slot(ports / 'stray/save/fedcba9876543210fedcba9876543210/slot_00')
    save_slot(ports / 'Backup/files/slot_00')
    save_slot(ports / 'Backup/save' / game_user / 'slot_00')
    (ports / 'empty').mkdir()
    # Switch emulators: Lichii's data folder, Eden's newer account layout, Fritchii installed portable.
    save_slot(ports / 'lichii/nand/user/save/0000000000000000/E571F9CC/0400486024DEC000/slot_02')
    (ports / 'lichii/nand/user/save/0000000000000000/E571F9CC/0400C3F00006E000/Play').mkdir(parents=True)
    save_slot(ports / 'eden/nand/user/save/account/0123/0400486024DEC000/0/slot_00')
    save_slot(ports / 'Fritchii/user/nand/user/save/0000000000000000/AB12/0400486024DEC000/slot_01')
    save_slot(ports / 'twousers/nand/user/save/0000000000000000/0123456789abcdef0123456789abcdef/0400486024DEC000/slot_00')
    save_slot(ports / 'twousers/nand/user/save/0000000000000000/fedcba9876543210fedcba9876543210/0400486024DEC000/slot_00')
    # Picked folder, and the profile folder expected (relative to ports), "none", or "several" for the error.
    cases = [('longshot', 'longshot/save/' + game_user), ('longshot/save', 'longshot/save/' + game_user),
             ('longshot/save/' + game_user, 'none'), ('ReLink', 'ReLink/user/save/' + game_user),
             ('ReLink/user', 'ReLink/user/save/' + game_user), ('several', 'several/save/' + game_user),
             ('stray', 'several'), ('Backup', 'none'), ('empty', 'none'),
             ('lichii', 'lichii/nand/user/save/0000000000000000/E571F9CC/0400486024DEC000'),
             ('lichii/nand', 'lichii/nand/user/save/0000000000000000/E571F9CC/0400486024DEC000'),
             ('lichii/nand/user/save/0000000000000000/E571F9CC', 'lichii/nand/user/save/0000000000000000/E571F9CC/0400486024DEC000'),
             ('eden', 'eden/nand/user/save/account/0123/0400486024DEC000/0'),
             ('Fritchii', 'Fritchii/user/nand/user/save/0000000000000000/AB12/0400486024DEC000'),
             ('twousers', 'several')]
    expected = ''.join(picked + ' -> ' + result + '\n' for picked, result in cases)
    picked = [case[0] for case in cases]

    helper = swift.split('enum PortSaves {', 1)[1].split('enum BackupReader {', 1)[0]
    source = '''import Foundation
struct HostError: LocalizedError { let message: String; init(_ message: String) { self.message = message }; var errorDescription: String? { message } }
enum HostLimits { static let slotCount = 6 }
enum PortSaves {''' + helper + '''
let root = URL(fileURLWithPath: CommandLine.arguments[1])
for picked in CommandLine.arguments.dropFirst(2) {
    do {
        let found = try PortSaves.profileFolder(root.appendingPathComponent(picked))
        print(picked + " -> " + (found.map { String($0.path.dropFirst(root.path.count + 1)) } ?? "none"))
    } catch {
        precondition(error.localizedDescription.contains("SEVERAL"))
        print(picked + " -> several")
    }
}
'''.replace('SEVERAL', several)
    (work / 'ports.swift').write_text(source)
    subprocess.run(['swiftc', '-swift-version', '6', '-module-cache-path', str(work / 'cache'), str(work / 'ports.swift'), '-o', str(work / 'swift-ports')], check=True)
    output = subprocess.run([str(work / 'swift-ports'), str(ports)] + picked, check=True, capture_output=True, text=True).stdout
    assert output == expected, output
    print('PASS Swift: save folders of PC ports and Switch emulators (Longshot, Project ReLink, Lichii, Fritchii, Eden), several profiles, saves in the picked folder')

    helper = cs.split('internal static class PortSaves', 1)[1].split('internal static class PatchFolderWriter', 1)[0]
    source = '''using System; using System.IO; using System.Collections.Generic;
internal static class PortSaves''' + helper + '''
class Test {
  static void Main(string[] args) {
    string root = Path.GetFullPath(args[0]);
    for (int i = 1; i < args.Length; i++) {
      try {
        string found = PortSaves.ProfileFolder(Path.Combine(root, args[i]));
        Console.Write(args[i] + " -> " + (found == null ? "none" : found.Substring(root.Length + 1).Replace('\\\\', '/')) + "\\n");
      } catch (IOException error) {
        if (!error.Message.Contains("SEVERAL")) throw;
        Console.Write(args[i] + " -> several\\n");
      }
    }
  }
}
'''.replace('SEVERAL', several)
    (work / 'Ports.cs').write_text(source)
    # The Windows build compiles with the .NET Framework's csc, which knows C# 5.
    subprocess.run(['mcs', '-langversion:5', '-out:' + str(work / 'cs-ports.exe'), str(work / 'Ports.cs')], check=True)
    output = subprocess.run(['mono', str(work / 'cs-ports.exe'), str(ports)] + picked, check=True, capture_output=True, text=True).stdout
    assert output == expected, output
    print('PASS C#: save folders of PC ports and Switch emulators (Longshot, Project ReLink, Lichii, Fritchii, Eden), several profiles, saves in the picked folder')
