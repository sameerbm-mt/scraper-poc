import { Radar } from "lucide-react";

import { API_URL } from "@/lib/api";

/** Orange mark + wordmark, echoing the Myra Technolabs brand. */
export function BrandMark({ className = "" }: { className?: string }) {
  return (
    <span
      className={`bg-primary text-primary-foreground inline-flex items-center justify-center rounded-xl shadow-sm ${className}`}
    >
      <Radar className="size-5" strokeWidth={2.2} />
    </span>
  );
}

export function SiteHeader() {
  return (
    <header className="border-border/70 surface-panel sticky top-0 z-40 border-b">
      <div
        className="mx-auto flex w-full max-w-6xl items-center justify-between gap-3 px-4 py-3 sm:px-6"
        style={{ paddingTop: "max(0.75rem, env(safe-area-inset-top, 0px))" }}
      >
        <div className="flex min-w-0 items-center gap-3">
          <BrandMark className="size-9 shrink-0" />
          <div className="min-w-0 leading-tight">
            <p className="truncate text-base font-semibold tracking-tight sm:text-lg">
              MyraCrawl
            </p>
            <p className="text-muted-foreground hidden truncate text-xs sm:block">
              Website Intelligence Crawler
            </p>
          </div>
        </div>

        <a
          href={`${API_URL}/docs`}
          target="_blank"
          rel="noreferrer noopener"
          className="text-muted-foreground hover:text-foreground hover:border-primary/40 shrink-0 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors sm:text-sm"
        >
          API docs
        </a>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer
      className="border-border/70 mt-auto border-t"
      style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
    >
      <div className="text-muted-foreground mx-auto flex w-full max-w-6xl flex-col items-center justify-between gap-2 px-4 py-6 text-center text-xs sm:flex-row sm:px-6 sm:text-left">
        <p>
          <span className="text-foreground font-medium">MyraCrawl</span> — a
          crawling proof of concept by Myra Technolabs.
        </p>
        <p className="font-mono">Scrapy · ARQ · FastAPI · MongoDB</p>
      </div>
    </footer>
  );
}
