<script setup lang="ts">
/**
 * PIN entry — cockpit aesthetic matching LoginView. Numeric keypad so
 * the user never waits for the OS soft-keyboard, with slot dots that
 * fill as digits are typed. In `unlock` mode with a known PIN length
 * the form can be wired to auto-submit — for now it requires an
 * explicit tap to keep the 4–8 digit window honest.
 *
 * `setup` mode is two-step: enter PIN → confirm. Step is driven by
 * local state, not routes, so back-button leaves the auth flow.
 */
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { loginWithPin, setupPin } from "@/api/auth";
import { configDefaults } from "@/api/me";
import { useSessionStore } from "@/stores/session";
import { ApiError, NetworkError } from "@/app/frappe";
import { isOnline } from "@/app/online";
import { NATIVE_VERSION } from "@/app/native-version";
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
const firstPin = ref(""); // held during setup between enter→confirm
const error = ref("");
const busy = ref(false);
const shake = ref(false);

const MAX_LEN = 8;

const heading = computed(() => {
  if (mode.value === "unlock") return "Enter PIN";
  return step.value === "enter" ? "Set PIN" : "Confirm PIN";
});
const sub = computed(() => {
  if (mode.value === "unlock") return session.email ?? "";
  return step.value === "enter"
    ? "Choose 4 to 8 digits"
    : "Re-enter to confirm";
});

const dots = computed(() => {
  const slots = 6;
  const n = pin.value.length;
  return Array.from({ length: slots }, (_, i) =>
    i < n ? "full" : i === n ? "next" : "empty",
  );
});

function buzz() {
  shake.value = true;
  window.setTimeout(() => { shake.value = false; }, 380);
}

function press(d: string) {
  if (busy.value) return;
  if (pin.value.length >= MAX_LEN) return;
  pin.value += d;
  if (error.value) error.value = "";
}

function del() {
  if (busy.value) return;
  pin.value = pin.value.slice(0, -1);
  if (error.value) error.value = "";
}

function clear() {
  pin.value = "";
  error.value = "";
}

function isValid(v: string): boolean { return /^\d{4,8}$/.test(v); }

async function submit() {
  if (busy.value) return;
  if (!isValid(pin.value)) {
    error.value = "PIN must be 4 to 8 digits";
    buzz();
    return;
  }

  // Setup: two-step dance.
  if (mode.value === "setup" && step.value === "enter") {
    firstPin.value = pin.value;
    pin.value = "";
    step.value = "confirm";
    return;
  }
  if (mode.value === "setup" && step.value === "confirm") {
    if (pin.value !== firstPin.value) {
      error.value = "PINs do not match";
      buzz();
      pin.value = "";
      step.value = "enter";
      firstPin.value = "";
      return;
    }
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

// Physical keyboard support (web/PWA).
function onKey(e: KeyboardEvent) {
  if (busy.value) return;
  if (/^[0-9]$/.test(e.key)) { e.preventDefault(); press(e.key); }
  else if (e.key === "Backspace") { e.preventDefault(); del(); }
  else if (e.key === "Enter") { e.preventDefault(); void submit(); }
}
</script>

<template>
  <div class="cockpit" @keydown="onKey" tabindex="-1">
    <div class="canvas-bg" aria-hidden="true">
      <div class="glow" />
      <div class="dots" />
    </div>

    <header class="top-bar">
      <button class="back-btn" type="button" @click="signInAgain" aria-label="Sign in as another user">
        <Icon name="back" :size="18" />
      </button>
      <div class="user-chip">
        <span class="avatar">{{ (session.fullName || session.email || '?').slice(0, 1).toUpperCase() }}</span>
        <div class="who">
          <span class="name">{{ session.fullName || 'Signed in' }}</span>
          <span class="email">{{ session.email }}</span>
        </div>
      </div>
      <span class="chip muted">v{{ NATIVE_VERSION }}</span>
    </header>

    <main class="stage">
      <div class="headline">
        <span class="eyebrow">
          <span v-if="mode === 'setup'">{{ step === 'enter' ? '1' : '2' }}<span class="slash">/</span>2 — SETUP</span>
          <span v-else>UNLOCK</span>
        </span>
        <h1 class="title">{{ heading }}</h1>
        <p class="lede">{{ sub }}</p>
      </div>

      <div class="pin-slot" :class="{ shake }">
        <span
          v-for="(s, i) in dots"
          :key="i"
          class="slot"
          :data-state="s"
        />
      </div>

      <p class="err" :class="{ 'is-empty': !error }" role="alert">
        <Icon v-if="error" name="alert" :size="14" />
        <span>{{ error || '\u00a0' }}</span>
      </p>

      <div class="keypad" role="group" aria-label="Numeric keypad">
        <button v-for="n in [1,2,3,4,5,6,7,8,9]" :key="n"
          type="button" class="key" :disabled="busy" @click="press(String(n))">
          <span class="digit">{{ n }}</span>
        </button>
        <button type="button" class="key key-util" :disabled="busy || !pin" @click="clear" aria-label="Clear">
          <span class="util">CLR</span>
        </button>
        <button type="button" class="key" :disabled="busy" @click="press('0')">
          <span class="digit">0</span>
        </button>
        <button type="button" class="key key-util" :disabled="busy || !pin" @click="del" aria-label="Delete">
          <Icon name="back" :size="18" />
        </button>
      </div>

      <button class="cta" :disabled="busy || pin.length < 4" @click="submit" type="button">
        <span class="cta-label">
          <template v-if="busy">VERIFYING</template>
          <template v-else-if="mode === 'setup' && step === 'enter'">NEXT</template>
          <template v-else-if="mode === 'setup'">SAVE PIN</template>
          <template v-else>UNLOCK</template>
        </span>
        <span class="cta-icon">
          <Icon v-if="!busy" name="chevron-right" :size="20" />
          <span v-else class="spinner" />
        </span>
      </button>
    </main>

    <footer class="foot">
      <span class="foot-line"></span>
      <span class="foot-text">SECURE ENCLAVE · BCRYPT</span>
      <span class="foot-line"></span>
    </footer>
  </div>
</template>

<style scoped>
.cockpit {
  --ink: #07090f;
  --ink-2: #0d1220;
  --ink-3: #161c2d;
  --line: rgba(255, 255, 255, 0.08);
  --line-strong: rgba(255, 255, 255, 0.16);
  --fg: #e7ecf5;
  --fg-muted: rgba(231, 236, 245, 0.55);
  --fg-faint: rgba(231, 236, 245, 0.32);
  --accent: var(--primary);
  --accent-ink: var(--primary-ink);

  position: relative;
  min-height: 100svh;
  color: var(--fg);
  background: var(--ink);
  display: grid;
  grid-template-rows: auto 1fr auto;
  padding:
    calc(0.9rem + env(safe-area-inset-top))
    1.1rem
    calc(0.9rem + env(safe-area-inset-bottom));
  overflow: hidden;
  font-family: var(--font-sans);
  outline: none;
}

/* Canvas */
.canvas-bg { position: absolute; inset: 0; pointer-events: none; z-index: 0; }
.canvas-bg .glow {
  position: absolute; inset: 0;
  background:
    radial-gradient(ellipse 70% 40% at 50% 5%,
      color-mix(in srgb, var(--accent) 36%, transparent) 0%,
      transparent 65%),
    radial-gradient(ellipse 60% 50% at 50% 110%,
      color-mix(in srgb, var(--accent) 18%, transparent) 0%,
      transparent 60%),
    linear-gradient(180deg, var(--ink) 0%, var(--ink-2) 55%, var(--ink) 100%);
}
.canvas-bg .dots {
  position: absolute; inset: 0;
  background-image: radial-gradient(circle, rgba(255,255,255,0.06) 1px, transparent 1px);
  background-size: 22px 22px;
  mask-image: radial-gradient(ellipse 80% 70% at 50% 50%, #000 30%, transparent 90%);
  -webkit-mask-image: radial-gradient(ellipse 80% 70% at 50% 50%, #000 30%, transparent 90%);
}

/* Top bar */
.top-bar {
  position: relative; z-index: 1;
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 0.55rem;
}
.back-btn {
  width: 2.1rem; height: 2.1rem;
  min-height: auto;
  padding: 0;
  border-radius: 2px;
  background: rgba(255,255,255,0.04);
  color: var(--fg-muted);
  border: 1px solid var(--line);
  display: grid; place-items: center;
}
.back-btn:hover { color: var(--fg); border-color: var(--line-strong); }

.user-chip {
  display: flex; align-items: center; gap: 0.55rem;
  min-width: 0;
}
.avatar {
  width: 2.1rem; height: 2.1rem;
  display: grid; place-items: center;
  background: linear-gradient(135deg, var(--accent) 0%, color-mix(in srgb, var(--accent) 60%, #0b1120) 100%);
  color: var(--accent-ink);
  border-radius: 2px;
  font-family: var(--font-display);
  font-weight: 800;
  font-size: 0.85rem;
  letter-spacing: 0.04em;
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 45%, transparent);
}
.who { display: flex; flex-direction: column; min-width: 0; line-height: 1.1; }
.name {
  font-weight: 700;
  font-size: 0.72rem;
  letter-spacing: 0.04em;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.email {
  font-size: 0.58rem;
  letter-spacing: 0.08em;
  color: var(--fg-faint);
  margin-top: 0.12rem;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

.chip {
  display: inline-flex; align-items: center;
  font-size: 0.56rem;
  letter-spacing: 0.22em;
  font-weight: 700;
  padding: 0.25rem 0.5rem;
  border: 1px solid var(--line);
  border-radius: 2px;
  color: var(--fg-faint);
  background: rgba(255,255,255,0.02);
}

/* Stage */
.stage {
  position: relative; z-index: 1;
  display: flex; flex-direction: column;
  gap: 1.2rem;
  padding: 1rem 0 0.5rem;
}

.headline { text-align: center; margin-bottom: 0.5rem; }
.eyebrow {
  display: inline-block;
  font-size: 0.58rem;
  letter-spacing: 0.3em;
  font-weight: 700;
  color: var(--fg-faint);
  margin-bottom: 0.65rem;
  padding: 0.2rem 0.55rem;
  border: 1px solid var(--line);
  border-radius: 2px;
}
.eyebrow .slash { color: var(--accent); margin: 0 0.15rem; }
.title {
  font-family: var(--font-display);
  font-weight: 800;
  font-size: clamp(1.8rem, 7vw, 2.4rem);
  letter-spacing: -0.03em;
  margin: 0;
}
.lede {
  margin: 0.35rem 0 0;
  font-size: 0.78rem;
  color: var(--fg-muted);
  letter-spacing: 0.02em;
}

/* Slot dots */
.pin-slot {
  display: flex; justify-content: center; gap: 0.7rem;
  padding: 0.4rem 0;
}
.pin-slot.shake { animation: shake 0.38s cubic-bezier(0.36, 0.07, 0.19, 0.97); }
@keyframes shake {
  10%, 90% { transform: translateX(-2px); }
  20%, 80% { transform: translateX(4px); }
  30%, 50%, 70% { transform: translateX(-8px); }
  40%, 60% { transform: translateX(8px); }
}
.slot {
  width: 14px; height: 14px;
  border-radius: 50%;
  border: 1.5px solid var(--line-strong);
  transition: all var(--dur-fast) var(--ease);
  background: transparent;
}
.slot[data-state="full"] {
  background: var(--accent);
  border-color: var(--accent);
  box-shadow: 0 0 12px color-mix(in srgb, var(--accent) 70%, transparent);
  transform: scale(1.1);
}
.slot[data-state="next"] {
  border-color: var(--fg-muted);
  animation: blink 1.2s ease-in-out infinite;
}
@keyframes blink { 50% { opacity: 0.35; } }

.err {
  display: flex; justify-content: center; align-items: center; gap: 0.4rem;
  margin: 0;
  min-height: 1.2rem;
  font-size: 0.75rem;
  color: #fca5a5;
  letter-spacing: 0.01em;
}
.err.is-empty { visibility: hidden; }

/* Keypad */
.keypad {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.55rem;
  margin-top: auto;
  padding: 0.25rem 0;
}
.key {
  background: rgba(255,255,255,0.035);
  color: var(--fg);
  border: 1px solid var(--line);
  border-radius: 4px;
  min-height: 3.5rem;
  font-family: var(--font-display);
  padding: 0;
  display: grid; place-items: center;
  transition:
    background var(--dur-fast) var(--ease),
    border-color var(--dur-fast) var(--ease),
    transform var(--dur-fast) var(--ease);
  position: relative;
  overflow: hidden;
}
.key::after {
  content: "";
  position: absolute; inset: 0;
  background: radial-gradient(circle at center,
    color-mix(in srgb, var(--accent) 40%, transparent) 0%,
    transparent 60%);
  opacity: 0; transition: opacity 0.3s var(--ease);
  pointer-events: none;
}
.key:hover:not(:disabled) {
  background: rgba(255,255,255,0.06);
  border-color: var(--line-strong);
}
.key:active:not(:disabled) {
  transform: scale(0.96);
  border-color: var(--accent);
}
.key:active::after { opacity: 1; }
.key:disabled { opacity: 0.35; cursor: not-allowed; }
.key .digit {
  font-size: 1.45rem;
  font-weight: 600;
  letter-spacing: -0.02em;
}
.key.key-util {
  background: rgba(255,255,255,0.02);
  color: var(--fg-muted);
}
.key.key-util .util {
  font-size: 0.64rem;
  letter-spacing: 0.22em;
  font-weight: 700;
}

/* CTA — same vocab as Login */
.cta {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: stretch;
  gap: 0;
  padding: 0;
  background: var(--accent);
  color: var(--accent-ink);
  border-radius: 2px;
  min-height: 3.2rem;
  font-family: var(--font-display);
  box-shadow:
    0 0 0 1px color-mix(in srgb, var(--accent) 50%, transparent),
    0 18px 40px -10px color-mix(in srgb, var(--accent) 55%, transparent);
  transition: transform var(--dur-fast) var(--ease), opacity var(--dur) var(--ease);
  overflow: hidden;
  position: relative;
  margin-top: 0.3rem;
}
.cta::before {
  content: "";
  position: absolute; inset: 0;
  background: linear-gradient(120deg, transparent 0%, rgba(255,255,255,0.18) 50%, transparent 100%);
  transform: translateX(-100%);
  transition: transform 0.7s var(--ease);
}
.cta:hover:not(:disabled)::before { transform: translateX(100%); }
.cta:active:not(:disabled) { transform: scale(0.98); }
.cta:disabled { opacity: 0.4; cursor: not-allowed; }
.cta-label {
  padding: 0 1rem;
  display: grid; place-items: center;
  font-weight: 700;
  font-size: 0.8rem;
  letter-spacing: 0.24em;
  text-align: center;
}
.cta-icon {
  display: grid; place-items: center;
  width: 3.2rem;
  background: rgba(0,0,0,0.18);
  border-inline-start: 1px solid rgba(255,255,255,0.18);
}
.spinner {
  width: 1rem; height: 1rem;
  border: 2px solid rgba(255,255,255,0.35);
  border-top-color: var(--accent-ink);
  border-radius: 50%;
  animation: spin 0.75s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Footer */
.foot {
  position: relative; z-index: 1;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 0.6rem;
  font-size: 0.54rem;
  letter-spacing: 0.32em;
  color: var(--fg-faint);
  font-weight: 700;
  padding-top: 0.25rem;
}
.foot-line { height: 1px; background: var(--line); }
.foot-text { white-space: nowrap; }

@media (prefers-reduced-motion: reduce) {
  .slot[data-state="next"] { animation: none; }
  .cta::before { display: none; }
  .pin-slot.shake { animation: none; }
}

@media (max-height: 680px) {
  .title { font-size: 1.6rem; }
  .keypad { gap: 0.42rem; }
  .key { min-height: 2.9rem; }
  .key .digit { font-size: 1.2rem; }
}
</style>
