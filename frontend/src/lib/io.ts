"use client";

import { apiBase, useAuth } from "@/lib/api";

/**
 * Absolute backend URL that carries the JWT as a query parameter.
 *
 * `<iframe>` / `<a download>` / `<video src>` can't set an `Authorization`
 * header, so the backend also accepts `?token=` on the raw-file endpoint.
 */
export function authedUrl(
  path: string,
  params: Record<string, string | number | boolean | undefined> = {}
): string {
  const token = useAuth.getState().token;
  const url = new URL(`${apiBase}${path}`);
  if (token) url.searchParams.set("token", token);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
  }
  return url.toString();
}

/** Filename-safe slug. Also strips path separators so a title can't escape a download dir. */
export function slugify(value: string | null | undefined, fallback = "export"): string {
  const cleaned = (value || "")
    .replace(/[\\/:*?"<>|\u0000-\u001f]+/g, "_")
    .replace(/\s+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 80);
  return cleaned || fallback;
}

/** Trigger a client-side JSON download. */
export function downloadJson(filename: string, data: unknown): void {
  const name = filename.endsWith(".json") ? filename : `${filename}.json`;
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** Open a file picker and parse the chosen file as JSON. */
export function pickJsonFile(): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "application/json,.json";
    input.onchange = () => {
      const file = input.files?.[0];
      if (!file) {
        reject(new Error("未选择文件"));
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        try {
          resolve(JSON.parse(String(reader.result)));
        } catch {
          reject(new Error("所选文件不是合法 JSON"));
        }
      };
      reader.onerror = () => reject(new Error("文件读取失败"));
      reader.readAsText(file);
    };
    input.click();
  });
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** Local time, `YYYY-MM-DD HH:mm:ss`. */
export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function formatBytes(size: number): string {
  if (!size) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(size) / Math.log(1024)));
  return `${(size / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export const QUESTION_TYPE_LABEL: Record<string, string> = {
  choice: "选择题",
  translation: "翻译",
  writing: "写作",
  speaking: "口语",
};
