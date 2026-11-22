/**
 * The branding the sign-in screen shows: Vansale Settings values from a public
 * endpoint, kept in localStorage so the screen is right on first paint and offline.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiBase = vi.fn(() => "");
vi.mock("@/app/platform", () => ({
  apiBase: () => apiBase(),
  absoluteUrl: (url: string | null | undefined) => url ?? "",
}));

import {
  authStyleClass,
  BRANDING_CACHE_KEY,
  normalizeBranding,
  readCachedBranding,
  resetBrandingForTests,
  useBranding,
} from "@/app/branding";

const FALLBACK = { appName: "Van Sale", logoUrl: "", style: "classic" };

function answer(message: unknown, ok = true) {
  return vi.fn().mockResolvedValue({ ok, json: async () => ({ message }) });
}

describe("branding", () => {
  beforeEach(() => {
    window.localStorage.clear();
    apiBase.mockReturnValue("");
    resetBrandingForTests();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("falls back to the build title, no logo and Classic when nothing is set", () => {
    expect(normalizeBranding(null)).toEqual(FALLBACK);
    expect(normalizeBranding({ app_name: "", logo_url: "", style: "" })).toEqual(FALLBACK);
    expect(useBranding().branding.value).toEqual(FALLBACK);
  });

  it("reads the value an earlier fetch cached", () => {
    window.localStorage.setItem(
      BRANDING_CACHE_KEY,
      JSON.stringify({ appName: "SF Connect", logoUrl: "/files/e.png", style: "split" }),
    );
    expect(readCachedBranding()).toEqual({ appName: "SF Connect", logoUrl: "/files/e.png", style: "split" });
    resetBrandingForTests();
    expect(useBranding().branding.value.appName).toBe("SF Connect");
  });

  it("ignores a garbage cache entry", () => {
    window.localStorage.setItem(BRANDING_CACHE_KEY, "{nope");
    expect(readCachedBranding()).toBeNull();
    resetBrandingForTests();
    expect(useBranding().branding.value).toEqual(FALLBACK);
  });

  it("an unknown style becomes classic", () => {
    expect(normalizeBranding({ app_name: "X", style: "neon" }).style).toBe("classic");
    expect(normalizeBranding({ app_name: "X", style: "dark" }).style).toBe("dark");
  });

  it("a long or markup name is cut to 40 characters and kept as plain text", () => {
    const long = normalizeBranding({ app_name: "<b>" + "x".repeat(80) + "</b>" });
    expect(long.appName.length).toBe(40);
    expect(long.appName.startsWith("<b>")).toBe(true);
  });

  it("refreshBranding stores the answer and updates the reactive value", async () => {
    const fetchMock = answer({ app_name: "SF Connect", logo_url: "/files/e.png", style: "split" });
    vi.stubGlobal("fetch", fetchMock);
    const { branding, refreshBranding } = useBranding();
    await refreshBranding();
    expect(fetchMock.mock.calls[0][0]).toContain("/api/method/vansale.api.auth.branding");
    expect(branding.value).toEqual({ appName: "SF Connect", logoUrl: "/files/e.png", style: "split" });
    expect(readCachedBranding()).toEqual(branding.value);
  });

  it("refreshBranding keeps the cached value when the request fails", async () => {
    window.localStorage.setItem(
      BRANDING_CACHE_KEY,
      JSON.stringify({ appName: "SF Connect", logoUrl: "", style: "dark" }),
    );
    resetBrandingForTests();
    const { branding, refreshBranding } = useBranding();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    await refreshBranding();
    expect(branding.value.appName).toBe("SF Connect");
    vi.stubGlobal("fetch", answer({ app_name: "Other" }, false));
    await refreshBranding();
    expect(branding.value.appName).toBe("SF Connect");
  });

  it("refreshBranding does nothing when no server is configured", async () => {
    apiBase.mockImplementation(() => {
      throw new Error("No server configured");
    });
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await useBranding().refreshBranding();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("authStyleClass names the style on the wrapper", () => {
    expect(authStyleClass("dark")).toBe("auth-style-dark");
    expect(authStyleClass("classic")).toBe("auth-style-classic");
  });
});
