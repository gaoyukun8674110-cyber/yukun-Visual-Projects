"use client";

import { useEffect, useMemo, useState } from "react";
import { Activity, FileVideo, Image as ImageIcon, Radio, UploadCloud } from "lucide-react";

import { Button } from "@/components/ui/button";
import { assetUrl, createJob, jobSocketUrl, listJobLogs, listJobs, uploadMedia } from "@/lib/api";
import type { DetectionJob, JobLog, MediaAsset } from "@/lib/types";

const statusLabel: Record<string, string> = {
  queued: "排队中",
  running: "推理中",
  succeeded: "已完成",
  failed: "失败",
};

function statusClass(status: string) {
  if (status === "succeeded") return "bg-[#1fc7a3]";
  if (status === "failed") return "bg-[#ff4f31] text-white";
  if (status === "running") return "bg-[#ffdd45]";
  return "bg-white";
}

export default function Home() {
  const [jobs, setJobs] = useState<DetectionJob[]>([]);
  const [logs, setLogs] = useState<JobLog[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [uploaded, setUploaded] = useState<MediaAsset | null>(null);
  const [selected, setSelected] = useState<DetectionJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("等待上传媒体文件");

  const selectedResultUrl = useMemo(() => assetUrl(selected?.result_url ?? null), [selected?.result_url]);

  async function refreshJobs(nextSelectedId?: string) {
    const next = await listJobs();
    setJobs(next);
    const id = nextSelectedId ?? selected?.id;
    if (id) {
      const found = next.find((job) => job.id === id);
      if (found) setSelected(found);
    } else if (next[0]) {
      setSelected(next[0]);
    }
  }

  useEffect(() => {
    refreshJobs().catch((error) => setMessage(error.message));
    const timer = window.setInterval(() => refreshJobs().catch(() => undefined), 2500);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!selected) return;
    listJobLogs(selected.id).then(setLogs).catch(() => setLogs([]));

    const socket = new WebSocket(jobSocketUrl(selected.id));
    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.event === "log") {
          setLogs((current) => [
            ...current,
            {
              id: `${Date.now()}`,
              job_id: selected.id,
              level: payload.level ?? "INFO",
              message: payload.message ?? "",
              payload: payload.payload ?? null,
              created_at: new Date().toISOString(),
            },
          ]);
        }
        if (payload.status) refreshJobs(selected.id).catch(() => undefined);
      } catch {
        setMessage(event.data);
      }
    };
    return () => socket.close();
  }, [selected?.id]);

  function onPick(nextFile: File | null) {
    setFile(nextFile);
    setUploaded(null);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(nextFile ? URL.createObjectURL(nextFile) : null);
    setMessage(nextFile ? `已选择 ${nextFile.name}` : "等待上传媒体文件");
  }

  async function submit() {
    if (!file) return;
    setBusy(true);
    setMessage("上传中");
    try {
      const media = await uploadMedia(file);
      setUploaded(media);
      setMessage("已上传，正在创建检测任务");
      const job = await createJob(media.id);
      setSelected(job);
      await refreshJobs(job.id);
      setMessage("任务已进入 Redis Streams 队列");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "提交失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen p-4 text-[#171914] md:p-6">
      <section className="mx-auto grid max-w-[1500px] gap-4 lg:grid-cols-[360px_minmax(0,1fr)_420px]">
        <aside className="hard-shadow border-2 border-[#171914] bg-white p-5">
          <div className="flex items-center justify-between border-b-2 border-[#171914] pb-4">
            <div>
              <p className="mono text-xs font-bold text-[#697066]">YOLO OPS</p>
              <h1 className="mt-1 text-3xl font-black leading-none">检测控制台</h1>
            </div>
            <div className="flex h-12 w-12 items-center justify-center rounded-[8px] border-2 border-[#171914] bg-[#d9ff3f]">
              <Radio size={25} />
            </div>
          </div>

          <label className="mt-5 flex min-h-[270px] cursor-pointer flex-col items-center justify-center border-2 border-dashed border-[#171914] bg-[#f1f4ef] p-4 text-center transition hover:bg-[#d9ff3f]">
            <input
              className="hidden"
              type="file"
              accept="image/*,video/*"
              onChange={(event) => onPick(event.target.files?.[0] ?? null)}
            />
            {previewUrl && file?.type.startsWith("image/") ? (
              <img src={previewUrl} alt="待检测图片预览" className="max-h-[230px] w-full object-contain" />
            ) : previewUrl && file?.type.startsWith("video/") ? (
              <video src={previewUrl} className="max-h-[230px] w-full" muted controls />
            ) : (
              <div className="flex flex-col items-center gap-3">
                <UploadCloud size={44} />
                <p className="text-xl font-black">拖入或选择图片/视频</p>
                <p className="max-w-[260px] text-sm font-bold text-[#697066]">支持 jpg、png、webp、mp4、mov、avi、mkv</p>
              </div>
            )}
          </label>

          <div className="mt-4 border-2 border-[#171914] bg-[#171914] p-3 text-white">
            <p className="mono text-xs text-[#d9ff3f]">STATUS</p>
            <p className="mt-1 text-sm font-bold">{message}</p>
          </div>

          <Button className="mt-4 w-full" disabled={!file || busy} onClick={submit}>
            {busy ? "处理中" : "上传并创建任务"}
          </Button>

          {uploaded ? (
            <dl className="mt-4 grid gap-2 text-sm">
              <div className="flex justify-between border-b border-[#171914] pb-2">
                <dt className="font-black">媒体类型</dt>
                <dd>{uploaded.media_type}</dd>
              </div>
              <div className="flex justify-between border-b border-[#171914] pb-2">
                <dt className="font-black">大小</dt>
                <dd>{(uploaded.file_size / 1024 / 1024).toFixed(2)} MB</dd>
              </div>
            </dl>
          ) : null}
        </aside>

        <section className="border-2 border-[#171914] bg-white">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b-2 border-[#171914] p-5">
            <div>
              <p className="mono text-xs font-bold text-[#697066]">REDIS STREAMS</p>
              <h2 className="text-2xl font-black">任务队列</h2>
            </div>
            <Button variant="quiet" onClick={() => refreshJobs().catch((error) => setMessage(error.message))}>
              刷新
            </Button>
          </div>

          <div className="divide-y-2 divide-[#171914]">
            {jobs.length === 0 ? (
              <div className="scanline flex min-h-[500px] items-center justify-center p-8 text-center">
                <div>
                  <Activity className="mx-auto" size={52} />
                  <p className="mt-3 text-2xl font-black">暂无检测任务</p>
                  <p className="mt-2 text-sm font-bold text-[#697066]">上传媒体后，任务会出现在这里。</p>
                </div>
              </div>
            ) : (
              jobs.map((job) => (
                <button
                  key={job.id}
                  onClick={() => setSelected(job)}
                  className={`grid w-full gap-3 p-5 text-left transition hover:bg-[#f1f4ef] md:grid-cols-[1fr_130px_140px] ${
                    selected?.id === job.id ? "bg-[#d9ff3f]" : "bg-white"
                  }`}
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      {job.result_path?.endsWith(".mp4") ? <FileVideo size={20} /> : <ImageIcon size={20} />}
                      <p className="mono truncate text-sm font-black">{job.id}</p>
                    </div>
                    <p className="mt-2 text-sm font-bold text-[#697066]">模型：{job.model_name}</p>
                    {job.error ? <p className="mt-1 text-sm font-black text-[#ff4f31]">{job.error}</p> : null}
                  </div>
                  <div>
                    <span className={`inline-flex rounded-[6px] border-2 border-[#171914] px-3 py-1 text-sm font-black ${statusClass(job.status)}`}>
                      {statusLabel[job.status] ?? job.status}
                    </span>
                  </div>
                  <div>
                    <div className="h-4 border-2 border-[#171914] bg-white">
                      <div className="h-full bg-[#1fc7a3]" style={{ width: `${Math.max(2, job.progress)}%` }} />
                    </div>
                    <p className="mono mt-1 text-xs font-black">{job.progress}%</p>
                  </div>
                </button>
              ))
            )}
          </div>
        </section>

        <aside className="border-2 border-[#171914] bg-white">
          <div className="border-b-2 border-[#171914] p-5">
            <p className="mono text-xs font-bold text-[#697066]">RESULT VIEW</p>
            <h2 className="text-2xl font-black">结果与日志</h2>
          </div>

          <div className="p-5">
            {selectedResultUrl ? (
              selected?.result_path?.endsWith(".mp4") ? (
                <video src={selectedResultUrl} className="max-h-[310px] w-full border-2 border-[#171914] object-contain" controls />
              ) : (
                <img src={selectedResultUrl} alt="检测结果" className="max-h-[310px] w-full border-2 border-[#171914] object-contain" />
              )
            ) : (
              <div className="scanline flex min-h-[240px] items-center justify-center border-2 border-[#171914] p-5 text-center">
                <p className="text-lg font-black">选择已完成任务后显示结果图或视频</p>
              </div>
            )}

            {selected?.result_json ? (
              <pre className="mono mt-4 max-h-[220px] overflow-auto border-2 border-[#171914] bg-[#171914] p-3 text-xs text-[#d9ff3f]">
                {JSON.stringify(selected.result_json, null, 2)}
              </pre>
            ) : null}

            <div className="mt-4 border-2 border-[#171914]">
              <div className="border-b-2 border-[#171914] bg-[#d9ff3f] px-3 py-2 text-sm font-black">任务日志</div>
              <div className="max-h-[300px] overflow-auto bg-[#171914] p-3 text-white">
                {logs.length === 0 ? (
                  <p className="text-sm font-bold text-[#d9ff3f]">暂无日志</p>
                ) : (
                  logs.map((log) => (
                    <div key={log.id} className="mono mb-3 text-xs leading-5">
                      <span className="text-[#1fc7a3]">{log.level}</span>
                      <span className="text-[#697066]"> / {new Date(log.created_at).toLocaleTimeString()}</span>
                      <p className="text-white">{log.message}</p>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </aside>
      </section>
    </main>
  );
}
