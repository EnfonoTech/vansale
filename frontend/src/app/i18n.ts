import { createI18n } from "vue-i18n";
import en from "@/locales/en.json";
import ar from "@/locales/ar.json";

const defaultLocale = (import.meta.env.VITE_DEFAULT_LOCALE as string) || "en";

export const i18n = createI18n({
  legacy: false,
  locale: defaultLocale,
  fallbackLocale: "en",
  messages: { en, ar },
});

export function setLocale(locale: "en" | "ar"): void {
  i18n.global.locale.value = locale;
  document.documentElement.setAttribute("dir", locale === "ar" ? "rtl" : "ltr");
  document.documentElement.setAttribute("lang", locale);
}
