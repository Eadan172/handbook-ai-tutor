"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { formatBytes } from "@/lib/io";
import type { PathEntry, PathsOut } from "@/lib/types";

const SOURCE_LABEL: Record<PathEntry["source"], string> = {
  default: "项目默认",
  custom: "已自定义",
  env: "启动环境固定",
};

function summarise(entry: PathEntry): string {
  const d = entry.detail || {};
  if (typeof d.error === "string") return `无法读取：${d.error}`;
  if (entry.kind === "directory") {
    const files = typeof d.files === "number" ? d.files : 0;
    const bytes = typeof d.bytes === "number" ? d.bytes : 0;
    return files === 0 ? "目录为空" : `已存 ${files} 个文件 · ${formatBytes(bytes)}`;
  }
  const providers = Array.isArray(d.providers) ? (d.providers as string[]) : [];
  const fallback = typeof d.default_provider === "string" ? d.default_provider : "—";
  return providers.length ? `${providers.length} 个供应商（默认 ${fallback}）` : "未解析到供应商";
}

export function PathSettings() {
  const queryClient = useQueryClient();
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<{ kind: "ok" | "err"; lines: string[] } | null>(null);
  const seededRef = useRef<string>("");

  const paths = useQuery({
    queryKey: ["system-paths"],
    queryFn: () => api<PathsOut>("/api/v1/system/paths"),
  });

  // Seed the inputs from the *stored* overrides, and only when those change —
  // otherwise a background refetch would wipe whatever the user is typing.
  useEffect(() => {
    if (!paths.data) return;
    const signature = JSON.stringify(paths.data.overrides);
    if (seededRef.current === signature) return;
    seededRef.current = signature;
    setDrafts(
      Object.fromEntries(paths.data.paths.map((p) => [p.key, p.custom_value ?? ""]))
    );
  }, [paths.data]);

  const save = useMutation({
    mutationFn: (body: Record<string, string>) =>
      api<PathsOut>("/api/v1/system/paths", { method: "PUT", body: JSON.stringify(body) }),
    onSuccess: (res) => {
      const touched = res.changed
        .map((key) => res.paths.find((p) => p.key === key)?.label || key)
        .join("、");
      setNotice({
        kind: "ok",
        lines: [`已更新：${touched}（已即时生效，无需重启）`, ...res.warnings],
      });
      void queryClient.invalidateQueries({ queryKey: ["system-paths"] });
      void queryClient.invalidateQueries({ queryKey: ["health"] });
      void queryClient.invalidateQueries({ queryKey: ["llm-routes"] });
    },
    onError: (err) =>
      setNotice({ kind: "err", lines: [err instanceof Error ? err.message : "保存失败"] }),
  });

  function submit(only?: string) {
    const list = paths.data?.paths || [];
    const body: Record<string, string> = {};
    for (const p of list) {
      if (only && p.key !== only) continue;
      body[p.key] = drafts[p.key] ?? "";
    }
    save.mutate(body);
  }

  const dirty = (paths.data?.paths || []).some(
    (p) => (drafts[p.key] ?? "") !== (p.custom_value ?? "")
  );

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">存储与配置文件位置</CardTitle>
        <CardDescription>
          默认值就是本项目文件夹内的地址，开箱即用；需要放到别的磁盘或共享盘时，在这里改即可，
          <strong>保存后立即生效，不用重启</strong>。留空表示回到项目默认。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5 text-sm">
        {paths.isLoading && <p className="text-muted-foreground">加载中…</p>}
        {paths.isError && (
          <p className="text-destructive">
            读取路径配置失败：{paths.error instanceof Error ? paths.error.message : "未知错误"}
          </p>
        )}

        {(paths.data?.paths || []).map((entry) => {
          const draft = drafts[entry.key] ?? "";
          const effective = draft.trim() || entry.default;
          return (
            <div key={entry.key} className="space-y-2 rounded-lg border p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{entry.label}</span>
                <Badge
                  variant={entry.source === "custom" ? "default" : "secondary"}
                  className={entry.locked_by_env ? "text-amber-700" : ""}
                >
                  {SOURCE_LABEL[entry.source]}
                </Badge>
                {!entry.exists && (
                  <Badge variant="outline" className="text-destructive">
                    路径不存在
                  </Badge>
                )}
                <code className="ml-auto text-xs text-muted-foreground">{entry.env_var}</code>
              </div>

              <p className="text-xs text-muted-foreground">{entry.hint}</p>

              <div className="flex flex-col gap-2 sm:flex-row">
                <Input
                  value={draft}
                  placeholder={entry.default}
                  disabled={entry.locked_by_env || save.isPending}
                  spellCheck={false}
                  onChange={(e) => setDrafts((prev) => ({ ...prev, [entry.key]: e.target.value }))}
                />
                <div className="flex shrink-0 gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={entry.locked_by_env || save.isPending || !draft}
                    onClick={() => setDrafts((prev) => ({ ...prev, [entry.key]: "" }))}
                  >
                    填默认值
                  </Button>
                  <Button
                    size="sm"
                    disabled={entry.locked_by_env || save.isPending}
                    onClick={() => submit(entry.key)}
                  >
                    应用
                  </Button>
                </div>
              </div>

              {entry.locked_by_env ? (
                <p className="text-xs text-amber-700">
                  该路径由启动时的环境变量 {entry.env_var} 固定，页面改动不会生效。
                  请修改启动脚本或 docker compose 后重启。
                </p>
              ) : (
                <p className="text-xs text-muted-foreground">
                  实际使用：<code className="break-all">{effective}</code> · {summarise(entry)}
                  {draft.trim() && draft.trim() !== entry.current && (
                    <span className="text-amber-700">（未保存）</span>
                  )}
                </p>
              )}

              {entry.note && <p className="text-xs text-amber-700">{entry.note}</p>}
            </div>
          );
        })}

        {notice && (
          <div
            className={`rounded-md border px-3 py-2 text-xs ${
              notice.kind === "ok"
                ? "border-emerald-300 bg-emerald-50 text-emerald-900"
                : "border-destructive/40 bg-destructive/10 text-destructive"
            }`}
          >
            <ul className="list-disc space-y-1 pl-4">
              {notice.lines.map((line) => (
                <li key={line} className="break-all">
                  {line}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-3">
          <p className="text-xs text-muted-foreground">
            覆盖项保存在 <code className="break-all">{paths.data?.overrides_file || "—"}</code>
            （已加入 .gitignore，不会提交）。
          </p>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={save.isPending}
              onClick={() => {
                setDrafts(
                  Object.fromEntries((paths.data?.paths || []).map((p) => [p.key, ""]))
                );
                setNotice(null);
              }}
            >
              全部填默认值
            </Button>
            <Button size="sm" disabled={!dirty || save.isPending} onClick={() => submit()}>
              {save.isPending ? "保存中…" : "保存"}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
