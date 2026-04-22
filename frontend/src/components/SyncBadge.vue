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

// Capacity pressure outranks everything except an actual drain error —
// a queue that's atCap is about to start rejecting user work, so the
// badge must show red even when we're merely "info" otherwise.
const tone = computed(() => {
  if (!online.value) return "offline";
  if (sync.capacity?.atCap) return "danger";
  if (sync.lastError) return "warn";
  if (sync.capacity?.nearCap) return "warn";
  if (sync.pending === 0) return "ok";
  return "info";
});

const capacityHint = computed(() => {
  const c = sync.capacity;
  if (!c) return "";
  if (c.atCap) return `Queue full (${c.count}/${c.cap}) — go online to drain`;
  if (c.nearCap) return `${c.count}/${c.cap} queued — drain soon`;
  return "";
});

function onTap() {
  if (sync.pending > 0 || sync.lastError) {
    void router.push({ name: "sync-errors" });
  } else if (online.value) {
    void sync.requestDrain();
  }
}
</script>

<template>
  <button
    type="button"
    class="sync-badge"
    :data-tone="tone"
    :title="capacityHint || undefined"
    @click="onTap"
  >
    <span class="dot" />
    <span class="text">{{ label }}</span>
    <span v-if="sync.capacity?.atCap || sync.capacity?.nearCap" class="cap-chip">
      {{ sync.capacity.count }}/{{ sync.capacity.cap }}
    </span>
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
.sync-badge[data-tone="danger"] {
  background: rgba(220, 38, 38, 0.85);
}
.sync-badge[data-tone="danger"] .dot {
  background: #fee2e2;
}
.sync-badge[data-tone="offline"] {
  background: rgba(0, 0, 0, 0.25);
}
.cap-chip {
  font-size: 0.62rem;
  padding: 0.05rem 0.35rem;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.25);
  font-variant-numeric: tabular-nums;
}
</style>
