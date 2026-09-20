"use client";

import { useEffect, useState } from "react";
import { Ban, Download, Loader2, Pause, Play } from "lucide-react";

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
import { Badge } from "@/components/ui/badge";
import {
  canCancel,
  canPause,
  canResume,
  exportUrl,
  isTerminal,
  type ExportFormat,
  type JobState,
} from "@/lib/api";

export type JobAction = "pause" | "resume" | "cancel";

interface JobStatusCardProps {
  job: JobState;
  /** Omitted on read-only views (the per-site history), where there is no worker to talk to. */
  onAction?: (action: JobAction) => Promise<void>;
  /** The action currently in flight, so only that button shows a spinner. */
  pending?: JobAction | null;
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

export function JobStatusCard({ job, onAction, pending = null }: JobStatusCardProps) {
  // With no page cap there is no denominator, so the bar cannot show real
  // progress mid-crawl — it stays indeterminate until the job finishes.
  const capped = job.max_pages > 0;
  const finished = isTerminal(job.status);
  const percent = finished
    ? 100
    : capped
      ? Math.min(100, (job.pages_crawled / job.max_pages) * 100)
      : null;
  const live =
    job.status === "queued" ||
    job.status === "running" ||
    job.status === "pausing" ||
    job.status === "resuming";
  const now = useNow(live);
  const elapsed = elapsedSeconds(job, now);
  const queuedFor =
    job.status === "queued" && job.created_at
      ? Math.floor((now - Date.parse(job.created_at)) / 1000)
      : 0;
  // Exports are offered once nothing is actively writing the files — that
  // includes a paused job, whose partial output is complete as far as it goes.
  const canDownload = (finished || job.status === "paused") && job.pages_crawled > 0;
  const controls = onAction ? (
    <div className="flex flex-wrap gap-2">
      {canPause(job.status) ? (
        <ControlButton
          action="pause"
          pending={pending}
          onAction={onAction}
          icon={<Pause />}
          label="Pause"
        />
      ) : null}
      {canResume(job.status) ? (
        <ControlButton
          action="resume"
          pending={pending}
          onAction={onAction}
          icon={<Play />}
          label="Resume"
        />
      ) : null}
      {canCancel(job.status) ? (
        <ControlButton
          action="cancel"
          pending={pending}
          onAction={onAction}
          icon={<Ban />}
          label="Cancel"
          variant="outline"
        />
      ) : null}
    </div>
  ) : null;

  return (
    <Card className="border-border/70 shadow-sm">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-lg sm:text-xl">
          Job status
          <StatusBadge status={job.status} />
          {job.resume_count > 0 ? (
            <Badge variant="outline" title={`Resumed ${job.resume_count} time(s)`}>
              Resumed {job.resume_count}x
            </Badge>
          ) : null}
        </CardTitle>
        <CardDescription className="break-anywhere">
          {job.url} · {capped ? `up to ${job.max_pages} pages` : "whole site"}
          {job.use_js ? " · JS rendered" : ""}
          {job.use_sitemap ? " · sitemap" : ""}
          {job.download_files ? " · files" : ""}
          {job.extract_contacts ? " · contacts" : ""}
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
            label="Documents"
            value={job.documents_downloaded.toLocaleString()}
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

        {job.status === "paused" ? (
          <p className="bg-muted/60 text-muted-foreground rounded-lg p-3 text-sm text-pretty">
            Paused with the queue saved to disk. Resuming picks up from exactly
            where it stopped; cancelling keeps these {job.pages_crawled} pages
            and discards the rest.
          </p>
        ) : null}

        {controls || canDownload ? (
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            {controls}
            {canDownload ? (
              <div className="flex gap-2 sm:ml-auto">
                <DownloadButton jobId={job.job_id} format="jsonl" />
                <DownloadButton jobId={job.job_id} format="csv" />
              </div>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ControlButton({
  action,
  pending,
  onAction,
  icon,
  label,
  variant = "default",
}: {
  action: JobAction;
  pending: JobAction | null;
  onAction: (action: JobAction) => Promise<void>;
  icon: React.ReactNode;
  label: string;
  variant?: "default" | "outline";
}) {
  const busy = pending === action;
  return (
    <Button
      size="sm"
      variant={variant}
      // Any action in flight locks all of them: the job is mid-transition.
      disabled={pending !== null}
      onClick={() => void onAction(action)}
    >
      {busy ? <Loader2 className="animate-spin" /> : icon}
      {label}
    </Button>
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
