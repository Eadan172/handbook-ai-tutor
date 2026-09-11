import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/**
 * Badge：保留 default/secondary/outline，新增
 * - success / warning / info / destructive：语义色
 * - soft：淡化背景版（用于不高亮但要可读）
 * - gradient：品牌渐变（用于高亮的「状态：ready」之类的关键状态）
 */
export type BadgeVariant =
  | "default"
  | "secondary"
  | "outline"
  | "success"
  | "warning"
  | "info"
  | "destructive"
  | "soft"
  | "gradient";

const VARIANT_CLASSES: Record<BadgeVariant, string> = {
  default: "border-transparent bg-primary text-primary-foreground",
  secondary: "border-transparent bg-secondary text-secondary-foreground",
  outline: "text-foreground",
  success: "border-transparent bg-success text-success-foreground",
  warning: "border-transparent bg-warning text-warning-foreground",
  info: "border-transparent bg-info text-info-foreground",
  destructive: "border-transparent bg-destructive text-destructive-foreground",
  soft: "border-transparent bg-primary/10 text-primary",
  gradient:
    "border-transparent bg-gradient-brand text-white shadow-soft",
};

export function Badge({
  className,
  variant = "default",
  ...props
}: HTMLAttributes<HTMLDivElement> & { variant?: BadgeVariant }) {
  return (
    <div
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
        VARIANT_CLASSES[variant],
        className
      )}
      {...props}
    />
  );
}
