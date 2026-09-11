import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Card 家族：保留原有 5 个组件的 API，扩展视觉
 * - 默认 shadow-soft；interactive = 悬浮 translate + lift
 * - gradient = 渐变描边（仅 1px 透明边框 + 渐变背景裁切）
 * - glass = 玻璃态（用于浮在内容上时）
 */
export function Card({
  className,
  interactive = false,
  variant = "default",
  ...props
}: React.HTMLAttributes<HTMLDivElement> & {
  interactive?: boolean;
  variant?: "default" | "gradient" | "glass";
}) {
  const base =
    variant === "gradient"
      ? "card-gradient rounded-xl text-card-foreground"
      : variant === "glass"
        ? "glass rounded-xl border text-card-foreground"
        : "rounded-xl border bg-card text-card-foreground shadow-soft";

  return (
    <div
      className={cn(
        base,
        // `hover-lift` already carries its own explicit transition list.
        // Adding Tailwind's `transition-shadow` here would override it (it sits
        // in a later layer), leaving `transform` un-animated — the lift would
        // then snap instead of glide, and hover in/out looked like a twitch.
        interactive && "hover-lift cursor-pointer hover:shadow-lift",
        className
      )}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col space-y-1.5 p-6", className)} {...props} />;
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3
      className={cn(
        "text-lg font-semibold leading-tight tracking-tight",
        className
      )}
      {...props}
    />
  );
}

export function CardDescription({
  className,
  ...props
}: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm text-muted-foreground leading-relaxed", className)} {...props} />;
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-6 pt-0", className)} {...props} />;
}

export function CardFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex items-center p-6 pt-0", className)} {...props} />;
}
