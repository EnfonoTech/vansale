import path from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Shared native-version file is the single source of truth for the APK
// version (bumped by scripts/bump-version.mjs). Exposing it as
// `__APP_VERSION__` keeps MoreView + About screens in sync; the old
// path read `../frontend/package.json.version` which is unrelated and
// never changes, so native MoreView crashed trying to dereference the
// undefined global.
const nativeVersionModule = readFileSync(
  path.resolve(__dirname, "../frontend/src/app/native-version.ts"),
  "utf8",
);
const versionMatch = nativeVersionModule.match(/NATIVE_VERSION\s*=\s*"([^"]+)"/);
const APP_VERSION = versionMatch ? versionMatch[1] : "0.0.0";

// Native build — symlinked `src/` points at `../frontend/src/`.
// `preserveSymlinks: false` (default) is load-bearing: setting it true
// makes the Capacitor plugin proxies fail to initialise (§5 rule 13).
export default defineConfig(({ mode }) => {
  // `VITE_API_BASE` is now the *default* server, not the only one: the APK
  // asks for a site URL on first run and stores it (see platform.ts
  // `loadSiteUrl`). Baking it in is still preferred for customer builds —
  // the tester never sees the setup screen — so a missing value warns
  // loudly rather than passing silently. v1.0.17 shipped without it and
  // every API call threw; back then there was no runtime fallback.
  const env = loadEnv(mode, __dirname, "VITE_");
  const apiBase = env.VITE_API_BASE ?? process.env.VITE_API_BASE;
  if (!apiBase) {
    console.warn(
      "\n⚠ VITE_API_BASE not set — the APK will open the server-address " +
      "setup screen on first run instead of connecting straight to a site.\n" +
      "  For a customer build, source customers/.env.<customer> first.\n",
    );
  }

  return {
    plugins: [vue()],
    base: "./",
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "src"),
      },
    },
    build: {
      outDir: path.resolve(__dirname, "www"),
      emptyOutDir: true,
      target: "es2020",
    },
    define: {
      __BUILD_TARGET__: JSON.stringify("native"),
      __APP_VERSION__: JSON.stringify(APP_VERSION),
      // `build-customer.sh` sources customers/.env.<customer> with `set -a`,
      // so CUSTOMER_* land in process.env. `loadEnv` above is VITE_-only.
      __APP_TITLE__: JSON.stringify(process.env.CUSTOMER_APP_TITLE ?? "Van Sale"),
    },
  };
});
