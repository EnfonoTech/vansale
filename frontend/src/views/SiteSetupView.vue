<script setup lang="ts">
/**
 * First-run server picker (APK only).
 *
 * The APK ships without a hardcoded server unless the customer build baked
 * `VITE_API_BASE` in, so the very first screen asks which Frappe site to
 * talk to. The URL is probed BEFORE it is saved — a typo that gets stored
 * would leave every later screen failing with a bare network error and no
 * way back, since the login screen has no address field.
 *
 * The probe deliberately bypasses `apiCall`: that helper resolves its base
 * from `apiBase()`, which is exactly the value we are still validating.
 */
import { ref } from "vue";
import { useRouter } from "vue-router";
import { normalizeSiteUrl, setSiteUrl, siteUrl } from "@/app/platform";
import { NATIVE_VERSION } from "@/app/native-version";
import BrandMark from "@/components/BrandMark.vue";
import Icon from "@/components/Icon.vue";

const router = useRouter();
const appTitle = __APP_TITLE__;

const input = ref(siteUrl() ?? "");
const error = ref("");
const busy = ref(false);

const PROBE_TIMEOUT_MS = 12000;

function withTimeout(url: string): Promise<Response> {
  // AbortController rather than relying on the platform timeout: a wrong
  // host behind a firewall can hang for minutes, and the driver just sees
  // a dead spinner.
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS);
  return fetch(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal: ctrl.signal,
  }).finally(() => clearTimeout(timer));
}

/**
 * Confirm the address is reachable and is a Frappe site.
 *
 * `vansale.api.auth.site_info` only exists from v1.0.26, so a failure there
 * does NOT mean "wrong address" — during a rollout the app is newer than the
 * server it points at. Measured against a v1.0.17 site, the missing method
 * answers **417**, not 404, so any non-OK status has to fall through rather
 * than a specific code. `frappe.ping` exists in every Frappe release, so it
 * is the real reachability test; features needing the new endpoints fail
 * later with their own messages, which beats an unpassable setup screen.
 */
async function probe(origin: string): Promise<void> {
  const res = await withTimeout(`${origin}/api/method/vansale.api.auth.site_info`);
  if (res.ok) {
    const body = (await res.json()) as { message?: { app?: string } };
    if (body?.message?.app !== "vansale") {
      throw new Error("That address is not a Van Sale server.");
    }
    return;
  }

  const ping = await withTimeout(`${origin}/api/method/frappe.ping`);
  if (!ping.ok) {
    throw new Error("Reached that address, but it is not a Van Sale server.");
  }
  // Frappe answers {"message":"pong"} — anything else is some other service
  // that happens to return 200 on that path.
  const pingBody = (await ping.json().catch(() => null)) as { message?: string } | null;
  if (pingBody?.message !== "pong") {
    throw new Error("Reached that address, but it is not a Van Sale server.");
  }
}

async function connect() {
  error.value = "";
  busy.value = true;
  try {
    const origin = normalizeSiteUrl(input.value);
    await probe(origin);
    await setSiteUrl(origin);
    await router.replace({ name: "login" });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      error.value = "No answer from that address. Check the spelling and your signal.";
    } else if (err instanceof TypeError) {
      // fetch() rejects with TypeError for DNS / TLS / offline failures.
      error.value = "Could not reach that address. Check the spelling and your signal.";
    } else {
      error.value = err instanceof Error ? err.message : "Could not connect";
    }
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="auth-wrap">
    <div class="auth">
      <div class="brand">
        <div class="brand-mark"><BrandMark :size="28" /></div>
        <h1>{{ appTitle }}</h1>
        <p class="muted small">Connect to your company server</p>
      </div>

      <form class="stack" @submit.prevent="connect">
        <label class="field">
          <span class="label">Server address</span>
          <input
            v-model="input"
            type="url"
            inputmode="url"
            autocapitalize="none"
            autocorrect="off"
            spellcheck="false"
            placeholder="van.company.com"
            :disabled="busy"
          />
        </label>

        <p v-if="error" class="error-box">{{ error }}</p>
        <p v-else class="muted xsmall">
          Ask your office for this address. You only enter it once.
        </p>

        <button class="primary" type="submit" :disabled="busy">
          <Icon v-if="!busy" name="truck" :size="18" />
          <span>{{ busy ? "Connecting…" : "Connect" }}</span>
        </button>
      </form>

      <p class="muted xsmall version">v{{ NATIVE_VERSION }}</p>
    </div>
  </div>
</template>

<style scoped>
.auth-wrap {
  min-height: 100dvh;
  display: grid;
  place-items: center;
  padding: 1.25rem;
}
.auth {
  width: min(26rem, 100%);
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}
.brand {
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.35rem;
}
.brand-mark {
  display: grid;
  place-items: center;
  width: 3.25rem;
  height: 3.25rem;
  border-radius: var(--radius);
  background: var(--primary-soft);
  color: var(--primary);
}
.brand h1 {
  margin: 0;
  font-size: var(--text-xl);
  letter-spacing: -0.02em;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.label {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-muted);
}
.error-box {
  margin: 0;
  padding: 0.6rem 0.7rem;
  border-radius: var(--radius);
  background: var(--danger-soft, color-mix(in srgb, red 12%, transparent));
  color: var(--danger, #b91c1c);
  font-size: 0.85rem;
}
.version {
  text-align: center;
  margin: 0;
}
</style>
