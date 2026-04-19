/**
 * White-label theme vars. Populated from `CUSTOMER_*` env at build time.
 * Keep this list small — it's injected into every page as CSS custom props.
 */
export interface ThemeTokens {
  primary: string;
  bg: string;
  surface: string;
  text: string;
  textMuted: string;
  success: string;
  warning: string;
  danger: string;
  radius: string;
}

export function defaultTokens(): ThemeTokens {
  return {
    primary: process.env.CUSTOMER_THEME_PRIMARY ?? "#2563eb",
    bg: process.env.CUSTOMER_THEME_BG ?? "#f8fafc",
    surface: "#ffffff",
    text: "#0f172a",
    textMuted: "#64748b",
    success: "#16a34a",
    warning: "#f59e0b",
    danger: "#dc2626",
    radius: "0.75rem",
  };
}

export function tokensToCss(tokens: ThemeTokens): string {
  return Object.entries(tokens)
    .map(([k, v]) => `  --${kebab(k)}: ${v};`)
    .join("\n");
}

function kebab(s: string): string {
  return s.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);
}
