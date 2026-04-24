import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex h-11 items-center justify-center rounded-[6px] border-2 border-[#171914] px-4 text-sm font-black transition active:translate-x-[2px] active:translate-y-[2px]",
  {
    variants: {
      variant: {
        primary: "bg-[#d9ff3f] text-[#171914] shadow-[4px_4px_0_#171914] hover:bg-[#ffdd45]",
        danger: "bg-[#ff4f31] text-white shadow-[4px_4px_0_#171914] hover:bg-[#e94125]",
        quiet: "bg-white text-[#171914] hover:bg-[#f1f4ef]",
      },
    },
    defaultVariants: {
      variant: "primary",
    },
  }
);

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants>;

export function Button({ className, variant, ...props }: ButtonProps) {
  return <button className={cn(buttonVariants({ variant }), className)} {...props} />;
}
