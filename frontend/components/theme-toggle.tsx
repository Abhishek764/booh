"use client";

import { useTheme } from "../hooks/use-theme";
import { Button } from "./button";

export function ThemeToggle() {
  const { theme, ready, toggleTheme } = useTheme();

  return (
    <Button
      className="theme-toggle"
      aria-pressed={theme === "dark"}
      onClick={toggleTheme}
      disabled={!ready}
    >
      <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" fill="none">
        <path d="M15.5 3.5a8.5 8.5 0 1 0 5 13A9 9 0 0 1 15.5 3.5Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      </svg>
      Night mode
    </Button>
  );
}
