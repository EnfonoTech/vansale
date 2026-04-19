<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { NATIVE_VERSION } from "@/app/native-version";
import { isNative } from "@/app/platform";

const { t } = useI18n();
const envLabel = computed(() => (isNative() ? t("dashboard.env_native") : t("dashboard.env_web")));
</script>

<template>
  <header class="top-bar">
    <span class="title">{{ t("app.title") }}</span>
    <span class="meta">{{ envLabel }} · v{{ NATIVE_VERSION }}</span>
  </header>
</template>

<style scoped>
.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.875rem 1rem;
  background: var(--primary);
  color: #fff;
  font-weight: 600;
}
.title {
  font-size: 1rem;
}
.meta {
  font-size: 0.75rem;
  opacity: 0.85;
  font-weight: 500;
}
</style>
