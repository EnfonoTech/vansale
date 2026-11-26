/** Small display helpers for the approval cards. Pure. */

/** How long an item has waited: "Today", "1 day", "7 days". */
export function ageLabel(days: number): string {
  if (!(days > 0)) return "Today";
  return days === 1 ? "1 day" : `${days} days`;
}

export type PriorityTone = "critical" | "high" | "medium" | "low";

/** The colour family of a priority; anything unknown reads as medium. */
export function priorityTone(priority: string): PriorityTone {
  switch ((priority || "").trim().toLowerCase()) {
    case "critical":
      return "critical";
    case "high":
      return "high";
    case "low":
      return "low";
    default:
      return "medium";
  }
}
