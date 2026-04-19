<script setup lang="ts">
import { computed, onMounted, watch } from "vue";
import { useRouter } from "vue-router";
import { useOnline } from "@/app/online";
import { useSyncStore } from "@/stores/sync";

const router = useRouter();
const online = useOnline();
const sync = useSyncStore();

onMounted(() => {
  void sync.refresh();
});

// When we come back online, kick a drain automatically. Mirrors the
// pattern in frappe-vue-pwa §4.9.
watch(online, async (nowOnline) => {
  if (nowOnline) await sync.requestDrain();
});

const label = computed(() => {
  if (sync.draining) return "Syncing…";
  if (!online.value) return `${sync.pending} offline`;
  if (sync.pending === 0) return "Up to date";
  return `${sync.pending} pending`;
});

const tone = computed(() =>
  !online.value ? "offline" : sync.lastError ? "warn" : sync.pending === 0 ? "ok" : "info",
);

function onTap() {
  if (sync.pending > 0 || sync.lastError) {
    void router.push({ name: "sync-errors" });
  } else if (online.value) {
    void sync.requestDrain();
  }
}
</script>

<template>
  <button type="button" class="sync-badge" :data-tone="tone" @click="onTap">
    <span class="dot" />
    <span class="text">{{ label }}</span>
  </button>
</template>

<style scoped>
.sync-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.28rem 0.65rem;
  background: rgba(255, 255, 255, 0.18);
  color: #fff;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 600;
  border: none;
}
.dot {
  width: 0.55rem;
  height: 0.55rem;
  border-radius: 50%;
  background: #fff;
}
.sync-badge[data-tone="ok"] .dot {
  background: #a7f3d0;
}
.sync-badge[data-tone="warn"] .dot {
  background: #fde68a;
}
.sync-badge[data-tone="offline"] {
  background: rgba(0, 0, 0, 0.25);
}
</style>
