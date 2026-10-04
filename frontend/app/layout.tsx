import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AppShell } from "../components/app-shell";
import "../styles/globals.css";

export const metadata: Metadata = {
  title: "BOOH",
  description: "A quiet space for the middle of the night. Your nighttime companion.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="en" data-theme="dark">
      <body><AppShell>{children}</AppShell></body>
    </html>
  );
}
