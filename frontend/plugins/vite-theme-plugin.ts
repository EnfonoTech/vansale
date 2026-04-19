import type { Plugin } from "vite";
import { defaultTokens, tokensToCss } from "./theme-utils";

interface ThemePluginOptions {
  customer?: string;
}

/**
 * Injects customer-specific CSS custom properties and an app title into
 * the built `index.html` at transform time. Full icon/splash generation
 * happens later via `scripts/generate-customer-assets.mjs` (Phase 5).
 */
export function themePlugin(options: ThemePluginOptions = {}): Plugin {
  const customer = options.customer ?? "demo";
  return {
    name: "vansale-theme",
    transformIndexHtml(html) {
      const tokens = defaultTokens();
      const title = process.env.CUSTOMER_APP_TITLE ?? "Van Sale";
      const style = `<style id="vansale-theme">
:root {
${tokensToCss(tokens)}
  --customer: "${customer}";
}
</style>`;
      return html
        .replace(/<title>.*<\/title>/, `<title>${title}</title>`)
        .replace("</head>", `${style}\n</head>`);
    },
  };
}
