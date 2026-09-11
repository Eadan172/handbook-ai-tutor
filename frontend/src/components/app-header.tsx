"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { BookOpen, Cpu, LogOut, Mail } from "lucide-react";
import { useAuth } from "@/lib/api";
import { Button } from "@/components/ui/button";

/**
 * AppHeader：sticky + 毛玻璃 + 渐变品牌字 + 当前路由高亮
 * 移动端：品牌字 + 邮箱缩写 + 退出按钮，全部压扁
 */
export function AppHeader() {
  const user = useAuth((s) => s.user);
  const logout = useAuth((s) => s.logout);
  const router = useRouter();
  const pathname = usePathname();

  const navItems = [{ href: "/settings/llm", label: "模型路由", icon: Cpu }];

  return (
    <header className="sticky top-0 z-40 w-full border-b border-border/60 glass">
      <div className="mx-auto flex w-full max-w-[1600px] items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-6">
          <Link
            href="/dashboard"
            className="group flex items-center gap-2 transition-opacity hover:opacity-90"
          >
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-brand text-white shadow-soft transition-transform group-hover:scale-105">
              <BookOpen className="h-5 w-5" />
            </span>
            <span className="hidden text-base font-semibold tracking-tight sm:inline">
              <span className="text-gradient">Handbook</span>
              <span className="ml-1 text-foreground/90">AI Tutor</span>
            </span>
          </Link>
          <nav className="flex items-center gap-1">
            {navItems.map((item) => {
              const active = pathname?.startsWith(item.href);
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={[
                    "group inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium",
                    "transition-all duration-200",
                    active
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  ].join(" ")}
                >
                  <Icon className="h-4 w-4" />
                  <span>{item.label}</span>
                  {active && (
                    <span className="ml-0.5 h-1.5 w-1.5 rounded-full bg-gradient-brand" />
                  )}
                </Link>
              );
            })}
          </nav>
        </div>

        <div className="flex items-center gap-2 sm:gap-3">
          <div className="hidden items-center gap-2 rounded-full border border-border/60 bg-muted/40 px-3 py-1.5 text-xs text-muted-foreground sm:flex">
            <Mail className="h-3.5 w-3.5" />
            <span className="max-w-[180px] truncate">{user?.email}</span>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              logout();
              router.push("/login");
            }}
          >
            <LogOut />
            <span className="hidden sm:inline">退出登录</span>
          </Button>
        </div>
      </div>
    </header>
  );
}
