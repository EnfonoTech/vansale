#!/usr/bin/env node
/**
 * Phase 1 stub. Bumps `NATIVE_VERSION` + `NATIVE_VERSION_CODE` in
 * `frontend/src/app/native-version.ts`.
 *
 * Phase 5 extends this to also bump `versionCode` / `versionName` in
 * `android-capacitor/android/app/build.gradle` atomically — the two
 * values MUST stay in lockstep (frappe-vue-pwa §5 rule 15).
 *
 * Usage: `node scripts/bump-version.mjs [patch|minor|major]` (default patch).
 */
import { readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const versionFile = join(__dirname, "..", "frontend", "src", "app", "native-version.ts");

const kind = process.argv[2] ?? "patch";
if (!["patch", "minor", "major"].includes(kind)) {
  console.error(`Unknown bump kind: ${kind}`);
  process.exit(1);
}

const src = readFileSync(versionFile, "utf8");
const versionMatch = src.match(/NATIVE_VERSION\s*=\s*"(\d+)\.(\d+)\.(\d+)"/);
const codeMatch = src.match(/NATIVE_VERSION_CODE\s*=\s*(\d+)/);
if (!versionMatch || !codeMatch) {
  console.error("Could not parse native-version.ts — aborting.");
  process.exit(1);
}
let [, maj, min, pat] = versionMatch.map((n, i) => (i === 0 ? n : Number(n)));
const nextCode = Number(codeMatch[1]) + 1;

if (kind === "major") {
  maj = Number(maj) + 1;
  min = 0;
  pat = 0;
} else if (kind === "minor") {
  min = Number(min) + 1;
  pat = 0;
} else {
  pat = Number(pat) + 1;
}
const nextVersion = `${maj}.${min}.${pat}`;

const updated = src
  .replace(/NATIVE_VERSION\s*=\s*"[^"]+"/, `NATIVE_VERSION = "${nextVersion}"`)
  .replace(/NATIVE_VERSION_CODE\s*=\s*\d+/, `NATIVE_VERSION_CODE = ${nextCode}`);

writeFileSync(versionFile, updated);
console.log(`Bumped → ${nextVersion} (code ${nextCode})`);
