/**
 * GPS breadcrumb helper — pull coords on demand (visit start/end) so we
 * don't drain the battery. Returns `null` if permission denied or
 * unavailable; caller treats that as "visit still recorded, no fix".
 */
import { isNative } from "@/app/platform";

export interface GeoPoint {
  lat: number;
  lng: number;
  accuracy?: number;
  ts: number;
}

export async function currentPosition(): Promise<GeoPoint | null> {
  if (isNative()) {
    try {
      // @ts-ignore optional
      const mod = await import("@capacitor/geolocation");
      const pos = await mod.Geolocation.getCurrentPosition({ enableHighAccuracy: true, timeout: 10_000 });
      return {
        lat: pos.coords.latitude,
        lng: pos.coords.longitude,
        accuracy: pos.coords.accuracy,
        ts: Date.now(),
      };
    } catch {
      return null;
    }
  }
  if (!("geolocation" in navigator)) return null;
  return await new Promise<GeoPoint | null>((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (p) =>
        resolve({
          lat: p.coords.latitude,
          lng: p.coords.longitude,
          accuracy: p.coords.accuracy,
          ts: Date.now(),
        }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 10_000 },
    );
  });
}
