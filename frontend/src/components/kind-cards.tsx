// Cartes de type de relation, en haut des pages Contacts et Entreprises (V2.7).
// Ordre voulu par Omar : Assureurs, Clients, Prospects, puis Partenaires.
import { Handshake, Landmark, Layers, Target, UserCheck } from "lucide-react";

import { cn } from "@/lib/utils";

export const KIND_ORDER = ["insurer", "client", "prospect", "partner"] as const;
const META: Record<string, { label: string; icon: typeof Layers; tone: string }> = {
  "": { label: "Tous", icon: Layers, tone: "text-foreground" },
  insurer: { label: "Assureurs", icon: Landmark, tone: "text-primary" },
  client: { label: "Clients", icon: UserCheck, tone: "text-success" },
  prospect: { label: "Prospects", icon: Target, tone: "text-brand" },
  partner: { label: "Partenaires", icon: Handshake, tone: "text-warning" },
};

export function KindCards({ counts, value, onChange, allLabel, kinds = KIND_ORDER }: {
  counts: Partial<Record<string, number>>; value: string; onChange: (k: string) => void; allLabel?: string; kinds?: readonly string[];
}) {
  const total = kinds.reduce((n, k) => n + (counts[k] ?? 0), 0);
  return (
    <div className={cn("mb-4 grid grid-cols-2 gap-2", kinds.length === 3 ? "sm:grid-cols-4" : "sm:grid-cols-5")}>
      {(["", ...kinds] as string[]).map((k) => {
        const m = META[k];
        const n = k ? counts[k] ?? 0 : total;
        const active = value === k;
        return (
          <button key={k || "all"} onClick={() => onChange(k)}
            className={cn("flex items-center gap-3 rounded-xl border bg-card p-3 text-left transition-all hover:border-primary/40",
              active && "border-primary ring-2 ring-primary/15", k === "" && "col-span-2 sm:col-span-1")}>
            <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted", m.tone)}><m.icon className="size-4" /></span>
            <span className="min-w-0">
              <span className="block text-lg font-semibold leading-tight tabular">{n}</span>
              <span className="block truncate text-xs text-muted-foreground">{k ? m.label : allLabel ?? m.label}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
