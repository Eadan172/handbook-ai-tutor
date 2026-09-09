"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AppHeader } from "@/components/app-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, useAuth } from "@/lib/api";

type Quiz = {
  id: string;
  title: string;
  questions: { id: string; ordinal: number; question: string; options: string[] }[];
};

type Attempt = {
  score: number;
  passed: boolean;
  results: {
    question_id: string;
    selected_index: number;
    correct_index: number;
    correct: boolean;
    explanation: string;
  }[];
};

export default function QuizPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const token = useAuth((s) => s.token);
  const router = useRouter();
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [result, setResult] = useState<Attempt | null>(null);

  useEffect(() => {
    if (!token) router.replace("/login");
  }, [token, router]);

  const quizQuery = useQuery({
    queryKey: ["quiz", id],
    queryFn: () => api<Quiz>(`/api/v1/sources/${id}/quiz`),
    enabled: !!token,
    retry: false,
  });

  const generate = useMutation({
    mutationFn: () => api<Quiz>(`/api/v1/sources/${id}/quiz/generate`, { method: "POST" }),
    onSuccess: () => {
      setResult(null);
      setAnswers({});
      void quizQuery.refetch();
    },
  });

  const submit = useMutation({
    mutationFn: (quizId: string) =>
      api<Attempt>(`/api/v1/quizzes/${quizId}/attempt`, {
        method: "POST",
        body: JSON.stringify({
          answers: Object.entries(answers).map(([question_id, selected_index]) => ({
            question_id,
            selected_index,
          })),
        }),
      }),
    onSuccess: setResult,
  });

  const quiz = generate.data || quizQuery.data;

  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-3xl space-y-6 px-6 py-8">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Quiz</h1>
          <Button onClick={() => generate.mutate()} disabled={generate.isPending}>
            {generate.isPending ? "Generating…" : "Generate quiz"}
          </Button>
        </div>
        {quizQuery.isError && !quiz && (
          <p className="text-sm text-muted-foreground">No quiz yet. Generate one from this source.</p>
        )}
        {quiz && (
          <Card>
            <CardHeader>
              <CardTitle>{quiz.title}</CardTitle>
              <CardDescription>Answers stay hidden until you submit.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {quiz.questions.map((q, idx) => (
                <div key={q.id} className="space-y-2">
                  <p className="font-medium">
                    {idx + 1}. {q.question}
                  </p>
                  <div className="space-y-1">
                    {q.options.map((opt, i) => (
                      <label key={i} className="flex items-center gap-2 text-sm">
                        <input
                          type="radio"
                          name={q.id}
                          checked={answers[q.id] === i}
                          onChange={() => setAnswers((prev) => ({ ...prev, [q.id]: i }))}
                        />
                        {opt}
                      </label>
                    ))}
                  </div>
                  {result && (
                    <p className="text-sm text-muted-foreground">
                      {result.results.find((r) => r.question_id === q.id)?.correct ? "Correct. " : "Incorrect. "}
                      {result.results.find((r) => r.question_id === q.id)?.explanation}
                    </p>
                  )}
                </div>
              ))}
              <Button onClick={() => submit.mutate(quiz.id)} disabled={submit.isPending}>
                Submit
              </Button>
              {result && (
                <p className="text-sm font-medium">
                  Score {Math.round(result.score * 100)}% {result.passed ? "· passed" : "· keep practicing"}
                </p>
              )}
            </CardContent>
          </Card>
        )}
      </main>
    </div>
  );
}
