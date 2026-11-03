<script setup lang="ts">
/** New lead / edit lead. A lead needs a person's name or a company name. */
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { leadDetail, leadOptions, saveLead, updateLead, type LeadInput, type LeadOptions } from "@/api/lead";
import { ApiError } from "@/app/frappe";
import { useToastStore } from "@/stores/toasts";
import Icon from "@/components/Icon.vue";

const props = defineProps<{ name?: string }>();
const router = useRouter();
const toasts = useToastStore();
const isEdit = computed(() => Boolean(props.name));

const form = reactive<Required<Pick<LeadInput, "lead_name" | "company_name" | "mobile_no" | "email_id" | "source" | "territory" | "city" | "status" | "note">>>({
  lead_name: "", company_name: "", mobile_no: "", email_id: "", source: "", territory: "", city: "", status: "Lead", note: "",
});
const opts = ref<LeadOptions>({ sources: [], territories: [], statuses: [] });
const busy = ref(false);

onMounted(async () => {
  try { opts.value = await leadOptions(); } catch { /* the pick lists are optional */ }
  if (!props.name) return;
  try {
    const d = await leadDetail(props.name);
    Object.assign(form, {
      lead_name: d.lead_name ?? "", company_name: d.company_name ?? "", mobile_no: d.mobile_no ?? "",
      email_id: d.email_id ?? "", source: d.source ?? "", territory: d.territory ?? "",
      city: d.city ?? "", status: d.status, note: "",
    });
  } catch (e) {
    toasts.error(e instanceof Error ? e.message : String(e));
    void router.replace({ name: "leads" });
  }
});

async function onSave() {
  if (!form.lead_name.trim() && !form.company_name.trim()) {
    toasts.warn("Enter the person's name or the company name");
    return;
  }
  busy.value = true;
  try {
    const res = props.name
      ? await updateLead(props.name, { ...form })
      : await saveLead({ ...form, status: undefined });
    toasts.success(props.name ? "Lead updated" : `Lead ${res.name} saved`);
    void router.replace({ name: "lead-detail", params: { name: res.name } });
  } catch (e) {
    toasts.error(e instanceof ApiError ? e.serverMessage ?? e.message : e instanceof Error ? e.message : String(e));
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <form class="stack" @submit.prevent="onSave">
    <section class="card stack">
      <label class="field"><span class="label">Contact name</span>
        <input v-model="form.lead_name" autocomplete="off" /></label>
      <label class="field"><span class="label">Company</span>
        <input v-model="form.company_name" autocomplete="off" /></label>
      <label class="field"><span class="label">Mobile</span>
        <input v-model="form.mobile_no" type="tel" inputmode="tel" autocomplete="off" /></label>
      <label class="field"><span class="label">Email</span>
        <input v-model="form.email_id" type="email" inputmode="email" autocomplete="off" /></label>
      <label class="field"><span class="label">City</span>
        <input v-model="form.city" autocomplete="off" /></label>
    </section>

    <section class="card stack">
      <label v-if="opts.sources.length" class="field"><span class="label">Source</span>
        <select v-model="form.source"><option value="">—</option>
          <option v-for="s in opts.sources" :key="s" :value="s">{{ s }}</option></select></label>
      <label v-if="opts.territories.length" class="field"><span class="label">Territory</span>
        <select v-model="form.territory"><option value="">—</option>
          <option v-for="t in opts.territories" :key="t" :value="t">{{ t }}</option></select></label>
      <label v-if="isEdit" class="field"><span class="label">Status</span>
        <select v-model="form.status">
          <option v-for="s in opts.statuses" :key="s" :value="s">{{ s }}</option></select></label>
      <label class="field"><span class="label">{{ isEdit ? "Add a note" : "Note" }}</span>
        <textarea v-model="form.note" rows="3" /></label>
    </section>

    <button class="submit" type="submit" :disabled="busy">
      <Icon name="check" :size="18" /> {{ busy ? "Saving…" : isEdit ? "Save changes" : "Save lead" }}
    </button>
  </form>
</template>

<style scoped>
.field { display: flex; flex-direction: column; gap: 0.3rem; }
.label { font-size: var(--text-sm); color: var(--text-muted); font-weight: 500; }
.submit { min-height: 3.25rem; font-size: var(--text-base); }
</style>
