#!/usr/bin/env node
/**
 * Atomic version bumper. The only supported path for bumping the app
 * version — manual edits desync `NATIVE_VERSION` and `versionCode` and
 * Android silently skips the reinstall (fatehhr lesson §5 rule 15).
 *
 * Writes:
 *   - frontend/src/app/native-version.ts : NATIVE_VERSION, NATIVE_VERSION_CODE
 *   - android-capacitor/android/app/build.gradle : versionName, versionCode
 *
 * The android/ file is optional (absent before `npx cap add android`).
 *
 * Usage: node scripts/bump-version.mjs [patch|minor|major]
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const VERSION_FILE = join(ROOT, "frontend", "src", "app", "native-version.ts");
const GRADLE_FILE = join(ROOT, "android-capacitor", "android", "app", "build.gradle");

const kind = process.argv[2] ?? "patch";
if (!["patch", "minor", "major"].includes(kind)) {
  console.error(`Unknown bump kind: ${kind}`);
  process.exit(1);
}

const src = readFileSync(VERSION_FILE, "utf8");
const versionMatch = src.match(/NATIVE_VERSION\s*=\s*"(\d+)\.(\d+)\.(\d+)"/);
const codeMatch = src.match(/NATIVE_VERSION_CODE\s*=\s*(\d+)/);
if (!versionMatch || !codeMatch) {
  console.error("Could not parse native-version.ts — aborting.");
  process.exit(1);
}

let maj = Number(versionMatch[1]);
let min = Number(versionMatch[2]);
let pat = Number(versionMatch[3]);
const nextCode = Number(codeMatch[1]) + 1;

if (kind === "major") { maj += 1; min = 0; pat = 0; }
else if (kind === "minor") { min += 1; pat = 0; }
else { pat += 1; }
const nextVersion = `${maj}.${min}.${pat}`;

const updated = src
  .replace(/NATIVE_VERSION\s*=\s*"[^"]+"/, `NATIVE_VERSION = "${nextVersion}"`)
  .replace(/NATIVE_VERSION_CODE\s*=\s*\d+/, `NATIVE_VERSION_CODE = ${nextCode}`);
writeFileSync(VERSION_FILE, updated);
console.log(`✓ ${VERSION_FILE} → ${nextVersion} (code ${nextCode})`);

if (existsSync(GRADLE_FILE)) {
  let gradle = readFileSync(GRADLE_FILE, "utf8");
  gradle = gradle
    .replace(/versionName\s+"[^"]+"/, `versionName "${nextVersion}"`)
    .replace(/versionCode\s+\d+/, `versionCode ${nextCode}`);
  writeFileSync(GRADLE_FILE, gradle);
  console.log(`✓ ${GRADLE_FILE} → ${nextVersion} (code ${nextCode})`);
}
