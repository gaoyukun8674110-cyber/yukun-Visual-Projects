import type { DetectionJob, JobLog, MediaAsset } from "@/lib/types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? "";

function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

// API_BASE may be a relative path (e.g. "/api") so requests follow the page origin.
// Resolve it against the current page origin to build absolute URLs when needed.
function absoluteApiBase(): URL {
  const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost";
  return new URL(API_BASE, origin);
}

function withApiKey(headers: HeadersInit = {}): Headers {
  const next = new Headers(headers);
  if (API_KEY) next.set("X-API-Key", API_KEY);
  return next;
}

export function assetUrl(path: string | null): string | null {
  if (!path) return null;
  if (path.startsWith("http")) return path;
  const origin = absoluteApiBase().origin;
  return `${origin}${path}`;
}

// Build a directly-usable media URL for native <video>/<img> playback.
// Authenticates via the `key` query param so the browser can stream with HTTP
// range requests (seek + progressive playback) instead of downloading a blob.
export function mediaSrcUrl(path: string | null): string | null {
  const url = assetUrl(path);
  if (!url) return null;
  if (!API_KEY) return url;
  const parsed = new URL(url, absoluteApiBase().origin);
  parsed.searchParams.set("key", API_KEY);
  return parsed.toString();
}

export async function fetchAssetObjectUrl(path: string | null): Promise<string | null> {
  const url = assetUrl(path);
  if (!url) return null;
  const response = await fetch(url, { headers: withApiKey() });
  if (!response.ok) {
    throw new Error(`Asset request failed: ${response.status}`);
  }
  return URL.createObjectURL(await response.blob());
}

export function jobSocketUrl(jobId: string): string {
  const url = absoluteApiBase();
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `${url.pathname.replace(/\/$/, "")}/ws/jobs/${jobId}`;
  return url.toString();
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function uploadMedia(file: File): Promise<MediaAsset> {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(apiUrl("/media"), { method: "POST", headers: withApiKey(), body: formData });
  return readJson<MediaAsset>(response);
}

export async function createJob(mediaId: string, modelName = "best.pt"): Promise<DetectionJob> {
  const response = await fetch(apiUrl("/jobs"), {
    method: "POST",
    headers: withApiKey({ "Content-Type": "application/json" }),
    body: JSON.stringify({ media_id: mediaId, model_name: modelName }),
  });
  return readJson<DetectionJob>(response);
}

export async function listJobs(): Promise<DetectionJob[]> {
  const response = await fetch(apiUrl("/jobs"), { cache: "no-store", headers: withApiKey() });
  return readJson<DetectionJob[]>(response);
}

export async function listJobLogs(jobId: string): Promise<JobLog[]> {
  const response = await fetch(apiUrl(`/jobs/${jobId}/logs`), { cache: "no-store", headers: withApiKey() });
  return readJson<JobLog[]>(response);
}
