import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * 按钮设计原则：
 * - 主操作（default）= 渐变实心 + 悬浮光晕 + 按压回弹，最有重量
 * - 次操作（secondary）= 浅色填充，hover 略微加深
 * - 描边（outline）= 透明背景 + 描边，hover 时给一个轻填充
 * - 幽灵（ghost）= 完全无背景，只在 hover 时浮起
 * - 危险（destructive）= 红实心 + 按压反馈
 * - 渐变（gradient）= 同 default 但更亮，悬浮有外发光
 *
 * size 默认 h-10，lg h-11，sm h-9，icon 是 40×40 方块
 *
 * loading：传 pending=true 时按钮变 disabled + 内部换 Loader2 自转
 */
const buttonVariants = cva(
  [
    "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium",
    "transition-all duration-200 ease-out",
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
    "disabled:pointer-events-none disabled:opacity-50",
    "press",
    "[&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  ].join(" "),
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow-soft hover:shadow-glow hover:brightness-110",
        gradient:
          "bg-gradient-brand text-white shadow-soft hover:shadow-glow animate-gradient",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        outline:
          "border border-input bg-background hover:bg-accent/10 hover:text-accent-foreground hover:border-accent/40",
        ghost: "hover:bg-accent/10 hover:text-accent-foreground",
        destructive:
          "bg-destructive text-destructive-foreground shadow-soft hover:brightness-110",
        link: "text-primary underline-offset-4 hover:underline",
        soft: "bg-primary/10 text-primary hover:bg-primary/15",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-9 rounded-md px-3 text-xs",
        lg: "h-11 rounded-md px-6 text-base",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  /** 内部 loading 状态：自动变 disabled + 替换图标 */
  pending?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { className, variant, size, asChild = false, pending = false, children, disabled, ...props },
    ref
  ) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref as never}
        className={cn(buttonVariants({ variant, size, className }))}
        disabled={pending || disabled}
        aria-busy={pending || undefined}
        {...props}
      >
        {pending ? <Loader2 className="animate-spin" /> : children}
      </Comp>
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
