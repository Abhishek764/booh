"use client";

import { useEffect, useState } from "react";
import { parseTheme, THEME_STORAGE_KEY } from "../lib/theme";
import type { Theme } from "../types/theme";

/** Used once by the shell. Stores only a display preference, never user history. */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>("dark");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let savedTheme: Theme = "dark";
    try {
      savedTheme = parseTheme(window.localStorage.getItem(THEME_STORAGE_KEY));
    } catch {
      // Storage may be unavailable in private or restricted browsing contexts.
    }
    document.documentElement.dataset.theme = savedTheme;
    setTheme(savedTheme);
    setReady(true);
  }, []);

  function toggleTheme() {
    const nextTheme = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = nextTheme;
    setTheme(nextTheme);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
    } catch {
      // The toggle still works for the current page when persistence is blocked.
    }
  }

  return { theme, ready, toggleTheme };
}
