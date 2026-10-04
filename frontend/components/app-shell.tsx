import type { ReactNode } from "react";
import { ThemeToggle } from "./theme-toggle";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="site-header">
        <a href="/" className="brand" aria-label="BOOH home">
          <span className="brand-mark" aria-hidden="true">b.</span>
          <span>BOOH</span>
        </a>
        <ThemeToggle />
      </header>
      <main id="main-content" className="main-content" tabIndex={-1}>
        {children}
      </main>
      <footer className="site-footer">
        <p>Your nighttime companion.</p>
        <span className="preview-label">Shell preview</span>
      </footer>
    </div>
  );
}
