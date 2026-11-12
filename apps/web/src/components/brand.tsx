import { cn } from "@/lib/cn";

/** The SQLAgent mark: a database, the thing every question is answered from. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 44 44" aria-hidden className={cn("size-7", className)}>
      <rect width="44" height="44" rx="12" className="fill-primary" />
      <g className="stroke-primary-foreground" strokeWidth="2.4" fill="none">
        <ellipse cx="22" cy="14" rx="11" ry="4.5" />
        <path d="M11 14v16c0 2.5 5 4.5 11 4.5s11-2 11-4.5V14" />
        <path d="M11 22c0 2.5 5 4.5 11 4.5s11-2 11-4.5" />
      </g>
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
