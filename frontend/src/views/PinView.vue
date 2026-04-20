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

const mode = ref<"setup" | "unlock">(session.pinVerifiedAt === null ? "setup" : "unlock");
const pin = ref("");
const confirm = ref("");
const error = ref("");
const busy = ref(false);

const heading = computed(() => (mode.value === "setup" ? "Set your PIN" : "Enter your PIN"));
const hint = computed(() =>
  mode.value === "setup"
    ? "Choose a 4–8 digit PIN. You'll use it every time you open the app."
    : `Enter the PIN you set for ${session.email}`,
);

function isValidPin(v: string): boolean { return /^\d{4,8}$/.test(v); }

async function onSubmit() {
  if (busy.value) return;
  error.value = "";
  if (!isValidPin(pin.value)) { error.value = "PIN must be 4 to 8 digits"; return; }
  if (mode.value === "setup" && pin.value !== confirm.value) { error.value = "PINs do not match"; return; }
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
  } finally {
    busy.value = false;
  }
}

function signInAgain() {
  session.logout();
  void router.replace({ name: "login" });
}
</script>

<template>
  <div class="auth-wrap">
    <div class="auth">
      <div class="brand">
        <div class="brand-mark"><Icon name="truck" :size="26" /></div>
        <h1>{{ heading }}</h1>
        <p class="muted">{{ hint }}</p>
      </div>

      <form class="card stack" @submit.prevent="onSubmit">
        <label class="field">
          <span class="label">PIN</span>
          <input
            v-model="pin"
            type="password"
            inputmode="numeric"
            pattern="[0-9]*"
            autocomplete="one-time-code"
            minlength="4"
            maxlength="8"
            :disabled="busy"
            required
            autofocus
          />
        </label>
        <label v-if="mode === 'setup'" class="field">
          <span class="label">Confirm PIN</span>
          <input
            v-model="confirm"
            type="password"
            inputmode="numeric"
            pattern="[0-9]*"
            minlength="4"
            maxlength="8"
            :disabled="busy"
            required
          />
        </label>

        <p class="error" :class="{ 'is-empty': !error }">{{ error || '\u00a0' }}</p>

        <button class="submit" type="submit" :disabled="busy">
          {{ busy ? "Unlocking…" : (mode === "setup" ? "Save PIN" : "Unlock") }}
        </button>
      </form>

      <button class="ghost forgot" type="button" @click="signInAgain">Forgot PIN? Sign in with password</button>
    </div>
  </div>
</template>

<style scoped>
/*
 * See LoginView — viewport-centered compact layout. User feedback:
 * "2 fields shouldn't scroll". Shrunk brand mark + tightened gaps,
 * switched to `grid place-items: center` so the card sits mid-screen
 * with safe-area padding. `svh` prevents jumps when soft keyboard
 * opens.
 */
.auth-wrap {
  min-height: 100svh;
  display: grid;
  place-items: center;
  padding: calc(1rem + env(safe-area-inset-top)) 1.5rem calc(1rem + env(safe-area-inset-bottom));
  overflow: hidden;
}
.auth {
  width: 100%;
  max-width: 24rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.brand { text-align: center; display: flex; flex-direction: column; align-items: center; gap: 0.25rem; }
.brand-mark {
  width: 3rem; height: 3rem;
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, var(--primary) 0%, color-mix(in srgb, var(--primary) 75%, #0f172a) 100%);
  color: var(--primary-ink);
  display: grid; place-items: center;
  box-shadow: var(--shadow-float);
}
.brand h1 { margin: 0; font-size: var(--text-lg); }
.brand .muted { font-size: var(--text-xs); }

.field { display: flex; flex-direction: column; gap: 0.3rem; }
.label { font-size: var(--text-sm); color: var(--text-muted); font-weight: 500; }

.error { margin: 0; min-height: 1.25rem; line-height: 1.25rem; }
.error.is-empty { visibility: hidden; }

.submit { min-height: 3.25rem; font-size: var(--text-base); }

.forgot { align-self: center; }
</style>
