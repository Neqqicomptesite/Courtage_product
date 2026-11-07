import { cn } from "@/lib/utils";

/** Bloc gris animé affiché pendant le chargement, à la place du contenu. */
function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("animate-pulse rounded-md bg-muted", className)} {...props} />;
}

export { Skeleton };
