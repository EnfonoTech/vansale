<script setup lang="ts">
import { useI18n } from "vue-i18n";
import { useRouter } from "vue-router";
import { useSessionStore } from "@/stores/session";
import { logout } from "@/api/auth";
import { NATIVE_VERSION } from "@/app/native-version";
import { isNative } from "@/app/platform";

const session = useSessionStore();
const router = useRouter();
const { t } = useI18n();

async function onLogout() {
  try {
    await logout();
  } finally {
    session.logout();
    await router.replace({ name: "login" });
  }
}
</script>

<template>
  <section class="card stack">
    <h1>
      {{ t("dashboard.welcome", { name: session.fullName ?? session.user ?? "" }) }}
    </h1>
    <p class="muted">
      {{ isNative() ? t("dashboard.env_native") : t("dashboard.env_web") }}
      ·
      {{ t("dashboard.version", { v: NATIVE_VERSION }) }}
    </p>
    <p>{{ t("dashboard.coming_soon") }}</p>
    <button class="ghost" @click="onLogout">{{ t("nav.logout") }}</button>
  </section>
</template>
