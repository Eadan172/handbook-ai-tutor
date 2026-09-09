"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { AppHeader } from "@/components/app-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { api, useAuth } from "@/lib/api";

type Citation = {
  chunk_id: string;
  locator?: string | null;
  page_number?: number | null;
  start_time?: number | null;
  end_time?: number | null;
  quote: string;
};

type Msg = { id: string; role: string; content: string; citations: Citation[] };

export default function TutorPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const token = useAuth((s) => s.token);
  const router = useRouter();
  const qc = useQueryClient();
  const [message, setMessage] = useState("What is the main idea of this source?");

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

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (message.trim()) send.mutate(message.trim());
  }

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-3xl space-y-6 px-6 py-8">
        <div>
          <h1 className="text-2xl font-semibold">Socratic tutor</h1>
          <p className="text-sm text-muted-foreground">
            Grounded in retrieved chunks with page or timestamp citations. The browser never calls an LLM vendor.
          </p>
        </div>
        <div className="space-y-4">
          {(history.data || []).map((m) => (
            <Card key={m.id}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm capitalize">{m.role}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="whitespace-pre-wrap text-sm leading-6">{m.content}</p>
                {m.citations?.length > 0 && (
                  <div className="space-y-2">
                    {m.citations.map((c) => (
                      <div key={c.chunk_id} className="rounded-md bg-muted p-3 text-xs">
                        <Badge variant="outline">{c.locator || c.chunk_id.slice(0, 8)}</Badge>
                        <p className="mt-1 text-muted-foreground">{c.quote}</p>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
        <form className="space-y-3" onSubmit={onSubmit}>
          <Textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={4} />
          {send.isError && (
            <p className="text-sm text-destructive">{send.error instanceof Error ? send.error.message : "Failed"}</p>
          )}
          <Button disabled={send.isPending}>{send.isPending ? "Thinking…" : "Ask"}</Button>
        </form>
      </main>
    </div>
  );
}
