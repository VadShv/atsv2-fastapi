import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Объединение Tailwind-классов с разрешением конфликтов.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
