"use client";

import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { getStats, type JobStats } from "@/lib/api";

interface JobStatsCardProps {
  jobId: string;
  /** Bumped by the parent while the crawl runs, so the numbers keep up. */
  refreshKey?: number;
}

/** How many schema.org types to name before collapsing the rest into a count. */
const SCHEMA_TYPES_SHOWN = 8;

export function JobStatsCard({ jobId, refreshKey = 0 }: JobStatsCardProps) {
  const [stats, setStats] = useState<JobStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getStats(jobId)
      .then((found) => {
        if (cancelled) return;
        setStats(found);
        setError(null);
      })
      .catch(() => {
        // A job whose files are not written yet simply has nothing to show.
        if (!cancelled) setError("Stats are not available for this job yet");
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, refreshKey]);

  if (error && !stats) return null;
  if (!stats) return null;

  const schemaTypes = Object.entries(stats.schema_types);
  const hidden = Math.max(0, schemaTypes.length - SCHEMA_TYPES_SHOWN);

  return (
    <Card className="border-border/70 shadow-sm">
      <CardHeader>
        <CardTitle className="text-lg sm:text-xl">What the crawl found</CardTitle>
        <CardDescription>
          Aggregated across every stored page in this job.
        </CardDescription>
      </CardHeader>

      <CardContent className="grid gap-5">
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Pages crawled" value={stats.pages_crawled} />
          <Stat label="Documents" value={stats.documents_downloaded} />
          <Stat label="Schema types" value={schemaTypes.length} />
          <Stat
            label="Avg response"
            value={stats.avg_response_time_ms}
            suffix="ms"
          />
          <Stat label="Total words" value={stats.total_words} />
          <Stat label="FAQs" value={stats.faqs_found} />
          <Stat label="Products" value={stats.products_found} />
          <Stat label="Pages failed" value={stats.pages_failed} />
        </dl>

        {schemaTypes.length > 0 ? (
          <div className="grid gap-2">
            <h3 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
              Structured data
            </h3>
            <div className="flex flex-wrap gap-1.5">
              {schemaTypes.slice(0, SCHEMA_TYPES_SHOWN).map(([name, count]) => (
                <Badge key={name} variant="secondary" title={`${count} pages`}>
                  {name}
                  <span className="text-muted-foreground ml-1 tabular-nums">
                    {count}
                  </span>
                </Badge>
              ))}
              {hidden > 0 ? (
                <Badge variant="outline">+{hidden} more</Badge>
              ) : null}
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Stat({
  label,
  value,
  suffix = "",
}: {
  label: string;
  value: number;
  suffix?: string;
}) {
  return (
    <div className="bg-muted/50 ring-foreground/5 rounded-lg px-3 py-2.5 ring-1">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="text-xl font-semibold tabular-nums sm:text-2xl">
        {value.toLocaleString()}
        {suffix ? (
          <span className="text-muted-foreground ml-0.5 text-sm font-normal">
            {suffix}
          </span>
        ) : null}
      </dd>
    </div>
  );
}
