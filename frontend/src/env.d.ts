/// <reference types="vite/client" />

declare module "*.vue" {
  import type { DefineComponent } from "vue";
  const component: DefineComponent<{}, {}, any>;
  export default component;
}

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_DEFAULT_LOCALE?: string;
  readonly VITE_APP_TITLE?: string;
  readonly CUSTOMER_BUILD_TARGET?: "web" | "native";
  readonly CUSTOMER_NAME?: string;
  readonly CUSTOMER_APP_ID?: string;
  readonly CUSTOMER_APP_TITLE?: string;
  readonly CUSTOMER_THEME_PRIMARY?: string;
  readonly CUSTOMER_THEME_BG?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare const __BUILD_TARGET__: "web" | "native";
declare const __APP_VERSION__: string;
/** `CUSTOMER_APP_TITLE` baked in at build time; "Van Sale" when unset. */
declare const __APP_TITLE__: string;
