/**
 * Offline PIN unlock: the right PIN unlocks, a wrong one doesn't, the PIN is
 * never stored in clear, and repeated wrong PINs stop offline unlock.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { canUnlockOffline, forgetPin, forgetPinOfOthers, rememberPin, verifyPinOffline } from "@/app/pin-offline";

const USER = "driver@example.com";

describe("offline PIN unlock", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("unlocks with the remembered PIN only", async () => {
    await rememberPin(USER, "4821");
    expect(canUnlockOffline(USER)).toBe(true);
    expect(await verifyPinOffline(USER, "4821")).toBe(true);
    expect(await verifyPinOffline(USER, "1111")).toBe(false);
  });

  it("never stores the PIN itself", async () => {
    await rememberPin(USER, "4821");
    expect(window.localStorage.getItem("vansale.pinVerifier")).not.toContain("4821");
  });

  it("is per user", async () => {
    await rememberPin(USER, "4821");
    expect(canUnlockOffline("other@example.com")).toBe(false);
    expect(await verifyPinOffline("other@example.com", "4821")).toBe(false);
  });

  it("stops after 5 wrong PINs, even for the right one", async () => {
    await rememberPin(USER, "4821");
    for (let i = 0; i < 5; i++) expect(await verifyPinOffline(USER, "0000")).toBe(false);
    expect(canUnlockOffline(USER)).toBe(false);
    expect(await verifyPinOffline(USER, "4821")).toBe(false);
  });

  it("is cleared on logout", async () => {
    await rememberPin(USER, "4821");
    forgetPin();
    expect(canUnlockOffline(USER)).toBe(false);
  });

  it("is kept when the same user signs in again with the password", async () => {
    await rememberPin(USER, "4821");
    forgetPinOfOthers(USER);
    expect(canUnlockOffline(USER)).toBe(true);
    expect(await verifyPinOffline(USER, "4821")).toBe(true);
  });

  it("is dropped when another user signs in", async () => {
    await rememberPin(USER, "4821");
    forgetPinOfOthers("other@example.com");
    expect(canUnlockOffline(USER)).toBe(false);
    expect(window.localStorage.getItem("vansale.pinVerifier")).toBeNull();
  });

  it("does nothing when no PIN was stored", () => {
    expect(() => forgetPinOfOthers(USER)).not.toThrow();
    expect(canUnlockOffline(USER)).toBe(false);
  });
});
