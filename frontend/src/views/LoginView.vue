<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { login } from "@/api/auth";
import { useSessionStore } from "@/stores/session";
import { ApiError, NetworkError } from "@/app/frappe";
import { NATIVE_VERSION } from "@/app/native-version";
import Icon from "@/components/Icon.vue";

const router = useRouter();
const session = useSessionStore();

const email = ref("");
const password = ref("");
const error = ref("");
const busy = ref(false);
const showPassword = ref(false);

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
  <div class="auth-wrap">
    <div class="auth">
      <div class="brand">
        <div class="brand-mark"><Icon name="truck" :size="28" /></div>
        <h1>Van Sale</h1>
        <p class="muted small">Sign in to continue</p>
      </div>

      <form class="card stack" @submit.prevent="onSubmit" novalidate>
        <label class="field">
          <span class="label">Email</span>
          <input
            v-model="email"
            type="email"
            autocomplete="email"
            inputmode="email"
            required
            autofocus
            :disabled="busy"
            placeholder="you@company.com"
          />
        </label>
        <label class="field">
          <span class="label">Password</span>
          <div class="pw-wrap">
            <input
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              autocomplete="current-password"
              required
              :disabled="busy"
              placeholder="••••••••"
            />
            <button
              type="button"
              class="pw-toggle"
              @click="showPassword = !showPassword"
              tabindex="-1"
              :aria-label="showPassword ? 'Hide password' : 'Show password'"
            >{{ showPassword ? "Hide" : "Show" }}</button>
          </div>
        </label>

        <p class="error" :class="{ 'is-empty': !error }" role="alert">{{ error || '\u00a0' }}</p>

        <button class="submit" type="submit" :disabled="busy">
          {{ busy ? "Signing in…" : "Continue" }}
        </button>
      </form>

      <p class="ver muted xsmall">v{{ NATIVE_VERSION }}</p>
    </div>
  </div>
</template>

<style scoped>
.auth-wrap {
  min-height: 100svh;
  display: grid;
  place-items: center;
  padding: calc(1.25rem + env(safe-area-inset-top)) 1.5rem calc(1.25rem + env(safe-area-inset-bottom));
  background:
    radial-gradient(ellipse 70% 40% at 50% 0%,
      color-mix(in srgb, var(--primary) 14%, transparent) 0%,
      transparent 65%),
    var(--bg);
}
.auth {
  width: 100%;
  max-width: 22rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.brand { text-align: center; display: flex; flex-direction: column; align-items: center; gap: 0.35rem; }
.brand-mark {
  width: 3rem; height: 3rem;
  border-radius: var(--radius-lg);
  background: var(--primary);
  color: var(--primary-ink);
  display: grid; place-items: center;
  box-shadow: var(--shadow-float);
  margin-bottom: 0.35rem;
}
.brand h1 { margin: 0; font-size: var(--text-xl); letter-spacing: -0.02em; }

.card {
  padding: 1.25rem;
  border-radius: var(--radius-lg);
  display: flex; flex-direction: column; gap: 0.85rem;
  box-shadow: var(--shadow-md);
}

.field { display: flex; flex-direction: column; gap: 0.35rem; }
.label { font-size: var(--text-sm); color: var(--text-muted); font-weight: 500; }

.pw-wrap { position: relative; }
.pw-toggle {
  position: absolute;
  top: 50%;
  inset-inline-end: 0.4rem;
  transform: translateY(-50%);
  background: transparent;
  color: var(--primary);
  font-size: var(--text-xs);
  font-weight: 600;
  padding: 0.35rem 0.55rem;
  min-height: auto;
  border-radius: var(--radius-sm);
}
.pw-toggle:hover { background: var(--primary-soft); }

.error { margin: 0; min-height: 1.25rem; line-height: 1.25rem; }
.error.is-empty { visibility: hidden; }

.submit { min-height: 3rem; font-size: var(--text-base); }

.ver { text-align: center; margin: 0; }
</style>
