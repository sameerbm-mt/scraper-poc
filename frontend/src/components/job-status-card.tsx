"use client";

import { Download } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  exportUrl,
  type ExportFormat,
  type JobState,
  type JobStatus,
} from "@/lib/api";

const STATUS_VARIANT: Record<
  JobStatus,
  "default" | "secondary" | "destructive" | "outline"
> = {
  queued: "outline",
  running: "secondary",
  completed: "default",
  failed: "destructive",
};

interface JobStatusCardProps {
  job: JobState;
}

function formatDuration(job: JobState): string | null {
  if (!job.started_at) return null;
  const end = job.finished_at ? new Date(job.finished_at) : new Date();
  const seconds = (end.getTime() - new Date(job.started_at).getTime()) / 1000;
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  return seconds < 60
    ? `${seconds.toFixed(1)}s`
    : `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

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
  const duration = formatDuration(job);
  const hasResults = job.pages_crawled > 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          Job status
          <Badge variant={STATUS_VARIANT[job.status]}>{job.status}</Badge>
        </CardTitle>
        <CardDescription className="break-all">
          {job.url} · {capped ? `up to ${job.max_pages} pages` : "whole site"}
          {job.use_js ? " · JS rendered" : ""}
        </CardDescription>
        <CardAction className="flex flex-wrap gap-2">
          <DownloadButton jobId={job.job_id} format="jsonl" enabled={hasResults} />
          <DownloadButton jobId={job.job_id} format="csv" enabled={hasResults} />
        </CardAction>
      </CardHeader>
      <CardContent className="grid gap-4">
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

        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div>
            <dt className="text-muted-foreground text-xs">Pages crawled</dt>
            <dd className="text-2xl font-semibold tabular-nums">
              {job.pages_crawled}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground text-xs">Pages failed</dt>
            <dd className="text-2xl font-semibold tabular-nums">
              {job.pages_failed}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground text-xs">Elapsed</dt>
            <dd className="text-2xl font-semibold tabular-nums">
              {duration ?? "—"}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground text-xs">Site folder</dt>
            <dd className="truncate font-mono text-sm" title={`data/${job.site}/${job.job_id}`}>
              {job.site || "—"}
            </dd>
          </div>
        </dl>

        {job.error ? (
          <pre className="bg-destructive/10 text-destructive max-h-40 overflow-auto rounded-md p-3 text-xs whitespace-pre-wrap">
            {job.error}
          </pre>
        ) : null}
      </CardContent>
    </Card>
  );
}


function DownloadButton({
  jobId,
  format,
  enabled,
}: {
  jobId: string;
  format: ExportFormat;
  enabled: boolean;
}) {
  const label = format.toUpperCase();
  return (
    <Button variant="outline" size="sm" disabled={!enabled} asChild={enabled}>
      {enabled ? (
        <a href={exportUrl(jobId, format)} download>
          <Download />
          {label}
        </a>
      ) : (
        <span>
          <Download />
          {label}
        </span>
      )}
    </Button>
  );
}
