import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { createI18n } from "vue-i18n";
import en from "@/locales/approvals/en/detail.json";
import ar from "@/locales/approvals/ar/detail.json";

type Tree = { [key: string]: string | Tree };

function flatten(tree: Tree, prefix = ""): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(tree)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") out[path] = value;
    else Object.assign(out, flatten(value, path));
  }
  return out;
}

const english = flatten(en as Tree);
const arabic = flatten(ar as Tree);

/** The files that ask for these strings. */
const SOURCES = ["components/ApprovalActionSheet.vue", "components/ForwardSheet.vue", "views/ApprovalDetailView.vue", "features/approvals/detail-display.ts"];

function source(path: string): string {
  // `pnpm test` runs from frontend/.
  return readFileSync(resolve(process.cwd(), "src", path), "utf8");
}

/** Keys the code builds from a value: the part after the prefix is one of these. */
const DYNAMIC: Record<string, string[]> = {
  "approvalsDetail.attach.": ["type", "empty", "tooLarge"],
  "approvalsDetail.priority.": ["Low", "Medium", "High", "Critical"],
  "approvalsDetail.route.": ["done", "current", "upcoming"],
};

describe("detail strings", () => {
  it("has the same keys in English and Arabic", () => {
    expect(Object.keys(arabic).sort()).toEqual(Object.keys(english).sort());
  });

  it("has no empty string", () => {
    for (const [key, value] of [...Object.entries(english), ...Object.entries(arabic)]) {
      expect(value.trim(), key).not.toBe("");
    }
  });

  it("keeps the same placeholders in both languages", () => {
    const names = (text: string) => (text.match(/\{(\w+)\}/g) ?? []).sort();
    for (const key of Object.keys(english)) expect(names(arabic[key]), key).toEqual(names(english[key]));
  });

  it("defines every key the screen, sheets and helpers ask for", () => {
    const used = new Set<string>();
    for (const path of SOURCES) {
      for (const match of source(path).matchAll(/["'`](approvalsDetail\.[A-Za-z0-9_.]+)(\$\{[^}]*\})?/g)) {
        const [, key, dynamic] = match;
        if (dynamic) {
          const prefix = key;
          const options = DYNAMIC[prefix];
          expect(options, `unlisted dynamic key ${prefix}...`).toBeDefined();
          for (const option of options) used.add(prefix + option);
        } else {
          used.add(key);
        }
      }
    }
    expect(used.size).toBeGreaterThan(40);
    for (const key of used) {
      expect(english[key], `en ${key}`).toBeDefined();
      expect(arabic[key], `ar ${key}`).toBeDefined();
    }
  });

  it("leaves no string unused", () => {
    const code = SOURCES.map(source).join("\n");
    for (const key of Object.keys(english)) {
      const dynamicPrefix = Object.keys(DYNAMIC).find((prefix) => key.startsWith(prefix));
      if (dynamicPrefix) continue;
      expect(code.includes(key), `unused ${key}`).toBe(true);
    }
  });

  it("compiles every message in both languages", () => {
    const params = { name: "Mariam K.", action: "Approve", count: 3, text: "mar", from: "Pending", to: "Approved" };
    for (const [locale, flat] of [["en", english], ["ar", arabic]] as const) {
      const i18n = createI18n({ legacy: false, locale, messages: { [locale]: { ...nest(flat) } } });
      for (const key of Object.keys(flat)) {
        const text = i18n.global.t(key, params, 3);
        expect(text, `${locale} ${key}`).not.toBe(key);
        expect(text, `${locale} ${key}`).not.toMatch(/\{\w+\}/);
      }
    }
  });
});

function nest(flat: Record<string, string>): Tree {
  const root: Tree = {};
  for (const [path, value] of Object.entries(flat)) {
    const parts = path.split(".");
    let node = root;
    for (const part of parts.slice(0, -1)) node = (node[part] ??= {}) as Tree;
    node[parts[parts.length - 1]] = value;
  }
  return root;
}
