import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./app/App.vue";
import { router } from "./app/router";
import { i18n, setLocale } from "./app/i18n";
import { isNative, loadSiteUrl } from "./app/platform";

// Bundled web fonts — self-hosted so the Capacitor APK stays fully offline.
// `@fontsource-variable/*` ships a single woff2 with the whole weight axis
// which is cheaper than loading 4–5 static weights.
import "@fontsource-variable/plus-jakarta-sans";
import "@fontsource-variable/manrope";
import "@fontsource/cairo/400.css";
import "@fontsource/cairo/600.css";
import "@fontsource/cairo/700.css";

import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/saudi-riyal.css";

const app = createApp(App);
app.use(createPinia());
app.use(router);
app.use(i18n);

const defaultLocale = (import.meta.env.VITE_DEFAULT_LOCALE as "en" | "ar") || "en";
setLocale(defaultLocale);

// The stored site URL must be in memory BEFORE the first navigation guard
// runs — `apiBase()` is synchronous, and mounting first would let the guard
// see "no server configured" and bounce a fully set-up app to /setup.
void loadSiteUrl().finally(() => {
  app.mount("#app");
});

// Native bootstrap — splash + status bar + back-button wiring.
if (isNative()) {
  void (async () => {
    try {
      const [{ SplashScreen }, { StatusBar }, { installNativeBack }] = await Promise.all([
        import("@capacitor/splash-screen"),
        import("@capacitor/status-bar"),
        import("./app/native-back"),
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
      await installNativeBack(router);
    } catch {
      /* plugins not bundled on web */
    }
  })();
}

// Service worker registered only on web, and only in production. It is the
// app's own (vansale/pwa.py), scoped to /vansale — not the site-wide /sw.js,
// which on some sites is another app's (POS Awesome) and blocked installing.
if (!isNative() && "serviceWorker" in navigator && import.meta.env.PROD) {
  void navigator.serviceWorker.register("/vansale/sw.js", { scope: "/vansale" }).catch(() => {
    /* not fatal: the app works without it, it just can't be installed */
  });
}
