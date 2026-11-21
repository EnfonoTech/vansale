import { describe, expect, it } from "vitest";
import { isIos, readSupport, type PushEnv } from "../support";

/** A browser that can take Web Push, permission not asked yet. */
function capable(over: Partial<PushEnv> = {}): PushEnv {
  return {
    native: false,
    navigator: { serviceWorker: {} },
    PushManager: function PushManager() {},
    Notification: { permission: "default" },
    ...over,
  };
}

describe("readSupport", () => {
  it("is ready when the browser has all three and permission is not asked yet", () => {
    expect(readSupport(capable())).toBe("ready");
  });

  it("is ready when permission is already granted", () => {
    expect(readSupport(capable({ Notification: { permission: "granted" } }))).toBe("ready");
  });

  it("is denied when the user blocked notifications for the site", () => {
    expect(readSupport(capable({ Notification: { permission: "denied" } }))).toBe("denied");
  });

  it("is unsupported in the native app, whatever the web view offers", () => {
    expect(readSupport(capable({ native: true }))).toBe("unsupported");
    expect(readSupport(capable({ native: true, Notification: { permission: "denied" } }))).toBe("unsupported");
  });

  it("is unsupported without a service worker", () => {
    expect(readSupport(capable({ navigator: {} }))).toBe("unsupported");
    expect(readSupport(capable({ navigator: undefined }))).toBe("unsupported");
    expect(readSupport(capable({ navigator: { serviceWorker: undefined } }))).toBe("unsupported");
  });

  it("is unsupported without the Push API (an iPhone tab that is not on the Home Screen)", () => {
    expect(readSupport(capable({ PushManager: undefined }))).toBe("unsupported");
  });

  it("is unsupported without notifications", () => {
    expect(readSupport(capable({ Notification: undefined }))).toBe("unsupported");
  });

  it("unsupported wins over denied", () => {
    expect(readSupport(capable({ PushManager: undefined, Notification: { permission: "denied" } }))).toBe(
      "unsupported",
    );
  });
});

describe("isIos", () => {
  it("knows an iPhone and an iPad by their user agent", () => {
    expect(isIos("Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15")).toBe(true);
    expect(isIos("Mozilla/5.0 (iPad; CPU OS 16_6 like Mac OS X) AppleWebKit/605.1.15")).toBe(true);
  });

  it("knows an iPad that poses as a Mac by its touch screen", () => {
    const mac = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15";
    expect(isIos(mac, "MacIntel", 5)).toBe(true);
    expect(isIos(mac, "MacIntel", 0)).toBe(false);
  });

  it("is false for Android and desktops", () => {
    expect(isIos("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/124.0 Mobile Safari/537.36")).toBe(false);
    expect(isIos("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36", "Win32", 0)).toBe(false);
  });
});
