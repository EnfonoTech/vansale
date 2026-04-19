<script setup lang="ts">
import { computed, ref } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { loginWithPin, setupPin } from "@/api/auth";
import { configDefaults } from "@/api/me";
import { useSessionStore } from "@/stores/session";
import { ApiError, NetworkError } from "@/app/frappe";
import { isOnline } from "@/app/online";

const router = useRouter();
const session = useSessionStore();
const { t } = useI18n();

// If the session knows no email, we can't do PIN flows — bounce to login.
if (!session.email) {
  void router.replace({ name: "login" });
}

// Decide mode: if there is no stored credentials pair on this device we
// treat this as a setup; otherwise it's an unlock.
const mode = ref<"setup" | "unlock">(session.pinVerifiedAt === null ? "setup" : "unlock");

const pin = ref("");
const confirm = ref("");
const error = ref("");
const busy = ref(false);

const heading = computed(() =>
  mode.value === "setup" ? t("pin.setup_heading") : t("pin.unlock_heading"),
);
const hint = computed(() =>
  mode.value === "setup" ? t("pin.hint_setup") : t("pin.hint_unlock"),
);
const submitLabel = computed(() =>
  mode.value === "setup" ? t("pin.submit_setup") : t("pin.submit_unlock"),
);

function isValidPin(v: string): boolean {
  return /^\d{4,8}$/.test(v);
}

async function onSubmit() {
  if (busy.value) return;
  error.value = "";
  if (!isValidPin(pin.value)) {
    error.value = t("pin.invalid");
    return;
  }
  if (mode.value === "setup" && pin.value !== confirm.value) {
    error.value = t("pin.mismatch");
    return;
  }
  busy.value = true;
  try {
    if (mode.value === "setup") {
      await setupPin(pin.value);
    } else {
      await loginWithPin(session.email ?? "", pin.value);
    }
    session.markPinVerified();
    // Pull fresh Vansale Configuration defaults so forms can pre-fill.
    if (isOnline()) {
      try {
        const defaults = await configDefaults();
        session.setDefaults(defaults);
      } catch {
        // Non-fatal — stored defaults from the last online session remain.
      }
    }
    await router.replace({ name: "dashboard" });
  } catch (err) {
    if (err instanceof ApiError) {
      error.value = err.serverMessage ?? t("pin.wrong");
    } else if (err instanceof NetworkError) {
      error.value = t("common.offline");
    } else {
      error.value = t("pin.wrong");
    }
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
  <section class="card stack">
    <h1>{{ heading }}</h1>
    <p class="muted">{{ hint }}</p>
    <form class="stack" @submit.prevent="onSubmit">
      <label class="stack" style="gap: 0.25rem">
        <span class="muted">PIN</span>
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
        />
      </label>
      <label v-if="mode === 'setup'" class="stack" style="gap: 0.25rem">
        <span class="muted">Confirm PIN</span>
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
      <p v-if="error" class="error">{{ error }}</p>
      <button type="submit" :disabled="busy">
        {{ busy ? t("common.loading") : submitLabel }}
      </button>
    </form>
    <button class="ghost" type="button" @click="signInAgain">
      {{ t("pin.forgot") }}
    </button>
  </section>
</template>
