import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export interface CheckboxProps
  extends InputHTMLAttributes<HTMLInputElement> {
  label?: React.ReactNode;
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, label, id, ...props }, ref) => (
    <label
      htmlFor={id}
      className="flex cursor-pointer items-center gap-2 text-sm text-fg"
    >
      <input
        ref={ref}
        id={id}
        type="checkbox"
        className={cn(
          "h-4 w-4 rounded border-border-strong text-brand-600",
          "focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20",
          className,
        )}
        {...props}
      />
      {label && <span className="select-none">{label}</span>}
    </label>
  ),
);
Checkbox.displayName = "Checkbox";
