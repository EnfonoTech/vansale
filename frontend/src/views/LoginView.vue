<script setup lang="ts">
/**
 * Login — industrial-cockpit aesthetic. Dark canvas, dot grid, asymmetric
 * brand, underline-only inputs. Survives customer theming through
 * `--primary`; everything else is locally scoped.
 */
import { ref, onMounted } from "vue";
import { useRouter } from "vue-router";
import { login } from "@/api/auth";
import { useSessionStore } from "@/stores/session";
import { ApiError, NetworkError } from "@/app/frappe";
import { isOnline } from "@/app/online";
import { NATIVE_VERSION } from "@/app/native-version";
import Icon from "@/components/Icon.vue";

const router = useRouter();
const session = useSessionStore();

const email = ref("");
const password = ref("");
const error = ref("");
const busy = ref(false);
const showPassword = ref(false);
const online = ref(true);

onMounted(() => { online.value = isOnline(); });

async function onSubmit() {
  if (busy.value) return;
  error.value = "";
  busy.value = true;
  try {
    const res = await login(email.value.trim(), password.value);
    session.setLogin({
      user: res.user,
      fullName: res.full_name,
      email: email.value.trim(),
      language: res.language,
    });
    await router.replace({ name: "pin" });
  } catch (err) {
    if (err instanceof ApiError) error.value = err.serverMessage ?? "Incorrect email or password";
    else if (err instanceof NetworkError) error.value = "Offline — try again when connected";
    else error.value = "Incorrect email or password";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="cockpit">
    <div class="canvas-bg" aria-hidden="true">
      <div class="glow" />
      <div class="dots" />
      <div class="horizon" />
    </div>

    <header class="top-bar">
      <div class="brand-chip">
        <div class="brand-mark"><Icon name="truck" :size="18" /></div>
        <div class="brand-text">
          <span class="wordmark">VANSALE</span>
          <span class="subword">FIELD OPS</span>
        </div>
      </div>
      <div class="status-row">
        <span class="chip" :data-tone="online ? 'live' : 'offline'">
          <span class="dot" />{{ online ? 'ONLINE' : 'OFFLINE' }}
        </span>
        <span class="chip muted">v{{ NATIVE_VERSION }}</span>
      </div>
    </header>

    <main class="stage">
      <div class="headline">
        <span class="eyebrow">0<span class="slash">/</span>1 — AUTHENTICATION</span>
        <h1 class="title">
          Sign<br />
          <em>in.</em>
        </h1>
        <p class="lede">Verify your identity to continue to the van terminal.</p>
      </div>

      <form class="form" @submit.prevent="onSubmit" novalidate>
        <div class="field">
          <label class="lbl" for="f-email">
            <span class="lbl-no">01</span>
            <span>Email address</span>
          </label>
          <input
            id="f-email"
            v-model="email"
            type="email"
            autocomplete="email"
            inputmode="email"
            required
            autofocus
            :disabled="busy"
            placeholder="rep@company.com"
          />
        </div>

        <div class="field">
          <label class="lbl" for="f-pwd">
            <span class="lbl-no">02</span>
            <span>Password</span>
            <button
              type="button"
              class="reveal"
              @click="showPassword = !showPassword"
              tabindex="-1"
            >{{ showPassword ? 'HIDE' : 'SHOW' }}</button>
          </label>
          <input
            id="f-pwd"
            v-model="password"
            :type="showPassword ? 'text' : 'password'"
            autocomplete="current-password"
            required
            :disabled="busy"
            placeholder="••••••••"
          />
        </div>

        <p class="err" :class="{ 'is-empty': !error }" role="alert">
          <Icon v-if="error" name="alert" :size="14" />
          <span>{{ error || '\u00a0' }}</span>
        </p>

        <button class="cta" type="submit" :disabled="busy">
          <span class="cta-label">{{ busy ? 'AUTHENTICATING' : 'PROCEED' }}</span>
          <span class="cta-icon">
            <Icon v-if="!busy" name="chevron-right" :size="20" />
            <span v-else class="spinner" />
          </span>
        </button>
      </form>
    </main>

    <footer class="foot">
      <span class="foot-line"></span>
      <span class="foot-text">ENFONO · VAN SALE TERMINAL</span>
      <span class="foot-line"></span>
    </footer>
  </div>
</template>

<style scoped>
/*
 * Cockpit shell — self-contained, dark-first, customer-primary accent.
 * Locally scoped variables override the app's light theme inside this
 * view only; app-level tokens stay untouched. 100svh so soft keyboard
 * doesn't shove the layout.
 */
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
    1.25rem
    calc(0.9rem + env(safe-area-inset-bottom));
  overflow: hidden;
  font-family: var(--font-sans);
}

/* Canvas: radial accent glow, dotted grid, horizon line. */
.canvas-bg { position: absolute; inset: 0; pointer-events: none; z-index: 0; }
.canvas-bg .glow {
  position: absolute; inset: 0;
  background:
    radial-gradient(ellipse 60% 40% at 20% 10%,
      color-mix(in srgb, var(--accent) 40%, transparent) 0%,
      transparent 60%),
    radial-gradient(ellipse 80% 50% at 85% 90%,
      color-mix(in srgb, var(--accent) 22%, transparent) 0%,
      transparent 65%),
    linear-gradient(180deg, var(--ink) 0%, var(--ink-2) 60%, var(--ink) 100%);
}
.canvas-bg .dots {
  position: absolute; inset: 0;
  background-image: radial-gradient(circle, rgba(255,255,255,0.065) 1px, transparent 1px);
  background-size: 22px 22px;
  mask-image: radial-gradient(ellipse 80% 70% at 50% 50%, #000 30%, transparent 90%);
  -webkit-mask-image: radial-gradient(ellipse 80% 70% at 50% 50%, #000 30%, transparent 90%);
}
.canvas-bg .horizon {
  position: absolute; left: 0; right: 0; bottom: 38%;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--line-strong) 50%, transparent);
}

/* Top bar */
.top-bar {
  position: relative; z-index: 1;
  display: flex; justify-content: space-between; align-items: center;
  gap: 0.5rem;
}
.brand-chip { display: flex; align-items: center; gap: 0.55rem; }
.brand-mark {
  width: 2.1rem; height: 2.1rem;
  display: grid; place-items: center;
  background: var(--accent);
  color: var(--accent-ink);
  border-radius: 0.45rem;
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 50%, transparent),
              0 8px 24px color-mix(in srgb, var(--accent) 30%, transparent);
  transform: rotate(-4deg);
}
.brand-text { display: flex; flex-direction: column; line-height: 1; }
.wordmark {
  font-family: var(--font-display);
  font-weight: 800;
  letter-spacing: 0.14em;
  font-size: 0.82rem;
}
.subword {
  font-size: 0.56rem;
  letter-spacing: 0.28em;
  color: var(--fg-faint);
  margin-top: 0.18rem;
  font-weight: 600;
}

.status-row { display: flex; gap: 0.35rem; }
.chip {
  display: inline-flex; align-items: center; gap: 0.3rem;
  font-size: 0.58rem;
  letter-spacing: 0.22em;
  font-weight: 700;
  padding: 0.25rem 0.5rem;
  border: 1px solid var(--line);
  border-radius: 2px;
  color: var(--fg-muted);
  background: rgba(255,255,255,0.02);
}
.chip.muted { color: var(--fg-faint); }
.chip[data-tone="live"] { color: #5eead4; border-color: rgba(94,234,212,0.3); }
.chip[data-tone="offline"] { color: #fbbf24; border-color: rgba(251,191,36,0.3); }
.chip .dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 6px currentColor;
  animation: pulse 2.4s ease-in-out infinite;
}
@keyframes pulse { 50% { opacity: 0.4; } }

/* Stage (asymmetric, left-weighted) */
.stage {
  position: relative; z-index: 1;
  display: flex; flex-direction: column; justify-content: center;
  gap: 1.75rem;
  padding: 1.25rem 0;
}

.headline { max-width: 28rem; }
.eyebrow {
  display: inline-block;
  font-size: 0.62rem;
  letter-spacing: 0.32em;
  font-weight: 700;
  color: var(--fg-faint);
  margin-bottom: 1rem;
  padding: 0.25rem 0 0.25rem 0.65rem;
  border-left: 2px solid var(--accent);
}
.eyebrow .slash { color: var(--accent); margin: 0 0.15rem; }
.title {
  font-family: var(--font-display);
  font-weight: 800;
  font-size: clamp(2.6rem, 12vw, 4.2rem);
  line-height: 0.95;
  letter-spacing: -0.04em;
  margin: 0;
  color: var(--fg);
}
.title em {
  font-style: italic;
  font-weight: 500;
  background: linear-gradient(135deg, var(--accent) 0%, color-mix(in srgb, var(--accent) 60%, #fff) 100%);
  -webkit-background-clip: text; background-clip: text;
  color: transparent;
}
.lede {
  margin: 0.9rem 0 0;
  font-size: 0.88rem;
  color: var(--fg-muted);
  max-width: 22rem;
  line-height: 1.5;
}

/* Form */
.form { display: flex; flex-direction: column; gap: 1.1rem; }
.field { display: flex; flex-direction: column; gap: 0.55rem; position: relative; }
.lbl {
  display: flex; align-items: center; gap: 0.5rem;
  font-size: 0.6rem;
  letter-spacing: 0.24em;
  font-weight: 700;
  color: var(--fg-muted);
  text-transform: uppercase;
}
.lbl-no {
  color: var(--fg-faint);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.1em;
  border: 1px solid var(--line);
  padding: 0.1rem 0.3rem;
  border-radius: 2px;
  font-size: 0.54rem;
}
.reveal {
  margin-inline-start: auto;
  background: transparent;
  color: var(--fg-muted);
  padding: 0.15rem 0.4rem;
  min-height: auto;
  font-size: 0.58rem;
  letter-spacing: 0.22em;
  border: 1px solid var(--line);
  border-radius: 2px;
}
.reveal:hover { color: var(--fg); border-color: var(--line-strong); }

.field input {
  background: transparent;
  border: none;
  border-bottom: 1px solid var(--line-strong);
  border-radius: 0;
  padding: 0.6rem 0;
  color: var(--fg);
  font-size: 1.05rem;
  font-weight: 500;
  letter-spacing: -0.005em;
  transition: border-color var(--dur-fast) var(--ease);
}
.field input::placeholder { color: var(--fg-faint); font-weight: 400; }
.field input:focus-visible {
  outline: none;
  border-bottom-color: var(--accent);
  box-shadow: 0 1px 0 0 var(--accent);
}
.field input:disabled { opacity: 0.5; }
.field input:-webkit-autofill,
.field input:-webkit-autofill:focus {
  -webkit-text-fill-color: var(--fg);
  -webkit-box-shadow: 0 0 0 1000px var(--ink) inset;
  transition: background-color 5000s;
}

.err {
  display: flex; align-items: center; gap: 0.4rem;
  margin: 0;
  min-height: 1.2rem;
  font-size: 0.78rem;
  color: #fca5a5;
  letter-spacing: -0.002em;
}
.err.is-empty { visibility: hidden; }

/* CTA — rectangular, tactile, asymmetric arrow */
.cta {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: stretch;
  gap: 0;
  padding: 0;
  background: var(--accent);
  color: var(--accent-ink);
  border-radius: 2px;
  min-height: 3.4rem;
  font-family: var(--font-display);
  box-shadow:
    0 0 0 1px color-mix(in srgb, var(--accent) 50%, transparent),
    0 18px 40px -10px color-mix(in srgb, var(--accent) 55%, transparent);
  transition: transform var(--dur-fast) var(--ease), box-shadow var(--dur) var(--ease);
  overflow: hidden;
  position: relative;
}
.cta::before {
  content: "";
  position: absolute; inset: 0;
  background: linear-gradient(120deg, transparent 0%, rgba(255,255,255,0.18) 50%, transparent 100%);
  transform: translateX(-100%);
  transition: transform 0.7s var(--ease);
}
.cta:hover::before { transform: translateX(100%); }
.cta:active { transform: scale(0.98); }
.cta:disabled { opacity: 0.7; cursor: wait; }
.cta-label {
  padding: 0 1.15rem;
  display: grid; place-items: center;
  font-weight: 700;
  font-size: 0.82rem;
  letter-spacing: 0.24em;
  text-align: center;
}
.cta-icon {
  display: grid; place-items: center;
  width: 3.4rem;
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
}
.foot-line { height: 1px; background: var(--line); }
.foot-text { white-space: nowrap; }

/* RTL friendly: flip the rotation */
[dir="rtl"] .brand-mark { transform: rotate(4deg); }
[dir="rtl"] .title { text-align: right; }

/* Reduce motion */
@media (prefers-reduced-motion: reduce) {
  .chip .dot { animation: none; }
  .cta::before { display: none; }
}
</style>
