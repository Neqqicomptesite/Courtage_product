import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, ArrowLeft, ArrowRight, CalendarCheck, CalendarClock, CheckCircle2, Download, Filter, ListOrdered, Loader2, MoreHorizontal,
  Eye, FileText, Pause, Play, Rocket, Search, Send, ShieldCheck, SkipForward, Trash2, UserMinus, Users,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { Outcomes, StepFunnel } from "@/components/charts";
import { EmailCard } from "@/components/send-sequence";
import { CampaignStatus, ConfirmDialog, EmptyState, EnrollmentStatus, KindBadge, PageHeader, toastError } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { NativeSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { api, type Activation, type Block, type BlockMap, type CampaignDetail, type Indicators, type SequenceCategory } from "@/lib/api";
import { CATEGORIES } from "@/pages/sequences";
import { formatDayTime, fullName, lot, pct } from "@/lib/format";
import { cn } from "@/lib/utils";

const KIND_FR: Record<string, string> = { prospect: "Prospect", client: "Client", insurer: "Assureur", partner: "Partenaire" };
const filterValue = (k: string, v: string) => (k === "wave" ? lot(v) : k === "kind" ? KIND_FR[v] ?? v
  : k === "contact_ids" ? `${v.split(",").filter(Boolean).length} personne(s) choisie(s)` : v);
const FILTER_LABELS: Record<string, string> = {
  kind: "Type de contact", target_segment: "Fonction", sector_family: "Secteur", sequence_code: "Profil", wave: "Lot d'envoi", reliability: "Qualité de l'email",
};

/* =============================================================== liste */

export function CampaignsPage() {
  const { data } = useQuery({ queryKey: ["campaigns"], queryFn: api.campaigns, refetchInterval: 30_000 });
  return (
    <>
      <PageHeader title="Campagnes" description="Une séquence envoyée à une sélection de contacts, un email à la fois."
        actions={<Button asChild><Link to="/campaigns/new"><Rocket /> Nouvelle campagne</Link></Button>} />
      {!data ? <Skeleton className="h-64 rounded-xl" /> : data.length === 0 ? (
        <EmptyState icon={Rocket} title="Aucune campagne" text="Choisissez des contacts et une séquence : l'assistant vérifie tout avant le lancement."
          action={<Button asChild><Link to="/campaigns/new"><Rocket /> Créer une campagne</Link></Button>} />
      ) : (
        <Card className="divide-y">
          {data.map((c) => {
            const i = c.indicators;
            return (
              <Link key={c.id} to={`/campaigns/${c.id}`} className="grid items-center gap-4 p-4 transition-colors hover:bg-accent/40 md:grid-cols-[minmax(0,2fr)_minmax(0,1.4fr)_auto]">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-medium">{c.name}</span>
                    <CampaignStatus status={c.status} />
                    {c.direct && <Badge variant="secondary" title="Envois lancés un par un depuis la boîte mail ou une fiche">À l'unité</Badge>}
                  </div>
                  <p className="mt-0.5 truncate text-xs text-muted-foreground">
                    {c.sequence ?? "—"}{Object.values(c.filters).length > 0 && ` · ${Object.entries(c.filters).map(([k, v]) => filterValue(k, v)).join(" · ")}`}
                    {c.start_at && new Date(c.start_at) > new Date() && <span className="text-primary"> · démarre {formatDayTime(c.start_at)}</span>}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <Progress value={i.enrolled ? (i.reached / i.enrolled) * 100 : 0} indicatorClassName="bg-brand" />
                  <span className="w-24 shrink-0 text-xs text-muted-foreground tabular">{i.reached}/{i.enrolled} contactés</span>
                </div>
                <div className="flex items-center gap-5 text-sm tabular">
                  <Metric label="réponses" value={i.replies} sub={pct(i.reply_rate)} accent />
                  <Metric label="intéressés" value={i.interested} />
                  <ArrowRight className="hidden size-4 text-muted-foreground md:block" />
                </div>
              </Link>
            );
          })}
        </Card>
      )}
    </>
  );
}

function Metric({ label, value, sub, accent }: { label: string; value: number; sub?: string; accent?: boolean }) {
  return (
    <div className="text-right">
      <div className={cn("font-semibold", accent && "text-brand")}>{value}{sub && <span className="ml-1 text-xs font-normal text-muted-foreground">{sub}</span>}</div>
      <div className="text-[11px] text-muted-foreground">{label}</div>
    </div>
  );
}

/* =============================================================== assistant */

const STEPS = [
  { key: "what", label: "Quoi", icon: ListOrdered },
  { key: "who", label: "Qui", icon: Users },
  { key: "check", label: "Vérifier et lancer", icon: Rocket },
] as const;

const WHO_HINT: Record<SequenceCategory, string> = {
  prospection: "Séquence de prospection : seuls les prospects la reçoivent (clients, assureurs et partenaires sont écartés d'office).",
  gestion: "Séquence de gestion : clients, assureurs, partenaires et prospects peuvent la recevoir.",
  souscription: "Séquence de souscription : clients, assureurs, partenaires et prospects peuvent la recevoir.",
};

export function CampaignWizardPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const wanted = params.get("sequence") ? Number(params.get("sequence")) : null;
  const [step, setStep] = useState(wanted ? 1 : 0);
  const [category, setCategory] = useState<SequenceCategory>("prospection");
  const [sequenceId, setSequenceId] = useState<number | null>(null);
  const [mode, setMode] = useState<"group" | "people">("group");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [picked, setPicked] = useState<number[]>([]);
  const [name, setName] = useState("");
  const [stopDomain, setStopDomain] = useState(false);
  const [startAt, setStartAt] = useState<string | null>(null);  // ISO, ou null = dès le lancement
  const [draft, setDraft] = useState<{ id: number; key: string } | null>(null);
  const [overlap, setOverlap] = useState(false);

  const { data: seqs } = useQuery({ queryKey: ["sequences"], queryFn: api.sequences });
  const seq = seqs?.items.find((q) => q.id === sequenceId);
  const seqCat: SequenceCategory = seq?.category ?? category;
  const seqItems = (seqs?.items ?? []).filter((q) => (q.category ?? "prospection") === category);
  // Les filtres réellement envoyés : un groupe, ou la liste des personnes cochées.
  const effective = useMemo<Record<string, string>>(() => {
    if (mode === "people") return { contact_ids: picked.join(",") };
    const f = { ...filters };
    if (seqCat === "prospection") delete f.kind;
    return f;
  }, [mode, picked, filters, seqCat]);
  const { data: count } = useQuery({
    queryKey: ["count", effective, seqCat], queryFn: () => api.contactsCount({ ...effective, category: seqCat }),
    placeholderData: (p) => p, enabled: mode === "group" || picked.length > 0,
  });

  // ?sequence=ID : arrivée depuis « Envoyer » sur la page Séquences -> séquence déjà choisie
  useEffect(() => {
    const q = seqs?.items.find((x) => x.id === wanted);
    if (q) { setCategory(q.category ?? "prospection"); setSequenceId(q.id); }
  }, [seqs, wanted]);
  const suggestedName = useMemo(() => {
    if (mode === "people") return `${seq?.name ?? "Campagne"} – ${picked.length} personne${picked.length > 1 ? "s" : ""}`;
    const parts = [lot(filters.wave), filters.sequence_code ?? filters.target_segment ?? filters.sector_family].filter(Boolean);
    return parts.length ? parts.join(" – ") : `${seq?.name ?? "Campagne"} – ${new Date().toLocaleDateString("fr-FR")}`;
  }, [filters, mode, picked, seq]);

  // Étape 3 : on enregistre un brouillon (rien n'est envoyé) pour obtenir le contrôle complet.
  const key = JSON.stringify({ effective, sequenceId, name: name || suggestedName, stopDomain, startAt });
  const prepare = useMutation({
    mutationFn: async () => {
      if (draft && draft.key === key) return draft;
      if (draft) await api.campaignAction(draft.id, "delete").catch(() => undefined);
      const { id } = await api.campaignCreate({ name: name.trim() || suggestedName, sequence_id: sequenceId!, filters: effective, stop_on_domain_reply: stopDomain, start_at: startAt });
      return { id, key };
    },
    onSuccess: (d) => setDraft(d),
    onError: (e) => toastError(e),
  });
  const { data: report, isFetching: checking } = useQuery({
    queryKey: ["activation", draft?.id, overlap],
    queryFn: () => api.activation(draft!.id, overlap),
    enabled: step === 2 && !!draft && draft.key === key,
  });
  const launch = useMutation({
    mutationFn: () => api.activate(draft!.id, overlap),
    onSuccess: (r) => {
      qc.invalidateQueries();
      toast.success("Campagne lancée", { description: `${r.enrolled} contact${r.enrolled > 1 ? "s" : ""} inscrit${r.enrolled > 1 ? "s" : ""}. ${startAt ? `Aucun email avant ${formatDayTime(startAt)}.` : "Premier envoi à la prochaine ouverture de la plage d'envoi."}` });
      navigate(`/campaigns/${draft!.id}`);
    },
    onError: (e) => toastError(e, "Lancement impossible"),
  });

  const go = (n: number) => {
    if (n === 2) prepare.mutate();
    setStep(n);
  };
  const canWho = mode === "group" ? !!count?.active : picked.length > 0 && !!count?.active;

  return (
    <>
      <PageHeader back={<Button variant="ghost" size="sm" className="-ml-2" asChild><Link to="/campaigns"><ArrowLeft /> Campagnes</Link></Button>}
        title="Nouvelle campagne" />
      <ol className="mb-6 flex items-center gap-2">
        {STEPS.map((s, i) => (
          <li key={s.key} className="flex flex-1 items-center gap-2 last:flex-none">
            <button disabled={i > step || (i > 0 && !sequenceId)} onClick={() => go(i)}
              className={cn("inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors",
                i === step ? "border-primary bg-primary text-primary-foreground" : i < step ? "border-primary/40 text-primary hover:bg-accent" : "text-muted-foreground")}>
              {i < step ? <CheckCircle2 className="size-4" /> : <s.icon className="size-4" />}
              <span className="hidden sm:inline">{s.label}</span>
            </button>
            {i < STEPS.length - 1 && <span className={cn("h-px flex-1", i < step ? "bg-primary/40" : "bg-border")} />}
          </li>
        ))}
      </ol>

      {step === 0 && (
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><ListOrdered className="size-4" /> Quelle séquence envoyer ?</CardTitle></CardHeader>
          <CardContent className="space-y-5">
            <div className="inline-flex w-full rounded-lg border bg-card p-0.5">
              {CATEGORIES.map((c) => (
                <button key={c.value} type="button" onClick={() => setCategory(c.value)}
                  className={cn("flex-1 rounded-md px-3 py-1.5 text-sm transition-colors", category === c.value ? "bg-primary font-medium text-primary-foreground" : "text-muted-foreground hover:bg-accent")}>
                  {c.label} <span className="text-xs opacity-75">{seqs?.items.filter((q) => (q.category ?? "prospection") === c.value).length ?? ""}</span>
                </button>
              ))}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {seqItems.length === 0 && seqs && (
                <p className="text-sm text-muted-foreground sm:col-span-2">Aucune séquence de ce type. <Link to={`/sequences?type=${category}`} className="text-primary hover:underline">En créer une</Link></p>
              )}
              {seqItems.map((q) => (
                <button key={q.id} onClick={() => setSequenceId(q.id)}
                  className={cn("rounded-xl border p-4 text-left transition-all", sequenceId === q.id ? "border-primary ring-2 ring-primary/15" : "hover:border-primary/40")}>
                  <p className="font-medium">{q.name}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{q.steps} email{q.steps > 1 ? "s" : ""} sur {q.total_days} jours</p>
                </button>
              ))}
            </div>
            {seqs && seqs.todo_blocks.length > 0 && (
              <p className="flex items-center gap-2 text-sm text-warning"><AlertTriangle className="size-4" />Textes personnalisés à rédiger : {seqs.todo_blocks.join(", ")}. Le lancement sera refusé pour les contacts concernés.</p>
            )}
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="space-y-1.5">
                <span className="text-sm font-medium">Nom de la campagne <span className="font-normal text-muted-foreground">(facultatif)</span></span>
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={suggestedName} />
              </label>
              <label className="flex items-center justify-between gap-3 rounded-xl border p-3 text-sm">
                <span>Arrêter si un collègue répond<span className="block text-xs text-muted-foreground">Même entreprise ; jamais pour Gmail, Hotmail…</span></span>
                <Switch checked={stopDomain} onCheckedChange={setStopDomain} />
              </label>
            </div>
            <StartPicker value={startAt} onChange={setStartAt} />
            <div className="flex justify-end">
              <Button disabled={!sequenceId} onClick={() => go(1)}>À qui ? <ArrowRight /></Button>
            </div>
          </CardContent>
        </Card>
      )}

      {step === 1 && (
        <Card>
          <CardHeader className="space-y-1">
            <CardTitle className="flex items-center gap-2"><Users className="size-4" /> À qui envoyer « {seq?.name ?? "…"} » ?</CardTitle>
            <p className="text-xs text-muted-foreground">{WHO_HINT[seqCat]}</p>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="grid gap-2 sm:grid-cols-2">
              {([["group", Filter, "Un groupe", "Par fonction, secteur, lot…"], ["people", Users, "Des personnes choisies", "Cochées une à une"]] as const).map(([m, Icon, label, hint]) => (
                <button key={m} onClick={() => setMode(m)}
                  className={cn("flex items-center gap-3 rounded-xl border p-3 text-left transition-colors", mode === m ? "border-primary bg-primary/5 ring-2 ring-primary/15" : "hover:bg-accent/40")}>
                  <Icon className={cn("size-4", mode === m ? "text-primary" : "text-muted-foreground")} />
                  <span><span className="block text-sm font-medium">{label}</span><span className="text-xs text-muted-foreground">{hint}</span></span>
                </button>
              ))}
            </div>
            {mode === "group" ? <GroupFilters filters={filters} setFilters={setFilters} prospection={seqCat === "prospection"} />
              : <PeopleChooser picked={picked} setPicked={setPicked} prospection={seqCat === "prospection"} />}
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-accent/60 p-4">
              <div>
                <p className="text-xl font-semibold tabular text-accent-foreground">{mode === "people" && !picked.length ? 0 : count?.active ?? "…"} <span className="text-base font-normal">{seqCat === "prospection" ? "prospect" : "contact"}{(count?.active ?? 0) > 1 ? "s" : ""} actif{(count?.active ?? 0) > 1 ? "s" : ""}</span></p>
                <p className="text-xs text-muted-foreground">{mode === "group" && count ? `${count.matching} correspondent aux filtres. ` : ""}Ceux qui ont répondu, rebondi ou sont désinscrits seront exclus.
                  {count && count.protected > 0 ? ` ${count.protected} client${count.protected > 1 ? "s, assureurs ou partenaires" : ", assureur ou partenaire"} écarté${count.protected > 1 ? "s" : ""} d'office.` : ""}</p>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => setStep(0)}><ArrowLeft /> Retour</Button>
                <Button disabled={!canWho} onClick={() => go(2)}>Vérifier <ArrowRight /></Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {step === 2 && (
        <div className="space-y-4">
          {!report || checking || prepare.isPending ? (
            <Card className="flex items-center gap-3 p-6 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" />Vérification de chaque email, pour chaque contact…</Card>
          ) : (
            <ActivationSummary report={report} sequenceId={sequenceId!} overlap={overlap} onOverlap={setOverlap} />
          )}
          <div className="flex flex-wrap justify-between gap-2">
            <Button variant="outline" onClick={() => setStep(1)}><ArrowLeft /> Retour</Button>
            <div className="flex gap-2">
              {draft && <Button variant="outline" onClick={() => navigate(`/campaigns/${draft.id}`)}>Garder en brouillon</Button>}
              <Button variant={report && !report.test_mode ? "destructive" : "brand"} disabled={!report || report.blocked || launch.isPending} onClick={() => launch.mutate()}>
                <Rocket /> {report?.test_mode === false ? "Lancer : envois réels" : "Lancer la campagne"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function GroupFilters({ filters, setFilters, prospection }: { filters: Record<string, string>; setFilters: (f: (x: Record<string, string>) => Record<string, string>) => void; prospection: boolean }) {
  const { data: options } = useQuery({ queryKey: ["contacts", {}], queryFn: () => api.contacts({}) });
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Object.entries(FILTER_LABELS).filter(([k]) => k !== "kind" || !prospection).map(([k, label]) => (
        <label key={k} className="space-y-1.5">
          <span className="text-sm font-medium">{label}</span>
          <NativeSelect value={filters[k] ?? ""} onChange={(e) => setFilters((f) => {
            const n = { ...f };
            if (e.target.value) n[k] = e.target.value; else delete n[k];
            return n;
          })}>
            <option value="">Tous</option>
            {k === "kind" ? (options?.vocab.kinds ?? []).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)
              : ((options?.options as unknown as Record<string, string[]>)?.[k] ?? []).map((v) => <option key={v} value={v}>{k === "wave" ? lot(v) : v}</option>)}
          </NativeSelect>
        </label>
      ))}
    </div>
  );
}

/** Choisir les personnes une à une : recherche, type, tout cocher. */
function PeopleChooser({ picked, setPicked, prospection }: { picked: number[]; setPicked: (ids: number[]) => void; prospection: boolean }) {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState(prospection ? "prospect" : "");
  const { data } = useQuery({ queryKey: ["contacts", "chooser", q, kind], queryFn: () => api.contacts({ q, kind }), placeholderData: (p) => p });
  const rows = (data?.items ?? []).filter((c) => c.status === "active");
  const sel = new Set(picked);
  const allShown = rows.length > 0 && rows.every((c) => sel.has(c.id));
  const toggleAll = () => setPicked(allShown ? picked.filter((id) => !rows.some((c) => c.id === id)) : [...new Set([...picked, ...rows.map((c) => c.id)])]);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <div className="relative min-w-[14rem] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-9" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Nom, email, entreprise, poste…" />
        </div>
        {!prospection && (
          <NativeSelect className="w-auto" value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">Tous les types</option>
            {(data?.vocab.kinds ?? []).map((o) => <option key={o.value} value={o.value}>{o.label}s</option>)}
          </NativeSelect>
        )}
      </div>
      <div className="overflow-hidden rounded-lg border">
        <div className="flex items-center gap-3 border-b bg-muted/40 px-3 py-2 text-xs">
          <input type="checkbox" className="accent-[hsl(var(--primary))]" checked={allShown} onChange={toggleAll} aria-label="Tout cocher" />
          <span className="flex-1 text-muted-foreground">{allShown ? "Tout décocher" : `Tout cocher (${rows.length} affichés)`}</span>
          <span className="font-medium">{picked.length} choisie{picked.length > 1 ? "s" : ""}</span>
          {picked.length > 0 && <button className="text-muted-foreground hover:text-foreground" onClick={() => setPicked([])}>Vider</button>}
        </div>
        <div className="max-h-80 divide-y overflow-y-auto">
          {rows.map((c) => (
            <label key={c.id} className="flex cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-accent/30">
              <input type="checkbox" className="accent-[hsl(var(--primary))]" checked={sel.has(c.id)}
                onChange={(e) => setPicked(e.target.checked ? [...picked, c.id] : picked.filter((x) => x !== c.id))} />
              <span className="min-w-0 flex-1 truncate">{fullName(c)}<span className="text-muted-foreground">{c.company ? ` · ${c.company}` : ""}{c.job_title ? ` · ${c.job_title}` : ""}</span></span>
              <KindBadge kind={c.kind} hideProspect />
            </label>
          ))}
          {data && rows.length === 0 && <p className="px-3 py-6 text-center text-sm text-muted-foreground">Personne ne correspond.</p>}
        </div>
      </div>
    </div>
  );
}

/** Résumé du contrôle avant lancement, partagé par l'assistant et la page d'une campagne brouillon. */
export function ActivationSummary({ report, sequenceId, overlap, onOverlap }: { report: Activation; sequenceId: number; overlap: boolean; onOverlap: (v: boolean) => void }) {
  return (
    <>
      <div className={cn("flex items-start gap-3 rounded-xl border p-4 text-sm", report.test_mode ? "border-warning/40 bg-warning/5" : "border-destructive/40 bg-destructive/5")}>
        <ShieldCheck className={cn("mt-0.5 size-4 shrink-0", report.test_mode ? "text-warning" : "text-destructive")} />
        {report.test_mode ? "Mode test : tous les emails partiront vers votre propre adresse, avec l'objet préfixé [TEST → contact]. Aucun prospect ne recevra rien."
          : "Mode test désactivé : les emails partiront réellement aux contacts."}
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Card className="p-4"><p className="text-xs text-muted-foreground">Contacts inscrits</p><p className="mt-1 text-xl font-semibold tabular">{report.eligible}</p>
          {report.excluded.length > 0 && <p className="text-xs text-muted-foreground">{report.excluded.length} exclus automatiquement</p>}</Card>
        <Card className="p-4"><p className="text-xs text-muted-foreground">Premier envoi</p><p className="mt-1 font-semibold">{report.first_send ? formatDayTime(report.first_send) : "—"}</p></Card>
        <Card className="p-4"><p className="flex items-center gap-1 text-xs text-muted-foreground"><CalendarCheck className="size-3.5" />Fin estimée</p>
          <p className="mt-1 font-semibold">{report.last_send ? formatDayTime(report.last_send) : "—"}</p>
          <p className="text-xs text-muted-foreground">Si personne ne répond : en pratique, plus tôt.</p></Card>
      </div>
      {report.with_problems_count > 0 && (
        <Card className="border-destructive/40">
          <CardHeader><CardTitle className="text-destructive">Lancement impossible : {report.with_problems_count} contact{report.with_problems_count > 1 ? "s" : ""} recevrai{report.with_problems_count > 1 ? "ent" : "t"} un email incomplet</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            {report.with_problems.slice(0, 8).map((c) => (
              <div key={c.id} className="rounded-lg border p-2.5">
                <span className="font-medium">{c.company ?? fullName(c)}</span> <code className="text-xs text-muted-foreground">{c.sequence_code ?? "sans code"}</code>
                <ul className="mt-1 text-xs text-muted-foreground">{c.problems?.map((p) => <li key={p}>• {p}</li>)}</ul>
              </div>
            ))}
            <Button variant="outline" size="sm" asChild><Link to={`/sequences/${sequenceId}`}>Corriger la séquence</Link></Button>
            <Button variant="outline" size="sm" className="ml-2" asChild><Link to="/sequences/blocks">Rédiger les blocs</Link></Button>
          </CardContent>
        </Card>
      )}
      {report.reliability_warn && (
        <p className="flex items-start gap-2 rounded-xl border border-warning/40 bg-warning/5 p-4 text-sm"><AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
          {Math.round(report.reliability_ratio * 100)} % des contacts ont un email dont la qualité n'est pas « Bonne ». Beaucoup de rebonds peuvent nuire à la réputation du domaine du cabinet.</p>
      )}
      {report.link_warnings.map((w) => <p key={w} className="rounded-xl border border-warning/40 bg-warning/5 p-4 text-sm">{w}</p>)}
      {report.overlapping.length > 0 && (
        <label className="flex items-center justify-between gap-3 rounded-xl border p-4 text-sm">
          <span>{report.overlapping.length} contact{report.overlapping.length > 1 ? "s sont" : " est"} déjà en cours dans une autre campagne
            <span className="block text-xs text-muted-foreground">{overlap ? "Ils seront inscrits quand même." : "Ils ne seront pas inscrits."}</span></span>
          <Switch checked={overlap} onCheckedChange={onOverlap} />
        </label>
      )}
      {report.excluded.length > 0 && (
        <details className="rounded-xl border p-4 text-sm">
          <summary className="cursor-pointer font-medium">Contacts exclus automatiquement ({report.excluded.length})</summary>
          <ul className="mt-2 space-y-1 text-xs text-muted-foreground">{report.excluded.map((c) => <li key={c.id}>{c.email} : {c.excluded}</li>)}</ul>
        </details>
      )}
    </>
  );
}

/* =============================================================== détail */

const VIEWS = [
  { key: "all", label: "Tous", match: () => true },
  { key: "running", label: "En cours", match: (s: string) => ["scheduled", "waiting", "sending"].includes(s) },
  { key: "replied", label: "Réponses", match: (s: string) => s === "replied" },
  { key: "done", label: "Terminés", match: (s: string) => ["completed", "stopped", "bounced", "unsubscribed"].includes(s) },
  { key: "issues", label: "À vérifier", match: (s: string) => ["error", "needs_review"].includes(s) },
];

/** V3 : les emails prévus pour UNE personne de la campagne (clic sur sa ligne). */
function EnrollmentEmailsDialog({ campaignId, enrollment, onClose }: { campaignId: number; enrollment: { id: number; name: string } | null; onClose: () => void }) {
  const { data, isLoading } = useQuery({ queryKey: ["campaign-upcoming", campaignId, enrollment?.id], queryFn: () => api.campaignUpcoming(campaignId, enrollment!.id), enabled: !!enrollment });
  const it = data?.items[0];
  return (
    <Dialog open={!!enrollment} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[calc(100vh-2rem)] max-w-3xl overflow-y-auto">
        <DialogTitle>Emails prévus pour {enrollment?.name}</DialogTitle>
        {isLoading || !data ? <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Préparation…</p>
          : !it ? <p className="text-sm text-muted-foreground">Plus aucun email prévu pour cette personne (séquence terminée, réponse reçue ou retirée).</p>
          : <>
              <p className="text-sm text-muted-foreground">
                Exactement ce qui partira, à la date indiquée. Les relances ne partent que s'il n'y a pas de réponse.
                {data.test_mode && <> <b>Mode test</b> : ils arriveront dans votre boîte.</>}
                {data.campaign_status === "paused" && <> Campagne <b>en pause</b>.</>}
              </p>
              <div className="space-y-3">{it.emails.map((e) => <EmailCard key={e.position} email={e} to={it.to} name={fullName(it.contact)} from={data.from} ab={false} />)}</div>
            </>}
      </DialogContent>
    </Dialog>
  );
}

/** V3 : les prochains emails de la campagne, tels qu'ils partiront. */
function UpcomingEmails({ campaignId }: { campaignId: number }) {
  const { data, isLoading } = useQuery({ queryKey: ["campaign-upcoming", campaignId], queryFn: () => api.campaignUpcoming(campaignId) });
  const [open, setOpen] = useState<number | null>(null);
  if (isLoading || !data) return <p className="flex items-center gap-2 p-6 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Préparation des emails…</p>;
  if (!data.items.length) return <p className="p-8 text-center text-sm text-muted-foreground">Aucun email prévu dans cette campagne.</p>;
  return (
    <div className="space-y-3 p-4">
      <p className="text-sm text-muted-foreground">
        {data.total} personne{data.total > 1 ? "s" : ""} avec des emails prévus{data.total > data.items.length ? ` (les ${data.items.length} premières)` : ""}.
        Le texte est exactement celui qui partira ; les relances ne partent que s'il n'y a pas de réponse.
        {data.test_mode && <> <b>Mode test</b> : ils arriveront dans votre boîte.</>}
        {data.campaign_status === "paused" && <> Campagne <b>en pause</b> : rien ne part avant « Reprendre ».</>}
      </p>
      {data.items.map((it) => {
        const isOpen = open === it.enrollment_id;
        return (
          <div key={it.enrollment_id} className="rounded-lg border">
            <button type="button" onClick={() => setOpen(isOpen ? null : it.enrollment_id)} aria-expanded={isOpen}
              className="flex w-full flex-wrap items-center gap-3 px-4 py-3 text-left text-sm hover:bg-muted/40">
              <span className="min-w-0 flex-1 truncate"><span className="font-medium">{fullName(it.contact)}</span> <span className="text-muted-foreground">&lt;{it.to}&gt;</span></span>
              <span className="text-xs text-muted-foreground">
                {it.emails.length} email{it.emails.length > 1 ? "s" : ""} · prochain {it.emails[0]?.planned_at ? formatDayTime(it.emails[0].planned_at) : "—"}
              </span>
              {it.emails.some((e) => e.problems.length) && <Badge variant="destructive">À corriger</Badge>}
              <span className="text-xs text-primary">{isOpen ? "Masquer" : "Voir les emails"}</span>
            </button>
            {isOpen && (
              <div className="grid gap-3 border-t bg-muted/20 p-3 lg:grid-cols-2">
                {it.emails.map((e) => <EmailCard key={e.position} email={e} to={it.to} name={fullName(it.contact)} from={data.from} ab={false} />)}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** V3.4 : textes de la campagne. Pour une fonction ou un secteur qui a des variantes, la campagne
 * peut envoyer une variante à la place du texte de la fiche, ou partager à parts égales entre
 * plusieurs (test). Rien de coché = selon la fiche du contact. */
function CampaignTexts({ camp }: { camp: CampaignDetail }) {
  const qc = useQueryClient();
  const { data: blocks } = useQuery({ queryKey: ["blocks"], queryFn: api.blocks, staleTime: 60_000 });
  const [map, setMap] = useState<BlockMap>(camp.block_map ?? {});
  useEffect(() => setMap(camp.block_map ?? {}), [camp.block_map]);
  const save = useMutation({
    mutationFn: (m: BlockMap) => api.campaignBlocks(camp.id, m),
    onSuccess: (r) => { setMap(r.block_map); qc.invalidateQueries({ queryKey: ["campaign", camp.id] }); qc.invalidateQueries({ queryKey: ["campaign-upcoming", camp.id] }); toast.success("Textes de la campagne enregistrés"); },
    onError: (e) => toastError(e),
  });
  const groups = useMemo(() => {
    const out: { kind: "target" | "sector"; root: Block; options: Block[] }[] = [];
    for (const b of blocks ?? []) {
      if (b.variant_of || b.generic) continue;
      const variants = (blocks ?? []).filter((x) => x.kind === b.kind && x.variant_of === b.key);
      if (variants.length) out.push({ kind: b.kind, root: b, options: [b, ...variants] });
    }
    return out;
  }, [blocks]);
  if (!blocks || groups.length === 0) return null;
  const chosen = (kind: "target" | "sector", root: string): string[] => {
    const v = map[kind]?.[root];
    return v ? (Array.isArray(v) ? v : [v]) : [];
  };
  const toggle = (kind: "target" | "sector", root: string, key: string) => {
    const cur = chosen(kind, root);
    const order = groups.find((g) => g.kind === kind && g.root.key === root)?.options.map((o) => o.key) ?? [];
    const next = (cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key]).sort((a, b) => order.indexOf(a) - order.indexOf(b));
    const m: BlockMap = { ...map, [kind]: { ...(map[kind] ?? {}) } };
    if (next.length) m[kind]![root] = next.length === 1 ? next[0] : next; else delete m[kind]![root];
    setMap(m);
    save.mutate(m);
  };
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2"><FileText className="size-4 text-muted-foreground" />Textes de la campagne</CardTitle>
        <p className="text-sm text-muted-foreground">
          Rien de coché : chacun reçoit le texte de sa fiche. <b>Une case</b> : tous les contacts de cette fonction (ou de ce secteur) reçoivent ce texte.
          <b> Plusieurs cases</b> : partage à parts égales, pour comparer les réponses dans « Taux de réponse ». Ne change que les 1ers emails pas encore partis.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        {groups.map((g) => {
          const sel = chosen(g.kind, g.root.key);
          return (
            <div key={`${g.kind}-${g.root.key}`} className="flex flex-wrap items-center gap-2 text-sm">
              <span className="w-full text-xs text-muted-foreground sm:w-56">{g.kind === "target" ? "Fonction" : "Secteur"} <b className="text-foreground">{g.root.label}</b> sur la fiche</span>
              {g.options.map((o) => (
                <button key={o.key} type="button" disabled={save.isPending} onClick={() => toggle(g.kind, g.root.key, o.key)}
                  className={cn("rounded-full border px-3 py-1 transition-colors", sel.includes(o.key) ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent", o.variant_of && "border-dashed")}>
                  {o.variant_of ? o.label.replace(`${g.root.label} · `, "") : "Texte d'origine"} <code className="ml-1 text-[11px] opacity-70">{o.key}</code>
                </button>
              ))}
              <span className="text-xs text-muted-foreground">
                {sel.length === 0 ? "selon la fiche" : sel.length === 1 ? `→ tous reçoivent ${sel[0]}` : `→ partage ${sel.join(" / ")}`}
              </span>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

/** V3.3.6 : les emails déjà partis (clic sur « Emails envoyés »), un clic ouvre l'aperçu. */
function SentEmails({ campaignId }: { campaignId: number }) {
  const { data, isLoading } = useQuery({ queryKey: ["campaign-sent", campaignId], queryFn: () => api.campaignSent(campaignId), refetchInterval: 30_000 });
  const [open, setOpen] = useState<number | null>(null);
  if (isLoading || !data) return <p className="flex items-center gap-2 p-6 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Chargement…</p>;
  if (!data.items.length) return <p className="p-8 text-center text-sm text-muted-foreground">Aucun email envoyé pour l'instant.</p>;
  return (
    <div>
      <p className="px-4 pt-3 text-sm text-muted-foreground">
        {data.total} email{data.total > 1 ? "s" : ""} envoyé{data.total > 1 ? "s" : ""}, du plus récent au plus ancien{data.total > data.items.length ? ` (les ${data.items.length} derniers)` : ""}. Cliquez pour voir l'email.
      </p>
      <div className="divide-y">
        {data.items.map((m) => {
          const isOpen = open === m.id;
          const name = m.contact ? fullName(m.contact) : m.to;
          return (
            <div key={m.id}>
              <button type="button" onClick={() => setOpen(isOpen ? null : m.id)} aria-expanded={isOpen}
                className={cn("grid w-full items-center gap-x-3 gap-y-0.5 px-4 py-2.5 text-left text-sm hover:bg-muted/40 sm:grid-cols-[minmax(0,13rem)_4.5rem_minmax(0,1fr)_auto]", isOpen && "bg-muted/40")}>
                <span className="min-w-0 truncate font-medium">{name}</span>
                <span className="text-xs text-muted-foreground">{m.position ? `Email ${m.position}` : "Email"}</span>
                <span className="min-w-0 truncate text-muted-foreground">{m.subject}</span>
                <span className="flex items-center gap-2 text-xs text-muted-foreground tabular">
                  {m.test_mode && <Badge variant="warning">Test</Badge>}
                  {m.replied && <Badge variant="success">A répondu</Badge>}
                  {formatDayTime(m.sent_at)}
                </span>
              </button>
              {isOpen && (
                <div className="border-t bg-muted/20 p-3">
                  <EmailCard email={{ position: m.position ?? 1, subject: m.subject, body: m.body, planned_at: null, same_thread: false, problems: [], warnings: [], attachments: [] }}
                    to={m.to} name={name} from={data.from} ab={false} sentAt={m.sent_at} />
                  {m.test_mode && <p className="mt-2 text-xs text-muted-foreground">Envoyé en mode test : il est arrivé dans votre boîte, pas chez le contact.</p>}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function CampaignDetailPage() {
  const id = Number(useParams().id);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data } = useQuery({ queryKey: ["campaign", id], queryFn: () => api.campaign(id), refetchInterval: 30_000 });
  const [view, setView] = useState("all");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [checking, setChecking] = useState(false);
  const [overlap, setOverlap] = useState(false);
  const [planning, setPlanning] = useState(false);
  const refresh = () => qc.invalidateQueries();

  const action = useMutation({
    mutationFn: (a: "pause" | "resume" | "delete") => api.campaignAction(id, a),
    onSuccess: (_, a) => {
      if (a === "delete") { toast.success("Campagne supprimée"); qc.invalidateQueries(); return navigate("/campaigns"); }
      toast.success(a === "pause" ? "Campagne en pause : plus aucun envoi" : "Campagne reprise");
      refresh();
    },
    onError: (e) => toastError(e),
  });
  const row = useMutation({
    mutationFn: ({ kind, eid, cid }: { kind: "send" | "skip" | "remove" | "confirm" | "retry"; eid: number; cid: number }) =>
      kind === "send" ? api.sendNow(eid) : kind === "skip" ? api.skip(eid) : kind === "remove" ? api.removeEnrollment(cid, eid)
        : kind === "confirm" ? api.confirmSent(eid) : api.retry(eid),
    onSuccess: (_, v) => {
      toast.success({ send: "Email envoyé", skip: "Email sauté", remove: "Contact retiré", confirm: "Envoi confirmé", retry: "Remis dans la file" }[v.kind]);
      refresh();
    },
    onError: (e) => toastError(e),
  });
  const { data: report } = useQuery({ queryKey: ["activation", id, overlap], queryFn: () => api.activation(id, overlap), enabled: checking });
  const launch = useMutation({
    mutationFn: () => api.activate(id, overlap),
    onSuccess: (r) => { toast.success(`Campagne lancée : ${r.enrolled} contacts`); setChecking(false); refresh(); },
    onError: (e) => toastError(e, "Lancement impossible"),
  });

  const [peek, setPeek] = useState<{ id: number; name: string } | null>(null); // V3 : emails prévus d'une personne
  if (!data) return <Skeleton className="h-96 rounded-xl" />;
  const list = view === "upcoming" || view === "sent" ? [] : data.enrollments.filter((e) => VIEWS.find((v) => v.key === view)!.match(e.status));

  return (
    <>
      <PageHeader
        back={<Button variant="ghost" size="sm" className="-ml-2" asChild><Link to="/campaigns"><ArrowLeft /> Campagnes</Link></Button>}
        title={<span className="flex items-center gap-3">{data.name}<CampaignStatus status={data.status} /></span>}
        description={<>Séquence <Link className="text-primary hover:underline" to={`/sequences/${data.sequence?.id}`}>{data.sequence?.name}</Link>
          {Object.entries(data.filters).map(([k, v]) => <Badge key={k} variant="secondary" className="ml-2">{k === "contact_ids" ? filterValue(k, v) : `${FILTER_LABELS[k] ?? k} : ${filterValue(k, v)}`}</Badge>)}
          {data.activated_at && <> · lancée le {formatDayTime(data.activated_at)}</>}
          {data.start_at && !data.started && new Date(data.start_at) > new Date() && <Badge variant="info" className="ml-2"><CalendarClock className="mr-1 size-3" />Démarre {formatDayTime(data.start_at)}</Badge>}</>}
        actions={<>
          {data.status !== "draft" && <Button variant="outline" asChild><a href={`/api/export?campaign_id=${data.id}`}><Download /> Exporter</a></Button>}
          {data.status === "active" && <Button variant="outline" onClick={() => action.mutate("pause")}><Pause /> Mettre en pause</Button>}
          {data.status === "paused" && <Button onClick={() => action.mutate("resume")}><Play /> Reprendre</Button>}
          {["draft", "active", "paused"].includes(data.status) && !data.started && <Button variant="outline" onClick={() => setPlanning(true)}><CalendarClock /> Démarrage</Button>}
          <Button variant="outline" className="text-destructive hover:text-destructive" onClick={() => setConfirmDelete(true)}><Trash2 /> Supprimer</Button>
          {data.status === "draft" && <Button variant="brand" onClick={() => setChecking(true)}><Rocket /> Vérifier et lancer</Button>}
        </>}
      />

      {data.status === "draft" ? (
        checking ? (
          <div className="space-y-4">
            {!report ? <Card className="flex items-center gap-3 p-6 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" />Vérification de chaque email…</Card>
              : <ActivationSummary report={report} sequenceId={data.sequence!.id} overlap={overlap} onOverlap={setOverlap} />}
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setChecking(false)}>Annuler</Button>
              <Button variant="brand" disabled={!report || report.blocked || launch.isPending} onClick={() => launch.mutate()}><Rocket /> Lancer la campagne</Button>
            </div>
          </div>
        ) : (
          <div className="space-y-6">
          <CampaignTexts camp={data} />
          <Card>
            <CardHeader><CardTitle>{data.candidates.filter((c) => !c.excluded).length} contacts seront inscrits</CardTitle></CardHeader>
            <CardContent className="divide-y p-0">
              {data.candidates.map((c) => (
                <div key={c.id} className="flex items-center gap-3 px-5 py-2.5 text-sm">
                  <span className="min-w-0 flex-1 truncate"><span className="font-medium">{fullName(c)}</span> <span className="text-muted-foreground">· {c.company}</span></span>
                  <code className="text-xs text-muted-foreground">{c.sequence_code}</code>
                  {c.excluded ? <Badge variant="destructive">Exclu : {c.excluded}</Badge> : c.other_campaigns.length ? <Badge variant="warning">Déjà dans {c.other_campaigns.join(", ")}</Badge> : <Badge variant="success">OK</Badge>}
                </div>
              ))}
            </CardContent>
          </Card>
          </div>
        )
      ) : (
        <div className="space-y-6">
          <MiniKpis i={data.indicators} counts={data.counts}
            onSent={() => { setView("sent"); requestAnimationFrame(() => document.getElementById("campaign-people")?.scrollIntoView({ behavior: "smooth", block: "start" })); }} />
          <div className="grid gap-6 lg:grid-cols-2">
            <StepFunnel i={data.indicators} />
            <Outcomes i={data.indicators} running={(data.counts.scheduled ?? 0) + (data.counts.waiting ?? 0) + (data.counts.sending ?? 0)} />
          </div>
          {(data.segments.length > 1 || data.ab.rows.length > 0) && <Breakdown data={data} />}
          {data.status !== "finished" && !data.direct && <CampaignTexts camp={data} />}
          <Card id="campaign-people" className="scroll-mt-4">
            <div className="flex flex-wrap items-center gap-1 border-b p-2">
              {VIEWS.map((v) => {
                const n = data.enrollments.filter((e) => v.match(e.status)).length;
                return (
                  <button key={v.key} onClick={() => setView(v.key)}
                    className={cn("rounded-md px-3 py-1.5 text-sm transition-colors", view === v.key ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:text-foreground")}>
                    {v.label} <span className="ml-1 text-xs tabular opacity-70">{n}</span>
                  </button>
                );
              })}
              <span className="flex-1" />
              <button onClick={() => setView("sent")}
                className={cn("flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors", view === "sent" ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:text-foreground")}>
                <Send className="size-3.5" /> Envoyés <span className="text-xs tabular opacity-70">{data.indicators.sent_total}</span>
              </button>
              <button onClick={() => setView("upcoming")}
                className={cn("flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors", view === "upcoming" ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:text-foreground")}>
                <Eye className="size-3.5" /> Prochains envois
              </button>
            </div>
            {view === "sent" ? <SentEmails campaignId={data.id} /> : view === "upcoming" ? <UpcomingEmails campaignId={data.id} /> : list.length === 0 ? <p className="p-8 text-center text-sm text-muted-foreground">Aucun contact dans cette vue.</p> : (
              <div className="divide-y">
                {list.map((e) => (
                  <div key={e.id} className="grid items-center gap-3 px-4 py-3 text-sm sm:grid-cols-[minmax(0,1.4fr)_13rem_minmax(0,1fr)_2.5rem]">
                    <Link to={`/contacts?open=${e.contact.id}`} className="min-w-0 hover:text-primary">
                      <span className="block truncate font-medium">{fullName(e.contact)}</span>
                      <span className="block truncate text-xs text-muted-foreground">{e.contact.company} · {e.contact.sequence_code}</span>
                    </Link>
                    <div className="flex items-center gap-2">
                      {e.variant && <span className="flex size-6 items-center justify-center rounded-md bg-muted text-[11px] font-semibold">{e.variant}</span>}
                      <EnrollmentStatus status={e.status} />
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {e.next_due_at ? <button type="button" onClick={() => setPeek({ id: e.id, name: fullName(e.contact) })} className="text-left hover:text-primary" title="Voir les emails prévus">
                        Email n°{e.step}{e.max_steps ? ` sur ${e.max_steps}` : ""} · {formatDayTime(e.next_due_at)} <span className="ml-1 inline-flex items-center gap-0.5 text-primary"><Eye className="size-3" /> voir</span>
                      </button> : e.error ? <span className="text-destructive">{e.error}</span> : `${Math.min(e.step - 1, data.sequence?.steps ?? e.step)} email(s) envoyé(s)`}
                    </div>
                    <RowActions e={e} onAct={(kind) => row.mutate({ kind, eid: e.id, cid: e.contact.id })} />
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}

      <StartDialog open={planning} onOpenChange={setPlanning} campaignId={data.id} current={data.start_at} onDone={refresh} />
      <EnrollmentEmailsDialog campaignId={data.id} enrollment={peek} onClose={() => setPeek(null)} />
      <ConfirmDialog open={confirmDelete} onOpenChange={setConfirmDelete} destructive pending={action.isPending}
        title={data.status === "draft" ? "Supprimer ce brouillon ?" : "Supprimer cette campagne ?"}
        description={data.status === "draft" ? undefined : <>
          <p>Tous les emails pas encore partis sont annulés et la campagne disparaît de la liste. C'est définitif.</p>
          <p className="mt-2">{data.indicators.sent_total > 0
            ? <>Les {data.indicators.sent_total} email(s) déjà envoyé(s) et les réponses restent dans la boîte mail et sur la fiche de chaque contact.</>
            : <>Aucun email n'est encore parti.</>}</p>
          {data.status === "active" && <p className="mt-2 text-muted-foreground">Pour arrêter sans rien effacer, utilisez plutôt « Mettre en pause ».</p>}
        </>}
        confirmLabel="Supprimer" onConfirm={() => action.mutate("delete")} />
    </>
  );
}

function RowActions({ e, onAct }: { e: CampaignDetail["enrollments"][number]; onAct: (k: "send" | "skip" | "remove" | "confirm" | "retry") => void }) {
  const due = ["scheduled", "waiting"].includes(e.status);
  const open = due || ["error", "needs_review"].includes(e.status);
  if (!open) return <span />;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild><Button variant="ghost" size="icon" className="size-8 justify-self-end" aria-label="Actions"><MoreHorizontal /></Button></DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {due && <DropdownMenuItem onSelect={() => onAct("send")}><Send /> Envoyer maintenant</DropdownMenuItem>}
        {due && <DropdownMenuItem onSelect={() => onAct("skip")}><SkipForward /> Sauter cet email</DropdownMenuItem>}
        {e.status === "needs_review" && <DropdownMenuItem onSelect={() => onAct("confirm")}><CheckCircle2 /> Il est dans mes Envoyés</DropdownMenuItem>}
        {["error", "needs_review"].includes(e.status) && <DropdownMenuItem onSelect={() => onAct("retry")}><Send /> Renvoyer</DropdownMenuItem>}
        <DropdownMenuSeparator />
        <DropdownMenuItem destructive onSelect={() => onAct("remove")}><UserMinus /> Retirer de la campagne</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function MiniKpis({ i, counts, onSent }: { i: Indicators; counts: Record<string, number>; onSent: () => void }) {
  const running = (counts.scheduled ?? 0) + (counts.waiting ?? 0) + (counts.sending ?? 0);
  const items = [
    { label: "Contacts", value: i.enrolled },
    { label: "En cours", value: running },
    { label: "Emails envoyés", value: i.sent_total, onClick: i.sent_total > 0 ? onSent : undefined },
    { label: "Réponses", value: i.replies, sub: pct(i.reply_rate), accent: true },
    { label: "Intéressés", value: i.interested },
    { label: "Rebonds · STOP", value: i.bounced + i.unsubscribed },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {items.map((t) => (
        <Card key={t.label} className={cn("p-3.5", t.accent && "border-brand/30 bg-brand/[0.04]",
          t.onClick && "cursor-pointer transition-colors hover:border-primary/40 hover:bg-accent/40")}
          onClick={t.onClick} role={t.onClick ? "button" : undefined} tabIndex={t.onClick ? 0 : undefined}
          onKeyDown={t.onClick ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); t.onClick!(); } } : undefined}
          title={t.onClick ? "Voir les emails envoyés" : undefined}>
          <p className="flex items-center justify-between text-xs text-muted-foreground">{t.label}{t.onClick && <Eye className="size-3.5" />}</p>
          <p className={cn("mt-1 text-xl font-semibold tabular", t.accent && "text-brand")}>{t.value}{t.sub && <span className="ml-1.5 text-xs font-normal text-muted-foreground">{t.sub}</span>}</p>
        </Card>
      ))}
    </div>
  );
}

/** Taux de réponse par segment et par variante d'objet (A/B), dans une même carte. */
function Breakdown({ data }: { data: CampaignDetail }) {
  const block = (title: string, rows: CampaignDetail["segments"], note?: string) => (
    <div className="space-y-2.5">
      <p className="text-sm font-medium">{title}</p>
      {rows.map((r) => (
        <div key={r.key} className="grid grid-cols-[minmax(0,7rem)_minmax(0,1fr)_5.5rem] items-center gap-3 text-sm">
          <code className="truncate text-xs text-muted-foreground">{r.key}</code>
          <Progress value={(r.rate ?? 0) * 100} indicatorClassName="bg-brand" />
          <span className="text-right text-xs tabular"><b>{pct(r.rate)}</b> <span className="text-muted-foreground">{r.replies}/{r.reached}</span></span>
        </div>
      ))}
      {note && <p className="text-xs text-muted-foreground">{note}</p>}
    </div>
  );
  return (
    <Card>
      <CardHeader><CardTitle>Taux de réponse</CardTitle></CardHeader>
      <CardContent className="grid gap-8 md:grid-cols-2">
        {data.segments.length > 1 && block("Par profil (fonction × secteur)", data.segments)}
        {data.ab.rows.length > 0 && block("Par objet (A/B)", data.ab.rows,
          data.ab.too_small ? `Pas encore significatif : attendez au moins ${data.ab.min_sample} contacts contactés par objet.` : undefined)}
      </CardContent>
    </Card>
  );
}

/* =============================================================== démarrage planifié (V2.5) */

function toLocalInputs(iso: string | null): { date: string; time: string } {
  if (!iso) return { date: "", time: "09:00" };
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return { date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`, time: `${pad(d.getHours())}:${pad(d.getMinutes())}` };
}

/** Date + heure saisies sur le PC (heure du Maroc chez Omar) -> ISO avec fuseau. */
function fromLocalInputs(date: string, time: string): string | null {
  if (!date) return null;
  const d = new Date(`${date}T${time || "09:00"}`);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

function StartPicker({ value, onChange }: { value: string | null; onChange: (v: string | null) => void }) {
  const [planned, setPlanned] = useState(!!value);
  const [{ date, time }, setInputs] = useState(toLocalInputs(value));
  const today = toLocalInputs(new Date().toISOString()).date;
  const update = (d: string, t: string) => { setInputs({ date: d, time: t }); onChange(fromLocalInputs(d, t)); };
  return (
    <div className="space-y-3 rounded-xl border p-4">
      <p className="flex items-center gap-2 text-sm font-medium"><CalendarClock className="size-4 text-muted-foreground" />Démarrage</p>
      <div className="flex flex-wrap gap-2">
        <Button type="button" size="sm" variant={!planned ? "default" : "outline"} onClick={() => { setPlanned(false); onChange(null); }}>Dès le lancement</Button>
        <Button type="button" size="sm" variant={planned ? "default" : "outline"} onClick={() => { setPlanned(true); update(date || today, time); }}>Planifier une date</Button>
      </div>
      {planned && (
        <div className="flex flex-wrap items-center gap-2">
          <Input type="date" className="w-44" min={today} value={date} onChange={(e) => update(e.target.value, time)} />
          <span className="text-sm text-muted-foreground">à partir de</span>
          <Input type="time" className="w-28" value={time} onChange={(e) => update(date, e.target.value)} />
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        {planned ? "Vous pouvez lancer la campagne dès maintenant : aucun email ne partira avant cette date. Les jours et heures de chaque étape s'appliquent ensuite."
          : "Les premiers emails partent à la prochaine ouverture de la plage d'envoi."}
      </p>
    </div>
  );
}

function StartDialog({ open, onOpenChange, campaignId, current, onDone }: { open: boolean; onOpenChange: (o: boolean) => void; campaignId: number; current: string | null; onDone: () => void }) {
  const [value, setValue] = useState<string | null>(current);
  const save = useMutation({
    mutationFn: () => api.campaignStart(campaignId, value),
    onSuccess: (r) => {
      toast.success(r.start_at ? `Démarrage planifié ${formatDayTime(r.start_at)}` : "Démarrage dès que possible",
        { description: r.moved ? `${r.moved} premier${r.moved > 1 ? "s" : ""} email${r.moved > 1 ? "s" : ""} replanifié${r.moved > 1 ? "s" : ""}.` : undefined });
      onOpenChange(false);
      onDone();
    },
    onError: (e) => toastError(e),
  });
  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (o) setValue(current); }}>
      <DialogContent>
        <DialogHeader><DialogTitle>Démarrage de la campagne</DialogTitle></DialogHeader>
        {open && <StartPicker value={current} onChange={setValue} />}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Annuler</Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending}>Enregistrer</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
