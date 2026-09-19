"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { PageDetailSheet } from "@/components/page-detail-sheet";
import { ResultsTable } from "@/components/results-table";
import {
  errorMessage,
  getResult,
  getResults,
  type PageDetail,
  type PageSummary,
  type ResultsPage,
} from "@/lib/api";

const PAGE_SIZE = 20;

const EMPTY_RESULTS: ResultsPage = {
  items: [],
  page: 1,
  size: PAGE_SIZE,
  total: 0,
  total_pages: 0,
};

interface JobResultsProps {
  jobId: string;
}

/**
 * The results table for one finished job: pagination and the markdown preview.
 *
 * Owns its own page number, so mount it with `key={jobId}` to start a different
 * job back on page 1.
 */
export function JobResults({ jobId }: JobResultsProps) {
  const [page, setPage] = useState(1);
  // The most recent page that loaded, kept on screen while the next one loads.
  const [results, setResults] = useState<ResultsPage | null>(null);
  const [failure, setFailure] = useState<{ page: number; message: string } | null>(
    null,
  );

  const [sheetOpen, setSheetOpen] = useState(false);
  const [detail, setDetail] = useState<PageDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getResults(jobId, page, PAGE_SIZE)
      .then((data) => {
        if (!cancelled) setResults(data);
      })
      .catch((error) => {
        if (cancelled) return;
        const message = errorMessage(error);
        setFailure({ page, message });
        toast.error("Could not load results", { description: message });
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, page]);

  const failed = failure?.page === page ? failure.message : null;
  const loading = results?.page !== page && !failed;

  async function handleSelect(item: PageSummary) {
    setSheetOpen(true);
    setDetail(null);
    setDetailError(null);
    setDetailLoading(true);
    try {
      setDetail(await getResult(jobId, item.index));
    } catch (error) {
      setDetailError(errorMessage(error));
    } finally {
      setDetailLoading(false);
    }
  }

  return (
    <>
      <ResultsTable
        results={results ?? EMPTY_RESULTS}
        loading={loading}
        error={failed}
        onSelect={handleSelect}
        onPageChange={setPage}
      />
      <PageDetailSheet
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        detail={detail}
        loading={detailLoading}
        error={detailError}
      />
    </>
  );
}
