"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/api";

export default function HomePage() {
  const token = useAuth((s) => s.token);
  const router = useRouter();
  useEffect(() => {
    router.replace(token ? "/dashboard" : "/login");
  }, [token, router]);
  return (
    <main className="flex min-h-screen items-center justify-center">
      <Link href="/login" className="text-sm text-muted-foreground">
        Opening…
      </Link>
    </main>
  );
}
