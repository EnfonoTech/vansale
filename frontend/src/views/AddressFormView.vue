<script setup lang="ts">
/**
 * Edit a customer's address, or add one (no `address` param).
 *
 * KSA (ZATCA) rules are checked here for a quick message and again on the
 * server: building number 4 digits, postal code 5 digits; a B2B customer
 * needs street, building number, district, city and postal code.
 */
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { detail, saveAddress, type CustomerDetail } from "@/api/customer";
import { ApiError } from "@/app/frappe";
import { useSessionStore } from "@/stores/session";
import { useToastStore } from "@/stores/toasts";
import Icon from "@/components/Icon.vue";
import { ksaAddressErrors } from "@/features/van/ksa";

const route = useRoute();
const router = useRouter();
const session = useSessionStore();
const toasts = useToastStore();

const customerName = computed(() => String(route.params.name ?? ""));
const addressName = computed(() => String(route.params.address ?? ""));

const customer = ref<CustomerDetail | null>(null);
const addressLine1 = ref("");
const addressLine2 = ref("");
const buildingNumber = ref("");
const additionalNumber = ref("");
const district = ref("");
const city = ref("");
const pincode = ref("");
const stateField = ref("");
const country = ref("Saudi Arabia");
const phone = ref("");
const busy = ref(false);

const isB2B = computed(() => customer.value?.customer_type === "Company");

onMounted(async () => {
  try {
    customer.value = await detail(customerName.value);
    const a = customer.value.addresses.find((x) => x.name === addressName.value);
    if (a) {
      addressLine1.value = a.address_line1 ?? "";
      addressLine2.value = a.address_line2 ?? "";
      buildingNumber.value = a.building_number ?? "";
      additionalNumber.value = a.additional_number ?? "";
      district.value = a.district ?? "";
      city.value = a.city ?? "";
      pincode.value = a.pincode ?? "";
      stateField.value = a.state ?? "";
      country.value = a.country || "Saudi Arabia";
      phone.value = a.phone ?? "";
    }
  } catch (e) {
    toasts.error(e instanceof Error ? e.message : String(e));
  }
});

async function submit() {
  if (!addressLine1.value.trim() || !city.value.trim()) {
    toasts.warn("Street and city are required");
    return;
  }
  const errors = ksaAddressErrors({
    country: country.value,
    isB2B: isB2B.value,
    street: addressLine1.value,
    buildingNumber: buildingNumber.value,
    district: district.value,
    city: city.value,
    pincode: pincode.value,
  });
  if (errors.length) {
    toasts.warn(errors.join(" · "));
    return;
  }
  busy.value = true;
  try {
    await saveAddress({
      customer: customerName.value,
      address: addressName.value || undefined,
      address_line1: addressLine1.value.trim(),
      address_line2: addressLine2.value || undefined,
      city: city.value.trim(),
      state: stateField.value || undefined,
      pincode: pincode.value || undefined,
      country: country.value || undefined,
      building_number: buildingNumber.value || undefined,
      additional_number: additionalNumber.value || undefined,
      district: district.value || undefined,
      phone: phone.value || undefined,
    });
    toasts.success("Address saved");
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
      <div class="row-head">
        <h3 style="margin:0">{{ addressName ? "Edit address" : "New address" }}</h3>
        <span v-if="isB2B" class="pill" data-tone="warning">B2B · ZATCA</span>
      </div>
      <div class="two-col">
        <label class="field">
          <span class="tiny">Building no. {{ isB2B ? "*" : "" }}</span>
          <input type="text" v-model="buildingNumber" inputmode="numeric" maxlength="4" />
        </label>
        <label v-if="session.customerForm?.additional_number" class="field">
          <span class="tiny">Additional no.</span>
          <input type="text" v-model="additionalNumber" inputmode="numeric" maxlength="4" />
        </label>
      </div>
      <label class="field">
        <span class="tiny">Street *</span>
        <input type="text" v-model="addressLine1" />
      </label>
      <label class="field">
        <span class="tiny">Address line 2</span>
        <input type="text" v-model="addressLine2" />
      </label>
      <div class="two-col">
        <label class="field">
          <span class="tiny">District {{ isB2B ? "*" : "" }}</span>
          <input type="text" v-model="district" />
        </label>
        <label class="field">
          <span class="tiny">City *</span>
          <input type="text" v-model="city" />
        </label>
      </div>
      <div class="two-col">
        <label class="field">
          <span class="tiny">Postal code {{ isB2B ? "*" : "" }}</span>
          <input type="text" v-model="pincode" inputmode="numeric" maxlength="5" />
        </label>
        <label class="field">
          <span class="tiny">State / province</span>
          <input type="text" v-model="stateField" />
        </label>
      </div>
      <div class="two-col">
        <label class="field">
          <span class="tiny">Country</span>
          <input type="text" v-model="country" />
        </label>
        <label class="field">
          <span class="tiny">Phone</span>
          <input type="tel" v-model="phone" inputmode="tel" />
        </label>
      </div>
    </section>

    <button class="submit" type="button" :disabled="busy" @click="submit">
      <Icon name="check" :size="18" /> {{ busy ? "Saving…" : "Save address" }}
    </button>
  </div>
</template>

<style scoped>
.field { display: flex; flex-direction: column; gap: 0.3rem; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 0.6rem; }
.row-head { display: flex; justify-content: space-between; align-items: center; }
</style>
