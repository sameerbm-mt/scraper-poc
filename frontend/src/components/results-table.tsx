"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

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

export function ResultsTable({
  results,
  loading,
  onSelect,
  onPageChange,
}: ResultsTableProps) {
  const { items, page, total, total_pages: totalPages } = results;
  const firstRow = total === 0 ? 0 : (page - 1) * results.size + 1;
  const lastRow = Math.min(page * results.size, total);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Results</CardTitle>
        <CardDescription>
          {total === 0
            ? "No pages yet."
            : `Showing ${firstRow}–${lastRow} of ${total} pages. Select a row to read the markdown.`}
        </CardDescription>
        {totalPages > 1 ? (
          <CardAction className="flex items-center gap-2">
            <Button
              variant="outline"
              size="icon"
              aria-label="Previous page"
              disabled={page <= 1 || loading}
              onClick={() => onPageChange(page - 1)}
            >
              <ChevronLeft />
            </Button>
            <span className="text-muted-foreground text-sm tabular-nums">
              {page} / {totalPages}
            </span>
            <Button
              variant="outline"
              size="icon"
              aria-label="Next page"
              disabled={page >= totalPages || loading}
              onClick={() => onPageChange(page + 1)}
            >
              <ChevronRight />
            </Button>
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[280px]">URL</TableHead>
                <TableHead className="min-w-[200px]">Title</TableHead>
                <TableHead className="text-right">Words</TableHead>
                <TableHead className="text-right">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className="text-muted-foreground h-24 text-center"
                  >
                    {loading ? "Loading…" : "Nothing crawled yet."}
                  </TableCell>
                </TableRow>
              ) : (
                items.map((item) => (
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
                        <span className="text-muted-foreground">
                          Untitled
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {item.word_count.toLocaleString()}
                    </TableCell>
                    <TableCell className="text-right">
                      <Badge
                        variant={
                          item.status_code && item.status_code < 300
                            ? "secondary"
                            : "destructive"
                        }
                      >
                        {item.status_code ?? "—"}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}
