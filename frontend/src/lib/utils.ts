import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Assemble des classes Tailwind en résolvant les conflits (utilitaire standard de shadcn/ui). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** V3 : lien externe sûr (http/https seulement) ; sinon undefined (le lien n'est pas affiché). */
export function safeUrl(value: string | null | undefined): string | undefined {
  const v = (value ?? "").trim();
  if (!v) return undefined;
  if (/^https?:\/\//i.test(v)) return v;
  if (/^[a-z][a-z0-9+.-]*:/i.test(v) || v.startsWith("//")) return undefined;
  return `https://${v}`;
}
