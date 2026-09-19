"use client";

import { ExternalLink, Loader2 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Badge } from "@/components/ui/badge";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import type { PageDetail } from "@/lib/api";

interface PageDetailSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  detail: PageDetail | null;
  loading: boolean;
  error: string | null;
}

export function PageDetailSheet({
  open,
  onOpenChange,
  detail,
  loading,
  error,
}: PageDetailSheetProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex w-full flex-col gap-0 p-0 sm:max-w-2xl"
      >
        <SheetHeader className="border-b">
          <SheetTitle className="pr-6 text-left">
            {detail?.title || (loading ? "Loading…" : "Page")}
          </SheetTitle>
          <SheetDescription className="text-left">
            {detail ? (
              <a
                href={detail.url}
                target="_blank"
                rel="noreferrer noopener"
                className="hover:text-foreground inline-flex items-center gap-1 font-mono text-xs break-all underline underline-offset-4"
              >
                {detail.url}
                <ExternalLink className="size-3 shrink-0" />
              </a>
            ) : (
              "Fetching the extracted markdown."
            )}
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto px-4 py-4">
          {loading ? (
            <div className="text-muted-foreground flex items-center gap-2 text-sm">
              <Loader2 className="size-4 animate-spin" />
              Loading page…
            </div>
          ) : error ? (
            <p className="text-destructive text-sm">{error}</p>
          ) : detail ? (
            <div className="grid gap-5">
              <div className="flex flex-wrap gap-2">
                <Badge variant="secondary">
                  {detail.word_count.toLocaleString()} words
                </Badge>
                <Badge variant="outline">depth {detail.depth}</Badge>
                <Badge variant="outline">HTTP {detail.status_code ?? "—"}</Badge>
                <Badge variant="outline" title={detail.content_hash}>
                  {detail.content_hash.slice(0, 10)}
                </Badge>
              </div>

              {detail.meta_description ? (
                <div className="grid gap-1">
                  <h3 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                    Meta description
                  </h3>
                  <p className="text-sm">{detail.meta_description}</p>
                </div>
              ) : null}

              {detail.h1 ? (
                <div className="grid gap-1">
                  <h3 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                    H1
                  </h3>
                  <p className="text-sm">{detail.h1}</p>
                </div>
              ) : null}

              <div className="grid gap-2">
                <h3 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                  Extracted markdown
                </h3>
                <article className="prose-sm max-w-none text-sm leading-relaxed [&_a]:underline [&_a]:underline-offset-4 [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_code]:bg-muted [&_code]:rounded [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs [&_h1]:mt-4 [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:mt-4 [&_h2]:text-base [&_h2]:font-semibold [&_h3]:mt-3 [&_h3]:font-semibold [&_li]:my-0.5 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-2 [&_table]:my-2 [&_table]:block [&_table]:overflow-x-auto [&_td]:border [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:px-2 [&_th]:py-1 [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {detail.markdown}
                  </ReactMarkdown>
                </article>
              </div>
            </div>
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  );
}
