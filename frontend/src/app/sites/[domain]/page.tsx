"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { ArrowLeft, Loader2, RefreshCw } from "lucide-react";

import { CrawlHistory } from "@/components/crawl-history";
import { JobResults } from "@/components/job-results";
import { JobStatusCard } from "@/components/job-status-card";
import { SiteProfileCard } from "@/components/site-profile-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  ApiError,
  errorMessage,
  getSiteJobs,
  getSiteProfile,
  isTerminal,
  type JobState,
  type SiteProfile,
} from "@/lib/api";
import { pluralize } from "@/lib/format";
import { useJobPolling } from "@/lib/use-job-polling";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string; notFound: boolean }
  | { status: "ready"; jobs: JobState[] };

interface SitePageProps {
  params: Promise<{ domain: string }>;
  searchParams: Promise<{ job?: string | string[] }>;
}

export default function SitePage({ params, searchParams }: SitePageProps) {
  const { domain } = use(params);
  const { job } = use(searchParams);
  const requestedJobId = Array.isArray(job) ? job[0] : job;

  // Keyed so that moving between sites starts from a clean slate.
  return (
    <SiteDetail key={domain} domain={domain} requestedJobId={requestedJobId} />
  );
}

function SiteDetail({
  domain,
  requestedJobId,
}: {
  domain: string;
  requestedJobId: string | undefined;
}) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [profile, setProfile] = useState<SiteProfile | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;

    getSiteJobs(domain)
      .then((jobs) => {
        if (!cancelled) setState({ status: "ready", jobs });
      })
      .catch((error) => {
        if (cancelled) return;
        setState({
          status: "error",
          message: errorMessage(error),
          notFound: error instanceof ApiError && error.status === 404,
        });
      });

    // The profile lives in Mongo, which is optional: without it the page simply
    // has no profile card.
    getSiteProfile(domain)
      .then((next) => {
        if (!cancelled) setProfile(next);
      })
      .catch(() => {
        if (!cancelled) setProfile(null);
      });

    return () => {
      cancelled = true;
    };
  }, [domain, attempt]);

  const jobs = state.status === "ready" ? state.jobs : null;
  const selected =
    jobs?.find((candidate) => candidate.job_id === requestedJobId) ??
    jobs?.[0] ??
    null;

  // A crawl that is still running refreshes in place; a finished one is static.
  const updateJob = useCallback((next: JobState) => {
    setState((current) =>
      current.status === "ready"
        ? {
            status: "ready",
            jobs: current.jobs.map((existing) =>
              existing.job_id === next.job_id ? next : existing,
            ),
          }
        : current,
    );
  }, []);
  useJobPolling(selected, updateJob);

  function retry() {
    setState({ status: "loading" });
    setAttempt((n) => n + 1);
  }

  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 sm:py-12">
      <Link
        href="/sites"
        className="text-muted-foreground hover:text-foreground focus-visible:ring-ring -ml-1 inline-flex items-center gap-1.5 rounded-md px-1 py-0.5 text-sm transition-colors focus-visible:ring-2 focus-visible:outline-none"
      >
        <ArrowLeft className="size-4" />
        Crawled sites
      </Link>

      <header className="mt-3 mb-6 sm:mb-8">
        <h1 className="text-3xl font-semibold tracking-tight break-anywhere text-balance sm:text-4xl">
          {profile?.name || domain}
        </h1>
        <p className="text-muted-foreground mt-1 font-mono text-sm break-anywhere">
          {domain}
          {jobs ? ` · ${pluralize(jobs.length, "crawl")}` : ""}
        </p>
      </header>

      {state.status === "loading" ? (
        <Card className="border-border/70 shadow-sm">
          <CardContent
            className="text-muted-foreground flex items-center justify-center gap-2 py-16 text-sm"
            role="status"
          >
            <Loader2 className="size-4 animate-spin" />
            Loading crawl…
          </CardContent>
        </Card>
      ) : state.status === "error" ? (
        <Card className="border-border/70 shadow-sm">
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <p
              className={`max-w-md text-sm text-pretty ${state.notFound ? "text-muted-foreground" : "text-destructive"}`}
            >
              {state.notFound
                ? `MyraCrawl has no crawls stored for ${domain}.`
                : state.message}
            </p>
            {state.notFound ? (
              <Button asChild variant="outline" size="sm">
                <Link href="/sites">Back to crawled sites</Link>
              </Button>
            ) : (
              <Button variant="outline" size="sm" onClick={retry}>
                <RefreshCw />
                Try again
              </Button>
            )}
          </CardContent>
        </Card>
      ) : selected && jobs ? (
        <div className="grid gap-5 sm:gap-6">
          {jobs.length > 1 ? (
            <CrawlHistory
              domain={domain}
              jobs={jobs}
              selectedJobId={selected.job_id}
            />
          ) : null}

          <JobStatusCard job={selected} />

          {profile ? <SiteProfileCard profile={profile} /> : null}

          {isTerminal(selected.status) ? (
            <JobResults key={selected.job_id} jobId={selected.job_id} />
          ) : (
            <Card className="border-border/70 shadow-sm">
              <CardContent className="text-muted-foreground py-10 text-center text-sm text-pretty">
                This crawl is still running. The results appear here as soon as
                it finishes.
              </CardContent>
            </Card>
          )}
        </div>
      ) : null}
    </main>
  );
}
