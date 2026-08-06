import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '../../lib/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap border text-sm font-semibold transition-colors disabled:pointer-events-none disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400/60',
  {
    variants: {
      variant: {
        default: 'border-blue-500 bg-blue-600 text-white hover:bg-blue-500',
        secondary: 'border-zinc-700 bg-zinc-800 text-zinc-100 hover:bg-zinc-700',
        outline: 'border-zinc-700 bg-transparent text-zinc-200 hover:bg-zinc-800',
        ghost: 'border-transparent bg-transparent text-zinc-300 hover:bg-zinc-800',
        danger: 'border-red-900 bg-red-950/40 text-red-300 hover:bg-red-950/70',
      },
      size: {
        default: 'h-9 px-3 rounded-[3px]',
        sm: 'h-8 px-2.5 rounded-[3px] text-xs',
        icon: 'h-8 w-8 rounded-[3px] p-0',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button';
    return <Comp ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />;
  },
);
Button.displayName = 'Button';
