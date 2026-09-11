"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { BookOpen, Loader2 } from "lucide-react";
import { useAuth } from "@/lib/api";

export default function HomePage() {
  const token = useAuth((s) => s.token);
  const router = useRouter();
  useEffect(() => {
    router.replace(token ? "/dashboard" : "/login");
  }, [token, router]);
  return (
    <main className="flex min-h-screen items-center justify-center bg-gradient-brand">
      <div className="flex flex-col items-center gap-4 text-white animate-fade-up">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-white/20 shadow-lift backdrop-blur-sm">
          <BookOpen className="h-8 w-8" />
        </div>
        <p className="text-lg font-semibold tracking-tight">Handbook AI Tutor</p>
        <div className="flex items-center gap-2 text-sm text-white/85">
          <Loader2 className="h-4 w-4 animate-spin" />
          <Link href="/login" className="hover:underline">
            正在跳转…
          </Link>
        </div>
      </div>
    </main>
  );
}
