import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Input：
 * - 保留原有 forwardRef + InputHTMLAttributes API
 * - focus 时光晕从 1px 边升级为 2px 环 + 边框变主色
 * - hover 时边框轻微提亮，引导可交互
 * - placeholder 弱化但保持可读
 */
const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type, ...props }, ref) => (
    <input
      type={type}
      className={cn(
        "flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm",
        "transition-all duration-200",
        "file:border-0 file:bg-transparent file:text-sm file:font-medium",
        "placeholder:text-muted-foreground/70",
        "hover:border-foreground/20",
        "focus-visible:outline-none focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/30",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      ref={ref}
      {...props}
    />
  )
);
Input.displayName = "Input";
export { Input };
