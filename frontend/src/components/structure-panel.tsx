"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ChevronDown, ChevronRight, Layers, ScanLine } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { CONTENT_TYPE_LABELS, type SourceStructure } from "@/lib/types";

/** Colour per content type, so the split is readable at a glance. */
const TYPE_TONE: Record<string, string> = {
  body: "bg-slate-100 text-slate-700",
  heading: "bg-indigo-100 text-indigo-700",
  caption: "bg-amber-100 text-amber-800",
  formula: "bg-violet-100 text-violet-700",
  table: "bg-emerald-100 text-emerald-700",
  figure: "bg-rose-100 text-rose-700",
  reference: "bg-stone-100 text-stone-700",
  outline: "bg-sky-100 text-sky-700",
};

function TypeChip({ kind, count }: { kind: string; count: number }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium transition-transform hover:scale-105 ${
        TYPE_TONE[kind] ?? "bg-muted text-muted-foreground"
      }`}
    >
      {CONTENT_TYPE_LABELS[kind] ?? kind}
      <span className="tabular-nums opacity-70">{count}</span>
    </span>
  );
}

export function StructurePanel({ sourceId }: { sourceId: string }) {
  const [showChunks, setShowChunks] = useState(false);

  const structure = useQuery({
    queryKey: ["structure", sourceId],
    queryFn: () => api<SourceStructure>(`/api/v1/sources/${sourceId}/structure?limit=400`),
  });

  const data = structure.data;
  if (structure.isLoading) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">文档结构解析</CardTitle>
          <CardDescription>读取中…</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="skeleton h-4 w-2/3" />
          <div className="skeleton h-4 w-1/2" />
          <div className="skeleton h-32 w-full" />
        </CardContent>
      </Card>
    );
  }
  if (!data) return null;

  const counts = data.content_types || {};
  const chapters = data.outline.filter((n) => n.level === 1);

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Layers className="h-3.5 w-3.5" />
          </span>
          <div>
            <CardTitle className="text-base">文档结构解析</CardTitle>
            <CardDescription>
              正文、标题、图注、公式、表格、图内文字被分别识别并标注归属。页码同时给出「书内页码」与「PDF 页码」，
              两者相差 {data.page_offset != null ? Math.abs(data.page_offset) : "?"} 页（前置页所致）。
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">
            <ScanLine className="h-3 w-3" />
            PDF 共 {data.page_count ?? "?"} 页
          </Badge>
          {data.page_offset != null && (
            <Badge variant="outline">
              书内页码 = PDF 页码 {data.page_offset >= 0 ? "+" : "−"}
              {Math.abs(data.page_offset)}
            </Badge>
          )}
          <Badge variant="outline">切块 {data.chunk_total}</Badge>
          <Badge variant="outline">章节 {chapters.length}</Badge>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {Object.entries(counts)
            .sort((a, b) => b[1] - a[1])
            .map(([kind, count]) => (
              <TypeChip key={kind} kind={kind} count={count} />
            ))}
        </div>

        {data.outline.length > 0 ? (
          <div>
            <p className="mb-1 text-xs font-medium text-muted-foreground">
              章节树（层级 · 标题 · 书内页码）
            </p>
            <div className="max-h-72 scroll-smooth-x overflow-y-auto rounded-lg border bg-muted/20 p-3 font-mono text-xs leading-6">
              {data.outline.slice(0, 200).map((node, i) => (
                <div
                  key={`${node.number}-${node.page_number}-${i}`}
                  className="flex items-baseline gap-2 rounded px-1.5 py-0.5 transition-colors hover:bg-background"
                  style={{ paddingLeft: `${(node.level - 1) * 14 + 6}px` }}
                >
                  {node.level === 1 ? (
                    <ChevronDown className="h-3 w-3 shrink-0 text-primary" />
                  ) : (
                    <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground/50" />
                  )}
                  <span className="shrink-0 rounded bg-muted px-1.5 text-[10px] text-muted-foreground">
                    L{node.level}
                  </span>
                  <span className="text-foreground/90">
                    {node.number} {node.title}
                  </span>
                  <span className="ml-auto text-muted-foreground">
                    书内 p.{node.printed_page ?? "?"}
                    {node.page_end != null && node.page_end !== node.page_number
                      ? `–${(node.printed_page ?? 0) + (node.page_end - node.page_number)}`
                      : ""}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">
            未识别出章节结构（该文档可能没有标题层级或目录页）。
          </p>
        )}

        <div>
          <Button variant="outline" size="sm" onClick={() => setShowChunks((v) => !v)}>
            {showChunks ? (
              <>
                <ChevronDown /> 隐藏切片明细
              </>
            ) : (
              <>
                <ChevronRight /> 查看切片明细（前 {data.chunks.length} 条）
              </>
            )}
          </Button>
        </div>

        {showChunks && (
          <div className="max-h-96 scroll-smooth-x space-y-2 overflow-y-auto pr-1">
            {data.chunks.map((chunk) => (
              <div
                key={chunk.id}
                className="rounded-lg border bg-card/60 p-2.5 text-xs transition-colors hover:bg-card"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`rounded-full px-2 py-0.5 font-medium ${
                      TYPE_TONE[chunk.content_type] ?? "bg-muted"
                    }`}
                  >
                    {CONTENT_TYPE_LABELS[chunk.content_type] ?? chunk.content_type}
                  </span>
                  {chunk.printed_page != null && <Badge>书内 p.{chunk.printed_page}</Badge>}
                  {chunk.page_number != null && chunk.page_number !== chunk.printed_page && (
                    <Badge variant="outline">PDF p.{chunk.page_number}</Badge>
                  )}
                  {chunk.heading_level != null && (
                    <span className="text-muted-foreground">L{chunk.heading_level}</span>
                  )}
                </div>
                {chunk.section_title && (
                  <p className="mt-1 text-foreground/80">{chunk.section_title}</p>
                )}
                <p className="mt-1 whitespace-pre-wrap text-muted-foreground">{chunk.preview}</p>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
