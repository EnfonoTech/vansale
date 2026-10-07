<script setup lang="ts">
/** Edit (or add) a customer's mobile and email — its primary Contact. */
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { customerLabel, detail, saveContact } from "@/api/customer";
import { ApiError } from "@/app/frappe";
import { useToastStore } from "@/stores/toasts";
import Icon from "@/components/Icon.vue";

const route = useRoute();
const router = useRouter();
const toasts = useToastStore();

const customerName = computed(() => String(route.params.name ?? ""));
const title = ref("");
const mobileNo = ref("");
const emailId = ref("");
const busy = ref(false);

onMounted(async () => {
  try {
    const c = await detail(customerName.value);
    title.value = customerLabel(c);
    mobileNo.value = c.mobile_no ?? "";
    emailId.value = c.email_id ?? "";
  } catch (e) {
    toasts.error(e instanceof Error ? e.message : String(e));
  }
});

async function submit() {
  busy.value = true;
  try {
    await saveContact({
      customer: customerName.value,
      mobile_no: mobileNo.value.trim(),
      email_id: emailId.value.trim(),
    });
    toasts.success("Contact saved");
    void router.replace({ name: "customer-detail", params: { name: customerName.value } });
  } catch (e) {
    toasts.error(
      e instanceof ApiError ? e.serverMessage ?? e.message
        : e instanceof Error ? e.message : String(e),
    );
  } finally {
    busy.value = false;
  }
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
        <span class="tiny">Email</span>
        <input type="email" v-model="emailId" inputmode="email" />
      </label>
    </section>
    <button class="submit" type="button" :disabled="busy" @click="submit">
      <Icon name="check" :size="18" /> {{ busy ? "Saving…" : "Save contact" }}
    </button>
  </div>
</template>

<style scoped>
.field { display: flex; flex-direction: column; gap: 0.3rem; }
</style>
