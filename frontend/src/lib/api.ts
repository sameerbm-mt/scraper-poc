/** Typed client for the crawler API. */

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type JobStatus = "queued" | "running" | "completed" | "failed";

export interface CrawlRequest {
  url: string;
  /** 0 crawls the entire site. */
  max_pages: number;
  use_js: boolean;
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
  pages_crawled: number;
  pages_failed: number;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
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

export interface PageDetail extends PageSummary {
  meta_description: string;
  h1: string;
  markdown: string;
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

export const TERMINAL_STATUSES: readonly JobStatus[] = ["completed", "failed"];

export function isTerminal(status: JobStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}
