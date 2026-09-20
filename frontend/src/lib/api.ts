/** Typed client for the crawler API. */

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type JobStatus =
  | "queued"
  | "running"
  /** The API has accepted a pause; the worker is still stopping Scrapy. */
  | "pausing"
  | "paused"
  | "resuming"
  | "completed"
  | "failed"
  | "cancelled";

export interface CrawlRequest {
  url: string;
  /** 0 crawls the entire site. */
  max_pages: number;
  use_js: boolean;
  /** Seed the frontier from the site's sitemap instead of following links. */
  use_sitemap?: boolean;
  /** Download linked pdf/docx/xlsx/pptx and extract their text. */
  download_files?: boolean;
  /** Collect emails, phones, socials and addresses. Personal data — opt in. */
  extract_contacts?: boolean;
}

export interface CrawlResponse {
  job_id: string;
}

export interface JobState {
  job_id: string;
  status: JobStatus;
  url: string;
  site: string;
  max_pages: number;
  use_js: boolean;
  use_sitemap: boolean;
  download_files: boolean;
  extract_contacts: boolean;
  pages_crawled: number;
  pages_failed: number;
  documents_downloaded: number;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  /** OS pid of the Scrapy subprocess while it runs. */
  pid: number | null;
  paused_at: string | null;
  resumed_at: string | null;
  resume_count: number;
  jobdir_path: string;
}

/** Aggregates over a job's stored pages. */
export interface JobStats {
  pages_crawled: number;
  pages_failed: number;
  documents_downloaded: number;
  /** schema.org type -> how many pages carried it, most common first. */
  schema_types: Record<string, number>;
  avg_response_time_ms: number;
  total_words: number;
  faqs_found: number;
  products_found: number;
}

/** One downloaded document and its extracted text. */
export interface DocumentRecord {
  source_url: string;
  filename: string;
  page_count: number;
  markdown: string;
  content_hash: string;
  size_bytes: number;
  ext: string;
}

export interface SocialLink {
  network: string;
  url: string;
}

export interface Service {
  name: string;
  url: string;
}

export interface TeamMember {
  name: string;
  role: string;
  image: string;
  source: string;
}

/** The `sites` document in MongoDB: what the crawl learned about the website. */
export interface SiteProfile {
  domain: string;
  name: string;
  start_url: string;
  description: string;
  logo: string;
  favicon: string;
  lang: string;
  address: string;
  founding_date: string;
  emails: string[];
  phones: string[];
  socials: SocialLink[];
  services: Service[];
  services_count: number;
  team: TeamMember[];
  team_count: number;
  key_pages: Record<string, string>;
  page_count: number;
  total_words: number;
  pages_by_type: Record<string, number>;
  first_seen_at: string | null;
  last_crawled_at: string | null;
}

/** One row of the crawled-sites list: a website and its most recent crawl. */
export interface SiteSummary {
  domain: string;
  /** From the Mongo site profile; empty when there is none. */
  name: string;
  job_count: number;
  latest_job_id: string;
  latest_status: JobStatus;
  pages: number;
  last_crawled_at: string | null;
}

export interface PageSummary {
  index: number;
  url: string;
  status_code: number | null;
  depth: number;
  title: string;
  word_count: number;
  content_hash: string;
  crawled_at: string;
}

export interface Heading {
  level: number;
  text: string;
}

export interface LinkRef {
  url: string;
  anchor: string;
}

export interface ImageRef {
  src: string;
  alt: string;
}

export interface VideoRef {
  type: "youtube" | "vimeo" | "file";
  url: string;
  video_id: string;
}

export interface DocumentLink {
  url: string;
  ext: string;
}

export interface Faq {
  question: string;
  answer: string;
}

export interface Product {
  name: string;
  sku: string;
  price: string;
  currency: string;
  availability: string;
}

export interface SocialRef {
  platform: string;
  url: string;
}

export interface PageDetail extends PageSummary {
  meta_description: string;
  h1: string;
  markdown: string;

  headings: Heading[];
  lang: string;

  meta_robots: string;
  canonical_url: string;
  og: Record<string, string>;
  twitter: Record<string, string>;
  hreflang: { lang: string; url: string }[];

  jsonld: Record<string, unknown>[];
  schema_types: string[];
  faqs: Faq[];
  products: Product[];

  internal_links_count: number;
  external_links: LinkRef[];
  images: ImageRef[];
  videos: VideoRef[];
  document_links: DocumentLink[];

  emails: string[];
  phones: string[];
  social_links: SocialRef[];
  addresses: string[];

  redirect_chain: string[];
  response_time_ms: number;
  content_type: string;
  page_size_bytes: number;
  page_type: string;
}

export interface ResultsPage {
  items: PageSummary[];
  page: number;
  size: number;
  total: number;
  total_pages: number;
}

/** An API error carrying the status code, so callers can tell 404 from 500. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong";
}

interface FastApiValidationDetail {
  loc: (string | number)[];
  msg: string;
}

function isValidationDetail(value: unknown): value is FastApiValidationDetail[] {
  return (
    Array.isArray(value) &&
    value.every(
      (entry) =>
        typeof entry === "object" && entry !== null && "msg" in entry,
    )
  );
}

/** Pull a human-readable message out of FastAPI's error shapes. */
async function toApiError(response: Response): Promise<ApiError> {
  let message = `Request failed (${response.status})`;
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") {
        message = detail;
      } else if (isValidationDetail(detail)) {
        message = detail.map((entry) => entry.msg).join("; ");
      }
    }
  } catch {
    // Non-JSON body (a proxy error page, say) — keep the generic message.
  }
  return new ApiError(message, response.status);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(`Cannot reach the API at ${API_URL}`, 0);
  }
  if (!response.ok) {
    throw await toApiError(response);
  }
  return (await response.json()) as T;
}

export function startCrawl(body: CrawlRequest): Promise<CrawlResponse> {
  return request<CrawlResponse>("/api/crawl", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getJob(jobId: string): Promise<JobState> {
  return request<JobState>(`/api/jobs/${jobId}`);
}

export function getResults(
  jobId: string,
  page: number,
  size: number,
): Promise<ResultsPage> {
  return request<ResultsPage>(
    `/api/jobs/${jobId}/results?page=${page}&size=${size}`,
  );
}

export function getResult(jobId: string, index: number): Promise<PageDetail> {
  return request<PageDetail>(`/api/jobs/${jobId}/results/${index}`);
}

export type ExportFormat = "jsonl" | "csv";

export function exportUrl(jobId: string, format: ExportFormat = "jsonl"): string {
  return `${API_URL}/api/jobs/${jobId}/export?format=${format}`;
}

/** The site profile for a job. 404 simply means the crawl stored none yet. */
export function getJobSite(jobId: string): Promise<SiteProfile> {
  return request<SiteProfile>(`/api/jobs/${jobId}/site`);
}

/** Every crawled website, most recently crawled first. */
export function getSites(): Promise<SiteSummary[]> {
  return request<SiteSummary[]>("/api/sites");
}

/** Every crawl of one website, newest first. 404 when it was never crawled. */
export function getSiteJobs(domain: string): Promise<JobState[]> {
  return request<JobState[]>(`/api/sites/${encodeURIComponent(domain)}/jobs`);
}

/** The stored profile for a domain. 404 or 503 just means there is none to show. */
export function getSiteProfile(domain: string): Promise<SiteProfile> {
  return request<SiteProfile>(`/api/sites/${encodeURIComponent(domain)}`);
}

/** Ask the worker to stop a running crawl, keeping its place. */
export function pauseJob(jobId: string): Promise<JobState> {
  return request<JobState>(`/api/jobs/${jobId}/pause`, { method: "POST" });
}

/** Re-queue a paused crawl against the same jobdir. */
export function resumeJob(jobId: string): Promise<JobState> {
  return request<JobState>(`/api/jobs/${jobId}/resume`, { method: "POST" });
}

/** Stop a crawl for good. Whatever it already wrote stays readable. */
export function cancelJob(jobId: string): Promise<JobState> {
  return request<JobState>(`/api/jobs/${jobId}/cancel`, { method: "POST" });
}

export function getStats(jobId: string): Promise<JobStats> {
  return request<JobStats>(`/api/jobs/${jobId}/stats`);
}

/** Downloaded documents. Extracted text is omitted unless `includeText`. */
export function getDocuments(
  jobId: string,
  includeText = false,
): Promise<DocumentRecord[]> {
  return request<DocumentRecord[]>(
    `/api/jobs/${jobId}/documents?include_text=${includeText}`,
  );
}

/** Nothing more will happen to a job in one of these, so polling stops. */
export const TERMINAL_STATUSES: readonly JobStatus[] = [
  "completed",
  "failed",
  "cancelled",
];

export function isTerminal(status: JobStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

/** Paused is not terminal, but nothing moves until someone resumes it. */
export function isSettled(status: JobStatus): boolean {
  return isTerminal(status) || status === "paused";
}

export function canPause(status: JobStatus): boolean {
  return status === "running";
}

export function canResume(status: JobStatus): boolean {
  return status === "paused";
}

export function canCancel(status: JobStatus): boolean {
  return status === "running" || status === "pausing" || status === "paused";
}
