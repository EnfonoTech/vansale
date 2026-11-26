import { describe, expect, it } from "vitest";
import { canToggle, INITIAL, isOn, reduce, statusKey, type StatusKey, type ToggleEvent, type ToggleState } from "../toggle";

const OFF: ToggleState = { kind: "off" };
const ON: ToggleState = { kind: "on" };

/** Apply events one after another. */
function run(state: ToggleState, ...events: ToggleEvent[]): ToggleState {
  return events.reduce(reduce, state);
}

describe("looking (checked)", () => {
  it("starts by checking", () => {
    expect(INITIAL).toEqual({ kind: "checking" });
  });

  it.each([
    ["unsupported", false, { kind: "unsupported" }],
    ["unsupported", true, { kind: "unsupported" }],
    ["denied", false, { kind: "blocked" }],
    ["denied", true, { kind: "blocked" }],
    ["ready", false, { kind: "off" }],
    ["ready", true, { kind: "on" }],
  ] as const)("%s, subscribed %s -> %j", (support, subscribed, expected) => {
    expect(reduce(INITIAL, { type: "checked", support, subscribed })).toEqual(expected);
  });

  it("a later look replaces an earlier answer and an error", () => {
    expect(reduce(ON, { type: "checked", support: "denied", subscribed: true })).toEqual({ kind: "blocked" });
    expect(
      reduce({ kind: "error", was: "off", problem: "failed" }, { type: "checked", support: "ready", subscribed: true }),
    ).toEqual(ON);
  });

  it("never undoes a change that is on its way", () => {
    const busy: ToggleState = { kind: "busy", target: "on" };
    expect(reduce(busy, { type: "checked", support: "ready", subscribed: false })).toBe(busy);
  });
});

describe("turning on", () => {
  it("goes busy, then on", () => {
    expect(run(OFF, { type: "start", target: "on" })).toEqual({ kind: "busy", target: "on" });
    expect(run(OFF, { type: "start", target: "on" }, { type: "done" })).toEqual(ON);
  });

  it("is refused by the browser's prompt: blocked", () => {
    expect(run(OFF, { type: "start", target: "on" }, { type: "denied" })).toEqual({ kind: "blocked" });
  });

  it("is dismissed without an answer: back to off, no error", () => {
    expect(run(OFF, { type: "start", target: "on" }, { type: "dismissed" })).toEqual(OFF);
  });

  it("fails: an error that remembers it was off", () => {
    expect(run(OFF, { type: "start", target: "on" }, { type: "failed", problem: "failed" })).toEqual({
      kind: "error",
      was: "off",
      problem: "failed",
    });
    expect(run(OFF, { type: "start", target: "on" }, { type: "failed", problem: "offline" })).toEqual({
      kind: "error",
      was: "off",
      problem: "offline",
    });
  });

  it("can be tried again after an error", () => {
    const failed = run(OFF, { type: "start", target: "on" }, { type: "failed", problem: "failed" });
    expect(run(failed, { type: "start", target: "on" }, { type: "done" })).toEqual(ON);
  });

  it("cannot start from on, busy, blocked, unsupported or checking", () => {
    for (const state of [ON, { kind: "busy", target: "on" }, { kind: "blocked" }, { kind: "unsupported" }, INITIAL] as ToggleState[]) {
      expect(reduce(state, { type: "start", target: "on" })).toBe(state);
    }
  });
});

describe("turning off", () => {
  it("goes busy, then off", () => {
    expect(run(ON, { type: "start", target: "off" })).toEqual({ kind: "busy", target: "off" });
    expect(run(ON, { type: "start", target: "off" }, { type: "done" })).toEqual(OFF);
  });

  it("fails: an error that remembers it was on", () => {
    expect(run(ON, { type: "start", target: "off" }, { type: "failed", problem: "offline" })).toEqual({
      kind: "error",
      was: "on",
      problem: "offline",
    });
  });

  it("an error that was on turns off on the next tap, not on", () => {
    const failed = run(ON, { type: "start", target: "off" }, { type: "failed", problem: "failed" });
    expect(reduce(failed, { type: "start", target: "on" })).toBe(failed);
    expect(reduce(failed, { type: "start", target: "off" })).toEqual({ kind: "busy", target: "off" });
  });

  it("cannot start from off", () => {
    expect(reduce(OFF, { type: "start", target: "off" })).toBe(OFF);
  });
});

describe("events with no change under way are ignored", () => {
  it.each([{ type: "done" }, { type: "denied" }, { type: "dismissed" }, { type: "failed", problem: "failed" }] as ToggleEvent[])(
    "%j",
    (event) => {
      for (const state of [OFF, ON, INITIAL, { kind: "blocked" }] as ToggleState[]) {
        expect(reduce(state, event)).toBe(state);
      }
    },
  );
});

describe("isOn: what the switch shows", () => {
  it("is on for on, for a change heading to on, and for an error that was on", () => {
    expect(isOn(ON)).toBe(true);
    expect(isOn({ kind: "busy", target: "on" })).toBe(true);
    expect(isOn({ kind: "error", was: "on", problem: "failed" })).toBe(true);
  });

  it("is off for everything else", () => {
    for (const state of [
      INITIAL,
      OFF,
      { kind: "blocked" },
      { kind: "unsupported" },
      { kind: "busy", target: "off" },
      { kind: "error", was: "off", problem: "failed" },
    ] as ToggleState[]) {
      expect(isOn(state)).toBe(false);
    }
  });
});

describe("canToggle", () => {
  it("is true for off, on and an error, with a connection", () => {
    for (const state of [OFF, ON, { kind: "error", was: "off", problem: "failed" }, { kind: "error", was: "on", problem: "offline" }] as ToggleState[]) {
      expect(canToggle(state, true)).toBe(true);
    }
  });

  it("is false without a connection: both directions talk to the server", () => {
    for (const state of [OFF, ON, { kind: "error", was: "off", problem: "failed" }] as ToggleState[]) {
      expect(canToggle(state, false)).toBe(false);
    }
  });

  it("is false while checking, busy, blocked or unsupported", () => {
    for (const state of [INITIAL, { kind: "busy", target: "on" }, { kind: "busy", target: "off" }, { kind: "blocked" }, { kind: "unsupported" }] as ToggleState[]) {
      expect(canToggle(state, true)).toBe(false);
    }
  });
});

describe("statusKey", () => {
  it.each([
    [INITIAL, true, false, "checking"],
    [OFF, true, false, "off"],
    [OFF, false, false, "needsConnection"],
    [ON, true, false, "on"],
    [ON, false, false, "on"],
    [{ kind: "busy", target: "on" }, true, false, "working"],
    [{ kind: "busy", target: "off" }, true, false, "working"],
    [{ kind: "blocked" }, true, false, "blocked"],
    [{ kind: "unsupported" }, true, false, "unsupported"],
    [{ kind: "unsupported" }, true, true, "unsupportedIos"],
    [{ kind: "error", was: "off", problem: "failed" }, true, false, "turnOnFailed"],
    [{ kind: "error", was: "on", problem: "failed" }, true, false, "turnOffFailed"],
    [{ kind: "error", was: "off", problem: "offline" }, true, false, "needsConnection"],
    [{ kind: "error", was: "on", problem: "offline" }, false, false, "needsConnection"],
  ] as [ToggleState, boolean, boolean, StatusKey][])("%j, online %s, ios %s -> %s", (state, online, ios, key) => {
    expect(statusKey(state, online, ios)).toBe(key);
  });

  it("the iPhone advice is only for an unsupported device", () => {
    expect(statusKey({ kind: "blocked" }, true, true)).toBe("blocked");
    expect(statusKey(OFF, true, true)).toBe("off");
  });
});
