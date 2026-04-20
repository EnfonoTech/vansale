<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import TopAppBar from "@/components/TopAppBar.vue";
import BottomNav from "@/components/BottomNav.vue";
import Toasts from "@/components/Toasts.vue";

const route = useRoute();
const isChrome = computed(() => {
  const name = String(route.name ?? "");
  return !["login", "pin"].includes(name);
});
</script>

<template>
  <div class="app-root">
    <TopAppBar v-if="isChrome" />
    <main class="app-main" :class="{ 'app-main--chrome': isChrome }">
      <RouterView v-slot="{ Component }">
        <transition name="page" mode="out-in">
          <component :is="Component" />
        </transition>
      </RouterView>
    </main>
    <BottomNav v-if="isChrome" />
    <Toasts />
  </div>
</template>

<style>
.app-root {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  color: var(--text);
}
.app-main {
  flex: 1;
  width: 100%;
  max-width: var(--max-content);
  margin: 0 auto;
  padding: 1rem;
  padding-inline: 1rem;
}
.app-main--chrome {
  padding-bottom: calc(var(--bottom-nav-height) + 1rem + var(--safe-bottom));
}

.page-enter-from { opacity: 0; transform: translateY(6px); }
.page-enter-active { transition: all var(--dur) var(--ease); }
.page-leave-to { opacity: 0; transform: translateY(-2px); }
.page-leave-active { transition: all var(--dur-fast) var(--ease); }
</style>
