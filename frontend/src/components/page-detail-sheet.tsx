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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { DocumentRecord, PageDetail } from "@/lib/api";

interface PageDetailSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  detail: PageDetail | null;
  loading: boolean;
  error: string | null;
  /** Documents for the whole job; the page's own links are matched against these. */
  documents?: DocumentRecord[];
}

export function PageDetailSheet({
  open,
  onOpenChange,
  detail,
  loading,
  error,
  documents = [],
}: PageDetailSheetProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex w-full flex-col gap-0 p-0 sm:max-w-2xl"
      >
        <SheetHeader className="border-b sm:px-6">
          <SheetTitle className="pr-6 text-left">
            {detail?.title || (loading ? "Loading…" : "Page")}
          </SheetTitle>
          <SheetDescription className="text-left">
            {detail ? (
              <a
                href={detail.url}
                target="_blank"
                rel="noreferrer noopener"
                className="hover:text-foreground inline-flex items-center gap-1 font-mono text-xs break-anywhere underline underline-offset-4"
              >
                {detail.url}
                <ExternalLink className="size-3 shrink-0" />
              </a>
            ) : (
              "Fetching the extracted page."
            )}
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto px-4 py-4 sm:px-6">
          {loading ? (
            <div className="text-muted-foreground flex items-center gap-2 text-sm">
              <Loader2 className="size-4 animate-spin" />
              Loading page…
            </div>
          ) : error ? (
            <p className="text-destructive text-sm">{error}</p>
          ) : detail ? (
            <DetailTabs detail={detail} documents={documents} />
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function DetailTabs({
  detail,
  documents,
}: {
  detail: PageDetail;
  documents: DocumentRecord[];
}) {
  // Only the documents this page actually links to.
  const linked = new Set(detail.document_links.map((d) => d.url));
  const pageDocuments = documents.filter((d) => linked.has(d.source_url));
  const structuredCount =
    detail.schema_types.length + detail.faqs.length + detail.products.length;

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap gap-2">
        <Badge variant="secondary">
          {detail.word_count.toLocaleString()} words
        </Badge>
        <Badge variant="outline">depth {detail.depth}</Badge>
        <Badge variant="outline">HTTP {detail.status_code ?? "—"}</Badge>
        {detail.lang ? <Badge variant="outline">{detail.lang}</Badge> : null}
        {detail.page_type ? (
          <Badge variant="outline">{detail.page_type}</Badge>
        ) : null}
      </div>

      <Tabs defaultValue="content">
        <TabsList>
          <TabsTrigger value="content">Content</TabsTrigger>
          <TabsTrigger value="meta">Meta / SEO</TabsTrigger>
          <TabsTrigger value="structured">
            Structured{structuredCount ? ` (${structuredCount})` : ""}
          </TabsTrigger>
          <TabsTrigger value="links">
            Links ({detail.external_links.length})
          </TabsTrigger>
          <TabsTrigger value="media">
            Media ({detail.images.length + detail.videos.length})
          </TabsTrigger>
          <TabsTrigger value="files">
            Files ({detail.document_links.length})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="content" className="grid gap-5">
          {detail.meta_description ? (
            <Field label="Meta description">{detail.meta_description}</Field>
          ) : null}
          {detail.h1 ? <Field label="H1">{detail.h1}</Field> : null}

          {detail.headings.length > 0 ? (
            <Section label={`Headings (${detail.headings.length})`}>
              <ul className="grid gap-1 text-sm">
                {detail.headings.map((heading, index) => (
                  <li
                    key={`${heading.level}-${index}`}
                    // Indent by level so the outline is readable at a glance.
                    style={{ paddingLeft: `${(heading.level - 1) * 12}px` }}
                    className="flex gap-2"
                  >
                    <span className="text-muted-foreground shrink-0 font-mono text-xs">
                      h{heading.level}
                    </span>
                    <span className="break-anywhere">{heading.text}</span>
                  </li>
                ))}
              </ul>
            </Section>
          ) : null}

          <Section label="Extracted markdown">
            <article className="prose-sm max-w-none text-sm leading-relaxed break-anywhere [&_a]:underline [&_a]:underline-offset-4 [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_code]:bg-muted [&_code]:rounded [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs [&_h1]:mt-4 [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:mt-4 [&_h2]:text-base [&_h2]:font-semibold [&_h3]:mt-3 [&_h3]:font-semibold [&_li]:my-0.5 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-2 [&_table]:my-2 [&_table]:block [&_table]:overflow-x-auto [&_td]:border [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:px-2 [&_th]:py-1 [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {detail.markdown}
              </ReactMarkdown>
            </article>
          </Section>
        </TabsContent>

        <TabsContent value="meta" className="grid gap-5">
          <dl className="grid gap-2 text-sm">
            <Row label="Canonical" value={detail.canonical_url} link />
            <Row label="Robots" value={detail.meta_robots} />
            <Row label="Language" value={detail.lang} />
            <Row label="Content type" value={detail.content_type} />
            <Row
              label="Response time"
              value={detail.response_time_ms ? `${detail.response_time_ms} ms` : ""}
            />
            <Row
              label="Page size"
              value={
                detail.page_size_bytes
                  ? `${(detail.page_size_bytes / 1024).toFixed(1)} KB`
                  : ""
              }
            />
            <Row label="Content hash" value={detail.content_hash} mono />
          </dl>

          {hasValues(detail.og) ? (
            <Section label="Open Graph">
              <dl className="grid gap-2 text-sm">
                {Object.entries(detail.og).map(([key, value]) =>
                  value ? <Row key={key} label={key} value={value} /> : null,
                )}
              </dl>
            </Section>
          ) : null}

          {hasValues(detail.twitter) ? (
            <Section label="Twitter card">
              <dl className="grid gap-2 text-sm">
                {Object.entries(detail.twitter).map(([key, value]) =>
                  value ? <Row key={key} label={key} value={value} /> : null,
                )}
              </dl>
            </Section>
          ) : null}

          {detail.hreflang.length > 0 ? (
            <Section label={`hreflang (${detail.hreflang.length})`}>
              <ul className="grid gap-1 text-sm">
                {detail.hreflang.map((alt) => (
                  <li key={alt.lang} className="flex gap-2">
                    <span className="text-muted-foreground w-12 shrink-0 font-mono text-xs">
                      {alt.lang}
                    </span>
                    <Link href={alt.url} />
                  </li>
                ))}
              </ul>
            </Section>
          ) : null}

          {detail.redirect_chain.length > 0 ? (
            <Section label="Redirect chain">
              <ol className="grid gap-1 text-sm">
                {detail.redirect_chain.map((url, index) => (
                  <li key={`${url}-${index}`} className="break-anywhere">
                    {index + 1}. {url}
                  </li>
                ))}
              </ol>
            </Section>
          ) : null}

          {detail.emails.length > 0 ||
          detail.phones.length > 0 ||
          detail.social_links.length > 0 ||
          detail.addresses.length > 0 ? (
            <Section label="Contacts">
              <div className="grid gap-2 text-sm">
                {detail.emails.length > 0 ? (
                  <Row label="Emails" value={detail.emails.join(", ")} />
                ) : null}
                {detail.phones.length > 0 ? (
                  <Row label="Phones" value={detail.phones.join(", ")} />
                ) : null}
                {detail.addresses.length > 0 ? (
                  <Row label="Addresses" value={detail.addresses.join(" · ")} />
                ) : null}
                {detail.social_links.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {detail.social_links.map((social) => (
                      <Badge key={social.platform} variant="outline" asChild>
                        <a
                          href={social.url}
                          target="_blank"
                          rel="noreferrer noopener"
                        >
                          {social.platform}
                        </a>
                      </Badge>
                    ))}
                  </div>
                ) : null}
              </div>
            </Section>
          ) : null}
        </TabsContent>

        <TabsContent value="structured" className="grid gap-5">
          {detail.schema_types.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {detail.schema_types.map((name) => (
                <Badge key={name} variant="secondary">
                  {name}
                </Badge>
              ))}
            </div>
          ) : null}

          {detail.faqs.length > 0 ? (
            <Section label={`FAQs (${detail.faqs.length})`}>
              <dl className="grid gap-3">
                {detail.faqs.map((faq, index) => (
                  <div key={index} className="bg-muted/40 rounded-lg p-3">
                    <dt className="text-sm font-medium break-anywhere">
                      {faq.question}
                    </dt>
                    <dd className="text-muted-foreground mt-1 text-sm break-anywhere">
                      {faq.answer}
                    </dd>
                  </div>
                ))}
              </dl>
            </Section>
          ) : null}

          {detail.products.length > 0 ? (
            <Section label={`Products (${detail.products.length})`}>
              <ul className="grid gap-2">
                {detail.products.map((product, index) => (
                  <li
                    key={index}
                    className="bg-muted/40 flex flex-wrap items-baseline gap-2 rounded-lg p-3 text-sm"
                  >
                    <span className="font-medium break-anywhere">
                      {product.name}
                    </span>
                    {product.price ? (
                      <Badge variant="outline">
                        {product.price} {product.currency}
                      </Badge>
                    ) : null}
                    {product.availability ? (
                      <Badge variant="outline">{product.availability}</Badge>
                    ) : null}
                    {product.sku ? (
                      <span className="text-muted-foreground font-mono text-xs">
                        {product.sku}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </Section>
          ) : null}

          {detail.jsonld.length > 0 ? (
            <Section label={`Raw JSON-LD (${detail.jsonld.length} objects)`}>
              <pre className="bg-muted/60 max-h-96 overflow-auto rounded-lg p-3 text-xs">
                {JSON.stringify(detail.jsonld, null, 2)}
              </pre>
            </Section>
          ) : (
            <Empty>No structured data on this page.</Empty>
          )}
        </TabsContent>

        <TabsContent value="links" className="grid gap-5">
          <p className="text-muted-foreground text-sm">
            {detail.internal_links_count.toLocaleString()} internal links (part
            of the crawl frontier) and {detail.external_links.length} external.
          </p>
          {detail.external_links.length > 0 ? (
            <Section label="External links">
              <ul className="grid gap-2 text-sm">
                {detail.external_links.map((link, index) => (
                  <li key={`${link.url}-${index}`} className="grid gap-0.5">
                    {link.anchor ? (
                      <span className="break-anywhere">{link.anchor}</span>
                    ) : null}
                    <Link href={link.url} />
                  </li>
                ))}
              </ul>
            </Section>
          ) : (
            <Empty>No external links on this page.</Empty>
          )}
        </TabsContent>

        <TabsContent value="media" className="grid gap-5">
          {detail.videos.length > 0 ? (
            <Section label={`Videos (${detail.videos.length})`}>
              <ul className="grid gap-2 text-sm">
                {detail.videos.map((video, index) => (
                  <li key={`${video.url}-${index}`} className="grid gap-0.5">
                    <div className="flex items-center gap-2">
                      <Badge variant="secondary">{video.type}</Badge>
                      {video.video_id ? (
                        <span className="text-muted-foreground font-mono text-xs">
                          {video.video_id}
                        </span>
                      ) : null}
                    </div>
                    <Link href={video.url} />
                  </li>
                ))}
              </ul>
            </Section>
          ) : null}

          {detail.images.length > 0 ? (
            <Section label={`Images (${detail.images.length})`}>
              <ul className="grid gap-2 text-sm">
                {detail.images.map((image, index) => (
                  <li key={`${image.src}-${index}`} className="grid gap-0.5">
                    <span className="break-anywhere">
                      {image.alt || (
                        <em className="text-muted-foreground">no alt text</em>
                      )}
                    </span>
                    <Link href={image.src} />
                  </li>
                ))}
              </ul>
            </Section>
          ) : (
            <Empty>No images kept for this page.</Empty>
          )}
        </TabsContent>

        <TabsContent value="files" className="grid gap-5">
          {detail.document_links.length === 0 ? (
            <Empty>No documents linked from this page.</Empty>
          ) : (
            <Section label={`Linked documents (${detail.document_links.length})`}>
              <ul className="grid gap-2 text-sm">
                {detail.document_links.map((doc) => {
                  const downloaded = pageDocuments.find(
                    (d) => d.source_url === doc.url,
                  );
                  return (
                    <li key={doc.url} className="grid gap-0.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="secondary">{doc.ext}</Badge>
                        {downloaded ? (
                          <>
                            <span className="font-medium break-anywhere">
                              {downloaded.filename}
                            </span>
                            {downloaded.page_count > 0 ? (
                              <Badge variant="outline">
                                {downloaded.page_count} pages
                              </Badge>
                            ) : null}
                            <Badge variant="outline">
                              {(downloaded.size_bytes / 1024).toFixed(0)} KB
                            </Badge>
                          </>
                        ) : (
                          <span className="text-muted-foreground text-xs">
                            not downloaded
                          </span>
                        )}
                      </div>
                      <Link href={doc.url} />
                    </li>
                  );
                })}
              </ul>
            </Section>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

function hasValues(record: Record<string, string>): boolean {
  return Object.values(record).some(Boolean);
}

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-2">
      <h3 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
        {label}
      </h3>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1">
      <h3 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
        {label}
      </h3>
      <p className="text-sm break-anywhere">{children}</p>
    </div>
  );
}

function Row({
  label,
  value,
  mono = false,
  link = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
  link?: boolean;
}) {
  if (!value) return null;
  return (
    <div className="grid grid-cols-[7rem_1fr] gap-2">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className={mono ? "font-mono text-xs break-anywhere" : "break-anywhere"}>
        {link ? <Link href={value} /> : value}
      </dd>
    </div>
  );
}

function Link({ href }: { href: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="text-muted-foreground hover:text-foreground font-mono text-xs break-anywhere underline underline-offset-4"
    >
      {href}
    </a>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-muted-foreground text-sm">{children}</p>;
}
