#!/usr/bin/env node
// Builds the web version of OOT SW2SE into web/dist (or --out <folder>):
//   index.html   editor.html with the browser host (web/browser-host.js) and
//                the version from Program.cs, otherwise unchanged
//   favicon.ico  editor.ico
//   LICENSE.txt  the project license
// The result is a static site: serve it from any web server, or open
// index.html straight from disk.
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const repository = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = name => readFileSync(join(repository, name), 'utf8');

export function editorVersion(program) {
  // Like the other builds: AssemblyVersion("x.y.z.w") without the last part.
  const version = /AssemblyVersion\("([0-9]+\.[0-9]+\.[0-9]+)/.exec(program)?.[1];
  if (!version) throw new Error('The editor version could not be read from Program.cs.');
  return version;
}

const CSP_META = /<meta http-equiv="Content-Security-Policy" content="[^"]*">/g;

// The browser host goes right after the Content-Security-Policy, before the
// editor's own script. The policy itself is unchanged: the host only uses
// inline script, blob: downloads and the browser's file pickers.
export function buildPage(html, host, version) {
  const policies = html.match(CSP_META) ?? [];
  if (policies.length !== 1 || !policies[0].includes("default-src 'none';")) {
    throw new Error('editor.html has an unexpected Content-Security-Policy; update web/build.mjs.');
  }
  if (/<\/script/i.test(host)) throw new Error('The browser host must not close its script element.');
  if (!html.includes('{{EDITOR_VERSION}}')) throw new Error('editor.html has no version placeholder.');
  return html.replace(policies[0], () => policies[0] + '\n<script>' + host + '</script>')
    .replaceAll('{{EDITOR_VERSION}}', version);
}

function main(args) {
  const outIndex = args.indexOf('--out');
  const out = outIndex >= 0 ? resolve(args[outIndex + 1] ?? '') : join(repository, 'web', 'dist');
  const version = editorVersion(read('Program.cs'));
  mkdirSync(out, { recursive: true });
  writeFileSync(join(out, 'index.html'), buildPage(read('editor.html'), read('web/browser-host.js'), version));
  copyFileSync(join(repository, 'editor.ico'), join(out, 'favicon.ico'));
  copyFileSync(join(repository, 'LICENSE'), join(out, 'LICENSE.txt'));
  console.log(`Built OOT SW2SE ${version} for the web in ${out}`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main(process.argv.slice(2));
