// Marque du produit : un symbole simple dessiné ici (aucune image externe) + le nom reçu du
// serveur (/api/auth/config → product_name). Renommer le produit = changer PRODUCT_NAME côté serveur.
import { cn } from "@/lib/utils";
import { PRODUCT_NAME } from "@/lib/auth";

/** Symbole : deux arcs qui se croisent (un dossier suivi de bout en bout), sur un carré arrondi. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={cn("size-8 shrink-0", className)}>
      <rect width="32" height="32" rx="8" className="fill-primary" />
      <path d="M21.5 10.2a8 8 0 1 0 0 11.6" fill="none" strokeWidth="3.2" strokeLinecap="round" className="stroke-primary-foreground" />
      <circle cx="22.2" cy="16" r="2.3" className="fill-brand" />
    </svg>
  );
}

export function Brand({ className, tagline = true }: { className?: string; tagline?: boolean }) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <BrandMark />
      <span className="flex flex-col leading-none">
        <span className="text-[17px] font-semibold tracking-tight text-foreground">{PRODUCT_NAME}</span>
        {tagline && <span className="mt-1 text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground">Courtage</span>}
      </span>
    </span>
  );
}
