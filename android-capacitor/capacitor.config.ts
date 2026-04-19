import type { CapacitorConfig } from "@capacitor/cli";

// `appId` is replaced per-customer at build time by `scripts/build-customer.sh`
// (it rewrites this file + android/app/build.gradle's applicationId).
// Default is the demo app id.
const config: CapacitorConfig = {
  appId: process.env.CUSTOMER_APP_ID ?? "com.enfono.vansale.demo",
  appName: process.env.CUSTOMER_APP_TITLE ?? "Van Sale",
  webDir: "www",
  server: { androidScheme: "https", cleartext: false },
  plugins: {
    SplashScreen: {
      launchShowDuration: 600,
      backgroundColor: "#2563eb",
      showSpinner: false,
    },
    StatusBar: { backgroundColor: "#2563eb", style: "LIGHT" },
  },
};

export default config;
