<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { login } from "@/api/auth";
import { useSessionStore } from "@/stores/session";
import { ApiError, NetworkError } from "@/app/frappe";
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
        <div class="brand-mark"><Icon name="truck" :size="30" /></div>
        <h1>Van Sale</h1>
        <p class="muted small">Sign in to start your day</p>
      </div>

      <form class="card stack" @submit.prevent="onSubmit">
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
            />
            <button
              type="button"
              class="ghost small pw-toggle"
              @click="showPassword = !showPassword"
              tabindex="-1"
            >
              {{ showPassword ? "Hide" : "Show" }}
            </button>
          </div>
        </label>

        <p class="error" :class="{ 'is-empty': !error }">{{ error || '\u00a0' }}</p>

        <button class="submit" type="submit" :disabled="busy">
          {{ busy ? "Signing in…" : "Continue" }}
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
/*
 * Viewport-locked layout: fill `100svh` exactly and center the card.
 * User feedback — "2 fields shouldn't scroll". With the old top-anchored
 * `min-height` + large brand + 1.75rem gaps, the page spilled below the
 * fold on mid-sized phones. Now the wrapper is a grid with
 * `place-items: center` and an `overflow: hidden` so content stays in
 * one viewport; the brand shrinks, gaps are tight, and safe-area insets
 * are respected via `padding`. If the soft keyboard opens `svh` stays
 * put, so the card doesn't jump.
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
  gap: 1.1rem;
}
.brand { text-align: center; display: flex; flex-direction: column; align-items: center; gap: 0.25rem; }
.brand-mark {
  width: 3.25rem; height: 3.25rem;
  border-radius: var(--radius-lg);
  background: linear-gradient(135deg, var(--primary) 0%, color-mix(in srgb, var(--primary) 75%, #0f172a) 100%);
  color: var(--primary-ink);
  display: grid; place-items: center;
  box-shadow: var(--shadow-float);
  margin-bottom: 0.25rem;
}
.brand h1 { font-size: var(--text-lg); }
.brand h1 { margin: 0; }

.field { display: flex; flex-direction: column; gap: 0.3rem; }
.label { font-size: var(--text-sm); color: var(--text-muted); font-weight: 500; }

.pw-wrap { position: relative; }
.pw-toggle { position: absolute; top: 50%; inset-inline-end: 0.4rem; transform: translateY(-50%); font-size: var(--text-xs); }

/* Reserve the row so "now there's an error" doesn't push the button down. */
.error { margin: 0; min-height: 1.25rem; line-height: 1.25rem; }
.error.is-empty { visibility: hidden; }

.submit { min-height: 3.25rem; font-size: var(--text-base); }
</style>
