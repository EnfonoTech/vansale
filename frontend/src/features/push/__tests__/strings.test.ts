/**
 * The status line is looked up by key (`approvalsPush.status.<key>`), so a key
 * that `statusKey` can return and a language lacks would show raw text.
 */
import { describe, expect, it } from "vitest";
import { i18n } from "@/app/i18n";
import { INITIAL, statusKey, type StatusKey, type ToggleState } from "../toggle";

const KEYS: StatusKey[] = [
  "checking",
  "off",
  "on",
  "working",
  "blocked",
  "unsupported",
  "unsupportedIos",
  "needsConnection",
  "turnOnFailed",
  "turnOffFailed",
];

describe("approvalsPush strings", () => {
  it.each(["en", "ar"] as const)("%s has a label and every status line", (locale) => {
    expect(i18n.global.te("approvalsPush.label", locale)).toBe(true);
    for (const key of KEYS) {
      expect(i18n.global.te(`approvalsPush.status.${key}`, locale), `${locale}: ${key}`).toBe(true);
    }
  });

  it("statusKey only ever returns a key that is listed here (and so translated)", () => {
    const states: ToggleState[] = [
      INITIAL,
      { kind: "unsupported" },
      { kind: "blocked" },
      { kind: "off" },
      { kind: "on" },
      { kind: "busy", target: "on" },
      { kind: "busy", target: "off" },
      { kind: "error", was: "on", problem: "failed" },
      { kind: "error", was: "off", problem: "failed" },
      { kind: "error", was: "on", problem: "offline" },
      { kind: "error", was: "off", problem: "offline" },
    ];
    for (const state of states) {
      for (const online of [true, false]) {
        for (const ios of [true, false]) {
          expect(KEYS).toContain(statusKey(state, online, ios));
        }
      }
    }
  });

  it("the Arabic lines are not the English ones", () => {
    for (const key of ["label", ...KEYS.map((k) => `status.${k}`)]) {
      const path = `approvalsPush.${key}`;
      expect(i18n.global.t(path, {}, { locale: "ar" })).not.toBe(i18n.global.t(path, {}, { locale: "en" }));
    }
  });
});
