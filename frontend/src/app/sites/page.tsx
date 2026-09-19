"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Globe, Loader2, Plus, RefreshCw } from "lucide-react";

import { SitesTable } from "@/components/sites-table";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { errorMessage, getSites, type SiteSummary } from "@/lib/api";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; sites: SiteSummary[] };

export default function SitesPage() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getSites()
      .then((sites) => {
        if (!cancelled) setState({ status: "ready", sites });
      })
      .catch((error) => {
        if (!cancelled) setState({ status: "error", message: errorMessage(error) });
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  function retry() {
    setState({ status: "loading" });
    setAttempt((n) => n + 1);
  }

  const count = state.status === "ready" ? state.sites.length : null;

  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 sm:py-12">
      <section className="mb-6 flex flex-col gap-4 sm:mb-8 sm:flex-row sm:items-end sm:justify-between">
        <div className="max-w-2xl">
          <h1 className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">
            Crawled sites
          </h1>
          <p className="text-muted-foreground mt-2 text-sm leading-relaxed text-pretty sm:text-base">
            Every website MyraCrawl has crawled. Select one to see its crawl
            status and browse the pages it stored.
          </p>
        </div>
        <Button asChild size="lg" className="h-11 w-full sm:w-auto">
          <Link href="/">
            <Plus />
            New crawl
          </Link>
        </Button>
      </section>

      <Card className="border-border/70 shadow-sm">
        <CardHeader>
          <CardTitle className="text-lg sm:text-xl">Sites</CardTitle>
          <CardDescription>
            {count === null
              ? " "
              : count === 0
                ? "Nothing crawled yet."
                : `${count} ${count === 1 ? "site" : "sites"}, most recently crawled first.`}
          </CardDescription>
        </CardHeader>

        <CardContent>
          {state.status === "loading" ? (
            <div
              className="text-muted-foreground flex items-center justify-center gap-2 py-12 text-sm"
              role="status"
            >
              <Loader2 className="size-4 animate-spin" />
              Loading sites…
            </div>
          ) : state.status === "error" ? (
            <div className="flex flex-col items-center gap-3 py-12 text-center">
              <p className="text-destructive max-w-md text-sm text-pretty">
                {state.message}
              </p>
              <Button variant="outline" size="sm" onClick={retry}>
                <RefreshCw />
                Try again
              </Button>
            </div>
          ) : state.sites.length === 0 ? (
            <div className="text-muted-foreground flex flex-col items-center gap-3 py-12 text-center text-sm">
              <Globe className="size-6 opacity-40" />
              <p>No sites have been crawled yet.</p>
              <Button asChild size="sm">
                <Link href="/">Start a crawl</Link>
              </Button>
            </div>
          ) : (
            <SitesTable sites={state.sites} />
          )}
        </CardContent>
      </Card>
    </main>
  );
}
