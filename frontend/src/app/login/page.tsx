"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import {
  AlertCircle,
  ArrowRight,
  BookOpen,
  FileText,
  GraduationCap,
  HelpCircle,
  Lock,
  Mail,
  MessageSquareQuote,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, useAuth } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const setToken = useAuth((s) => s.setToken);
  const setUser = useAuth((s) => s.setUser);
  const [email, setEmail] = useState("demo@example.com");
  const [password, setPassword] = useState("password123");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      const tok = await api<{ access_token: string }>("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setToken(tok.access_token);
      const me = await api<{ id: string; email: string }>("/api/v1/auth/me");
      setUser(me);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-2">
      <AuthHero />

      <div className="flex items-center justify-center px-4 py-12 sm:px-6 lg:px-12">
        <Card className="w-full max-w-md animate-fade-up border-border/70 shadow-lift">
          <CardHeader className="space-y-2 pb-2">
            <Badge className="w-fit">欢迎回来</Badge>
            <CardTitle className="text-2xl">登录学习空间</CardTitle>
            <CardDescription>
              上传一份 PDF / MP4 / 截图，AI 会帮你梳理、做 Quiz、当导师讲解。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5 pt-4">
            <form className="space-y-4" onSubmit={onSubmit}>
              <Field label="邮箱" icon={<Mail className="h-4 w-4" />}>
                <Input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  required
                  autoComplete="email"
                />
              </Field>
              <Field label="密码" icon={<Lock className="h-4 w-4" />}>
                <Input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="至少 8 位"
                  required
                  autoComplete="current-password"
                />
              </Field>
              {error && (
                <div
                  role="alert"
                  className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2.5 text-sm text-destructive animate-fade-in"
                >
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span className="leading-relaxed break-all">{error}</span>
                </div>
              )}
              <Button
                type="submit"
                className="w-full"
                size="lg"
                variant="gradient"
                pending={pending}
              >
                {pending ? "登录中…" : "登录"}
                {!pending && <ArrowRight />}
              </Button>
            </form>
            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-card px-2 text-muted-foreground">或</span>
              </div>
            </div>
            <p className="text-center text-sm text-muted-foreground">
              还没有账号？
              <Link
                href="/register"
                className="ml-1 font-medium text-primary underline-offset-4 hover:underline"
              >
                立即注册
              </Link>
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Field({
  label,
  icon,
  children,
}: {
  label: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-1.5">
      <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        {icon}
        {label}
      </span>
      {children}
    </label>
  );
}

function Badge({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <span
      className={[
        "inline-flex items-center gap-1 rounded-full bg-primary/10 px-2.5 py-0.5",
        "text-xs font-medium text-primary",
        className,
      ].join(" ")}
    >
      <Sparkles className="h-3 w-3" />
      {children}
    </span>
  );
}

function AuthHero() {
  return (
    <div className="relative hidden overflow-hidden bg-gradient-brand lg:block">
      <div className="absolute inset-0 opacity-30">
        <div className="absolute -left-20 top-20 h-72 w-72 rounded-full bg-white/20 blur-3xl" />
        <div className="absolute right-0 top-1/2 h-96 w-96 -translate-y-1/2 rounded-full bg-white/10 blur-3xl" />
        <div className="absolute bottom-10 left-1/3 h-64 w-64 rounded-full bg-white/15 blur-3xl" />
      </div>
      <div className="relative flex h-full flex-col justify-between p-12 text-white">
        <div className="flex items-center gap-2 text-lg font-semibold">
          <BookOpen className="h-6 w-6" />
          Handbook AI Tutor
        </div>

        <div className="max-w-md space-y-6">
          <h2 className="text-3xl font-bold leading-tight">
            让每一份学习资料
            <br />
            都被 AI 认真读过一遍
          </h2>
          <p className="text-base leading-relaxed text-white/85">
            上传 PDF、MP4 或图片，AI 自动拆解章节、梳理知识点、按你的薄弱点出题并讲解。
            所有调用在本地后端完成，浏览器不接触任何 API KEY。
          </p>
          <ul className="space-y-3 text-sm">
            <Feature
              icon={<FileText className="h-4 w-4" />}
              title="结构化解析"
              desc="正文、标题、图注、公式、表格被分别识别，页码同时给书内页码与 PDF 页码。"
            />
            <Feature
              icon={<GraduationCap className="h-4 w-4" />}
              title="按章节出题 + 解析"
              desc="选择题 / 翻译 / 写作 / 口语混合题型，提交后立刻给出 AI 解析。"
            />
            <Feature
              icon={<MessageSquareQuote className="h-4 w-4" />}
              title="带引用的导师讲解"
              desc="每个回答都标注书内页码与 PDF 页码，定位到具体原文切片。"
            />
          </ul>
        </div>

        <div className="flex items-center gap-2 text-xs text-white/70">
          <HelpCircle className="h-3.5 w-3.5" />
          第一次使用？默认账号已预填，点登录即可体验。
        </div>
      </div>
    </div>
  );
}

function Feature({
  icon,
  title,
  desc,
}: {
  icon: React.ReactNode;
  title: string;
  desc: string;
}) {
  return (
    <li className="flex items-start gap-3">
      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-white/15 backdrop-blur-sm">
        {icon}
      </span>
      <div>
        <p className="font-medium">{title}</p>
        <p className="text-xs leading-relaxed text-white/75">{desc}</p>
      </div>
    </li>
  );
}
