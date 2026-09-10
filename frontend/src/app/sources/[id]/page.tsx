"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";
import { AppHeader } from "@/components/app-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { api, useAuth } from "@/lib/api";

type Source = {
  id: string;
  filename: string;
  kind: string;
  status: string;
  title: string | null;
  task_id?: string | null;
};

type Task = { id: string; status: string; progress: number; step: string; message: string | null };
type Summary = { title: string; overview: string; outline: string[] };
type Knowledge = { id: string; title: string; summary: string; key_terms: string[]; chunk_ids: string[] };

export default function SourcePage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const token = useAuth((s) => s.token);
  const router = useRouter();

  useEffect(() => {
    if (!token) router.replace("/login");
  }, [token, router]);

  const source = useQuery({
    queryKey: ["source", id],
    queryFn: () => api<Source>(`/api/v1/sources/${id}`),
    enabled: !!token && !!id,
    refetchInterval: (q) => (q.state.data?.status === "ready" || q.state.data?.status === "failed" ? false : 1500),
  });

  const taskId = source.data?.task_id;
  const task = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => api<Task>(`/api/v1/tasks/${taskId}`),
    enabled: !!token && !!taskId,
    refetchInterval: (q) =>
      q.state.data?.status === "succeeded" || q.state.data?.status === "failed" ? false : 1000,
  });

  const ready = source.data?.status === "ready";
  const summary = useQuery({
    queryKey: ["summary", id],
    queryFn: () => api<Summary>(`/api/v1/sources/${id}/summary`),
    enabled: !!token && ready,
  });
  const knowledge = useQuery({
    queryKey: ["knowledge", id],
    queryFn: () => api<Knowledge[]>(`/api/v1/sources/${id}/knowledge`),
    enabled: !!token && ready,
  });

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-5xl space-y-6 px-6 py-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold">{source.data?.title || source.data?.filename || "Source"}</h1>
            <p className="text-sm text-muted-foreground">{source.data?.filename}</p>
          </div>
          <div className="flex gap-2">
            <Button asChild variant="secondary">
              <Link href={`/sources/${id}/quiz`}>Quiz</Link>
            </Button>
            <Button asChild>
              <Link href={`/sources/${id}/tutor`}>Tutor</Link>
            </Button>
          </div>
        </div>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Pipeline</CardTitle>
              <Badge>{source.data?.status || "…"}</Badge>
            </div>
            <CardDescription>
              Step: {task.data?.step || "—"} {task.data?.message ? `· ${task.data.message}` : ""}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Progress value={task.data?.progress ?? (ready ? 100 : 5)} />
          </CardContent>
        </Card>

        {summary.data && (
          <Card>
            <CardHeader>
              <CardTitle>{summary.data.title}</CardTitle>
              <CardDescription>Auto summary (prompt summarize.v1)</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="whitespace-pre-wrap text-sm leading-6">{summary.data.overview}</p>
              <ul className="list-disc pl-5 text-sm text-muted-foreground">
                {summary.data.outline.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}

        {knowledge.data && knowledge.data.length > 0 && (
          <div className="grid gap-4 md:grid-cols-2">
            {knowledge.data.map((k) => (
              <Card key={k.id}>
                <CardHeader>
                  <CardTitle className="text-base">{k.title}</CardTitle>
                  <CardDescription>{k.key_terms.join(" · ")}</CardDescription>
                </CardHeader>
                <CardContent>
                  <p className="text-sm leading-6">{k.summary}</p>
                  {k.chunk_ids.length > 0 && (
                    <p className="mt-2 text-xs text-muted-foreground">Grounded in {k.chunk_ids.length} chunk(s)</p>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
