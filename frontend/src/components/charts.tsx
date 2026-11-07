// Graphiques de résultats : entonnoir par étape et répartition des issues.
// Les mêmes composants servent au tableau de bord et à la page d'une campagne.
import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { Indicators } from "@/lib/api";
import { cn } from "@/lib/utils";

const stepLabel = (n: number) => (n === 1 ? "1er email" : `Relance ${n - 1}`);

/** Combien de contacts ont reçu chaque étape : la chute d'une barre à l'autre = réponses + arrêts. */
export function StepFunnel({ i, className }: { i: Indicators; className?: string }) {
  const data = Object.entries(i.sent_by_step)
    .map(([k, v]) => ({ step: Number(k), label: stepLabel(Number(k)), sent: v }))
    .sort((a, b) => a.step - b.step);
  const max = Math.max(1, ...data.map((d) => d.sent));
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Emails par étape</CardTitle>
        <CardDescription>Contacts ayant reçu chaque email de la séquence.</CardDescription>
      </CardHeader>
      <CardContent className="h-48 pl-1 pr-6">
        {data.length === 0 ? <p className="py-12 text-center text-sm text-muted-foreground">Aucun email envoyé pour l'instant.</p> : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} layout="vertical" margin={{ top: 0, right: 28, left: 0, bottom: 0 }} barCategoryGap={10}>
              <XAxis type="number" hide domain={[0, max]} />
              <YAxis type="category" dataKey="label" tickLine={false} axisLine={false} width={78} fontSize={12} stroke="hsl(var(--muted-foreground))" />
              <Tooltip cursor={{ fill: "hsl(var(--accent))", opacity: 0.4 }} content={({ active, payload }) => active && payload?.[0] ? (
                <div className="rounded-lg border bg-popover px-3 py-2 text-xs shadow-md">
                  <b>{payload[0].payload.label}</b> : {payload[0].value} envoyé{Number(payload[0].value) > 1 ? "s" : ""}
                </div>) : null} />
              <Bar dataKey="sent" radius={[0, 6, 6, 0]} isAnimationActive={false}>
                {data.map((d, idx) => <Cell key={d.step} fill="hsl(var(--primary))" fillOpacity={1 - idx * 0.15} />)}
                <LabelList dataKey="sent" position="right" fontSize={12} className="fill-foreground tabular" />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}

/** Que sont devenus les contacts touchés ? Une barre empilée, plus lisible qu'un camembert. */
export function Outcomes({ i, running, className }: { i: Indicators; running: number; className?: string }) {
  const others = Math.max(0, i.replies - i.interested);
  const parts = [
    { key: "interested", label: "Intéressés", value: i.interested, color: "bg-brand" },
    { key: "replies", label: "Autres réponses", value: others, color: "bg-brand/40" },
    { key: "running", label: "Séquence en cours", value: running, color: "bg-primary/70" },
    { key: "done", label: "Terminés sans réponse", value: i.completed_no_reply, color: "bg-muted-foreground/30" },
    { key: "bounce", label: "Rebonds et STOP", value: i.bounced + i.unsubscribed, color: "bg-destructive/70" },
  ];
  // Le reste : arrêtés à la main, retirés, collègue ayant répondu… pour que le total tombe juste.
  const known = parts.reduce((a, p) => a + p.value, 0);
  if (i.enrolled > known) parts.push({ key: "other", label: "Autres arrêts", value: i.enrolled - known, color: "bg-warning/60" });
  const total = Math.max(i.enrolled, known);
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>Issues</CardTitle>
        <CardDescription>Ce que sont devenus les {total} contacts inscrits.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex h-3 overflow-hidden rounded-full bg-muted">
          {total > 0 && parts.map((p) => p.value > 0 && (
            <div key={p.key} className={cn("h-full transition-all", p.color)} style={{ width: `${(p.value / total) * 100}%` }} title={`${p.label} : ${p.value}`} />
          ))}
        </div>
        <ul className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          {parts.map((p) => (
            <li key={p.key} className="flex items-center gap-2">
              <span className={cn("size-2.5 shrink-0 rounded-sm", p.color)} />
              <span className="min-w-0 flex-1 truncate text-muted-foreground">{p.label}</span>
              <span className="font-medium tabular">{p.value}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
