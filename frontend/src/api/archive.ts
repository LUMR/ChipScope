import { apiGet, apiPost } from "./client";

export interface ArchiveStatus {
  state: "running" | "done" | "error" | null;
  trade_date: string | null;
  total: number;
  done: number;
  ok: number;
  failed: number;
  started_at: number | null;
  finished_at: number | null;
  error: string | null;
}

export const triggerArchive = (date?: string) =>
  apiPost<{ task_id: string; trade_date: string }>(
    `/archive/minute${date ? `?date=${date}` : ""}`
  );

export const getArchiveStatus = () =>
  apiGet<ArchiveStatus | null>("/archive/minute/status");
