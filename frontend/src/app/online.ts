/**
 * Reactive online state. On native we prefer the `@capacitor/network`
 * plugin (fires immediate, reliable events); on web we fall back to
 * the standard browser listeners. `navigator.onLine` alone has bitten
 * us before (fatehhr P5 fix — "Failed to fetch" was being treated as
 * a wrong-PIN) so drain code should rely on this ref, not on raw
 * `navigator.onLine`.
 */
import { ref } from "vue";
import { Network } from "@capacitor/network";
import { isNative } from "./platform";

const online = ref<boolean>(typeof navigator !== "undefined" ? navigator.onLine : true);
let initialised = false;

async function initOnce(): Promise<void> {
  if (initialised) return;
  initialised = true;

  if (isNative()) {
    try {
      const status = await Network.getStatus();
      online.value = status.connected;
      await Network.addListener("networkStatusChange", (s) => {
        online.value = s.connected;
      });
      return;
    } catch {
      /* plugin unavailable — fall through to web listeners */
    }
  }

  window.addEventListener("online", () => {
    online.value = true;
  });
  window.addEventListener("offline", () => {
    online.value = false;
  });
}

export function useOnline() {
  void initOnce();
  return online;
}

export function isOnline(): boolean {
  void initOnce();
  return online.value;
}
