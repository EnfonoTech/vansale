import { apiCall } from "./client";
import { setCredentials, clearCredentials } from "@/app/frappe";

export interface LoginResult {
  user: string;
  full_name: string;
  language: string;
  has_pin: boolean;
  /** Effective PIN requirement for this user (user row -> van -> global). */
  require_pin?: boolean;
  api_key: string;
  api_secret: string;
}

export interface PinUnlockResult {
  user: string;
  full_name: string;
  api_key: string;
  api_secret: string;
  roles?: string[];
  language?: string;
}

export async function login(usr: string, pwd: string): Promise<LoginResult> {
  const res = await apiCall<LoginResult>("POST", "vansale.api.auth.login", { usr, pwd });
  // Stash token immediately so native setup_pin/ping/etc. can use
  // Authorization: token header. On web this is harmless (cookie +
  // CSRF path still authenticates).
  if (res.api_key && res.api_secret) {
    await setCredentials({ apiKey: res.api_key, apiSecret: res.api_secret });
  }
  return res;
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
