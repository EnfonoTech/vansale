/** Small async helpers for the push flow. */

/**
 * `promise`, or a rejection once `ms` have passed. A service worker that never
 * becomes ready (the dev server registers none) would otherwise leave the
 * switch busy for ever, and a slow network would hold up a logout.
 */
export function withTimeout<T>(promise: Promise<T>, ms: number, message = "Timed out"): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(message)), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error: unknown) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}
