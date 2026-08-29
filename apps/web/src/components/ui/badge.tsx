import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type Tone = "neutral" | "brand" | "success" | "danger" | "warning";

const TONES: Record<Tone, string> = {
  neutral: "bg-bg-muted text-fg-muted",
  brand: "bg-brand-50 text-brand-700",
  success: "bg-success-50 text-success-700",
  danger: "bg-danger-50 text-danger-700",
  warning: "bg-warning-50 text-warning-700",
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
}

export function Badge({ className, tone = "neutral", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
        TONES[tone],
        className,
      )}
      {...props}
    />
  );
}
