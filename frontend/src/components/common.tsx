// Petites briques réutilisées par toutes les pages : en-tête, état vide, pastilles de statut,
// confirmation, enregistrement différé.
import type { LucideIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

export function PageHeader({ title, description, actions, back, className }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; back?: ReactNode; className?: string }) {
  return (
    <div className={cn("mb-5 space-y-2", className)}>
      {back}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}

export function EmptyState({ icon: Icon, title, text, action, className }: { icon?: LucideIcon; title: string; text?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed px-6 py-14 text-center", className)}>
      {Icon && (
        <div className="flex size-11 items-center justify-center rounded-full bg-accent text-accent-foreground">
          <Icon className="size-5" />
        </div>
      )}
      <div>
        <p className="font-medium">{title}</p>
        {text && <p className="mt-1 max-w-md text-sm text-muted-foreground">{text}</p>}
      </div>
      {action}
    </div>
  );
}

const CONTACT_STATUS: Record<string, [string, BadgeProps["variant"]]> = {
  active: ["Actif", "success"],
  replied: ["A répondu", "info"],
  bounced: ["Rebond", "destructive"],
  unsubscribed: ["Désinscrit", "destructive"],
  do_not_contact: ["Ne plus contacter", "secondary"],
};
const KIND: Record<string, [string, "secondary" | "info" | "success" | "warning"]> = {
  prospect: ["Prospect", "secondary"], client: ["Client", "success"], insurer: ["Assureur", "info"], partner: ["Partenaire", "warning"],
};
/** Type de relation. Les non-prospects ne reçoivent jamais de campagne. */
export function KindBadge({ kind, hideProspect }: { kind: string; hideProspect?: boolean }) {
  if (hideProspect && kind === "prospect") return null;
  const [label, variant] = KIND[kind] ?? [kind, "secondary"];
  return <Badge variant={variant}>{label}</Badge>;
}

export function ContactStatus({ status }: { status: string }) {
  const [label, variant] = CONTACT_STATUS[status] ?? [status, "secondary"];
  return <Badge variant={variant}>{label}</Badge>;
}

const ENROLLMENT: Record<string, [string, BadgeProps["variant"]]> = {
  scheduled: ["Programmé", "info"],
  sending: ["Envoi en cours", "info"],
  waiting: ["En attente de relance", "info"],
  replied: ["A répondu", "success"],
  completed: ["Terminé sans réponse", "secondary"],
  stopped: ["Arrêté", "secondary"],
  bounced: ["Rebond", "destructive"],
  unsubscribed: ["Désinscrit", "destructive"],
  error: ["Erreur", "destructive"],
  needs_review: ["À vérifier", "warning"],
};
export function EnrollmentStatus({ status }: { status: string }) {
  const [label, variant] = ENROLLMENT[status] ?? [status, "secondary"];
  return <Badge variant={variant}>{label}</Badge>;
}

const CAMPAIGN: Record<string, [string, BadgeProps["variant"]]> = {
  draft: ["Brouillon", "secondary"],
  active: ["Active", "success"],
  paused: ["En pause", "warning"],
  finished: ["Terminée", "outline"],
};
export function CampaignStatus({ status }: { status: string }) {
  const [label, variant] = CAMPAIGN[status] ?? [status, "secondary"];
  return <Badge variant={variant}>{label}</Badge>;
}

export function ReliabilityDot({ value }: { value: string }) {
  const tone = value === "Bonne" ? "bg-success" : value === "Moyenne" || value === "À vérifier" ? "bg-warning" : "bg-muted-foreground/50";
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className={cn("size-1.5 rounded-full", tone)} />
      {value}
    </span>
  );
}

/** Affiche l'erreur d'une action dans une notification. */
export function toastError(e: unknown, title = "Action impossible") {
  toast.error(title, { description: e instanceof Error ? e.message : String(e) });
}

/** Fenêtre de confirmation ; `typed` exige de taper un mot (ex. EFFACER) pour les actions irréversibles. */
export function ConfirmDialog({
  open, onOpenChange, title, description, confirmLabel = "Confirmer", destructive, typed, onConfirm, pending,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  destructive?: boolean;
  typed?: string;
  onConfirm: (typedValue: string) => void;
  pending?: boolean;
}) {
  const [value, setValue] = useState("");
  useEffect(() => setValue(""), [open]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription asChild><div>{description}</div></DialogDescription>}
        </DialogHeader>
        {typed && (
          <Input autoFocus value={value} onChange={(e) => setValue(e.target.value)} placeholder={`Tapez ${typed} pour confirmer`} />
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Annuler</Button>
          <Button variant={destructive ? "destructive" : "default"} disabled={pending || (!!typed && value.trim().toUpperCase() !== typed)}
            onClick={() => onConfirm(value)}>
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Appelle `fn` seulement après `delay` ms sans nouvel appel : sert à l'enregistrement automatique. */
export function useDebounced<A extends unknown[]>(fn: (...args: A) => void, delay = 800) {
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const latest = useRef(fn);
  latest.current = fn;
  useEffect(() => () => clearTimeout(timer.current), []);
  return useCallback((...args: A) => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => latest.current(...args), delay);
  }, [delay]);
}

export function fieldError(e: unknown, field: string): string | undefined {
  return e instanceof ApiError ? e.fields[field] : undefined;
}

export function Field({ label, hint, error, children, className }: { label: ReactNode; hint?: ReactNode; error?: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn("block space-y-1.5", className)}>
      <span className="text-sm font-medium">{label}</span>
      {children}
      {error ? <span className="block text-xs text-destructive">{error}</span> : hint ? <span className="block text-xs text-muted-foreground">{hint}</span> : null}
    </label>
  );
}
