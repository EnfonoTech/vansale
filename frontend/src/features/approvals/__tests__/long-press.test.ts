import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SWALLOW_MS, createClickSwallow } from "../long-press";

describe("createClickSwallow", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("lets an ordinary click through", () => {
    const swallow = createClickSwallow();
    expect(swallow.consume()).toBe(false);
  });

  it("swallows the click that follows a long press, once", () => {
    const swallow = createClickSwallow();
    swallow.arm();
    swallow.released();
    vi.advanceTimersByTime(5);
    expect(swallow.consume()).toBe(true);
    expect(swallow.consume()).toBe(false);
  });

  it("a click that never comes does not swallow the next tap", () => {
    const swallow = createClickSwallow();
    swallow.arm();
    swallow.released();
    vi.advanceTimersByTime(SWALLOW_MS + 1);
    expect(swallow.consume()).toBe(false);
  });

  it("keeps swallowing until the finger is lifted, however long it is held", () => {
    const swallow = createClickSwallow();
    swallow.arm();
    vi.advanceTimersByTime(10 * SWALLOW_MS);
    swallow.released();
    expect(swallow.consume()).toBe(true);
  });

  it("a new press starts a new gesture: nothing is left over", () => {
    const swallow = createClickSwallow();
    swallow.arm();
    swallow.reset();
    expect(swallow.consume()).toBe(false);
  });

  it("lifting a finger that did not long-press changes nothing", () => {
    const swallow = createClickSwallow();
    swallow.released();
    vi.advanceTimersByTime(SWALLOW_MS + 1);
    expect(swallow.consume()).toBe(false);
  });

  it("a later long press is swallowed after an earlier one timed out", () => {
    const swallow = createClickSwallow();
    swallow.arm();
    swallow.released();
    vi.advanceTimersByTime(SWALLOW_MS + 1);
    swallow.arm();
    swallow.released();
    expect(swallow.consume()).toBe(true);
  });
});
