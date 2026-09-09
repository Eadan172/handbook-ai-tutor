"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AppHeader } from "@/components/app-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, useAuth } from "@/lib/api";

type Source = {
  id: string;
  filename: string;
  kind: string;
  status: string;
  title: string | null;
  created_at: string;
};

export default function DashboardPage() {
  const token = useAuth((s) => s.token);
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    if (!token) router.replace("/login");
  }, [token, router]);

  const sources = useQuery({
    queryKey: ["sources"],
    queryFn: () => api<Source[]>("/api/v1/sources"),
    enabled: !!token,
    refetchInterval: 2000,
  });

  async function onFile(file: File) {
    setUploading(true);
    setError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      const created = await api<Source & { task_id?: string }>("/api/v1/sources/upload", {
        method: "POST",
        body,
      });
      router.push(`/sources/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-5xl space-y-8 px-6 py-8">
        <Card>
          <CardHeader>
            <CardTitle>Upload a source</CardTitle>
            <CardDescription>PDF or MP4. Processing is async (ARQ in Docker, inline in local/dev).</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <input
              type="file"
              accept=".pdf,.mp4,application/pdf,video/mp4"
              disabled={uploading}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void onFile(file);
              }}
            />
            {uploading && <p className="text-sm text-muted-foreground">Uploading and enqueueing…</p>}
            {error && <p className="text-sm text-destructive">{error}</p>}
          </CardContent>
        </Card>

        <section className="space-y-3">
          <h2 className="text-lg font-semibold">Your library</h2>
          <div className="grid gap-4 md:grid-cols-2">
            {(sources.data || []).map((s) => (
              <Link key={s.id} href={`/sources/${s.id}`}>
                <Card className="h-full hover:border-primary">
                  <CardHeader>
                    <div className="flex items-center justify-between gap-2">
                      <CardTitle className="text-base">{s.title || s.filename}</CardTitle>
                      <Badge variant="secondary">{s.status}</Badge>
                    </div>
                    <CardDescription>
                      {s.kind.toUpperCase()} · {s.filename}
                    </CardDescription>
                  </CardHeader>
                </Card>
              </Link>
            ))}
          </div>
          {sources.data?.length === 0 && (
            <p className="text-sm text-muted-foreground">Nothing uploaded yet. Drop a PDF or a short MP4 to start.</p>
          )}
        </section>
      </main>
    </div>
  );
}
