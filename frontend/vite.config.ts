import path from "node:path";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";
import { themePlugin } from "./plugins/vite-theme-plugin";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const pkg = JSON.parse(readFileSync(path.join(__dirname, "package.json"), "utf8")) as { version: string };

/**
 * `CUSTOMER_BUILD_TARGET` switches base path:
 *   - "web"    → bundle served by Frappe at `/assets/vansale/spa/`
 *   - "native" → bundle served from the Capacitor WebView root; base = "./"
 *
 * Output always lands in `../vansale/public/spa` so Frappe can serve it.
 * For native builds the Capacitor shell's own vite config (added in P5)
 * copies from this same src and outputs to `android-capacitor/www/`.
 */
export default defineConfig(({ mode, command }) => {
  const env = loadEnv(mode, process.cwd(), ["VITE_", "CUSTOMER_"]);
  const target = (env.CUSTOMER_BUILD_TARGET ?? process.env.CUSTOMER_BUILD_TARGET ?? "web") as
    | "web"
    | "native";

  const base = command === "serve" ? "/" : target === "native" ? "./" : "/assets/vansale/spa/";

  return {
    base,
    plugins: [vue(), themePlugin({ customer: env.CUSTOMER_NAME ?? "demo" })],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "src"),
      },
    },
    build: {
      outDir: path.resolve(__dirname, "../vansale/public/spa"),
      emptyOutDir: true,
      target: "es2020",
      chunkSizeWarningLimit: 1000,
      rollupOptions: {
        output: {
          manualChunks: {
            "vue-vendor": ["vue", "vue-router", "pinia", "vue-i18n"],
            idb: ["idb"],
          },
        },
      },
    },
    server: {
      port: 8082,
      proxy: {
        "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
        "/assets": { target: "http://127.0.0.1:8000", changeOrigin: true },
      },
    },
    define: {
      __BUILD_TARGET__: JSON.stringify(target),
      __APP_VERSION__: JSON.stringify(pkg.version),
      __APP_TITLE__: JSON.stringify(
        env.CUSTOMER_APP_TITLE ?? process.env.CUSTOMER_APP_TITLE ?? "Van Sale",
      ),
    },
  };
});
