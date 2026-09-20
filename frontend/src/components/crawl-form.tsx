"use client";

import { useState } from "react";
import { Globe, Loader2, Play } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import type { CrawlRequest } from "@/lib/api";

interface CrawlFormProps {
  onSubmit: (request: CrawlRequest) => Promise<void>;
  disabled: boolean;
}

type FieldErrors = Partial<Record<"url", string>>;

/** Client-side mirror of the API's validation, so mistakes surface immediately. */
function validate(url: string): FieldErrors {
  const errors: FieldErrors = {};

  const trimmed = url.trim();
  if (!trimmed) {
    errors.url = "Enter a URL to crawl";
  } else {
    const withScheme = trimmed.includes("://") ? trimmed : `https://${trimmed}`;
    try {
      const parsed = new URL(withScheme);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
        errors.url = "URL must use http or https";
      } else if (!parsed.hostname.includes(".")) {
        errors.url = "Enter a full host, e.g. https://example.com";
      }
    } catch {
      errors.url = "That does not look like a valid URL";
    }
  }

  return errors;
}

export function CrawlForm({ onSubmit, disabled }: CrawlFormProps) {
  const [url, setUrl] = useState("");
  const [useJs, setUseJs] = useState(false);
  const [useSitemap, setUseSitemap] = useState(false);
  const [downloadFiles, setDownloadFiles] = useState(false);
  const [extractContacts, setExtractContacts] = useState(false);
  const [errors, setErrors] = useState<FieldErrors>({});

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = validate(url);
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    // max_pages 0 = the whole site; the API keeps the field for scripted callers.
    await onSubmit({
      url: url.trim(),
      max_pages: 0,
      use_js: useJs,
      use_sitemap: useSitemap,
      download_files: downloadFiles,
      extract_contacts: extractContacts,
    });
  }

  return (
    <Card className="border-border/70 shadow-sm">
      <CardHeader>
        <CardTitle className="text-lg sm:text-xl">Crawl a site</CardTitle>
        <CardDescription className="text-pretty">
          Follows every internal link from the start URL to the end of the site
          and extracts each page as markdown.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="grid gap-5" noValidate>
          <div className="grid gap-2">
            <Label htmlFor="url">Start URL</Label>
            <div className="relative">
              <Globe className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
              <Input
                id="url"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://example.com"
                aria-invalid={Boolean(errors.url)}
                aria-describedby={errors.url ? "url-error" : undefined}
                autoComplete="url"
                inputMode="url"
                className="h-11 pl-9 text-base sm:text-sm"
              />
            </div>
            {errors.url ? (
              <p id="url-error" className="text-destructive text-sm">
                {errors.url}
              </p>
            ) : null}
          </div>

          {/* One column on phones, two from sm — four switches never fit a row. */}
          <div className="grid gap-4 sm:grid-cols-2">
            <Option
              id="use-js"
              label="Render JS"
              checked={useJs}
              onChange={setUseJs}
              hint={
                useJs ? "Playwright — slower, for JS-rendered sites" : "Plain HTTP"
              }
            />
            <Option
              id="use-sitemap"
              label="Use sitemap"
              checked={useSitemap}
              onChange={setUseSitemap}
              hint={
                useSitemap
                  ? "Seed from /sitemap.xml, falling back to links"
                  : "Discover pages by following links"
              }
            />
            <Option
              id="download-files"
              label="Download files"
              checked={downloadFiles}
              onChange={setDownloadFiles}
              hint={
                downloadFiles
                  ? "Fetch linked PDFs and Office docs, and extract their text"
                  : "Document links are listed but not fetched"
              }
            />
            <Option
              id="extract-contacts"
              label="Extract contacts"
              checked={extractContacts}
              onChange={setExtractContacts}
              hint={
                extractContacts
                  ? "Emails, phones and addresses — personal data, see the README"
                  : "No personal data is collected"
              }
            />
          </div>

          <div className="flex justify-end">
            <Button
              type="submit"
              size="lg"
              disabled={disabled}
              className="h-11 w-full sm:w-auto"
            >
              {disabled ? (
                <Loader2 className="animate-spin" />
              ) : (
                <Play />
              )}
              {disabled ? "Crawling…" : "Start crawl"}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}

function Option({
  id,
  label,
  hint,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  hint: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="flex items-start gap-3">
      <Switch
        id={id}
        checked={checked}
        onCheckedChange={onChange}
        className="mt-0.5"
      />
      <Label htmlFor={id} className="cursor-pointer leading-tight font-normal">
        <span className="block text-sm font-medium">{label}</span>
        <span className="text-muted-foreground block text-xs text-pretty">
          {hint}
        </span>
      </Label>
    </div>
  );
}
