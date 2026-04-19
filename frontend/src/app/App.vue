<script setup lang="ts">
import TopAppBar from "@/components/TopAppBar.vue";
</script>

<template>
  <div class="app-root">
    <TopAppBar />
    <main class="app-main">
      <RouterView v-slot="{ Component }">
        <component :is="Component" />
      </RouterView>
    </main>
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
  padding: 1rem;
  max-width: 32rem;
  width: 100%;
  margin: 0 auto;
}
</style>
