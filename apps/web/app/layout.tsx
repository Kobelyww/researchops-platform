import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { Inter } from "next/font/google";

import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
  // Graceful degradation if the Google Fonts download is unavailable at build time.
  fallback: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
});

export const metadata: Metadata = {
  title: "ResearchOps — Autonomous Research & Experiment Agent",
  description:
    "Launch, monitor, and approve autonomous research runs: planning, research, code, execution, evaluation, and reporting.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

  return (
    <html lang="en" className={inter.variable}>
      <body className="flex min-h-screen flex-col bg-[#0a0a0f] font-sans text-zinc-200 antialiased">
        <div
          aria-hidden
          className="bg-grid pointer-events-none fixed inset-0 opacity-70 [mask-image:radial-gradient(ellipse_at_top,black_20%,transparent_75%)]"
        />
        <header className="sticky top-0 z-20 border-b border-white/10 bg-[#0a0a0f]/85 backdrop-blur">
          <nav className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between px-6">
            <Link href="/" className="flex items-center gap-2.5">
              <span className="flex h-6 w-6 items-center justify-center rounded-md border border-cyan-400/40 bg-cyan-400/10 font-mono text-[11px] font-bold text-cyan-300">
                R
              </span>
              <span className="font-mono text-sm font-semibold tracking-tight text-white">
                ResearchOps
              </span>
              <span className="hidden rounded-full border border-white/10 bg-white/5 px-2 py-0.5 font-mono text-[10px] text-zinc-500 sm:inline">
                agent platform
              </span>
            </Link>
            <div className="flex items-center gap-5 font-mono text-xs text-zinc-400">
              <Link href="/" className="transition-colors hover:text-cyan-300">
                New run
              </Link>
              <Link href="/runs" className="transition-colors hover:text-cyan-300">
                Runs
              </Link>
            </div>
          </nav>
        </header>
        <main className="relative z-10 mx-auto w-full max-w-6xl flex-1 px-6 py-8">{children}</main>
        <footer className="relative z-10 border-t border-white/5">
          <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-2 px-6 py-4 font-mono text-[11px] text-zinc-600">
            <span>researchops · autonomous research &amp; experiment agent</span>
            <span>api · {apiBase}</span>
          </div>
        </footer>
      </body>
    </html>
  );
}
