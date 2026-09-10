"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import {
  AlertCircle,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  FileText,
  GraduationCap,
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

export default function RegisterPage() {
  const router = useRouter();
  const setToken = useAuth((s) => s.setToken);
  const setUser = useAuth((s) => s.setUser);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      const tok = await api<{ access_token: string }>("/api/v1/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setToken(tok.access_token);
      const me = await api<{ id: string; email: string }>("/api/v1/auth/me");
      setUser(me);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Register failed");
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
            <span className="inline-flex w-fit items-center gap-1 rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
              <Sparkles className="h-3 w-3" />
              30 秒创建账号
            </span>
            <CardTitle className="text-2xl">开始你的智能学习</CardTitle>
            <CardDescription>
              密码至少 8 位。API KEY 全部存在后端，浏览器不接触任何密钥。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5 pt-4">
            <form className="space-y-4" onSubmit={onSubmit}>
              <label className="block space-y-1.5">
                <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  <Mail className="h-4 w-4" />
                  邮箱
                </span>
                <Input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                  required
                  autoComplete="email"
                />
              </label>
              <label className="block space-y-1.5">
                <span className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                  <Lock className="h-4 w-4" />
                  密码
                </span>
                <Input
                  type="password"
                  minLength={8}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="至少 8 位"
                  required
                  autoComplete="new-password"
                />
                <PasswordStrengthHint password={password} />
              </label>
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
                {pending ? "创建中…" : "注册并登录"}
                {!pending && <ArrowRight />}
              </Button>
            </form>
            <p className="text-center text-sm text-muted-foreground">
              已有账号？
              <Link
                href="/login"
                className="ml-1 font-medium text-primary underline-offset-4 hover:underline"
              >
                返回登录
              </Link>
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function PasswordStrengthHint({ password }: { password: string }) {
  if (!password) return null;
  const checks = [
    { ok: password.length >= 8, label: "至少 8 位" },
    { ok: /[A-Za-z]/.test(password) && /\d/.test(password), label: "字母 + 数字" },
  ];
  return (
    <div className="flex flex-wrap gap-2 pt-1 text-xs text-muted-foreground">
      {checks.map((c) => (
        <span
          key={c.label}
          className={[
            "inline-flex items-center gap-1 rounded-full px-2 py-0.5",
            c.ok ? "bg-success/10 text-success" : "bg-muted",
          ].join(" ")}
        >
          <CheckCircle2 className="h-3 w-3" />
          {c.label}
        </span>
      ))}
    </div>
  );
}

function AuthHero() {
  return (
    <div className="relative hidden overflow-hidden bg-gradient-brand lg:block">
      <div className="absolute inset-0 opacity-30">
        <div className="absolute -right-20 top-32 h-72 w-72 rounded-full bg-white/20 blur-3xl" />
        <div className="absolute left-0 top-1/2 h-96 w-96 -translate-y-1/2 rounded-full bg-white/10 blur-3xl" />
        <div className="absolute bottom-10 right-1/3 h-64 w-64 rounded-full bg-white/15 blur-3xl" />
      </div>
      <div className="relative flex h-full flex-col justify-between p-12 text-white">
        <div className="flex items-center gap-2 text-lg font-semibold">
          <BookOpen className="h-6 w-6" />
          Handbook AI Tutor
        </div>

        <div className="max-w-md space-y-6">
          <h2 className="text-3xl font-bold leading-tight">
            几秒钟，
            <br />
            拥有你的智能学习空间
          </h2>
          <p className="text-base leading-relaxed text-white/85">
            账号独立保存你的资料、笔记、Quiz 记录与对话历史。
            任何时候导出 JSON 带走，换设备也可一键还原。
          </p>
          <ul className="space-y-3 text-sm">
            <Feature
              icon={<FileText className="h-4 w-4" />}
              title="结构化解析"
              desc="正文、标题、图注、公式、表格被分别识别。"
            />
            <Feature
              icon={<GraduationCap className="h-4 w-4" />}
              title="按章节出题 + 解析"
              desc="提交后立即获得 AI 评分与逐题讲解。"
            />
            <Feature
              icon={<MessageSquareQuote className="h-4 w-4" />}
              title="带引用的导师讲解"
              desc="每个回答都标注书内页码与 PDF 页码。"
            />
          </ul>
        </div>

        <div className="text-xs text-white/70">
          已是老用户？
          <Link
            href="/login"
            className="ml-1 font-medium text-white underline-offset-4 hover:underline"
          >
            直接登录
          </Link>
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
