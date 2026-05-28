import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Class-name merger used by every shadcn-style primitive.
 * `clsx` resolves conditionals; `twMerge` deduplicates conflicting
 * tailwind classes (e.g. `p-2 p-4` → `p-4`).
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
