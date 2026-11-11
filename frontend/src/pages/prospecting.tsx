// V3.7 : « Trouver des prospects ». Formulaire (pas d'IA) qui interroge looot avec la clé de l'administrateur :
// aperçu payant d'une page (≈ 0,04 $), puis recherche des emails en tâche de fond, importés dans une liste.
// Réservé à l'administrateur ; le plafond de dépense est le crédit chargé sur le compte looot.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, CircleSlash, KeyRound, Loader2, MoreHorizontal, Rocket, Search, Square, Users, Wallet } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { EmptyState, PageHeader, toastError } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type ProspectCriteria, type ProspectOption, type ProspectSearch } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useMe } from "@/pages/login";

const usd = (n: number) => `${n.toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} $`;
const STATUS: Record<ProspectSearch["status"], { label: string; variant: "secondary" | "outline" | "info" | "success" | "destructive" }> = {
  preview: { label: "Aperçu", variant: "outline" }, running: { label: "En cours", variant: "info" }, done: { label: "Terminée", variant: "success" },
  stopped: { label: "Arrêtée", variant: "secondary" }, failed: { label: "En échec", variant: "destructive" },
};

function Chips({ label, hint, options, value, onChange, small }: { label: string; hint?: string; options: ProspectOption[]; value: string[]; onChange: (v: string[]) => void; small?: boolean }) {
  const toggle = (v: string) => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v]);
  return (
    <fieldset className="space-y-2">
      <legend className={cn("font-medium", small ? "text-xs" : "text-sm")}>{label}{hint && <span className="ml-1.5 font-normal text-muted-foreground">{hint}</span>}</legend>
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => {
          const on = value.includes(o.value);
          return (
            <button key={o.value} type="button" aria-pressed={on} onClick={() => toggle(o.value)}
              className={cn("rounded-full border transition-colors", small ? "px-2.5 py-0.5 text-xs" : "px-3 py-1 text-sm",
                on ? "border-primary bg-primary text-primary-foreground" : "bg-background hover:bg-muted")}>
              {o.label}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

function KeyCard({ onSaved, compact }: { onSaved: () => void; compact?: boolean }) {
  const [key, setKey] = useState("");
  const save = useMutation({
    mutationFn: () => api.prospectingSetKey(key.trim()),
    onSuccess: (r) => { setKey(""); toast.success(`Clé looot enregistrée · crédit disponible : ${usd(r.balance)}`); onSaved(); },
    onError: (e) => toastError(e, "Clé refusée"),
  });
  return (
    <Card className={cn("space-y-3 p-5", compact && "border-dashed")}>
      <div className="flex items-start gap-3">
        <KeyRound className="mt-0.5 size-5 text-muted-foreground" />
        <div className="space-y-1">
          <div className="font-medium">Reliez votre compte looot</div>
          <p className="text-sm text-muted-foreground">
            Collez une clé d'API looot. Elle est vérifiée, gardée chiffrée sur le serveur et n'est plus jamais réaffichée.
            Vous ne dépensez que le crédit chargé sur looot : c'est votre plafond. Vous pouvez aussi fixer une limite à la clé dans les réglages de looot.
          </p>
        </div>
      </div>
      <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (key.trim().length >= 10) save.mutate(); }}>
        <Input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} placeholder="Clé d'API looot" aria-label="Clé d'API looot" className="max-w-sm flex-1" />
        <Button disabled={key.trim().length < 10 || save.isPending}>{save.isPending ? <Loader2 className="animate-spin" /> : <KeyRound />} Vérifier et enregistrer</Button>
      </form>
    </Card>
  );
}

function Counters({ s }: { s: ProspectSearch }) {
  const items = [
    ["Profils examinés", s.checked], ["Emails trouvés", s.emails_found], ["Importés", s.imported],
    ["Déjà connus", s.skipped_existing], ["Sans email", s.skipped_no_email], ["Exclus", s.skipped_excluded],
  ] as const;
  return (
    <dl className="grid grid-cols-3 gap-3 sm:grid-cols-6">
      {items.map(([l, v]) => (
        <div key={l}><dt className="text-xs text-muted-foreground">{l}</dt><dd className="text-lg font-semibold tabular">{v}</dd></div>
      ))}
    </dl>
  );
}

function Preview({ s, onDone }: { s: ProspectSearch; onDone: (s: ProspectSearch | null) => void }) {
  const [wanted, setWanted] = useState(s.wanted);
  const est = s.estimate!;
  const ratio = est.findable_ratio;
  const cost = Math.max(0, Math.ceil(wanted / Math.max(0.01, 25 * ratio * 0.85)) - 1) * 0.039 + Math.min(wanted, est.reachable) * 0.006;
  const start = useMutation({ mutationFn: () => api.prospectingStart(s.id, wanted), onSuccess: (r) => { onDone(r); toast.success("Recherche lancée : elle continue même si vous quittez la page"); }, onError: (e) => toastError(e) });
  const cancel = useMutation({ mutationFn: () => api.prospectingStop(s.id), onSuccess: () => onDone(null) });
  return (
    <Card className="space-y-4 p-5">
      <div>
        <div className="text-sm text-muted-foreground">{s.summary}</div>
        <div className="mt-1 text-2xl font-semibold tabular">{(s.total_found ?? 0).toLocaleString("fr-FR")} profils trouvés</div>
        <p className="mt-1 text-sm text-muted-foreground">
          Sur ce premier échantillon, {Math.round(ratio * 100)} % ont un email vérifiable : environ <b className="text-foreground">{est.reachable.toLocaleString("fr-FR")}</b> contacts joignables au total.
          Aperçu payé : {usd(s.cost_usd)}.
        </p>
      </div>
      {!!s.sample?.length && (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs text-muted-foreground"><tr>
              <th className="px-3 py-2 font-medium">Nom</th><th className="px-3 py-2 font-medium">Poste</th><th className="px-3 py-2 font-medium">Entreprise</th>
              <th className="px-3 py-2 font-medium">Ville</th><th className="px-3 py-2 font-medium">Email</th>
            </tr></thead>
            <tbody className="divide-y">
              {s.sample.map((p, i) => (
                <tr key={i}>
                  <td className="whitespace-nowrap px-3 py-2">{p.first} {p.last}</td>
                  <td className="px-3 py-2 text-muted-foreground">{p.title}</td>
                  <td className="px-3 py-2">{p.company}<div className="text-xs text-muted-foreground">{[p.industry, p.size && `${p.size} sal.`].filter(Boolean).join(" · ")}</div></td>
                  <td className="px-3 py-2 text-muted-foreground">{p.city}</td>
                  <td className="px-3 py-2">{p.findable ? <span className="inline-flex items-center gap-1 text-success"><CheckCircle2 className="size-3.5" /> trouvable</span>
                    : <span className="inline-flex items-center gap-1 text-muted-foreground"><CircleSlash className="size-3.5" /> non</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="wanted">Combien de contacts importer ?</Label>
          <Input id="wanted" type="number" min={1} max={500} value={wanted} onChange={(e) => setWanted(Math.max(1, Math.min(500, Number(e.target.value) || 1)))} className="w-28" />
        </div>
        <div className="pb-2 text-sm text-muted-foreground">Coût estimé : <b className="text-foreground">≈ {usd(cost)}</b> <span className="text-xs">(on ne paie que les emails trouvés)</span></div>
        <div className="ml-auto flex gap-2">
          <Button variant="outline" onClick={() => cancel.mutate()} disabled={cancel.isPending}>Abandonner</Button>
          <Button onClick={() => start.mutate()} disabled={start.isPending || !est.reachable}><Rocket /> Lancer la recherche</Button>
        </div>
      </div>
    </Card>
  );
}

function Running({ id }: { id: number }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data: s } = useQuery({
    queryKey: ["prospecting", id], queryFn: () => api.prospectingGet(id),
    refetchInterval: (q) => (q.state.data?.status === "running" ? 3000 : false),
  });
  const status = s?.status;
  useEffect(() => {  // le crédit looot baisse pendant la recherche : on le relit à chaque étape
    if (status) qc.invalidateQueries({ queryKey: ["prospecting-balance"] });
  }, [status, s?.imported, qc]);
  const stop = useMutation({ mutationFn: () => api.prospectingStop(id), onSuccess: () => { qc.invalidateQueries({ queryKey: ["prospecting"] }); } });
  if (!s) return <Skeleton className="h-40 rounded-xl" />;
  const running = s.status === "running";
  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 font-medium">{running && <Loader2 className="size-4 animate-spin text-primary" />}{s.summary}</div>
          <div className="text-sm text-muted-foreground">{s.imported} / {s.wanted} contacts importés · dépensé : {usd(s.cost_usd)}</div>
        </div>
        <Badge variant={STATUS[s.status].variant}>{STATUS[s.status].label}</Badge>
        {running && <Button size="sm" variant="outline" onClick={() => stop.mutate()} disabled={stop.isPending}><Square /> Arrêter</Button>}
      </div>
      <Progress value={(s.imported / Math.max(1, s.wanted)) * 100} />
      <Counters s={s} />
      {s.error && !running && <p className="text-sm text-muted-foreground">{s.error}</p>}
      {s.list_id && (
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" asChild><Link to={`/contacts?list_id=${s.list_id}`}><Users /> Voir les {s.imported} contacts</Link></Button>
          {!running && <Button onClick={() => navigate(`/campaigns/new?list_id=${s.list_id}`)}><Rocket /> Créer une campagne pour eux</Button>}
        </div>
      )}
    </Card>
  );
}

export function ProspectingPage() {
  const me = useMe();
  const qc = useQueryClient();
  const { data, refetch } = useQuery({ queryKey: ["prospecting"], queryFn: api.prospecting });
  const { data: bal } = useQuery({ queryKey: ["prospecting-balance"], queryFn: api.prospectingBalance, enabled: !!data?.configured, retry: false });
  const [c, setC] = useState<ProspectCriteria>({ functions: [], sectors: [], details: [], cities: [], sizes: [], wanted: 50 });
  const [current, setCurrent] = useState<ProspectSearch | null>(null);
  const [changingKey, setChangingKey] = useState(false);
  const preview = useMutation({ mutationFn: () => api.prospectingPreview(c), onSuccess: (r) => { setCurrent(r); refetch(); qc.invalidateQueries({ queryKey: ["prospecting-balance"] }); }, onError: (e) => toastError(e, "Aperçu impossible") });
  const dropKey = useMutation({ mutationFn: api.prospectingDeleteKey, onSuccess: () => { refetch(); toast.success("Clé looot retirée"); } });

  if (me && me.server_mode && me.role !== "admin") {
    return <EmptyState icon={Search} title="Réservé à l'administrateur" text="La recherche de prospects dépense le crédit looot : seul l'administrateur peut la lancer." />;
  }
  const opts = data?.options;
  const history = (data?.items ?? []).filter((s) => s.status !== "preview" && s.id !== current?.id);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["prospecting"] }); setChangingKey(false); };

  return (
    <>
      <PageHeader title="Trouver des prospects" back={<Button variant="ghost" size="sm" className="-ml-2" asChild><Link to="/contacts"><ArrowLeft /> Contacts</Link></Button>}
        description="Choisissez une cible : l'application cherche les profils, trouve leurs emails et les importe dans une liste, prête pour une campagne."
        actions={data?.configured && <>
          <Badge variant="secondary" className="h-8 gap-1.5 px-3 text-sm font-normal"><Wallet className="size-3.5" /> Crédit looot : {bal ? usd(bal.balance) : "…"}</Badge>
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button size="icon" variant="ghost" aria-label="Réglages looot"><MoreHorizontal /></Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => setChangingKey(true)}><KeyRound /> Changer de clé looot</DropdownMenuItem>
              <DropdownMenuItem className="text-destructive" onSelect={() => dropKey.mutate()}>Retirer la clé</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </>} />
      {!data || !opts ? <Skeleton className="h-72 rounded-xl" /> : (
        <div className="space-y-5">
          {(!data.configured || changingKey) && <KeyCard onSaved={refresh} compact={changingKey} />}
          {data.configured && !current && (
            <Card className="space-y-5 p-5">
              <Chips label="Fonction" hint="(au moins une)" options={opts.functions} value={c.functions} onChange={(v) => setC({ ...c, functions: v })} />
              <Chips label="Secteur" hint="(aucun = tous)" options={opts.sectors} value={c.sectors}
                onChange={(v) => setC({ ...c, sectors: v, details: (c.details ?? []).filter((d) => v.includes(d.split(".")[0])) })} />
              {opts.sectors.filter((s) => c.sectors.includes(s.value)).map((s) => (
                <div key={s.value} className="ml-4 border-l-2 pl-4">
                  <Chips label={`Préciser « ${s.label} »`} hint="(rien de coché = tout le secteur)" options={s.details} value={c.details ?? []}
                    onChange={(v) => setC({ ...c, details: v })} small />
                </div>
              ))}
              <Chips label="Ville" hint="(aucune = tout le Maroc)" options={opts.cities.map((x) => ({ value: x, label: x }))} value={c.cities} onChange={(v) => setC({ ...c, cities: v })} />
              <Chips label="Taille de l'entreprise" hint="(aucune = toutes)" options={opts.sizes} value={c.sizes} onChange={(v) => setC({ ...c, sizes: v })} />
              <div className="flex flex-wrap items-center gap-3 border-t pt-4">
                <Button onClick={() => preview.mutate()} disabled={!c.functions.length || preview.isPending}>
                  {preview.isPending ? <Loader2 className="animate-spin" /> : <Search />} Voir un aperçu
                </Button>
                <span className="text-sm text-muted-foreground">L'aperçu coûte {usd(opts.page_cost)} et montre combien de profils correspondent. Rien n'est importé avant que vous lanciez.</span>
              </div>
            </Card>
          )}
          {current?.status === "preview" && <Preview s={current} onDone={(r) => { setCurrent(r); refetch(); }} />}
          {current && current.status !== "preview" && <Running id={current.id} />}
          {current && current.status !== "preview" && <Button variant="ghost" onClick={() => { setCurrent(null); refetch(); }}><Search /> Nouvelle recherche</Button>}
          {history.length > 0 && (
            <section className="space-y-2">
              <h2 className="text-sm font-medium text-muted-foreground">Recherches précédentes</h2>
              <Card className="divide-y">
                {history.map((s) => (
                  <button key={s.id} type="button" onClick={() => setCurrent(s)} className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3 text-left hover:bg-muted/40">
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">{s.summary}</div>
                      <div className="text-xs text-muted-foreground">
                        {s.created_at && new Date(s.created_at).toLocaleDateString("fr-FR")} · {s.imported} importé{s.imported > 1 ? "s" : ""} sur {s.wanted} · {usd(s.cost_usd)}
                      </div>
                    </div>
                    <Badge variant={STATUS[s.status].variant}>{STATUS[s.status].label}</Badge>
                  </button>
                ))}
              </Card>
            </section>
          )}
        </div>
      )}
    </>
  );
}
