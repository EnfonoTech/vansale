#!/usr/bin/env node
/**
 * Minimal customer asset generator for the Android project.
 * Writes colors.xml (overwrite — never append; fatehhr lesson §5.1)
 * and strings.xml (app_name) from CUSTOMER_* env vars.
 *
 * Icon regeneration from a 1024×1024 PNG source is a longer story;
 * for the demo APK we use the Capacitor default icon and swap in a
 * custom one later via `cordova-res` or manual drops into mipmap-*.
 *
 * Usage: CUSTOMER_NAME=demo CUSTOMER_APP_TITLE='Van Sale' ... node scripts/generate-customer-assets.mjs
 */
import { mkdirSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ANDROID_ROOT = join(__dirname, "..", "android-capacitor", "android");

if (!existsSync(ANDROID_ROOT)) {
  console.error("✗ android/ not generated yet — run `npx cap add android` first");
  process.exit(1);
}

const primary = process.env.CUSTOMER_THEME_PRIMARY ?? "#2563eb";
const appTitle = process.env.CUSTOMER_APP_TITLE ?? "Van Sale";

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
    <string name="package_name">${process.env.CUSTOMER_APP_ID ?? "com.enfono.vansale.demo"}</string>
    <string name="custom_url_scheme">${process.env.CUSTOMER_APP_ID ?? "com.enfono.vansale.demo"}</string>
</resources>
`,
);

console.log(`✓ Wrote colors.xml + strings.xml for "${appTitle}"`);
