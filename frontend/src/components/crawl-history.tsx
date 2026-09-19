import Link from "next/link";

import { formatDateTime, pluralize } from "@/lib/format";
import type { JobState } from "@/lib/api";
import { cn } from "@/lib/utils";

interface CrawlHistoryProps {
  domain: string;
  /** Newest first. */
  jobs: JobState[];
  selectedJobId: string;
}

/** One link per crawl of the site, so an older crawl is one click away. */
export function CrawlHistory({ domain, jobs, selectedJobId }: CrawlHistoryProps) {
  return (
    <nav aria-label="Crawls of this site">
      <p className="text-muted-foreground mb-2 text-xs font-medium tracking-wide uppercase">
        Crawls
      </p>
      <ul className="flex flex-wrap gap-2">
        {jobs.map((job, index) => {
          const selected = job.job_id === selectedJobId;
          return (
            <li key={job.job_id}>
              <Link
                href={`/sites/${encodeURIComponent(domain)}?job=${job.job_id}`}
                replace
                scroll={false}
                aria-current={selected ? "true" : undefined}
                className={cn(
                  "focus-visible:ring-ring block rounded-lg border px-3 py-2 text-xs transition-colors focus-visible:ring-2 focus-visible:outline-none",
                  selected
                    ? "border-primary bg-accent text-accent-foreground"
                    : "bg-card hover:border-primary/40",
                )}
              >
                <span className="block font-medium">
                  {index === 0 ? "Latest · " : ""}
                  {formatDateTime(job.started_at ?? job.created_at)}
                </span>
                <span
                  className={cn(
                    "block tabular-nums",
                    selected ? "opacity-80" : "text-muted-foreground",
                  )}
                >
                  {pluralize(job.pages_crawled, "page")} · {job.status}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
