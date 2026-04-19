import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./app/App.vue";
import { router } from "./app/router";
import { i18n, setLocale } from "./app/i18n";
import { isNative } from "./app/platform";

import "./styles/tokens.css";
import "./styles/base.css";

const app = createApp(App);
app.use(createPinia());
app.use(router);
app.use(i18n);

const defaultLocale = (import.meta.env.VITE_DEFAULT_LOCALE as "en" | "ar") || "en";
setLocale(defaultLocale);

app.mount("#app");

// Native-only bootstrap. Splash + status bar + back button wiring lands
// in Phase 5 — this block is a placeholder so the symbol exists.
if (isNative()) {
  void (async () => {
    try {
      const [{ SplashScreen }, { StatusBar }] = await Promise.all([
        import("@capacitor/splash-screen"),
        import("@capacitor/status-bar"),
      ]);
      try {
        await StatusBar.setBackgroundColor({ color: "#2563eb" });
      } catch {
        /* StatusBar not available */
      }
      try {
        await SplashScreen.hide();
      } catch {
        /* SplashScreen not available */
      }
    } catch {
      /* plugins not bundled on web */
    }
  })();
}

// Service worker registered only on web, and only in production.
if (!isNative() && "serviceWorker" in navigator && import.meta.env.PROD) {
  // sw.js is served by Frappe (wired in Phase 2 via hooks.website_route_rules).
  void navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {
    /* first-run failure is fine; dev has no SW */
  });
}
