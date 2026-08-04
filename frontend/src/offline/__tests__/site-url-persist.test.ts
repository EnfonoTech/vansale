/**
 * Regression: the saved server address must be visible SYNCHRONOUSLY on the
 * next cold start.
 *
 * v1.0.27 stored it in Capacitor Preferences only. `loadSiteUrl()` runs before
 * `app.mount()`, and at that point the native bridge has not necessarily
 * injected `window.Capacitor` — so `isNative()` answered false, the read went
 * to an empty localStorage, and the first router guard bounced an
 * already-configured app to /setup on every launch.
 *
 * These tests pin the fix: the value lands in localStorage, and a freshly
 * imported module sees it with no await at all.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const KEY = "vansale.siteUrl";

describe("site URL persistence", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.resetModules();
  });

  it("writes the normalised origin to localStorage", async () => {
    const { setSiteUrl } = await import("@/app/platform");
    await setSiteUrl("trading-demo.enfonoerp.com/app/whatever");
    expect(window.localStorage.getItem(KEY)).toBe("https://trading-demo.enfonoerp.com");
  });

  it("is visible to a fresh module import with no await (the cold-start path)", async () => {
    window.localStorage.setItem(KEY, "https://van.company.com");
    vi.resetModules();
    // No `loadSiteUrl()` call — this is exactly what the router guard sees on
    // the very first navigation.
    const { siteUrl } = await import("@/app/platform");
    expect(siteUrl()).toBe("https://van.company.com");
  });

  it("clearSiteUrl removes it so the setup screen returns", async () => {
    window.localStorage.setItem(KEY, "https://van.company.com");
    vi.resetModules();
    const { clearSiteUrl, siteUrl } = await import("@/app/platform");
    await clearSiteUrl();
    expect(siteUrl()).toBeNull();
    expect(window.localStorage.getItem(KEY)).toBeNull();
  });

  it("loadSiteUrl is a no-op once the synchronous seed already found a value", async () => {
    window.localStorage.setItem(KEY, "https://van.company.com");
    vi.resetModules();
    const { loadSiteUrl, siteUrl } = await import("@/app/platform");
    await loadSiteUrl();
    expect(siteUrl()).toBe("https://van.company.com");
  });
});
