import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronRight,
  AlertTriangle,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  Clock,
  Download,
  Cpu,
  Inbox,
  MailCheck,
  MailX,
  Phone,
  PhoneCall,
  Reply,
  Send,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import { ActivityChart } from "@/components/activity-chart";
import { StepFunnel } from "@/components/charts";
import { useStatus } from "@/components/layout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type Dashboard, type Status } from "@/lib/api";
import { formatDayLabel, formatDayTime, formatTime, fullName, localDay, pct, relativeTime } from "@/lib/format";
import { PRODUCT_NAME } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { GuideBanner } from "@/pages/guide";

export function DashboardPage() {
  const { data: status } = useStatus();
  // Les données du tableau de bord se rafraîchissent seules toutes les 30 s.
  const { data, isLoading, isError } = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard, refetchInterval: 30_000 });

  const firstName = status?.mailbox.display_name?.split(" ")[0];
  const today = formatDayLabel(new Date().toISOString());

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-muted-foreground">{today}</p>
          <h1 className="text-xl font-semibold tracking-tight">{firstName ? `Bonjour ${firstName}` : "Tableau de bord"}</h1>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" asChild>
            <a href="/api/export"><Download /> Exporter</a>
          </Button>
          <Button asChild>
            <Link to="/campaigns/new"><Send /> Nouvelle campagne</Link>
          </Button>
        </div>
      </div>

      <Alerts status={status} />
      <GuideBanner />
      <StatusRow status={status} toClassify={status?.to_classify ?? 0} />

      {isError && (
        <Card className="border-destructive/40">
          <CardContent className="p-4 text-sm text-destructive">Impossible de charger le tableau de bord : l'application est-elle ouverte ?</CardContent>
        </Card>
      )}
      {isLoading || !data ? (
        <LoadingGrid />
      ) : !data.has_contacts ? (
        <Onboarding configured={status?.mailbox.configured ?? false} />
      ) : (
        <>
          <BounceAlert data={data} />
          <Kpis data={data} />
          <div className="grid gap-6 lg:grid-cols-3">
            <ActivityChart className="lg:col-span-2" />
            <StepFunnel i={data.indicators} />
          </div>
          <div className="grid items-start gap-6 lg:grid-cols-2">
            <div className="min-w-0 space-y-6">
              <Campaigns data={data} />
              <Segments data={data} />
            </div>
            <Queue data={data} />
          </div>
          {/* Cartes qui n'apparaissent que si elles ont du contenu : rangées en deux colonnes « maçonnerie » */}
          <div className="gap-6 space-y-6 lg:columns-2 [&>*]:break-inside-avoid">
            <ToReview data={data} />
            <Callbacks data={data} />
            <Unmatched data={data} />
            <AbTest data={data} />
          </div>
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ alertes */

function Alerts({ status }: { status: Status | undefined }) {
  if (!status) return null;
  const items: { title: string; text: string; href: string }[] = [];
  if (status.engine.error) items.push({ title: "Envois suspendus", text: status.engine.error, href: "/settings" });
  if (status.sync.error)
    items.push({
      title: "Lecture de la boîte impossible",
      text: `${status.sync.error}. Par sécurité, aucun email ne part tant que les réponses ne peuvent pas être vérifiées.`,
      href: "/settings",
    });
  if (!items.length) return null;
  return (
    <div className="space-y-2">
      {items.map((a) => (
        <div key={a.title} className="flex items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
          <div className="flex-1">
            <p className="font-medium text-destructive">{a.title}</p>
            <p className="text-muted-foreground">{a.text}</p>
          </div>
          <Button variant="outline" size="sm" asChild><Link to={a.href}>Vérifier les réglages</Link></Button>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------- ligne d'état */

function StatTile({ icon, label, children, footer, href }: { icon: ReactNode; label: string; children: ReactNode; footer?: ReactNode; href?: string }) {
  const body = (
    <Card className={cn("h-full p-4", href && "transition-colors hover:border-primary/40")}>
      <div className="flex items-center gap-2 truncate text-xs font-medium text-muted-foreground">{icon}<span className="truncate">{label}</span></div>
      <div className="mt-2 text-base font-semibold tracking-tight">{children}</div>
      {footer && <div className="mt-2 text-xs text-muted-foreground">{footer}</div>}
    </Card>
  );
  return href ? <Link to={href} className="block">{body}</Link> : body;
}

function StatusRow({ status, toClassify }: { status: Status | undefined; toClassify: number }) {
  if (!status) return <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[104px] rounded-xl" />)}</div>;
  const c = status.counters;
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatTile icon={<Send className="size-3.5" />} label="Envoyés aujourd'hui"
        footer={c && <Progress value={(c.today / Math.max(1, c.daily_cap)) * 100} />}>
        <span className="tabular">{c?.today ?? 0}</span>
        <span className="text-sm font-normal text-muted-foreground"> / {c?.daily_cap ?? "—"}</span>
      </StatTile>
      <StatTile icon={<Clock className="size-3.5" />} label="Prochain envoi"
        footer={status.next_send_at ? formatDayTime(status.next_send_at) : "Aucune campagne active"}>
        {status.next_send_at ? relativeTime(status.next_send_at) : "—"}
      </StatTile>
      <StatTile icon={<Cpu className="size-3.5" />} label="Moteur d'envoi"
        footer={status.engine.last_tick ? `Dernier passage ${relativeTime(status.engine.last_tick)}` : "Pas encore passé"}>
        <span className={cn("inline-flex items-center gap-2", status.engine.running ? "text-success" : "text-destructive")}>
          <span className={cn("size-2 rounded-full", status.engine.running ? "bg-success" : "bg-destructive")} />
          {status.engine.running ? "En marche" : "Arrêté"}
        </span>
      </StatTile>
      <StatTile icon={<Inbox className="size-3.5" />} label="Réponses à classer" href="/replies"
        footer={toClassify ? <span className="inline-flex items-center gap-1 text-primary">Classer maintenant <ArrowRight className="size-3" /></span> : "Tout est classé"}>
        <span className="tabular">{toClassify}</span>
      </StatTile>
    </div>
  );
}

/* --------------------------------------------------------------- indicateurs */

function Kpis({ data }: { data: Dashboard }) {
  const i = data.indicators;
  const f = data.followups;
  return (
    <section>
      <h2 className="mb-3 text-sm font-medium text-muted-foreground">Résultats, toutes campagnes</h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        <Card className="p-4">
          <div className="flex items-center justify-between text-xs text-muted-foreground">Emails envoyés <Send className="size-3.5" /></div>
          <div className="mt-1.5 text-2xl font-semibold tracking-tight tabular">{i.sent_total}</div>
          <div className="mt-0.5 text-xs text-muted-foreground">à {i.reached} contact{i.reached > 1 ? "s" : ""}</div>
        </Card>
        <Link to="/replies?f=all" className="block">
          <Card className="h-full border-brand/30 bg-brand/[0.04] p-4 transition-colors hover:border-brand/60">
            <div className="flex items-center justify-between text-xs text-muted-foreground">Réponses <MailCheck className="size-3.5 text-brand" /></div>
            <div className="mt-1.5 text-2xl font-semibold tracking-tight tabular text-brand">{i.replies}</div>
            <div className="mt-0.5 text-xs text-muted-foreground">{i.reached ? `${pct(i.reply_rate)} des contacts joints` : "aucun contact joint pour l'instant"}{i.interested > 0 && ` · ${i.interested} intéressé${i.interested > 1 ? "s" : ""}`}</div>
          </Card>
        </Link>
        <Link to="/inbox/followups" className="block text-left">
          <Card className={cn("h-full p-4 transition-colors", f.count ? "border-warning/40 bg-warning/[0.05] hover:border-warning/70" : "")}>
            <div className="flex items-center justify-between text-xs text-muted-foreground">Ils n'ont pas répondu ({f.days} j+) <PhoneCall className={cn("size-3.5", f.count && "text-warning")} /></div>
            <div className={cn("mt-1.5 text-2xl font-semibold tracking-tight tabular", f.count && "text-warning")}>{f.count}</div>
            <div className="mt-0.5 text-xs text-muted-foreground">{f.count ? <span className="inline-flex items-center gap-1">Jours ouvrés · voir les emails <ArrowRight className="size-3" /></span> : "jours ouvrés, week-ends et fériés exclus"}</div>
          </Card>
        </Link>
        <AwaitingTile />
        <TodayTile />
      </div>
    </section>
  );
}

/** V2.12 : le pendant de « sans réponse » : emails reçus auxquels je n'ai pas répondu. */
function AwaitingTile() {
  const { data, isError } = useQuery({ queryKey: ["awaiting"], queryFn: () => api.awaiting(), refetchInterval: 300_000, retry: false });
  const n = data?.items.length ?? 0;
  return (
    <Link to="/inbox/awaiting" className="block">
      <Card className={cn("h-full p-4 transition-colors hover:border-primary/50", n ? "border-primary/30 bg-primary/[0.04]" : "")}>
        <div className="flex items-center justify-between text-xs text-muted-foreground">À répondre ({data?.days ?? 3} j+) <Reply className={cn("size-3.5", n && "text-primary")} /></div>
        <div className={cn("mt-1.5 text-2xl font-semibold tracking-tight tabular", n && "text-primary")}>{isError ? "—" : data ? n : "…"}</div>
        <div className="mt-0.5 truncate text-xs text-muted-foreground">
          {isError ? "Boîte mail injoignable" : n ? <span className="inline-flex items-center gap-1">{data!.items.slice(0, 2).map((m) => m.contact ? fullName(m.contact) : m.from_name || m.from_email).join(", ")} <ArrowRight className="size-3" /></span> : "Emails reçus, vous avez tout traité"}
        </div>
      </Card>
    </Link>
  );
}

/** V2.11 : ce qu'il y a à faire aujourd'hui (rappels du jour et en retard, personnes à rappeler). */
function TodayTile() {
  const d = new Date();
  const ymd = (x: Date) => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
  const today = ymd(d);
  const start = ymd(new Date(d.getFullYear(), d.getMonth(), d.getDate() - 90));
  const { data } = useQuery({ queryKey: ["reminders", "today", today], queryFn: () => api.reminders({ start, end: today, include_done: false }), refetchInterval: 60_000 });
  const items = (data?.items ?? []).filter((r) => !r.done);
  const late = items.filter((r) => r.due_on < today).length;
  return (
    <Link to="/agenda" className="block">
      <Card className={cn("h-full p-4 transition-colors hover:border-primary/50", items.length ? "border-primary/30 bg-primary/[0.04]" : "")}>
        <div className="flex items-center justify-between text-xs text-muted-foreground">Aujourd'hui <CalendarClock className={cn("size-3.5", items.length && "text-primary")} /></div>
        <div className={cn("mt-1.5 text-2xl font-semibold tracking-tight tabular", items.length && "text-primary")}>{items.length}</div>
        <div className="mt-0.5 truncate text-xs text-muted-foreground">
          {items.length ? <>{items.slice(0, 2).map((r) => r.title).join(" · ")}{late ? <span className="text-destructive"> · {late} en retard</span> : ""}</> : "Aucun rappel pour aujourd'hui"}
        </div>
      </Card>
    </Link>
  );
}

/** Les rebonds abîment la réputation du domaine du cabinet : on ne les montre que lorsqu'il y en a. */
function BounceAlert({ data }: { data: Dashboard }) {
  const n = data.indicators.bounced;
  if (!n) return null;
  return (
    <Link to="/contacts?status=bounced" className="flex items-center gap-3 rounded-xl border border-warning/40 bg-warning/5 p-4 text-sm transition-colors hover:bg-warning/10">
      <MailX className="size-4 shrink-0 text-warning" />
      <span className="flex-1"><b>{n} adresse{n > 1 ? "s ont" : " a"} rebondi.</b> <span className="text-muted-foreground">Trop de rebonds nuisent à la réputation du domaine du cabinet : commencez les campagnes par les emails de qualité « Bonne ».</span></span>
      <ArrowRight className="size-4 text-muted-foreground" />
    </Link>
  );
}

/* ----------------------------------------------------------------- campagnes */

function Campaigns({ data }: { data: Dashboard }) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>Campagnes en cours</CardTitle>
          <CardDescription className="mt-1">Avancement et réponses</CardDescription>
        </div>
        <Button variant="ghost" size="sm" asChild><Link to="/campaigns">Tout voir <ArrowRight /></Link></Button>
      </CardHeader>
      <CardContent>
        {data.campaigns.length === 0 ? (
          <Empty text="Aucune campagne active pour l'instant." action={<Button size="sm" asChild><Link to="/campaigns/new">Créer une campagne</Link></Button>} />
        ) : (
          <ul className="divide-y">
            {data.campaigns.map((c) => (
              <li key={c.id}>
                <Link to={`/campaigns/${c.id}`} className="block py-3 first:pt-0 last:pb-0 group">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium group-hover:text-primary">{c.name}</span>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <span className="tabular">{c.replies} réponse{c.replies > 1 ? "s" : ""} · {pct(c.reply_rate)}</span>
                      {c.status === "paused" ? <Badge variant="warning">En pause</Badge> : <Badge variant="success">Active</Badge>}
                    </div>
                  </div>
                  <div className="mt-2 flex items-center gap-3">
                    <Progress value={(c.reached / Math.max(1, c.enrolled)) * 100} indicatorClassName="bg-brand" />
                    <span className="w-24 shrink-0 text-right text-xs text-muted-foreground tabular">{c.reached}/{c.enrolled} contactés</span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------- file d'envoi */

function Queue({ data }: { data: Dashboard }) {
  // Résumé par jour (nombre d'envois, 1ers emails / relances) ; un clic déplie la liste du jour.
  const groups = new Map<string, Dashboard["queue"]>();
  for (const q of data.queue) {
    const k = localDay(q.due_at);
    groups.set(k, [...(groups.get(k) ?? []), q]);
  }
  const [open, setOpen] = useState<Set<string>>(new Set());
  const all = open.size === groups.size && groups.size > 0;
  const toggle = (k: string) => setOpen((o) => { const n = new Set(o); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle>File d'envoi</CardTitle>
            <CardDescription className="mt-1">
              {data.queue.length ? `${data.queue.length} envoi${data.queue.length > 1 ? "s" : ""} prévu${data.queue.length > 1 ? "s" : ""} sur 7 jours. ` : ""}Heures indicatives : un email à la fois, selon vos plafonds.
            </CardDescription>
          </div>
          {groups.size > 0 && (
            <Button variant="ghost" size="sm" className="shrink-0" onClick={() => setOpen(all ? new Set() : new Set(groups.keys()))}>
              {all ? "Tout replier" : "Tout déplier"}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {data.queue.length === 0 ? (
          <Empty text="Aucun envoi prévu dans les 7 prochains jours." />
        ) : (
          <div className="divide-y rounded-lg border">
            {[...groups.entries()].map(([day, items]) => {
              const firsts = items.filter((q) => q.step === 1).length;
              const camps = new Set(items.map((q) => q.campaign.id)).size;
              const isOpen = open.has(day);
              return (
                <div key={day}>
                  <button type="button" onClick={() => toggle(day)} aria-expanded={isOpen}
                    className="flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm hover:bg-muted/40">
                    <ChevronRight className={cn("size-4 shrink-0 text-muted-foreground transition-transform", isOpen && "rotate-90")} />
                    <span className="min-w-0 flex-1 font-medium">{formatDayLabel(items[0].due_at)}</span>
                    <span className="text-xs text-muted-foreground">
                      {firsts > 0 && <>{firsts} 1<sup>er</sup> email{firsts > 1 ? "s" : ""}</>}{firsts > 0 && items.length - firsts > 0 && " · "}
                      {items.length - firsts > 0 && <>{items.length - firsts} relance{items.length - firsts > 1 ? "s" : ""}</>}
                      {camps > 1 && <> · {camps} campagnes</>}
                    </span>
                    <Badge variant="secondary" className="tabular">{items.length}</Badge>
                  </button>
                  {isOpen && (
                    <ul className="divide-y border-t bg-muted/20">
                      {items.map((q) => (
                        <li key={q.enrollment_id} className="flex items-center gap-3 px-3 py-2 pl-10 text-sm">
                          <span className="w-12 shrink-0 text-xs text-muted-foreground tabular">{formatTime(q.due_at)}</span>
                          <Link to={`/contacts?open=${q.contact.id}`} className="min-w-0 flex-1 truncate hover:text-primary">
                            <span className="font-medium">{fullName(q.contact)}</span>
                            <span className="text-muted-foreground"> · {q.contact.company ?? q.contact.email}</span>
                          </Link>
                          <Badge variant="info">Étape {q.step}</Badge>
                          <Link to={`/campaigns/${q.campaign.id}`} className="hidden max-w-[10rem] truncate text-xs text-muted-foreground hover:text-primary sm:block">{q.campaign.name}</Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ToReview({ data }: { data: Dashboard }) {
  const qc = useQueryClient();
  const act = useMutation({
    mutationFn: ({ id, kind }: { id: number; kind: "confirm" | "retry" }) => (kind === "confirm" ? api.confirmSent(id) : api.retry(id)),
    onSuccess: () => {
      qc.invalidateQueries();
      toast.success("C'est noté");
    },
  });
  if (!data.to_review.length) return null;
  return (
    <Card className="border-warning/40">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><AlertTriangle className="size-4 text-warning" /> À vérifier ({data.to_review.length})</CardTitle>
        <CardDescription className="mt-1">Envoi interrompu ou en erreur. Rien n'est renvoyé sans votre accord.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {data.to_review.map((r) => (
          <div key={r.enrollment_id} className="rounded-lg border p-3 text-sm">
            <p className="font-medium">{fullName(r.contact)} <span className="font-normal text-muted-foreground">· étape {r.step}</span></p>
            {r.error && <p className="mt-0.5 text-xs text-muted-foreground">{r.error}</p>}
            <div className="mt-2 flex flex-wrap gap-2">
              {r.status === "needs_review" && (
                <Button size="sm" variant="secondary" onClick={() => act.mutate({ id: r.enrollment_id, kind: "confirm" })}>Il est dans mes Envoyés</Button>
              )}
              <Button size="sm" variant="outline" onClick={() => act.mutate({ id: r.enrollment_id, kind: "retry" })}>
                {r.status === "needs_review" ? "Pas parti : renvoyer" : "Réessayer"}
              </Button>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function Callbacks({ data }: { data: Dashboard }) {
  const qc = useQueryClient();
  const done = useMutation({
    mutationFn: api.callbackDone,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast.success("Rappel marqué comme effectué");
    },
  });
  if (!data.callbacks.length) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Phone className="size-4 text-primary" /> Rappels du jour</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {data.callbacks.map((c) => (
          <div key={c.message_id} className="flex items-center gap-3 rounded-lg border p-3 text-sm">
            <div className="min-w-0 flex-1">
              <Link to={`/contacts?open=${c.contact.id}`} className="font-medium hover:text-primary">{fullName(c.contact)}</Link>
              <p className="truncate text-xs text-muted-foreground">
                {c.contact.company}{c.contact.phone && <> · <a href={`tel:${c.contact.phone}`} className="hover:text-primary">{c.contact.phone}</a></>}
                {c.note && ` · ${c.note}`}
              </p>
            </div>
            <Button size="sm" variant="outline" onClick={() => done.mutate(c.message_id)}>Fait</Button>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function Unmatched({ data }: { data: Dashboard }) {
  if (!data.unmatched.length) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Réponses à rattacher ({data.unmatched.length})</CardTitle>
        <CardDescription className="mt-1">Un collègue d'une entreprise prospectée a écrit.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {data.unmatched.slice(0, 3).map((m) => (
          <div key={m.id} className="rounded-lg border p-3 text-sm">
            <p className="font-medium">{m.subject || "(sans objet)"}</p>
            <p className="line-clamp-2 text-xs text-muted-foreground">{m.excerpt}</p>
            {m.suggestion && <p className="mt-1 text-xs">Probablement : <span className="font-medium">{m.suggestion.company ?? fullName(m.suggestion)}</span></p>}
          </div>
        ))}
        <Button variant="outline" size="sm" className="w-full" asChild><Link to="/replies">Rattacher</Link></Button>
      </CardContent>
    </Card>
  );
}

/* ---------------------------------------------------------- segments et A/B */

function RateBar({ rate }: { rate: number | null }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-secondary">
        <div className="h-full rounded-full bg-primary" style={{ width: `${Math.round((rate ?? 0) * 100)}%` }} />
      </div>
      <span className="w-12 whitespace-nowrap text-right tabular">{pct(rate)}</span>
    </div>
  );
}

function Segments({ data }: { data: Dashboard }) {
  if (!data.segments.length) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Par profil</CardTitle>
        <CardDescription className="mt-1">Fonction × secteur. Petits effectifs : à lire avec prudence.</CardDescription>
      </CardHeader>
      <CardContent>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="pb-2 font-medium">Code</th>
              <th className="pb-2 text-right font-medium">Réponses / contactés</th>
              <th className="pb-2 text-right font-medium">Taux</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {data.segments.map((s) => (
              <tr key={s.key}>
                <td className="py-2"><code className="rounded bg-muted px-1.5 py-0.5 text-xs">{s.key}</code></td>
                <td className="py-2 text-right text-muted-foreground tabular">{s.replies}/{s.reached}</td>
                <td className="py-2"><div className="flex justify-end"><RateBar rate={s.rate} /></div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function AbTest({ data }: { data: Dashboard }) {
  if (!data.ab.rows.length) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Test A/B des objets</CardTitle>
        {data.ab.too_small && (
          <CardDescription className="mt-1 text-warning">
            Échantillon trop petit pour conclure avec certitude (moins de {data.ab.min_sample} contacts par variante).
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {data.ab.rows.map((r) => (
          <div key={r.key} className="flex items-center gap-3 text-sm">
            <span className="flex size-7 items-center justify-center rounded-md bg-accent text-xs font-semibold text-accent-foreground">{r.key}</span>
            <span className="flex-1 text-muted-foreground tabular">{r.replies} réponse{r.replies > 1 ? "s" : ""} / {r.reached}</span>
            <RateBar rate={r.rate} />
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------- états particuliers */

function Empty({ text, action }: { text: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed py-8 text-center text-sm text-muted-foreground">
      {text}
      {action}
    </div>
  );
}

function Onboarding({ configured }: { configured: boolean }) {
  const steps = [
    { done: configured, title: "Connecter la boîte mail", text: "Serveurs du cPanel et test de connexion.", href: "/settings", cta: "Réglages" },
    { done: false, title: "Importer vos contacts", text: "Votre fichier Excel, colonnes reconnues automatiquement.", href: "/contacts/import", cta: "Importer" },
    { done: false, title: "Lire le guide", text: "Les écrans, les bons réflexes, les questions fréquentes.", href: "/guide", cta: "Guide" },
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Bienvenue dans {PRODUCT_NAME}</CardTitle>
        <CardDescription>Trois étapes avant votre première campagne.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-3">
        {steps.map((s, i) => (
          <div key={s.title} className="rounded-lg border p-4">
            <div className={cn("mb-3 flex size-7 items-center justify-center rounded-full text-xs font-semibold", s.done ? "bg-success text-success-foreground" : "bg-accent text-accent-foreground")}>
              {s.done ? <CheckCircle2 className="size-4" /> : i + 1}
            </div>
            <p className="font-medium">{s.title}</p>
            <p className="mt-1 text-sm text-muted-foreground">{s.text}</p>
            <Button size="sm" variant={s.done ? "outline" : "default"} className="mt-3" asChild><Link to={s.href}>{s.cta}</Link></Button>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function LoadingGrid() {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-[92px] rounded-xl" />)}</div>
      <div className="grid gap-6 lg:grid-cols-5">
        <Skeleton className="h-72 rounded-xl lg:col-span-3" />
        <Skeleton className="h-72 rounded-xl lg:col-span-2" />
      </div>
    </div>
  );
}
