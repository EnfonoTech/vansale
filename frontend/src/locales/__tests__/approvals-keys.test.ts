/**
 * The approvals strings live in one JSON file per screen owner, under
 * `locales/approvals/en/` and `locales/approvals/ar/`, and `app/i18n.ts`
 * merges them into the app's messages. These tests keep the two languages
 * in step (a key missing in Arabic would silently show the English text) and
 * keep the files from overwriting each other when they are merged.
 */
import { describe, expect, it } from "vitest";
import { i18n } from "@/app/i18n";

type Messages = Record<string, unknown>;

const en = import.meta.glob("../approvals/en/*.json", { eager: true, import: "default" }) as Record<string, Messages>;
const ar = import.meta.glob("../approvals/ar/*.json", { eager: true, import: "default" }) as Record<string, Messages>;

/** `en/inbox.json` -> `inbox.json`. */
function byFileName(modules: Record<string, Messages>): Record<string, Messages> {
  const out: Record<string, Messages> = {};
  for (const [path, messages] of Object.entries(modules)) {
    out[path.slice(path.lastIndexOf("/") + 1)] = messages;
  }
  return out;
}

/** `{ a: { b: "x" } }` -> `["a.b"]`, sorted. */
function flatten(messages: unknown, prefix = ""): string[] {
  if (messages === null || typeof messages !== "object" || Array.isArray(messages)) return [prefix];
  return Object.entries(messages as Messages)
    .flatMap(([key, value]) => flatten(value, prefix ? `${prefix}.${key}` : key))
    .sort();
}

const enFiles = byFileName(en);
const arFiles = byFileName(ar);
const fileNames = [...new Set([...Object.keys(enFiles), ...Object.keys(arFiles)])].sort();

describe("approvals locale files", () => {
  it("has at least the inbox file", () => {
    expect(fileNames).toContain("inbox.json");
  });

  it.each(fileNames)("%s exists in both languages", (name) => {
    expect(Object.keys(enFiles), `${name} missing in en/`).toContain(name);
    expect(Object.keys(arFiles), `${name} missing in ar/`).toContain(name);
  });

  it.each(fileNames)("%s has the same keys in en and ar", (name) => {
    expect(flatten(arFiles[name] ?? {})).toEqual(flatten(enFiles[name] ?? {}));
  });

  it.each(fileNames)("%s has no empty string", (name) => {
    for (const files of [enFiles, arFiles]) {
      const messages = files[name] ?? {};
      const leaves = flatten(messages);
      for (const leaf of leaves) {
        const value = leaf.split(".").reduce<unknown>((node, key) => (node as Messages)?.[key], messages);
        expect(typeof value === "string" && value.trim().length > 0, `${name}: ${leaf}`).toBe(true);
      }
    }
  });

  it("never defines the same top-level key in two files", () => {
    for (const files of [enFiles, arFiles]) {
      const seen = new Map<string, string>();
      for (const [name, messages] of Object.entries(files)) {
        for (const key of Object.keys(messages)) {
          expect(seen.get(key), `${key} is in ${seen.get(key)} and ${name}`).toBeUndefined();
          seen.set(key, name);
        }
      }
    }
  });
});

describe("app/i18n merges the approvals files", () => {
  it.each(["en", "ar"] as const)("%s messages carry every top-level key", (locale) => {
    const files = locale === "en" ? enFiles : arFiles;
    const merged = i18n.global.getLocaleMessage(locale) as Messages;
    for (const messages of Object.values(files)) {
      for (const key of Object.keys(messages)) {
        expect(merged, `${locale} lacks ${key}`).toHaveProperty(key);
      }
    }
  });

  it("keeps the app's own messages", () => {
    expect(i18n.global.getLocaleMessage("en")).toHaveProperty("login");
    expect(i18n.global.getLocaleMessage("ar")).toHaveProperty("login");
  });

  it("answers the bulk reason key in both languages", () => {
    for (const locale of ["en", "ar"] as const) {
      expect(i18n.global.te("approvals.bulk.mixedTypes", locale)).toBe(true);
    }
  });
});
