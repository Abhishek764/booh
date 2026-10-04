import type { Theme } from "../types/theme";

export const THEME_STORAGE_KEY = "booh.theme";

/** An absent or untrusted preference always falls back to the nighttime theme. */
export function parseTheme(value: string | null): Theme {
  return value === "light" ? "light" : "dark";
}
