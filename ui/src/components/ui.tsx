import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-pine/40",
  {
    variants: {
      variant: {
        default: "bg-pine text-white hover:bg-pine-deep",
        secondary: "bg-sand text-ink hover:bg-line",
        outline: "border border-line bg-card text-ink hover:bg-sand",
        ghost: "text-ink hover:bg-sand",
      },
      size: {
        default: "h-10 px-4",
        sm: "h-8 rounded-md px-3 text-xs",
        lg: "h-11 px-5",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "button";
  return <Comp className={cn(buttonVariants({ variant, size, className }))} {...props} />;
}

export function Input(props: React.ComponentProps<"input">) {
  return (
    <input
      {...props}
      className={cn(
        "h-10 w-full rounded-md border border-line bg-card px-3 text-sm text-ink outline-none placeholder:text-muted focus:border-pine",
        props.className,
      )}
    />
  );
}

export function Textarea(props: React.ComponentProps<"textarea">) {
  return (
    <textarea
      {...props}
      className={cn(
        "min-h-36 w-full rounded-md border border-line bg-card px-3 py-2 text-sm leading-6 text-ink outline-none placeholder:text-muted focus:border-pine",
        props.className,
      )}
    />
  );
}

export function Card({ className, ...props }: React.ComponentProps<"section">) {
  return (
    <section
      {...props}
      className={cn("rounded-lg border border-line bg-card p-4 shadow-[0_1px_0_rgba(30,26,20,0.04)]", className)}
    />
  );
}

const badgeVariants = cva("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", {
  variants: {
    tone: {
      neutral: "bg-sand text-ink",
      ok: "bg-ok-bg text-ok",
      warn: "bg-warn-bg text-warn",
      bad: "bg-bad-bg text-bad",
      live: "bg-pine text-white",
    },
  },
  defaultVariants: { tone: "neutral" },
});

export function Badge({
  className,
  tone,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone, className }))} {...props} />;
}

export function statusTone(status: string): "neutral" | "ok" | "warn" | "bad" | "live" {
  if (status === "succeeded" || status === "active") return "ok";
  if (status === "needs_review" || status === "paused" || status === "draft") return "warn";
  if (status === "failed") return "bad";
  if (status === "running" || status === "pending") return "live";
  return "neutral";
}
