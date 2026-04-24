import type { DetectionJob, JobLog, MediaAsset } from "@/lib/types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api";

function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export function assetUrl(path: string | null): string | null {
  if (!path) return null;
  if (path.startsWith("http")) return path;
  const origin = new URL(API_BASE).origin;
  return `${origin}${path}`;
}

export function jobSocketUrl(jobId: string): string {
  const url = new URL(API_BASE);
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
  const response = await fetch(apiUrl("/media"), { method: "POST", body: formData });
  return readJson<MediaAsset>(response);
}

export async function createJob(mediaId: string, modelName = "best.pt"): Promise<DetectionJob> {
  const response = await fetch(apiUrl("/jobs"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ media_id: mediaId, model_name: modelName }),
  });
  return readJson<DetectionJob>(response);
}

export async function listJobs(): Promise<DetectionJob[]> {
  const response = await fetch(apiUrl("/jobs"), { cache: "no-store" });
  return readJson<DetectionJob[]>(response);
}

export async function listJobLogs(jobId: string): Promise<JobLog[]> {
  const response = await fetch(apiUrl(`/jobs/${jobId}/logs`), { cache: "no-store" });
  return readJson<JobLog[]>(response);
}
