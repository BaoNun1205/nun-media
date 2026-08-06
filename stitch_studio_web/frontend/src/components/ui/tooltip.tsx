import * as React from 'react';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';

export const TooltipProvider = TooltipPrimitive.Provider;
export const Tooltip = TooltipPrimitive.Root;
export const TooltipTrigger = TooltipPrimitive.Trigger;

export function TooltipContent({ children, ...props }: React.ComponentProps<typeof TooltipPrimitive.Content>) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content sideOffset={6} className="z-50 border border-zinc-700 bg-zinc-950 px-2 py-1 text-xs text-zinc-200 shadow-lg rounded-[2px]" {...props}>
        {children}
        <TooltipPrimitive.Arrow className="fill-zinc-700" />
      </TooltipPrimitive.Content>
    </TooltipPrimitive.Portal>
  );
}
