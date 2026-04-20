<script setup lang="ts">
/**
 * New customer form — Phase C.
 *
 * Per PDF 2026-04-20 §2:
 *  - B2B / B2C toggle
 *  - Address mandatory for B2B (address_line1 + city)
 *  - Address optional for B2C
 *  - Email, mobile, tax id optional
 *
 * Entry points:
 *  - Bottom-nav Customers → "New" button
 *  - Invoice form → "New" link near customer select (query: ?redirect=invoice)
 */
import { ref, computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { create as createCustomer } from "@/api/customer";
import { ApiError } from "@/app/frappe";
import { useToastStore } from "@/stores/toasts";
import Icon from "@/components/Icon.vue";

const router = useRouter();
const route = useRoute();
const toasts = useToastStore();

const customerType = ref<"b2c" | "b2b">("b2c");
const customerName = ref("");
const mobileNo = ref("");
const emailId = ref("");
const taxId = ref("");

const addressLine1 = ref("");
const addressLine2 = ref("");
const city = ref("");
const stateField = ref("");
const pincode = ref("");
const country = ref("");
// KSA ZATCA Phase 2 — building number is mandatory on B2B addresses.
const buildingNumber = ref("");
const additionalNumber = ref("");
const district = ref("");

const busy = ref(false);

const isB2B = computed(() => customerType.value === "b2b");
const canSubmit = computed(() => {
  if (!customerName.value.trim()) return false;
  if (isB2B.value) {
    if (!addressLine1.value.trim()) return false;
    if (!city.value.trim()) return false;
    if (!buildingNumber.value.trim()) return false;
  }
  return true;
});

const redirectTo = String(route.query.redirect ?? "");

async function submit() {
  if (!canSubmit.value) { toasts.warn("Fill mandatory fields"); return; }
  busy.value = true;
  try {
    const res = await createCustomer({
      customer_name: customerName.value.trim(),
      customer_type: customerType.value,
      mobile_no: mobileNo.value || undefined,
      email_id: emailId.value || undefined,
      tax_id: taxId.value || undefined,
      address_line1: addressLine1.value || undefined,
      address_line2: addressLine2.value || undefined,
      city: city.value || undefined,
      state: stateField.value || undefined,
      pincode: pincode.value || undefined,
      country: country.value || undefined,
      building_number: buildingNumber.value || undefined,
      additional_number: additionalNumber.value || undefined,
      district: district.value || undefined,
    });
    toasts.success(`Customer ${res.customer_name} created`);
    if (redirectTo === "invoice") {
      router.replace({ name: "invoice-new", query: { customer: res.name } });
    } else {
      router.replace({ name: "customer-detail", params: { name: res.name } });
    }
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
      <span class="label">Customer type</span>
      <div class="seg">
        <button type="button" class="seg-btn" :data-active="customerType === 'b2c'"
                @click="customerType = 'b2c'">
          <Icon name="user" :size="16" /> B2C (Individual)
        </button>
        <button type="button" class="seg-btn" :data-active="customerType === 'b2b'"
                @click="customerType = 'b2b'">
          <Icon name="customer" :size="16" /> B2B (Company)
        </button>
      </div>
    </section>

    <section class="card stack">
      <h3 style="margin:0">Basic</h3>
      <label class="field">
        <span class="tiny">Customer name *</span>
        <input type="text" v-model="customerName" placeholder="Name or company" />
      </label>
      <div class="two-col">
        <label class="field">
          <span class="tiny">Mobile</span>
          <input type="tel" v-model="mobileNo" inputmode="tel" placeholder="+966…" />
        </label>
        <label class="field">
          <span class="tiny">Email</span>
          <input type="email" v-model="emailId" inputmode="email" />
        </label>
      </div>
      <label class="field">
        <span class="tiny">Tax ID (VAT)</span>
        <input type="text" v-model="taxId" inputmode="numeric" />
      </label>
    </section>

    <section class="card stack">
      <div class="row-head">
        <h3 style="margin:0">Address</h3>
        <span v-if="isB2B" class="pill" data-tone="warning">Required for B2B · ZATCA</span>
        <span v-else class="muted xsmall">Optional</span>
      </div>
      <!--
        KSA ZATCA Phase 2 building number is 4 digits and appears before
        address line 1 on the printed invoice. We keep the 4-char maxlength
        as a soft nudge; strict validation happens server-side.
      -->
      <div class="two-col">
        <label class="field">
          <span class="tiny">Building no. {{ isB2B ? "*" : "" }}</span>
          <input
            type="text"
            v-model="buildingNumber"
            inputmode="numeric"
            maxlength="4"
            placeholder="4-digit"
          />
        </label>
        <label class="field">
          <span class="tiny">Additional no.</span>
          <input type="text" v-model="additionalNumber" inputmode="numeric" maxlength="4" />
        </label>
      </div>
      <label class="field">
        <span class="tiny">Address line 1 (street) {{ isB2B ? "*" : "" }}</span>
        <input type="text" v-model="addressLine1" />
      </label>
      <label class="field">
        <span class="tiny">Address line 2</span>
        <input type="text" v-model="addressLine2" />
      </label>
      <div class="two-col">
        <label class="field">
          <span class="tiny">District</span>
          <input type="text" v-model="district" />
        </label>
        <label class="field">
          <span class="tiny">City {{ isB2B ? "*" : "" }}</span>
          <input type="text" v-model="city" />
        </label>
      </div>
      <div class="two-col">
        <label class="field">
          <span class="tiny">Pincode</span>
          <input type="text" v-model="pincode" inputmode="numeric" maxlength="5" />
        </label>
        <label class="field">
          <span class="tiny">State / Region</span>
          <input type="text" v-model="stateField" />
        </label>
      </div>
      <label class="field">
        <span class="tiny">Country</span>
        <input type="text" v-model="country" placeholder="Saudi Arabia" />
      </label>
    </section>

    <button class="submit" type="button" :disabled="!canSubmit || busy" @click="submit">
      <Icon name="check" :size="18" />
      {{ busy ? "Saving…" : "Save customer" }}
    </button>
  </div>
</template>

<style scoped>
.field { display: flex; flex-direction: column; gap: 0.3rem; }
.label { font-size: var(--text-sm); color: var(--text-muted); font-weight: 500; }
.row-head { display: flex; justify-content: space-between; align-items: center; }
.tiny { font-size: 0.65rem; color: var(--text-faint); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }
.seg { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
.seg-btn {
  all: unset; cursor: pointer;
  padding: 0.55rem 0.75rem; border-radius: var(--radius-sm);
  background: var(--surface-muted); text-align: center;
  font-weight: 500; display: inline-flex; justify-content: center; align-items: center; gap: 0.35rem;
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}
.seg-btn[data-active="true"] { background: var(--primary); color: var(--on-primary, white); }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
.submit { min-height: 3.25rem; font-size: var(--text-base); }
</style>
