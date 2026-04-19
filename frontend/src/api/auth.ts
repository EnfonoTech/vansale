import { apiCall } from "./client";
import { setCredentials, clearCredentials, type Credentials } from "@/app/frappe";

export interface LoginResult {
  user: string;
  full_name: string;
  language: string;
  has_pin: boolean;
}

export interface PinUnlockResult extends Credentials {
  user: string;
  full_name: string;
  roles?: string[];
  language?: string;
}

export async function login(usr: string, pwd: string): Promise<LoginResult> {
  return apiCall<LoginResult>("POST", "vansale.api.auth.login", { usr, pwd });
}

export async function setupPin(pin: string): Promise<PinUnlockResult> {
  const res = await apiCall<PinUnlockResult>("POST", "vansale.api.auth.setup_pin", { pin });
  await setCredentials({ apiKey: res.api_key, apiSecret: res.api_secret });
  return res;
}

export async function loginWithPin(email: string, pin: string): Promise<PinUnlockResult> {
  const res = await apiCall<PinUnlockResult>("POST", "vansale.api.auth.login_with_pin", {
    email,
    pin,
  });
  await setCredentials({ apiKey: res.api_key, apiSecret: res.api_secret });
  return res;
}

export async function changePin(oldPin: string, newPin: string): Promise<void> {
  await apiCall<{ ok: boolean }>("POST", "vansale.api.auth.change_pin", {
    old_pin: oldPin,
    new_pin: newPin,
  });
}

export async function ping(): Promise<{ user: string; full_name: string }> {
  return apiCall("GET", "vansale.api.auth.ping");
}

export async function logout(): Promise<void> {
  try {
    await apiCall("POST", "vansale.api.auth.logout");
  } finally {
    await clearCredentials();
  }
}
