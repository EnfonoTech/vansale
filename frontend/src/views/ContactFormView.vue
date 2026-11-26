<script setup lang="ts">
/** Edit (or add) a customer's mobile, second phone and email — its primary
 *  Contact — and attach documents. Steel Force bills a credit customer only
 *  with two numbers, an email and a document on file; the salesman can add
 *  them here instead of waiting for the office. */
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { attachDocument, customerLabel, detail, saveContact } from "@/api/customer";
import { ApiError } from "@/app/frappe";
import { useToastStore } from "@/stores/toasts";
import Icon from "@/components/Icon.vue";

const route = useRoute();
const router = useRouter();
const toasts = useToastStore();

const customerName = computed(() => String(route.params.name ?? ""));
const title = ref("");
const mobileNo = ref("");
const phone2 = ref("");
const emailId = ref("");
const documents = ref(0);
const busy = ref(false);
const uploading = ref(false);
// Save stays off until the contact has loaded: a blank box means "remove" on
// the server, so saving early (or after a failed load) wiped the mobile / email.
const loaded = ref(false);

onMounted(async () => {
  try {
    const c = await detail(customerName.value);
    title.value = customerLabel(c);
    mobileNo.value = c.mobile_no ?? "";
    phone2.value = c.phone_2 ?? "";
    emailId.value = c.email_id ?? "";
    documents.value = c.documents ?? 0;
    loaded.value = true;
  } catch (e) {
    toasts.error(e instanceof Error ? e.message : String(e));
  }
});

function errorText(e: unknown): string {
  return e instanceof ApiError ? e.serverMessage ?? e.message : e instanceof Error ? e.message : String(e);
}

async function submit() {
  busy.value = true;
  try {
    await saveContact({
      customer: customerName.value,
      mobile_no: mobileNo.value.trim(),
      email_id: emailId.value.trim(),
      phone_2: phone2.value.trim(),
    });
    toasts.success("Contact saved");
    void router.replace({ name: "customer-detail", params: { name: customerName.value } });
  } catch (e) {
    toasts.error(errorText(e));
  } finally {
    busy.value = false;
  }
}

/** A document photo is sent at once: it does not wait for "Save contact". */
function onDocumentPicked(ev: Event) {
  const input = ev.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  if (file.size > 8 * 1024 * 1024) { toasts.warn("The document is too large (8 MB at most)"); return; }
  const reader = new FileReader();
  reader.onload = async () => {
    uploading.value = true;
    try {
      await attachDocument(customerName.value, { filename: file.name, data: String(reader.result) });
      documents.value += 1;
      toasts.success("Document attached");
    } catch (e) {
      toasts.error(errorText(e));
    } finally {
      uploading.value = false;
      input.value = "";
    }
  };
  reader.readAsDataURL(file);
}
</script>

<template>
  <div class="stack">
    <section class="card stack">
      <h3 style="margin:0">{{ title }}</h3>
      <label class="field">
        <span class="tiny">Mobile</span>
        <input type="tel" v-model="mobileNo" inputmode="tel" placeholder="+966…" />
      </label>
      <label class="field">
        <span class="tiny">Second phone</span>
        <input type="tel" v-model="phone2" inputmode="tel" />
      </label>
      <label class="field">
        <span class="tiny">Email</span>
        <input type="email" v-model="emailId" inputmode="email" />
      </label>
    </section>
    <button class="submit" type="button" :disabled="busy || !loaded" @click="submit">
      <Icon name="check" :size="18" /> {{ busy ? "Saving…" : "Save contact" }}
    </button>
    <section class="card stack">
      <h3 style="margin:0">Documents</h3>
      <p class="muted xsmall" style="margin:0">
        {{ documents ? `${documents} on file.` : "None on file." }} A photo of the CR, VAT certificate or ID is attached at once.
      </p>
      <label class="field">
        <span class="tiny">{{ uploading ? "Sending…" : "Add a document photo" }}</span>
        <input type="file" accept="image/*,application/pdf" capture="environment" :disabled="uploading" @change="onDocumentPicked" />
      </label>
    </section>
  </div>
</template>

<style scoped>
.field { display: flex; flex-direction: column; gap: 0.3rem; }
</style>
