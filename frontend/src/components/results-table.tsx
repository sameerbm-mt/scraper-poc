"use client";

import { ChevronLeft, ChevronRight, FileText } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { PageSummary, ResultsPage } from "@/lib/api";

interface ResultsTableProps {
  results: ResultsPage;
  loading: boolean;
  onSelect: (item: PageSummary) => void;
  onPageChange: (page: number) => void;
}

function statusVariant(code: number | null): "secondary" | "destructive" {
  return code && code < 300 ? "secondary" : "destructive";
}

export function ResultsTable({
  results,
  loading,
  onSelect,
  onPageChange,
}: ResultsTableProps) {
  const { items, page, total, total_pages: totalPages } = results;
  const firstRow = total === 0 ? 0 : (page - 1) * results.size + 1;
  const lastRow = Math.min(page * results.size, total);
  const empty = items.length === 0;

  return (
    <Card className="border-border/70 shadow-sm">
      <CardHeader>
        <CardTitle className="text-lg sm:text-xl">Results</CardTitle>
        <CardDescription className="text-pretty">
          {total === 0
            ? "No pages yet."
            : `Showing ${firstRow}–${lastRow} of ${total} pages. Select a row to read the markdown.`}
        </CardDescription>
      </CardHeader>

      <CardContent className="grid gap-4">
        {empty ? (
          <div className="text-muted-foreground flex flex-col items-center gap-2 py-10 text-center text-sm">
            <FileText className="size-6 opacity-40" />
            {loading ? "Loading…" : "Nothing crawled yet."}
          </div>
        ) : (
          <>
            {/* Phones: a tap-friendly card per page, no sideways scrolling. */}
            <ul className="grid gap-2 md:hidden">
              {items.map((item) => (
                <li key={item.index}>
                  <button
                    type="button"
                    onClick={() => onSelect(item)}
                    className="bg-muted/40 hover:bg-muted active:bg-muted ring-foreground/5 focus-visible:ring-ring w-full rounded-lg px-3 py-3 text-left ring-1 transition-colors focus-visible:ring-2 focus-visible:outline-none"
                  >
                    <p className="text-sm font-medium text-pretty">
                      {item.title || (
                        <span className="text-muted-foreground">Untitled</span>
                      )}
                    </p>
                    <p className="text-muted-foreground mt-1 font-mono text-xs break-anywhere">
                      {item.url}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Badge variant={statusVariant(item.status_code)}>
                        {item.status_code ?? "—"}
                      </Badge>
                      <span className="text-muted-foreground text-xs tabular-nums">
                        {item.word_count.toLocaleString()} words
                      </span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>

            {/* Tablet and up: the full table. */}
            <div className="hidden overflow-x-auto md:block">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="min-w-[260px]">URL</TableHead>
                    <TableHead className="min-w-[180px]">Title</TableHead>
                    <TableHead className="text-right">Words</TableHead>
                    <TableHead className="text-right">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => (
                    <TableRow
                      key={item.index}
                      tabIndex={0}
                      role="button"
                      className="hover:bg-muted/50 focus-visible:bg-muted/50 cursor-pointer outline-none"
                      onClick={() => onSelect(item)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          onSelect(item);
                        }
                      }}
                    >
                      <TableCell
                        className="max-w-[420px] truncate font-mono text-xs"
                        title={item.url}
                      >
                        {item.url}
                      </TableCell>
                      <TableCell
                        className="max-w-[320px] truncate"
                        title={item.title}
                      >
                        {item.title || (
                          <span className="text-muted-foreground">Untitled</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {item.word_count.toLocaleString()}
                      </TableCell>
                      <TableCell className="text-right">
                        <Badge variant={statusVariant(item.status_code)}>
                          {item.status_code ?? "—"}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </>
        )}

        {totalPages > 1 ? (
          <div className="border-border/70 flex items-center justify-between gap-3 border-t pt-4">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1 || loading}
              onClick={() => onPageChange(page - 1)}
              className="flex-1 sm:flex-none"
            >
              <ChevronLeft />
              <span>Previous</span>
            </Button>
            <span className="text-muted-foreground shrink-0 text-sm tabular-nums">
              {page} / {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages || loading}
              onClick={() => onPageChange(page + 1)}
              className="flex-1 sm:flex-none"
            >
              <span>Next</span>
              <ChevronRight />
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
