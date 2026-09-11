"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Cpu,
  Database,
  Eraser,
  PlugZap,
  Save,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { EmbedOut, EmbedTestOut } from "@/lib/types";

/**
 * The hand-entered Embedding API.
 *
 * Every chat vendor in this project can be swapped from `providers.yaml`, but
 * embeddings are the one thing most of them do not expose (DeepSeek has no
 * `/embeddings` at all), so the endpoint is entered here instead of in the YAML.
 *
 * Leaving all three fields blank is a supported, first-class state: vectorising
 * falls back through the normal chain and ends on the local deterministic mock
 * vectors, which keeps the app fully usable offline — it is just less precise at
 * semantic retrieval. The card says which of the two is in force rather than
 * letting the user guess.
 */
export function EmbedSettings() {
  const queryClient = useQueryClient();
  const [base, setBase] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  // A saved key is never echoed back by the API, so a blank input does not mean
  // "no key". Only send the field once the user actually touched it.
  const [keyTouched, setKeyTouched] = useState(false);
  const seededRef = useRef<string>("");
  const [notice, setNotice] = useState<{ kind: "ok" | "err"; lines: string[] } | null>(null);
  const [probe, setProbe] = useState<EmbedTestOut | null>(null);

  const embed = useQuery({
    queryKey: ["system-embed"],
    queryFn: () => api<EmbedOut>("/api/v1/system/embed"),
  });

  useEffect(() => {
    if (!embed.data) return;
    const signature = JSON.stringify(embed.data.fields.map((f) => [f.key, f.value, f.hint_value]));
    if (seededRef.current === signature) return;
    seededRef.current = signature;
    const get = (key: string) => embed.data.fields.find((f) => f.key === key);
    setBase(get("embed_api_base")?.value ?? "");
    setModel(get("embed_model")?.value ?? "");
    setApiKey("");
    setKeyTouched(false);
  }, [embed.data]);

  function afterChange(res: EmbedOut, okLines: string[]) {
    setNotice({ kind: "ok", lines: [...okLines, ...res.warnings] });
    setProbe(null);
    void queryClient.invalidateQueries({ queryKey: ["system-embed"] });
    void queryClient.invalidateQueries({ queryKey: ["llm-routes"] });
    void queryClient.invalidateQueries({ queryKey: ["health"] });
  }

  const save = useMutation({
    mutationFn: (body: Record<string, string>) =>
      api<EmbedOut>("/api/v1/system/embed", { method: "PUT", body: JSON.stringify(body) }),
    onSuccess: (res) => {
      const cleared = !res.configured;
      afterChange(
        res,
        [
          cleared
            ? "已保存：未配置自定义 Embedding API，向量化走自动回退。"
            : `已保存并即时生效：向量将由 ${res.effective_provider}${
                res.effective_model ? ` / ${res.effective_model}` : ""
              } 生成。`,
        ]
      );
    },
    onError: (err) =>
      setNotice({ kind: "err", lines: [err instanceof Error ? err.message : "保存失败"] }),
  });

  const test = useMutation({
    mutationFn: () => api<EmbedTestOut>("/api/v1/system/embed/test", { method: "POST" }),
    onSuccess: (res) => setProbe(res),
    onError: (err) =>
      setProbe({
        ok: false,
        provider: null,
        model: null,
        dim: 0,
        note: null,
        error: err instanceof Error ? err.message : "测试失败",
      }),
  });

  const locked = (key: string) =>
    embed.data?.fields.find((f) => f.key === key)?.locked_by_env ?? false;
  const keyHint = embed.data?.fields.find((f) => f.key === "embed_api_key")?.hint_value ?? null;

  const pairIncomplete = Boolean(base.trim()) !== Boolean(model.trim());
  const dirty =
    (embed.data?.fields.find((f) => f.key === "embed_api_base")?.value ?? "") !== base ||
    (embed.data?.fields.find((f) => f.key === "embed_model")?.value ?? "") !== model ||
    (keyTouched && apiKey.trim().length > 0);

  function submit(extra?: Record<string, string>) {
    const body: Record<string, string> = {
      embed_api_base: base.trim(),
      embed_model: model.trim(),
    };
    if (keyTouched) body.embed_api_key = apiKey.trim();
    save.mutate({ ...body, ...(extra ?? {}) });
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Database className="h-4 w-4" />
          </span>
          <div>
            <CardTitle className="text-base">Embedding（向量化）API</CardTitle>
            <CardDescription>
              知识点的语义检索靠向量完成。<strong>留空即使用本地 mock 向量</strong>
              ：完全离线可用、不消耗额度，只是语义检索精度有限。填写一个 OpenAI 兼容的
              /embeddings 服务后即时生效，无需重启。
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {embed.isLoading && <p className="text-muted-foreground">加载中…</p>}
        {embed.isError && (
          <p className="text-destructive">
            读取 Embedding 配置失败：
            {embed.error instanceof Error ? embed.error.message : "未知错误"}
          </p>
        )}

        {embed.data && (
          <>
            <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-muted/30 px-3 py-2.5">
              <Badge variant={embed.data.active ? "success" : "secondary"}>
                {embed.data.active ? (
                  <>
                    <CheckCircle2 className="h-3 w-3" />
                    已启用自定义 API
                  </>
                ) : (
                  <>
                    <Cpu className="h-3 w-3" />
                    未填写 · 自动回退
                  </>
                )}
              </Badge>
              <span className="text-muted-foreground">
                当前实际使用：
                <code className="ml-1 text-foreground">{embed.data.effective_provider}</code>
                {embed.data.effective_model ? (
                  <code className="ml-1 text-muted-foreground">/ {embed.data.effective_model}</code>
                ) : null}
              </span>
            </div>

            {embed.data.note && (
              <p className="text-xs leading-relaxed text-muted-foreground">{embed.data.note}</p>
            )}

            <div className="space-y-3">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground" htmlFor="embed-base">
                  Embedding API 地址
                  <span className="ml-2 font-normal text-muted-foreground/70">EMBED_API_BASE</span>
                </label>
                <Input
                  id="embed-base"
                  value={base}
                  disabled={locked("embed_api_base") || save.isPending}
                  spellCheck={false}
                  placeholder="https://api.openai.com/v1"
                  onChange={(e) => setBase(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  OpenAI 兼容的接口前缀，末尾的 <code>/v1</code> 要保留。
                  {locked("embed_api_base") && "（由启动环境变量固定，页面不可改）"}
                </p>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground" htmlFor="embed-model">
                  Embedding 模型
                  <span className="ml-2 font-normal text-muted-foreground/70">EMBED_MODEL</span>
                </label>
                <Input
                  id="embed-model"
                  value={model}
                  disabled={locked("embed_model") || save.isPending}
                  spellCheck={false}
                  placeholder="text-embedding-3-small"
                  onChange={(e) => setModel(e.target.value)}
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-medium text-muted-foreground" htmlFor="embed-key">
                  Embedding API 密钥
                  <span className="ml-2 font-normal text-muted-foreground/70">EMBED_API_KEY</span>
                </label>
                <Input
                  id="embed-key"
                  type="password"
                  value={apiKey}
                  disabled={locked("embed_api_key") || save.isPending}
                  spellCheck={false}
                  autoComplete="off"
                  placeholder={keyHint ? `已保存（${keyHint}），留空表示不修改` : "sk-...（本地无鉴权服务可留空）"}
                  onChange={(e) => {
                    setApiKey(e.target.value);
                    setKeyTouched(true);
                  }}
                />
                <p className="text-xs text-muted-foreground">
                  只保存在本机的 <code>backend/config/runtime.json</code>，页面不会回显明文。
                </p>
              </div>
            </div>

            {pairIncomplete && (
              <p className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-foreground">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
                地址与模型名需要同时填写；两者都留空即走自动回退（本地 mock 向量）。
              </p>
            )}

            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                disabled={save.isPending || pairIncomplete || !dirty}
                onClick={() => submit()}
              >
                <Save />
                {save.isPending ? "保存中…" : "保存"}
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={test.isPending || embed.isLoading}
                onClick={() => test.mutate()}
                title="用当前生效的供应商真实向量化一段文本"
              >
                <PlugZap />
                {test.isPending ? "测试中…" : "测试连通性"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={save.isPending}
                onClick={() => {
                  setBase("");
                  setModel("");
                  setApiKey("");
                  setKeyTouched(true);
                  submit({ embed_api_base: "", embed_model: "", embed_api_key: "" });
                }}
                title="清空三项配置，向量化回到自动回退"
              >
                <Eraser />
                清空并回到 mock
              </Button>
            </div>

            {probe && (
              <div
                className={`rounded-lg border p-3 text-xs ${
                  probe.ok
                    ? "border-success/30 bg-success/5"
                    : "border-destructive/30 bg-destructive/5"
                }`}
              >
                {probe.ok ? (
                  <p className="flex flex-wrap items-center gap-2">
                    <Badge variant="success">
                      <CheckCircle2 className="h-3 w-3" />
                      向量化成功
                    </Badge>
                    <span className="text-muted-foreground">
                      provider=<code>{probe.provider}</code> · model=<code>{probe.model}</code> · 维度=
                      <code>{probe.dim}</code>
                    </span>
                  </p>
                ) : (
                  <p className="flex items-start gap-2 text-destructive">
                    <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                    <span className="break-all">测试失败：{probe.error}</span>
                  </p>
                )}
              </div>
            )}

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

            <p className="border-t pt-3 text-xs text-muted-foreground">
              覆盖项保存在 <code className="break-all">{embed.data.overrides_file}</code>
              （已加入 .gitignore）。修改后下一个请求即生效，无需重启后端。
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
