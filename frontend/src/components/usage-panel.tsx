"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import type { UsageOut } from "@/lib/types";

export function UsagePanel({
  sourceId,
  compact = false,
}: {
  sourceId?: string;
  compact?: boolean;
}) {
  const usage = useQuery({
    queryKey: sourceId ? ["usage", sourceId] : ["usage"],
    queryFn: () =>
      api<UsageOut>(sourceId ? `/api/v1/sources/${sourceId}/usage` : "/api/v1/usage"),
  });

  const data = usage.data;
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Activity className="h-4 w-4" />
          </span>
          <div>
            <CardTitle className="text-base">Token 用量</CardTitle>
            <CardDescription>
              按资料与任务汇总的 prompt / completion token。Mock 供应商也会记账（字符估算），不换算金额。
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {usage.isLoading && <p className="text-muted-foreground">加载用量…</p>}
        {usage.isError && (
          <p className="text-destructive">
            {usage.error instanceof Error ? usage.error.message : "用量读取失败"}
          </p>
        )}
        {data && (
          <>
            <p>
              合计 <span className="font-medium tabular-nums">{data.total_tokens}</span> tokens
              （prompt {data.prompt_tokens} + completion {data.completion_tokens}）· {data.calls} 次调用
            </p>
            {data.by_task.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {data.by_task.map((row) => (
                  <Badge key={`${row.task}-${row.provider}-${row.model}`} variant="secondary">
                    {row.task}: {row.total_tokens}
                    <span className="ml-1 opacity-70">
                      {row.provider}/{row.model}
                    </span>
                  </Badge>
                ))}
              </div>
            )}
            {!compact && data.by_source.length > 0 && (
              <ul className="space-y-1.5 text-xs text-muted-foreground">
                {data.by_source.map((row) => (
                  <li key={row.source_id || "none"}>
                    {row.source_title || row.source_filename || row.source_id || "（未绑定资料）"}
                    ：{row.total_tokens} tokens / {row.calls} 次
                  </li>
                ))}
              </ul>
            )}
            {data.calls === 0 && <p className="text-muted-foreground">还没有调用记录。</p>}
          </>
        )}
      </CardContent>
    </Card>
  );
}
