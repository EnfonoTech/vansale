<script setup lang="ts">
/**
 * Global confirm modal — one instance lives at the app root and reads
 * from `useConfirmStore`. Every destructive action in the app should
 * route through `confirm.ask()` instead of `window.confirm()`; this
 * keeps the UI themed, branded, and — critically — consistent across
 * web + native (the browser's native confirm dialog renders very
 * differently on Android WebView vs. iOS Safari vs. desktop Chrome).
 */
import { watch, onMounted, onBeforeUnmount } from "vue";
import { useConfirmStore } from "@/stores/confirm";
import Icon from "./Icon.vue";

const confirm = useConfirmStore();

function onCancel() {
  confirm._close(false);
}
function onOk() {
  confirm._close(true);
}

// ESC key dismisses (matches the browser confirm UX we're replacing).
function onKey(e: KeyboardEvent) {
  if (!confirm.open) return;
  if (e.key === "Escape") onCancel();
  else if (e.key === "Enter") onOk();
}

onMounted(() => window.addEventListener("keydown", onKey));
onBeforeUnmount(() => window.removeEventListener("keydown", onKey));

// Lock body scroll while open — keeps the modal from feeling detached
// when the user's finger drifts outside the card on mobile.
watch(
  () => confirm.open,
  (open) => {
    document.body.style.overflow = open ? "hidden" : "";
  },
);
</script>

<template>
  <Teleport to="body">
    <transition name="confirm">
      <div v-if="confirm.open" class="confirm-overlay" @click.self="onCancel">
        <div class="confirm-card" role="dialog" aria-modal="true" :aria-labelledby="'confirm-title'">
          <div class="head" :class="{ danger: confirm.options.danger }">
            <div class="icon-wrap">
              <Icon
                :name="confirm.options.danger ? 'alert' : 'check'"
                :size="22"
              />
            </div>
            <h3 id="confirm-title">{{ confirm.options.title }}</h3>
          </div>
          <p v-if="confirm.options.message" class="message">{{ confirm.options.message }}</p>
          <div class="actions">
            <button type="button" class="cancel" @click="onCancel">
              {{ confirm.options.cancelText || 'Cancel' }}
            </button>
            <button
              type="button"
              class="ok"
              :class="{ danger: confirm.options.danger }"
              @click="onOk"
            >
              {{ confirm.options.confirmText || 'Confirm' }}
            </button>
          </div>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<style scoped>
.confirm-overlay {
  position: fixed;
  inset: 0;
  background: color-mix(in srgb, black 55%, transparent);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
  z-index: 1000;
  display: grid;
  place-items: center;
  padding: 1.25rem;
  padding-top: calc(1.25rem + env(safe-area-inset-top));
  padding-bottom: calc(1.25rem + env(safe-area-inset-bottom));
}
.confirm-card {
  width: 100%;
  max-width: 22rem;
  background: var(--surface);
  border-radius: var(--radius-lg);
  padding: 1.25rem;
  box-shadow: var(--shadow-float);
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}

.head {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.head h3 {
  margin: 0;
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text);
}
.icon-wrap {
  width: 2.5rem;
  height: 2.5rem;
  border-radius: 999px;
  display: grid;
  place-items: center;
  background: var(--primary-soft);
  color: var(--primary);
  flex-shrink: 0;
}
.head.danger .icon-wrap {
  background: color-mix(in srgb, var(--danger) 15%, transparent);
  color: var(--danger);
}

.message {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--text-sm);
  line-height: 1.45;
}

.actions {
  display: grid;
  grid-template-columns: 1fr 1.2fr;
  gap: 0.6rem;
  margin-top: 0.25rem;
}
.cancel,
.ok {
  all: unset;
  cursor: pointer;
  min-height: 2.85rem;
  border-radius: var(--radius);
  font-weight: 600;
  font-size: var(--text-sm);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  transition: background var(--dur-fast) var(--ease), opacity var(--dur-fast) var(--ease);
}
.cancel {
  background: var(--surface-muted);
  color: var(--text);
}
.cancel:active {
  opacity: 0.7;
}
.ok {
  background: var(--primary);
  color: var(--primary-ink, white);
}
.ok.danger {
  background: var(--danger);
  color: white;
}
.ok:active {
  opacity: 0.85;
}

.confirm-enter-from,
.confirm-leave-to {
  opacity: 0;
}
.confirm-enter-active,
.confirm-leave-active {
  transition: opacity var(--dur) var(--ease);
}
.confirm-enter-from .confirm-card,
.confirm-leave-to .confirm-card {
  transform: translateY(12px) scale(0.98);
}
.confirm-enter-active .confirm-card,
.confirm-leave-active .confirm-card {
  transition: transform var(--dur) var(--ease);
}
</style>
