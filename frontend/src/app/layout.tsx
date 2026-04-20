import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Outcome Execution Layer",
  description: "Regulatory compliance workflow execution MVP",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-dvh text-slate-50 antialiased">
        <div className="min-h-dvh">{children}</div>
      </body>
    </html>
  );
}

