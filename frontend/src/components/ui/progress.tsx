import { cn } from "@/lib/utils";

/**
 * Progress：渐变填充 + 可选 label（百分比或自定义文本）
 * - 默认走品牌渐变
 * - 填充动画 transition-all duration-500
 * - 圆角继承父级
 */
export function Progress({
  value,
  className,
  showLabel = false,
  label,
}: {
  value: number;
  className?: string;
  showLabel?: boolean;
  label?: string;
}) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="space-y-1.5">
      {showLabel && (
        <div className="flex items-center justify-between text-xs">
          <span className="font-medium text-foreground">{label || "进度"}</span>
          <span className="tabular-nums text-muted-foreground">{Math.round(pct)}%</span>
        </div>
      )}
      <div
        className={cn(
          "relative h-2 w-full overflow-hidden rounded-full bg-muted",
          className
        )}
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="h-full rounded-full bg-gradient-brand transition-[width] duration-500 ease-out"
          style={{ width: `${pct}%` }}
        />
        <div
          className="pointer-events-none absolute inset-y-0 left-0 w-12 opacity-40"
          style={{
            background:
              "linear-gradient(90deg, transparent, rgba(255,255,255,.6), transparent)",
            transform: `translateX(${pct * 4}px)`,
          }}
        />
      </div>
    </div>
  );
}
