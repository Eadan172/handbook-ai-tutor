"use client";

import { forwardRef, useCallback, useImperativeHandle, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import type { Citation } from "@/lib/types";

export type SourcePreviewHandle = {
  seek: (seconds: number) => void;
  jumpToPage: (page: number) => void;
  jumpToCitation: (citation: Citation) => void;
};

export function jumpTarget(citation: Pick<Citation, "page_number" | "printed_page" | "start_time">): {
  page?: number;
  time?: number;
} {
  if (citation.start_time != null && Number.isFinite(citation.start_time)) {
    return { time: citation.start_time };
  }
  if (citation.page_number != null) return { page: citation.page_number };
  if (citation.printed_page != null) return { page: citation.printed_page };
  return {};
}

export const SourcePreview = forwardRef<
  SourcePreviewHandle,
  {
    fileUrl: string;
    kind?: string;
    filename?: string | null;
    onError?: (message: string) => void;
  }
>(function SourcePreview({ fileUrl, kind, filename, onError }, ref) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [pdfPage, setPdfPage] = useState<number | null>(null);
  const isVideo = kind === "video";

  const pdfUrl = useMemo(
    () => (pdfPage && fileUrl ? `${fileUrl}#page=${pdfPage}` : fileUrl),
    [fileUrl, pdfPage]
  );

  const seek = useCallback((seconds: number) => {
    const el = videoRef.current;
    if (!el) return;
    el.currentTime = seconds;
    const apply = () => {
      el.currentTime = seconds;
      void el.play().catch(() => undefined);
    };
    if (el.readyState >= 1) apply();
    else el.addEventListener("loadedmetadata", apply, { once: true });
  }, []);

  const jumpToPage = useCallback((page: number) => setPdfPage(page), []);

  const jumpToCitation = useCallback(
    (citation: Citation) => {
      const target = jumpTarget(citation);
      if (target.time != null) seek(target.time);
      else if (target.page != null) jumpToPage(target.page);
    },
    [seek, jumpToPage]
  );

  useImperativeHandle(ref, () => ({ seek, jumpToPage, jumpToCitation }), [seek, jumpToPage, jumpToCitation]);

  return (
    <section className="flex min-h-[28rem] min-w-0 flex-col overflow-hidden rounded-xl border bg-card lg:min-h-0">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b px-3 py-2">
        <span className="flex items-center gap-2 text-sm font-medium">
          原文
          {!isVideo && pdfPage != null && (
            <button
              type="button"
              onClick={() => setPdfPage(null)}
              className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-normal text-primary underline-offset-4 hover:underline"
              title="回到文档开头"
            >
              已跳到第 {pdfPage} 页 · 复位
            </button>
          )}
        </span>
        <div className="flex gap-2">
          <Button asChild size="sm" variant="ghost">
            <a href={fileUrl} target="_blank" rel="noreferrer">
              新窗口打开
            </a>
          </Button>
          <Button asChild size="sm" variant="ghost">
            <a href={fileUrl} download={filename || "source"}>
              下载
            </a>
          </Button>
        </div>
      </div>
      <div className="relative min-h-0 flex-1 bg-muted/40">
        {isVideo ? (
          <video
            ref={videoRef}
            src={fileUrl}
            controls
            playsInline
            preload="metadata"
            className="absolute inset-0 h-full w-full bg-black object-contain"
            onError={(e) =>
              onError?.(`视频无法播放：${e.currentTarget.error?.message || "浏览器拒绝了该媒体文件"}`)
            }
          >
            你的浏览器不支持内嵌视频播放。
          </video>
        ) : kind === "image" ? (
          <div className="absolute inset-0 overflow-auto">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={fileUrl} alt={filename || "source"} className="mx-auto block max-w-full" />
          </div>
        ) : fileUrl ? (
          <iframe
            key={pdfUrl}
            src={pdfUrl}
            title="source-pdf"
            className="absolute inset-0 h-full w-full border-0"
          />
        ) : null}
      </div>
    </section>
  );
});
