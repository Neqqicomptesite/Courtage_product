import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const RANGES = [14, 30, 90] as const;
const short = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", timeZone: "UTC" });
const long = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" });

/** Envois et réponses par jour. Les couleurs viennent du thème (couleur principale et accent de marque). */
export function ActivityChart({ className }: { className?: string }) {
  const [days, setDays] = useState<(typeof RANGES)[number]>(30);
  const { data } = useQuery({ queryKey: ["activity", days], queryFn: () => api.activity(days), refetchInterval: 60_000 });
  const totals = (data ?? []).reduce((a, d) => ({ sent: a.sent + d.sent, replies: a.replies + d.replies }), { sent: 0, replies: 0 });

  return (
    <Card className={className}>
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>Activité</CardTitle>
          <CardDescription className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
            <span className="inline-flex items-center gap-1.5"><span className="size-2 rounded-full bg-primary" />{totals.sent} emails envoyés</span>
            <span className="inline-flex items-center gap-1.5"><span className="size-2 rounded-full bg-brand" />{totals.replies} réponses</span>
          </CardDescription>
        </div>
        <div className="inline-flex rounded-lg bg-muted p-0.5 text-xs">
          {RANGES.map((r) => (
            <button key={r} onClick={() => setDays(r)}
              className={cn("rounded-md px-2.5 py-1 font-medium transition-colors", days === r ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
              {r} j
            </button>
          ))}
        </div>
      </CardHeader>
      <CardContent className="h-56 pl-1 pr-4">
        {!data ? (
          <Skeleton className="h-full w-full" />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 8, right: 4, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="g-sent" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity={0.25} />
                  <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="g-rep" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="hsl(var(--brand-green))" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="hsl(var(--brand-green))" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} stroke="hsl(var(--border))" strokeDasharray="3 3" />
              <XAxis dataKey="day" tickLine={false} axisLine={false} minTickGap={24} fontSize={11}
                stroke="hsl(var(--muted-foreground))" tickFormatter={(d: string) => short.format(new Date(d))} />
              <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={28} fontSize={11} stroke="hsl(var(--muted-foreground))" />
              <Tooltip
                cursor={{ stroke: "hsl(var(--border))" }}
                contentStyle={{ background: "hsl(var(--popover))", border: "1px solid hsl(var(--border))", borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: "hsl(var(--foreground))", fontWeight: 600, marginBottom: 4 }}
                labelFormatter={(d) => long.format(new Date(String(d)))}
                formatter={(v, name) => [v as number, name === "sent" ? "Envoyés" : "Réponses"]}
              />
              <Area type="monotone" dataKey="sent" stroke="hsl(var(--primary))" strokeWidth={2} fill="url(#g-sent)" />
              <Area type="monotone" dataKey="replies" stroke="hsl(var(--brand-green))" strokeWidth={2} fill="url(#g-rep)" />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
