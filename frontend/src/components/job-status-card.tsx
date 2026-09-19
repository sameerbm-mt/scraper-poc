"use client";

import { useEffect, useState } from "react";
import { Download } from "lucide-react";

import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { exportUrl, type ExportFormat, type JobState } from "@/lib/api";

interface JobStatusCardProps {
  job: JobState;
}

/** A wall clock that ticks every second while `active`, so elapsed time is live. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

function elapsedSeconds(job: JobState, now: number): number | null {
  if (!job.started_at) return null;
  const start = Date.parse(job.started_at);
  const end = job.finished_at ? Date.parse(job.finished_at) : now;
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  // The API stamps started_at with its own clock; a client a moment behind it
  // would otherwise read as negative time.
  return Math.max(0, Math.floor((end - start) / 1000));
}

function formatDuration(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

/** Queued this long with no start almost always means no worker is running. */
const WORKER_HINT_AFTER_SECONDS = 15;

export function JobStatusCard({ job }: JobStatusCardProps) {
  // With no page cap there is no denominator, so the bar cannot show real
  // progress mid-crawl — it stays indeterminate until the job finishes.
  const capped = job.max_pages > 0;
  const finished = job.status === "completed" || job.status === "failed";
  const percent = finished
    ? 100
    : capped
      ? Math.min(100, (job.pages_crawled / job.max_pages) * 100)
      : null;
  const live = job.status === "queued" || job.status === "running";
  const now = useNow(live);
  const elapsed = elapsedSeconds(job, now);
  const queuedFor =
    job.status === "queued" && job.created_at
      ? Math.floor((now - Date.parse(job.created_at)) / 1000)
      : 0;
  // Exports are only offered once the crawl has ended, so the files are complete.
  const canDownload = finished && job.pages_crawled > 0;

  return (
    <Card className="border-border/70 shadow-sm">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-lg sm:text-xl">
          Job status
          <StatusBadge status={job.status} />
        </CardTitle>
        <CardDescription className="break-anywhere">
          {job.url} · {capped ? `up to ${job.max_pages} pages` : "whole site"}
          {job.use_js ? " · JS rendered" : ""}
        </CardDescription>
      </CardHeader>

      <CardContent className="grid gap-5">
        {percent === null ? (
          <div
            className="bg-primary/20 h-2 w-full overflow-hidden rounded-full"
            role="progressbar"
            aria-label="Crawling, total unknown"
          >
            <div className="bg-primary h-full w-1/3 animate-pulse rounded-full" />
          </div>
        ) : (
          <Progress value={percent} />
        )}

        {/* 2-up on phones, 4-up from sm — never a horizontal scroll. */}
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Pages crawled" value={job.pages_crawled.toLocaleString()} />
          <Stat label="Pages failed" value={job.pages_failed.toLocaleString()} />
          <Stat
            label="Elapsed"
            value={elapsed === null ? "—" : formatDuration(elapsed)}
          />
          <Stat
            label="Site folder"
            value={job.site || "—"}
            mono
            title={`data/${job.site}/${job.job_id}`}
          />
        </dl>

        {job.error ? (
          <pre className="bg-destructive/10 text-destructive max-h-40 overflow-auto rounded-lg p-3 text-xs break-anywhere whitespace-pre-wrap">
            {job.error}
          </pre>
        ) : null}

        {queuedFor >= WORKER_HINT_AFTER_SECONDS ? (
          <p className="bg-muted/60 text-muted-foreground rounded-lg p-3 text-sm text-pretty">
            Still queued after {queuedFor}s. Check that the crawl worker is
            running (
            <code className="font-mono text-xs">
              arq worker.worker.WorkerSettings
            </code>
            ).
          </p>
        ) : null}

        {canDownload ? (
          <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <DownloadButton jobId={job.job_id} format="jsonl" />
            <DownloadButton jobId={job.job_id} format="csv" />
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Stat({
  label,
  value,
  mono = false,
  title,
}: {
  label: string;
  value: string;
  mono?: boolean;
  title?: string;
}) {
  return (
    <div className="bg-muted/50 ring-foreground/5 rounded-lg px-3 py-2.5 ring-1">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd
        className={
          mono
            ? "truncate font-mono text-sm font-medium"
            : "text-xl font-semibold tabular-nums sm:text-2xl"
        }
        title={title}
      >
        {value}
      </dd>
    </div>
  );
}

function DownloadButton({
  jobId,
  format,
}: {
  jobId: string;
  format: ExportFormat;
}) {
  return (
    <Button variant="outline" size="sm" asChild className="w-full sm:w-auto">
      <a href={exportUrl(jobId, format)} download>
        <Download />
        {format.toUpperCase()}
      </a>
    </Button>
  );
}
