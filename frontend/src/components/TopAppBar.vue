<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import { useI18n } from "vue-i18n";
import { NATIVE_VERSION } from "@/app/native-version";
import { isNative } from "@/app/platform";
import SyncBadge from "./SyncBadge.vue";

const { t } = useI18n();
const route = useRoute();
const envLabel = computed(() => (isNative() ? t("dashboard.env_native") : t("dashboard.env_web")));
const showSync = computed(() => route.name && route.name !== "login" && route.name !== "pin");
</script>

<template>
  <header class="top-bar">
    <span class="title">{{ t("app.title") }}</span>
    <div class="right">
      <SyncBadge v-if="showSync" />
      <span class="meta">{{ envLabel }} · v{{ NATIVE_VERSION }}</span>
    </div>
  </header>
</template>

<style scoped>
.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  background: var(--primary);
  color: #fff;
  font-weight: 600;
  gap: 0.5rem;
}
.title {
  font-size: 1rem;
}
.right {
  display: flex;
  align-items: center;
  gap: 0.55rem;
}
.meta {
  font-size: 0.72rem;
  opacity: 0.85;
  font-weight: 500;
}
</style>
