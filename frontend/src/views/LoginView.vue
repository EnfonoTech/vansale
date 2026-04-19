<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { login } from "@/api/auth";
import { useSessionStore } from "@/stores/session";
import { ApiError, NetworkError } from "@/app/frappe";

const router = useRouter();
const session = useSessionStore();
const { t } = useI18n();

const email = ref("");
const password = ref("");
const error = ref("");
const busy = ref(false);

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
    if (err instanceof ApiError) {
      error.value = err.serverMessage ?? t("login.error_generic");
    } else if (err instanceof NetworkError) {
      error.value = t("common.offline");
    } else {
      error.value = t("login.error_generic");
    }
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="card stack">
    <h1>{{ t("login.heading") }}</h1>
    <form class="stack" @submit.prevent="onSubmit">
      <label class="stack" style="gap: 0.25rem">
        <span class="muted">{{ t("login.email") }}</span>
        <input
          v-model="email"
          type="email"
          autocomplete="email"
          inputmode="email"
          required
          :disabled="busy"
        />
      </label>
      <label class="stack" style="gap: 0.25rem">
        <span class="muted">{{ t("login.password") }}</span>
        <input
          v-model="password"
          type="password"
          autocomplete="current-password"
          required
          :disabled="busy"
        />
      </label>
      <p v-if="error" class="error">{{ error }}</p>
      <button type="submit" :disabled="busy">
        {{ busy ? t("common.loading") : t("login.submit") }}
      </button>
    </form>
  </section>
</template>
