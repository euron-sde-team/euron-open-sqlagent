import { cn } from "@/lib/cn";

/** The SQLAgent mark: one agent at the centre, wired to the three things it works with. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={cn("size-7", className)}>
      <rect width="32" height="32" rx="9" className="fill-primary" />
      <g className="stroke-primary-foreground" strokeWidth="1.7" strokeLinecap="round" fill="none" opacity="0.75">
        <path d="M16 16 9.6 10.6M16 16l6.4-5.4M16 16v7.2" />
      </g>
      <g className="fill-primary-foreground">
        <circle cx="9.2" cy="10.2" r="2.3" />
        <circle cx="22.8" cy="10.2" r="2.3" />
        <circle cx="16" cy="23.6" r="2.3" />
      </g>
      <circle cx="16" cy="16" r="3.6" className="fill-primary stroke-primary-foreground" strokeWidth="2" />
    </svg>
  );
}

export function BrandLogo({ collapsed = false, className }: { collapsed?: boolean; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <BrandMark />
      {!collapsed && <span className="text-[15px] font-semibold tracking-[-0.02em]">SQLAgent</span>}
    </span>
  );
}
