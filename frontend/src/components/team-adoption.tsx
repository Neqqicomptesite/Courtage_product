// V3.3.5 : suivi de la prise en main par l'équipe (administrateur, page Équipe).
import { useQuery } from "@tanstack/react-query";
import { Check, TrendingUp } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type Adoption } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const LEVEL: Record<Adoption["items"][number]["level"], { label: string; variant: "success" | "info" | "warning" | "destructive" | "secondary" }> = {
  active: { label: "Actif", variant: "success" },
  testing: { label: "En test", variant: "info" },
  quiet: { label: "Calme", variant: "warning" },
  setup: { label: "À régler", variant: "warning" },
  idle: { label: "Absent", variant: "destructive" },
  invited: { label: "Invité", variant: "secondary" },
};

export function TeamAdoption() {
  const { data } = useQuery({ queryKey: ["team-adoption"], queryFn: api.teamAdoption, refetchInterval: 60_000 });
  return (
    <Card className="mb-5 overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
        <TrendingUp className="size-4 text-primary" />
        <p className="font-medium">Prise en main</p>
        <p className="text-xs text-muted-foreground">Où en est chacun : réglages, puis usage réel. Activité des 7 derniers jours.</p>
      </div>
      {!data ? <Skeleton className="m-4 h-24" /> : (
        <div className="divide-y">
          {data.items.map((u) => <Person key={u.id} u={u} steps={data.steps} />)}
        </div>
      )}
    </Card>
  );
}

function Person({ u, steps }: { u: Adoption["items"][number]; steps: Adoption["steps"] }) {
  const lv = LEVEL[u.level];
  const a = u.activity;
  const stats: [string, number, string?][] = [
    ["emails réels", a.sent_real_7d], ["essais", a.sent_test_7d], ["réponses", a.replies_7d],
    ["à classer", a.to_classify, a.to_classify > 5 ? "text-warning" : undefined],
    ["campagnes en cours", a.active_campaigns], ["dossiers ouverts", a.open_quotes],
  ];
  return (
    <div className="grid gap-3 px-4 py-3 text-sm lg:grid-cols-[minmax(0,14rem)_minmax(0,1fr)_minmax(0,22rem)] lg:items-center">
      <div className="min-w-0">
        <p className="flex items-center gap-2 font-medium"><span className="truncate">{u.name}</span><Badge variant={lv.variant}>{lv.label}</Badge></p>
        <p className="truncate text-xs text-muted-foreground">{u.last_seen_at ? `vu ${relativeTime(u.last_seen_at)}` : "jamais connecté"}</p>
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-1" aria-label={`${u.done} étapes sur ${u.total}`}>
          {steps.map((st, i) => (
            <span key={st.key} title={`${st.label} : ${u.steps[st.key] ? "fait" : "pas encore"}`}
              className={cn("flex size-5 shrink-0 items-center justify-center rounded-full border text-[10px]",
                i === 5 && "ml-2",
                u.steps[st.key] ? "border-success/40 bg-success/15 text-success" : "border-border bg-muted/40 text-muted-foreground/60")}>
              {u.steps[st.key] ? <Check className="size-3" /> : i + 1}
            </span>
          ))}
          <span className="ml-2 text-xs tabular text-muted-foreground">{u.done}/{u.total}</span>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">{u.level_label}</p>
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {stats.map(([label, n, cls]) => (
          <span key={label} className={cls}><span className={cn("font-semibold tabular", n > 0 ? "text-foreground" : "", cls)}>{n}</span> {label}</span>
        ))}
      </div>
    </div>
  );
}
