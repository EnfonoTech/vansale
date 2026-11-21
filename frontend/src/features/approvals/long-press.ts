/**
 * The click that follows a long press is not a tap: it must not open the card
 * the user just pressed and held. The browser sends it right after the finger
 * lifts, but not always (a drag off the card, a system gesture, a cancelled
 * pointer): a flag waiting for a click that never comes would swallow the NEXT
 * tap instead. So the flag is armed when the long press fires, given a short
 * time to be used once the finger is up, and then dropped; a new press drops
 * it too. Pure: timers only, no Vue.
 */

/** How long after the finger lifts a click may still come (it normally comes at once). */
export const SWALLOW_MS = 350;

export interface ClickSwallow {
  /** The long press fired: the click that follows is not a tap. */
  arm(): void;
  /** The finger lifted (or the pointer was lost): forget the flag if no click comes soon. */
  released(): void;
  /** A new press starts a new gesture: forget everything. */
  reset(): void;
  /** A click arrived: true when it must be ignored (the flag is then spent). */
  consume(): boolean;
}

export function createClickSwallow(ms: number = SWALLOW_MS): ClickSwallow {
  let swallowing = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  function stop() {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
  }

  return {
    arm() {
      stop();
      swallowing = true;
    },
    released() {
      if (!swallowing) return;
      stop();
      timer = setTimeout(() => {
        swallowing = false;
        timer = undefined;
      }, ms);
    },
    reset() {
      stop();
      swallowing = false;
    },
    consume() {
      if (!swallowing) return false;
      stop();
      swallowing = false;
      return true;
    },
  };
}
