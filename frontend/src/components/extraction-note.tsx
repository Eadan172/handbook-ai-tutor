"use client";

import { AlertTriangle, ScanLine } from "lucide-react";

/** True when the ingest note says the text is mock STT / mock OCR / not real lecture text. */
export function isMockProvenance(note: string | null | undefined): boolean {
  if (!note) return false;
  const n = note.toLowerCase();
  // Only warn for mock *extraction* (STT/OCR). A text-layer PDF summarized by
  // MockLLM still contains the word "mock" and must not look like a fake transcript.
  return (
    n.includes("mock stt") ||
    n.includes("stt mock") ||
    n.includes("ocr mock") ||
    n.includes("mock ocr") ||
    n.includes("mock transcription") ||
    n.includes("模拟语音") ||
    n.includes("模拟转写")
  );
}

export function ExtractionNote({
  note,
  compact = false,
}: {
  note: string | null | undefined;
  compact?: boolean;
}) {
  if (!note) return null;
  const mock = isMockProvenance(note);
  return (
    <div
      className={[
        "flex items-start gap-2 rounded-lg border px-3 py-2 text-xs leading-relaxed",
        mock
          ? "border-warning/40 bg-warning/10 text-foreground"
          : "border-border/70 bg-muted/40 text-muted-foreground",
        compact ? "mt-2" : "",
      ].join(" ")}
      role={mock ? "status" : undefined}
    >
      {mock ? (
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
      ) : (
        <ScanLine className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      )}
      <div className="min-w-0">
        {mock && (
          <p className="font-medium text-foreground">
            文本来源需注意：模拟转写 / 模拟 OCR，请勿当成真实课堂录音或扫描识别结果。
          </p>
        )}
        <p className={mock ? "mt-0.5 break-all" : "break-all"}>{note}</p>
      </div>
    </div>
  );
}
