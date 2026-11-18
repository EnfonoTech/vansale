import { createI18n } from "vue-i18n";
import en from "@/locales/en.json";
import ar from "@/locales/ar.json";

type Messages = Record<string, unknown>;

/**
 * The approvals screens keep their strings in one JSON file each, under
 * `locales/approvals/<lang>/`, so that the people building different screens
 * never edit the same file. Every file adds its own top-level keys to the
 * language's messages; `locales/__tests__/approvals-keys.test.ts` checks that
 * the two languages have the same keys and that no key is defined twice.
 */
const approvalsEn = import.meta.glob("../locales/approvals/en/*.json", { eager: true, import: "default" });
const approvalsAr = import.meta.glob("../locales/approvals/ar/*.json", { eager: true, import: "default" });

/** `base` with the top-level keys of every module added (the files' names do not matter). */
function withModules<T extends Messages>(base: T, modules: Record<string, unknown>): T {
  return Object.keys(modules)
    .sort()
    .reduce<T>((merged, path) => ({ ...merged, ...(modules[path] as Messages) }), { ...base });
}

const defaultLocale = (import.meta.env.VITE_DEFAULT_LOCALE as string) || "en";

export const i18n = createI18n({
  legacy: false,
  locale: defaultLocale,
  fallbackLocale: "en",
  messages: {
    en: withModules(en, approvalsEn),
    ar: withModules(ar, approvalsAr),
  },
});

export function setLocale(locale: "en" | "ar"): void {
  i18n.global.locale.value = locale;
  document.documentElement.setAttribute("dir", locale === "ar" ? "rtl" : "ltr");
  document.documentElement.setAttribute("lang", locale);
}
