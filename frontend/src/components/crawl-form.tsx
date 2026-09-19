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
  const [errors, setErrors] = useState<FieldErrors>({});

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const found = validate(url);
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    // max_pages 0 = the whole site; the API keeps the field for scripted callers.
    await onSubmit({ url: url.trim(), max_pages: 0, use_js: useJs });
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

          {/* Stacks on phones; switch and button share a row from sm up. */}
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-3">
              <Switch id="use-js" checked={useJs} onCheckedChange={setUseJs} />
              <Label
                htmlFor="use-js"
                className="cursor-pointer font-normal leading-tight"
              >
                <span className="block text-sm font-medium">Render JS</span>
                <span className="text-muted-foreground block text-xs">
                  {useJs
                    ? "Playwright — slower, for JS-rendered sites"
                    : "Plain HTTP"}
                </span>
              </Label>
            </div>

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
