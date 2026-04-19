import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Native build — symlinked `src/` points at `../frontend/src/`.
// `preserveSymlinks: false` (default) is load-bearing: setting it true
// makes the Capacitor plugin proxies fail to initialise (§5 rule 13).
export default defineConfig({
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
  },
});
