"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { FormEvent, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  Bot,
  Loader2,
  MessageSquareQuote,
  Send,
  Sparkles,
  User,
} from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api, useAuth } from "@/lib/api";
import { CONTENT_TYPE_LABELS, type Citation } from "@/lib/types";

type Msg = { id: string; role: string; content: string; citations: Citation[] };

function CitationCard({ c }: { c: Citation }) {
  const typeLabel = CONTENT_TYPE_LABELS[c.content_type] ?? c.content_type;
  return (
    <div className="space-y-1.5 rounded-lg border border-border/60 bg-background/60 p-2.5 text-xs">
      <div className="flex flex-wrap items-center gap-1.5">
        {c.printed_page != null && <Badge>书内 p.{c.printed_page}</Badge>}
        {c.page_number != null && c.page_number !== c.printed_page && (
          <Badge variant="outline">PDF p.{c.page_number}</Badge>
        )}
        {c.printed_page == null && c.page_number == null && (
          <Badge variant="outline">{c.locator || c.chunk_id.slice(0, 8)}</Badge>
        )}
        <Badge variant="soft">{typeLabel}</Badge>
        {c.score != null && (
          <span className="text-muted-foreground">score {c.score.toFixed(2)}</span>
        )}
      </div>
      {c.section_title && (
        <p className="font-medium text-foreground/80">{c.section_title}</p>
      )}
      <p className="whitespace-pre-wrap text-muted-foreground leading-relaxed">{c.quote}</p>
    </div>
  );
}

export default function TutorPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const token = useAuth((s) => s.token);
  const router = useRouter();
  const qc = useQueryClient();
  const [message, setMessage] = useState("What is the main idea of this source?");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!token) router.replace("/login");
  }, [token, router]);

  const history = useQuery({
    queryKey: ["tutor", id],
    queryFn: () => api<Msg[]>(`/api/v1/sources/${id}/tutor/messages`),
    enabled: !!token,
  });

  const send = useMutation({
    mutationFn: (text: string) =>
      api<Msg>(`/api/v1/sources/${id}/tutor/chat`, {
        method: "POST",
        body: JSON.stringify({ message: text }),
      }),
    onSuccess: () => {
      setMessage("");
      void qc.invalidateQueries({ queryKey: ["tutor", id] });
    },
  });

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [history.data, send.isPending]);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (message.trim()) send.mutate(message.trim());
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background">
      <AppHeader />

      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-4 sm:px-6">
        <div className="flex items-center gap-3 border-b py-4">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-brand text-white shadow-soft">
            <MessageSquareQuote className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Socratic tutor</h1>
            <p className="text-xs text-muted-foreground">
              基于检索到的原文片段回答，每条都附带页码或时间戳引用。
            </p>
          </div>
        </div>

        <div
          ref={scrollRef}
          className="scroll-smooth-x flex-1 space-y-4 overflow-y-auto py-4"
        >
          {history.isLoading && (
            <div className="space-y-3">
              <SkeletonBubble who="user" />
              <SkeletonBubble who="bot" />
            </div>
          )}
          {!history.isLoading && (history.data?.length ?? 0) === 0 && (
            <div className="rounded-xl border border-dashed bg-card/50 p-8 text-center">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-brand text-white shadow-soft">
                <Sparkles className="h-6 w-6" />
              </div>
              <p className="mt-3 text-sm font-medium">开始第一轮对话</p>
              <p className="mt-1 text-xs text-muted-foreground">
                导师只引用你这本资料里的原文，绝不胡编。
              </p>
            </div>
          )}
          {(history.data || []).map((m) => (
            <Bubble key={m.id} role={m.role} content={m.content} citations={m.citations} />
          ))}
          {send.isPending && (
            <Bubble role="assistant" content="" pending citations={[]} />
          )}
        </div>

        <form
          className="space-y-2 border-t bg-card/40 py-4 backdrop-blur-sm"
          onSubmit={onSubmit}
        >
          {send.isError && (
            <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive animate-fade-in">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span className="leading-relaxed break-all">
                {send.error instanceof Error ? send.error.message : "Failed"}
              </span>
            </div>
          )}
          <div className="flex items-end gap-2">
            <Textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={3}
              placeholder="把你最想问的问题写在这里…"
              className="flex-1"
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  if (message.trim()) send.mutate(message.trim());
                }
              }}
            />
            <Button
              type="submit"
              variant="gradient"
              size="lg"
              pending={send.isPending}
              disabled={!message.trim()}
              className="h-[88px] px-5"
            >
              <span className="flex flex-col items-center gap-1">
                {send.isPending ? <Loader2 className="animate-spin" /> : <Send />}
                <span className="text-[10px] opacity-80">Ctrl+↵</span>
              </span>
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

function Bubble({
  role,
  content,
  citations,
  pending = false,
}: {
  role: string;
  content: string;
  citations: Citation[];
  pending?: boolean;
}) {
  const isUser = role === "user";
  return (
    <div className={["flex gap-2.5", isUser ? "flex-row-reverse" : ""].join(" ")}>
      <span
        className={[
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full shadow-soft",
          isUser
            ? "bg-secondary text-secondary-foreground"
            : "bg-gradient-brand text-white",
        ].join(" ")}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </span>
      <div
        className={[
          "max-w-[80%] space-y-2 rounded-2xl px-4 py-3 text-sm leading-relaxed",
          isUser
            ? "rounded-tr-sm bg-secondary text-secondary-foreground"
            : "rounded-tl-sm border bg-card shadow-soft",
          pending && "animate-pulse-soft",
        ].join(" ")}
      >
        {pending ? (
          <span className="inline-flex items-center gap-1 text-muted-foreground">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary [animation-delay:-0.3s]" />
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary [animation-delay:-0.15s]" />
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
          </span>
        ) : (
          <>
            <p className="whitespace-pre-wrap break-words">{content}</p>
            {citations && citations.length > 0 && (
              <div className="mt-2 space-y-2 border-t pt-2">
                <p className="text-xs font-medium text-muted-foreground">引用来源</p>
                {citations.map((c) => (
                  <CitationCard key={c.chunk_id} c={c} />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function SkeletonBubble({ who }: { who: "user" | "bot" }) {
  return (
    <div className={["flex gap-2.5", who === "user" ? "flex-row-reverse" : ""].join(" ")}>
      <div className="skeleton h-8 w-8 rounded-full" />
      <div className="space-y-1.5">
        <div className="skeleton h-3 w-32" />
        <div className="skeleton h-3 w-48" />
      </div>
    </div>
  );
}
