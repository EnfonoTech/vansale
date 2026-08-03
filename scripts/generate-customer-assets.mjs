#!/usr/bin/env node
/**
 * Customer asset generator. Two stages, because Vite bundles `public/`
 * during the build while the Android resources only exist after
 * `npx cap copy android`:
 *
 *   node scripts/generate-customer-assets.mjs brand    # BEFORE the vite builds
 *   node scripts/generate-customer-assets.mjs android  # AFTER `cap copy android`
 *
 * `brand` copies the in-app logo into both public dirs. The web build's
 * root is `frontend/` and the native build's is `android-capacitor/`, so
 * each needs its own copy — Vite only bundles the `public/` under the root
 * it was invoked with.
 *
 * `android` writes colors.xml + strings.xml (overwrite — never append;
 * fatehhr lesson §5.1) and regenerates the launcher icon + splash from the
 * customer's 1024×1024 PNG via `@capacitor/assets`.
 *
 * Per-customer artwork lives at:
 *   customers/assets/<customer>/icon.png    1024×1024, required for icons
 *   customers/assets/<customer>/splash.png  2732×2732, optional
 *   customers/assets/<customer>/logo.png    in-app brand mark, optional
 *                                           (falls back to icon.png)
 *
 * Missing artwork is a warning, never a failure — the build still produces
 * an installable APK with the Capacitor default icon.
 */
import { mkdirSync, writeFileSync, existsSync, copyFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const ANDROID_ROOT = join(ROOT, "android-capacitor", "android");

const stage = process.argv[2] ?? "android";
if (!["brand", "android"].includes(stage)) {
  console.error(`✗ Unknown stage "${stage}" — expected "brand" or "android"`);
  process.exit(1);
}

const customer = process.env.CUSTOMER_NAME ?? "demo";
const primary = process.env.CUSTOMER_THEME_PRIMARY ?? "#2563eb";
const background = process.env.CUSTOMER_THEME_BG ?? "#f8fafc";
const appTitle = process.env.CUSTOMER_APP_TITLE ?? "Van Sale";
const appId = process.env.CUSTOMER_APP_ID ?? "com.enfono.vansale.demo";

const assetDir = join(ROOT, "customers", "assets", customer);
const iconPath = join(assetDir, "icon.png");
const logoPath = join(assetDir, "logo.png");

// ---------------------------------------------------------------- brand ----
if (stage === "brand") {
  const source = existsSync(logoPath) ? logoPath : existsSync(iconPath) ? iconPath : null;
  if (!source) {
    console.warn(
      `⚠ No brand logo at ${logoPath} (or icon.png) — the app keeps the ` +
        `built-in truck mark. Drop a PNG there and rebuild to brand the login screen.`,
    );
  } else {
    for (const publicDir of [
      join(ROOT, "frontend", "public"),
      join(ROOT, "android-capacitor", "public"),
    ]) {
      mkdirSync(publicDir, { recursive: true });
      copyFileSync(source, join(publicDir, "brand-logo.png"));
    }
    console.log(`✓ Brand logo staged from ${source}`);
  }
  process.exit(0);
}

// -------------------------------------------------------------- android ----
if (!existsSync(ANDROID_ROOT)) {
  console.error("✗ android/ not generated yet — run `npx cap add android` first");
  process.exit(1);
}

const valuesDir = join(ANDROID_ROOT, "app", "src", "main", "res", "values");
mkdirSync(valuesDir, { recursive: true });

// NOTE: `ic_launcher_background` is declared by the Capacitor template in
// a separate `ic_launcher_background.xml` resource file. Do NOT redeclare
// it here or AGP fails with "Duplicate resources". Override the adaptive
// icon background via ic_launcher_background.xml directly if needed.
writeFileSync(
  join(valuesDir, "colors.xml"),
  `<?xml version="1.0" encoding="utf-8"?>
<resources>
    <color name="colorPrimary">${primary}</color>
    <color name="colorPrimaryDark">${primary}</color>
    <color name="colorAccent">${primary}</color>
</resources>
`,
);

// Adaptive-icon background — overwrite the template's value to match brand.
writeFileSync(
  join(valuesDir, "ic_launcher_background.xml"),
  `<?xml version="1.0" encoding="utf-8"?>
<resources>
    <color name="ic_launcher_background">${primary}</color>
</resources>
`,
);

writeFileSync(
  join(valuesDir, "strings.xml"),
  `<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">${appTitle}</string>
    <string name="title_activity_main">${appTitle}</string>
    <string name="package_name">${appId}</string>
    <string name="custom_url_scheme">${appId}</string>
</resources>
`,
);

console.log(`✓ Wrote colors.xml + strings.xml for "${appTitle}"`);

// Launcher icon + splash. `@capacitor/assets` rewrites every mipmap-* and
// drawable-* density from one source PNG, which is the only correct way to
// get an adaptive icon — hand-dropping files into mipmap-anydpi-v26 leaves
// the legacy densities stale and the launcher picks those on older devices.
if (!existsSync(iconPath)) {
  console.warn(
    `⚠ No launcher icon at ${iconPath} — keeping the Capacitor default. ` +
      `Add a 1024×1024 PNG there and rebuild.`,
  );
} else {
  const res = spawnSync(
    "npx",
    [
      "--yes",
      "@capacitor/assets@3",
      "generate",
      "--android",
      "--assetPath",
      join("..", "customers", "assets", customer),
      "--iconBackgroundColor",
      primary,
      "--iconBackgroundColorDark",
      primary,
      "--splashBackgroundColor",
      background,
      "--splashBackgroundColorDark",
      background,
    ],
    { cwd: join(ROOT, "android-capacitor"), stdio: "inherit", env: process.env },
  );
  if (res.status !== 0) {
    console.warn(
      `⚠ @capacitor/assets exited with ${res.status ?? "a signal"} — icons NOT ` +
        `regenerated. The APK still builds with the previous icon. Needs network ` +
        `on first run.`,
    );
  } else {
    console.log(`✓ Regenerated launcher icon + splash from ${iconPath}`);
  }
}
