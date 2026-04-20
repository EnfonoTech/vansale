<script setup lang="ts">
import { useToastStore } from "@/stores/toasts";
import Icon from "./Icon.vue";

const toasts = useToastStore();
</script>

<template>
  <Teleport to="body">
    <div class="toast-stack" role="status" aria-live="polite">
      <transition-group name="toast">
        <div
          v-for="t in toasts.items"
          :key="t.id"
          class="toast"
          :data-tone="t.tone"
          @click="toasts.dismiss(t.id)"
        >
          <Icon :name="t.tone === 'success' ? 'check' : t.tone === 'danger' ? 'alert' : 'sync'" :size="18" />
          <span>{{ t.message }}</span>
        </div>
      </transition-group>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-stack {
  position: fixed;
  inset-inline: 0;
  bottom: calc(var(--bottom-nav-height) + 0.5rem + var(--safe-bottom));
  z-index: 100;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
  padding: 0 1rem;
  pointer-events: none;
}
.toast {
  pointer-events: auto;
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.65rem 0.95rem;
  background: var(--text);
  color: var(--surface);
  border-radius: var(--radius-pill);
  box-shadow: var(--shadow-lg);
  font-size: var(--text-sm);
  font-weight: 500;
  max-width: 28rem;
}
.toast[data-tone="success"] { background: var(--success); }
.toast[data-tone="danger"] { background: var(--danger); }
.toast[data-tone="warning"] { background: var(--warning); }

.toast-enter-from { opacity: 0; transform: translateY(10px); }
.toast-enter-active { transition: all var(--dur) var(--ease); }
.toast-leave-to { opacity: 0; transform: translateY(-4px); }
.toast-leave-active { transition: all var(--dur) var(--ease); }
</style>
