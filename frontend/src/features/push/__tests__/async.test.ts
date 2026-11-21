import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { withTimeout } from "../async";

describe("withTimeout", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("passes the value on when it comes in time", async () => {
    await expect(withTimeout(Promise.resolve("ok"), 1000)).resolves.toBe("ok");
  });

  it("passes the error on when it fails in time", async () => {
    await expect(withTimeout(Promise.reject(new Error("boom")), 1000)).rejects.toThrow("boom");
  });

  it("gives up with the message once the time is up", async () => {
    const never = new Promise<string>(() => {});
    const result = withTimeout(never, 1000, "not ready");
    const settled = expect(result).rejects.toThrow("not ready");
    await vi.advanceTimersByTimeAsync(999);
    await vi.advanceTimersByTimeAsync(1);
    await settled;
  });

  it("does not time out a value that comes just in time, and leaves no timer behind", async () => {
    let resolve!: (value: string) => void;
    const slow = new Promise<string>((res) => (resolve = res));
    const result = withTimeout(slow, 1000);
    await vi.advanceTimersByTimeAsync(999);
    resolve("late but fine");
    await expect(result).resolves.toBe("late but fine");
    expect(vi.getTimerCount()).toBe(0);
  });
});
