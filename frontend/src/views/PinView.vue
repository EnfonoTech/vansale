<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { loginWithPin, setupPin } from "@/api/auth";
import { configDefaults } from "@/api/me";
import { useSessionStore } from "@/stores/session";
import { ApiError, NetworkError } from "@/app/frappe";
import { isOnline } from "@/app/online";
import Icon from "@/components/Icon.vue";

const router = useRouter();
const session = useSessionStore();

if (!session.email) {
  void router.replace({ name: "login" });
}

type Mode = "setup" | "unlock";
type Step = "enter" | "confirm";

const mode = ref<Mode>(session.pinVerifiedAt === null ? "setup" : "unlock");
const step = ref<Step>("enter");
const pin = ref("");
const firstPin = ref("");
const error = ref("");
const busy = ref(false);
const shake = ref(false);

const PIN_LEN = 4;

const heading = computed(() => {
  if (mode.value === "unlock") return "Enter PIN";
  return step.value === "enter" ? "Set a PIN" : "Confirm PIN";
});
const hint = computed(() => {
  if (mode.value === "unlock") return session.email ?? "";
  return step.value === "enter" ? "Choose 4 digits" : "Re-enter to confirm";
});

const dots = computed(() => {
  const n = pin.value.length;
  return Array.from({ length: PIN_LEN }, (_, i) => (i < n ? "full" : "empty"));
});

function buzz() {
  shake.value = true;
  window.setTimeout(() => { shake.value = false; }, 380);
}

function press(d: string) {
  if (busy.value || pin.value.length >= PIN_LEN) return;
  pin.value += d;
  if (error.value) error.value = "";
  // Auto-advance once all digits entered — keeps the UX snappy and prevents the
  // user wondering if they also need to hit the "Unlock" button.
  if (pin.value.length === PIN_LEN) void submit();
}
function del() {
  if (busy.value) return;
  pin.value = pin.value.slice(0, -1);
  if (error.value) error.value = "";
}

function isValid(v: string): boolean { return new RegExp(`^\\d{${PIN_LEN}}$`).test(v); }

async function submit() {
  if (busy.value) return;
  if (!isValid(pin.value)) { error.value = `PIN must be ${PIN_LEN} digits`; buzz(); return; }

  if (mode.value === "setup" && step.value === "enter") {
    firstPin.value = pin.value;
    pin.value = "";
    step.value = "confirm";
    return;
  }
  if (mode.value === "setup" && step.value === "confirm" && pin.value !== firstPin.value) {
    error.value = "PINs do not match";
    buzz();
    pin.value = "";
    step.value = "enter";
    firstPin.value = "";
    return;
  }

  busy.value = true;
  try {
    if (mode.value === "setup") await setupPin(pin.value);
    else await loginWithPin(session.email ?? "", pin.value);
    session.markPinVerified();
    if (isOnline()) {
      try { session.setDefaults(await configDefaults()); } catch { /* non-fatal */ }
    }
    await router.replace({ name: "dashboard" });
  } catch (err) {
    if (err instanceof ApiError) error.value = err.serverMessage ?? "Incorrect PIN";
    else if (err instanceof NetworkError) error.value = "Offline";
    else error.value = "Incorrect PIN";
    buzz();
    pin.value = "";
  } finally {
    busy.value = false;
  }
}

function signInAgain() {
  session.logout();
  void router.replace({ name: "login" });
}

function onKey(e: KeyboardEvent) {
  if (busy.value) return;
  if (/^[0-9]$/.test(e.key)) { e.preventDefault(); press(e.key); }
  else if (e.key === "Backspace") { e.preventDefault(); del(); }
  else if (e.key === "Enter") { e.preventDefault(); void submit(); }
}

const cta = computed(() => {
  if (busy.value) return "Working…";
  if (mode.value === "setup" && step.value === "enter") return "Next";
  if (mode.value === "setup") return "Save PIN";
  return "Unlock";
});
</script>

<template>
  <div class="auth-wrap" @keydown="onKey" tabindex="-1">
    <div class="auth">
      <div class="brand">
        <div class="brand-mark"><Icon name="truck" :size="24" /></div>
        <h1>{{ heading }}</h1>
        <p class="muted small">{{ hint }}</p>
      </div>

      <div class="pin-card">
        <div class="pin-dots" :class="{ shake }">
          <span v-for="(s, i) in dots" :key="i" class="dot" :data-state="s" />
        </div>

        <p class="error" :class="{ 'is-empty': !error }" role="alert">{{ error || '\u00a0' }}</p>

        <div class="keypad">
          <button v-for="n in [1,2,3,4,5,6,7,8,9]" :key="n"
            type="button" class="key" :disabled="busy" @click="press(String(n))">{{ n }}</button>
          <span />
          <button type="button" class="key" :disabled="busy" @click="press('0')">0</button>
          <button type="button" class="key key-util" :disabled="busy || !pin" @click="del" aria-label="Delete">
            <Icon name="back" :size="18" />
          </button>
        </div>

        <button class="submit" type="button" :disabled="busy || pin.length < PIN_LEN" @click="submit">
          {{ cta }}
        </button>
      </div>

      <button class="ghost forgot" type="button" @click="signInAgain">Sign in with password instead</button>
    </div>
  </div>
</template>

<style scoped>
.auth-wrap {
  min-height: 100svh;
  display: grid;
  place-items: center;
  padding: calc(1.25rem + env(safe-area-inset-top)) 1rem calc(1.25rem + env(safe-area-inset-bottom));
  background:
    radial-gradient(ellipse 70% 40% at 50% 0%,
      color-mix(in srgb, var(--primary) 14%, transparent) 0%,
      transparent 65%),
    var(--bg);
  outline: none;
}
.auth {
  width: 100%;
  max-width: 22rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.brand { text-align: center; display: flex; flex-direction: column; align-items: center; gap: 0.3rem; }
.brand-mark {
  width: 2.6rem; height: 2.6rem;
  border-radius: var(--radius-lg);
  background: var(--primary);
  color: var(--primary-ink);
  display: grid; place-items: center;
  box-shadow: var(--shadow-float);
  margin-bottom: 0.25rem;
}
.brand h1 { margin: 0; font-size: var(--text-xl); letter-spacing: -0.02em; }

.pin-card {
  background: var(--surface);
  border-radius: var(--radius-lg);
  padding: 1.1rem;
  box-shadow: var(--shadow-md);
  display: flex; flex-direction: column; gap: 0.85rem;
}

.pin-dots { display: flex; justify-content: center; gap: 0.55rem; padding: 0.25rem 0; }
.pin-dots.shake { animation: shake 0.38s cubic-bezier(0.36, 0.07, 0.19, 0.97); }
@keyframes shake {
  10%, 90% { transform: translateX(-2px); }
  20%, 80% { transform: translateX(3px); }
  30%, 50%, 70% { transform: translateX(-6px); }
  40%, 60% { transform: translateX(6px); }
}
.dot {
  width: 11px; height: 11px;
  border-radius: 50%;
  border: 1.5px solid var(--border-strong);
  transition: all var(--dur-fast) var(--ease);
}
.dot[data-state="full"] {
  background: var(--primary);
  border-color: var(--primary);
  transform: scale(1.15);
}

.error { margin: 0; min-height: 1.1rem; font-size: var(--text-xs); text-align: center; }
.error.is-empty { visibility: hidden; }

.keypad {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.5rem;
}
.keypad > span { visibility: hidden; }
.key {
  background: var(--surface-muted);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  min-height: 3rem;
  font-size: 1.3rem;
  font-weight: 600;
  padding: 0;
  display: grid; place-items: center;
  transition: background var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease);
}
.key:hover:not(:disabled) { background: var(--surface-sunk); }
.key:active:not(:disabled) { transform: scale(0.96); background: var(--primary-soft); }
.key:disabled { opacity: 0.4; cursor: not-allowed; }
.key.key-util { color: var(--text-muted); }

.submit { min-height: 3rem; font-size: var(--text-base); margin-top: 0.1rem; }
.forgot { align-self: center; }

@media (max-height: 680px) {
  .key { min-height: 2.6rem; font-size: 1.15rem; }
}
</style>
