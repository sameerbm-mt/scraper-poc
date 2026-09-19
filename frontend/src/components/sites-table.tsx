"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronRight, Globe } from "lucide-react";

import { StatusBadge } from "@/components/status-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDateTime, formatRelativeTime, pluralize } from "@/lib/format";
import type { SiteSummary } from "@/lib/api";

function siteHref(site: SiteSummary): string {
  return `/sites/${encodeURIComponent(site.domain)}`;
}

function SiteIcon() {
  return (
    <span className="bg-accent text-accent-foreground inline-flex size-9 shrink-0 items-center justify-center rounded-lg">
      <Globe className="size-4" />
    </span>
  );
}

/** The name when the profile has one, with the domain underneath. */
function SiteLabel({ site }: { site: SiteSummary }) {
  const hasName = site.name !== "" && site.name !== site.domain;
  return (
    <span className="min-w-0">
      <span className="block truncate text-sm font-medium">
        {hasName ? site.name : site.domain}
      </span>
      {hasName ? (
        <span className="text-muted-foreground block truncate font-mono text-xs">
          {site.domain}
        </span>
      ) : null}
    </span>
  );
}

export function SitesTable({ sites }: { sites: SiteSummary[] }) {
  const router = useRouter();

  return (
    <>
      {/* Phones: one tappable card per site. */}
      <ul className="grid gap-2 md:hidden">
        {sites.map((site) => (
          <li key={site.domain}>
            <Link
              href={siteHref(site)}
              className="bg-card hover:bg-muted/60 focus-visible:ring-ring ring-foreground/5 flex items-center gap-3 rounded-xl px-3 py-3 ring-1 transition-colors focus-visible:ring-2 focus-visible:outline-none"
            >
              <SiteIcon />
              <span className="min-w-0 flex-1">
                <SiteLabel site={site} />
                <span className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
                  <StatusBadge status={site.latest_status} />
                  <span className="text-muted-foreground text-xs tabular-nums">
                    {pluralize(site.pages, "page")} ·{" "}
                    {pluralize(site.job_count, "crawl")}
                  </span>
                  <span className="text-muted-foreground text-xs">
                    {formatRelativeTime(site.last_crawled_at)}
                  </span>
                </span>
              </span>
              <ChevronRight className="text-muted-foreground size-4 shrink-0" />
            </Link>
          </li>
        ))}
      </ul>

      {/* Tablet and up: the full table. The whole row is clickable; the link in
          the first cell is what keyboard and screen-reader users reach. */}
      <div className="hidden overflow-x-auto md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="min-w-[240px]">Site</TableHead>
              <TableHead className="text-right">Crawls</TableHead>
              <TableHead className="text-right">Pages</TableHead>
              <TableHead>Latest crawl</TableHead>
              <TableHead className="text-right">Last crawled</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sites.map((site) => (
              <TableRow
                key={site.domain}
                className="hover:bg-muted/50 focus-within:bg-muted/50 cursor-pointer"
                onClick={(event) => {
                  if ((event.target as HTMLElement).closest("a")) return;
                  router.push(siteHref(site));
                }}
              >
                <TableCell>
                  <Link
                    href={siteHref(site)}
                    className="focus-visible:ring-ring flex items-center gap-3 rounded-md focus-visible:ring-2 focus-visible:outline-none"
                  >
                    <SiteIcon />
                    <SiteLabel site={site} />
                  </Link>
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {site.job_count}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {site.pages.toLocaleString()}
                </TableCell>
                <TableCell>
                  <StatusBadge status={site.latest_status} />
                </TableCell>
                <TableCell
                  className="text-muted-foreground text-right text-sm"
                  title={formatDateTime(site.last_crawled_at)}
                >
                  {formatRelativeTime(site.last_crawled_at)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </>
  );
}
