import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Outcome Execution Layer",
  description: "Regulatory compliance workflow execution MVP",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-dvh bg-zinc-950 text-zinc-50">
        {children}
      </body>
    </html>
  );
}

