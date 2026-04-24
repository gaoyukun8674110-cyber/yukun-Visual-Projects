export type MediaAsset = {
  id: string;
  original_filename: string;
  media_type: "image" | "video";
  content_type: string | null;
  storage_path: string;
  file_size: number;
  sha256: string;
  created_at: string;
  url: string;
};

export type DetectionJob = {
  id: string;
  media_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | string;
  progress: number;
  model_name: string;
  result_path: string | null;
  result_json: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  result_url: string | null;
};

export type JobLog = {
  id: string;
  job_id: string;
  level: string;
  message: string;
  payload: Record<string, unknown> | null;
  created_at: string;
};
