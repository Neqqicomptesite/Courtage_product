// V3.10 : portefeuille clients (export DIAMM). Tableau de bord, opportunités de vente croisée,
// clients (filtres, fiche, appels) et rappels. Commun à toute l'équipe ; l'import est réservé à
// l'administrateur. Un client sans email se travaille au téléphone (liste d'appels) ; avec email,
// il est aussi un contact « client » pour les campagnes (gestion ou souscription).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, Briefcase, Building2, CalendarClock, ListPlus, Loader2, Mail, Phone, PhoneCall, Search, Send, Upload, User, Users,
} from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { EmptyState, PageHeader, toastError, useUrlState } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { api, type PfDetail, type PfOpportunity, type PfRow, type PfSummary } from "@/lib/api";
import { formatDayTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useMe } from "@/pages/login";

const n = (x: number | null | undefined) => (x ?? 0).toLocaleString("fr-FR");
const pct = (a: number, b: number) => (b ? Math.round((100 * a) / b) : 0);
const SEG: Record<string, string> = { particulier: "Particuliers", pro: "Entreprises" };
const SEG1: Record<string, string> = { particulier: "Particulier", pro: "Entreprise" };
const OUTCOMES: { value: string; label: string; tone: string }[] = [
  { value: "interested", label: "Intéressé", tone: "border-success/50 text-success" },
  { value: "callback", label: "À rappeler", tone: "border-warning/50 text-warning" },
  { value: "not_interested", label: "Pas intéressé", tone: "" },
  { value: "no_answer", label: "Pas de réponse", tone: "" },
  { value: "wrong_number", label: "Mauvais numéro", tone: "" },
  { value: "done", label: "Traité", tone: "" },
];
const dayISO = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const fmtDay = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" });

type View = "tableau" | "opportunites" | "clients" | "rappels";

export function PortfolioPage() {
  const me = useMe();
  const admin = !me || !me.server_mode || me.role === "admin";
  const [view, setView] = useUrlState<View>("vue", "tableau");
  const [params, setParams] = useSearchParams();
  const openId = params.get("client") ? Number(params.get("client")) : null;
  const setOpen = (id: number | null) => {
    const p = new URLSearchParams(params);
    if (id) p.set("client", String(id)); else p.delete("client");
    setParams(p, { replace: true });
  };
  const [importing, setImporting] = useState(false);
  const { data, isLoading } = useQuery({ queryKey: ["pf-summary"], queryFn: api.pfSummary });
  const goClients = (f: Record<string, string>) => {
    const p = new URLSearchParams();
    p.set("vue", "clients");
    Object.entries(f).forEach(([k, v]) => v && p.set(k, v));
    setParams(p);
  };

  const tabs: { key: View; label: string; badge?: number }[] = [
    { key: "tableau", label: "Tableau de bord" },
    { key: "opportunites", label: "Vente croisée" },
    { key: "clients", label: "Clients" },
    { key: "rappels", label: "À rappeler", badge: data?.callbacks_due },
  ];
  return (
    <>
      <PageHeader title="Portefeuille"
        description={data?.clients ? <>Export DIAMM du {data.imported_at ? formatDayTime(data.imported_at) : "—"} · {n(data.active_clients)} clients, {n(data.contracts)} contrats en cours. Visible par toute l'équipe.</>
          : "Vos clients, leurs contrats, et ce qu'on peut leur proposer."}
        actions={admin && <Button variant={data?.clients ? "outline" : "default"} onClick={() => setImporting(true)}><Upload /> Importer l'export DIAMM</Button>} />
      {isLoading ? <Skeleton className="h-96 rounded-xl" /> : !data?.clients ? (
        <EmptyState icon={Briefcase} title="Aucun portefeuille importé"
          text={admin ? "Importez l'export du portefeuille DIAMM (.xls, .xlsx ou .csv), tel quel : une ligne par police."
            : "L'administrateur importe l'export DIAMM ; il apparaîtra ici pour toute l'équipe."}
          action={admin && <Button onClick={() => setImporting(true)}><Upload /> Importer l'export DIAMM</Button>} />
      ) : (
        <>
          <div className="mb-4 flex gap-6 overflow-x-auto border-b" role="tablist">
            {tabs.map((t) => (
              <button key={t.key} role="tab" aria-selected={view === t.key} onClick={() => setView(t.key)}
                className={cn("inline-flex shrink-0 items-center gap-2 border-b-2 px-1 pb-2.5 text-sm transition-colors",
                  view === t.key ? "border-primary font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
                {t.label}
                {!!t.badge && <span className="rounded-full bg-warning/15 px-1.5 text-[11px] font-semibold text-warning tabular">{t.badge}</span>}
              </button>
            ))}
          </div>
          {view === "tableau" && <Dashboard d={data} onFilter={goClients} onOpen={setOpen} />}
          {view === "opportunites" && <Opportunities d={data} onFilter={goClients} />}
          {view === "clients" && <Clients d={data} onOpen={setOpen} />}
          {view === "rappels" && <Callbacks onOpen={setOpen} />}
        </>
      )}
      <ImportDialog open={importing} onOpenChange={setImporting} />
      <ClientDialog id={openId} rule={params.get("rule")} onClose={() => setOpen(null)} />
    </>
  );
}

/* ================================================================ tableau de bord */

function Tile({ icon, label, value, foot }: { icon: ReactNode; label: string; value: ReactNode; foot?: ReactNode }) {
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">{icon}{label}</div>
      <div className="mt-2 text-2xl font-semibold tracking-tight tabular">{value}</div>
      {foot && <div className="mt-1 text-xs text-muted-foreground">{foot}</div>}
    </Card>
  );
}

/** Une barre horizontale (une seule couleur : la grandeur), avec sa valeur en clair. */
function Bar({ value, max, label, onClick, title }: { value: number; max: number; label: ReactNode; onClick?: () => void; title?: string }) {
  const w = max ? Math.max(value ? 2 : 0, (100 * value) / max) : 0;
  const inner = (
    <>
      <span className="relative block h-2 flex-1 overflow-hidden rounded-full bg-muted">
        <span className="absolute inset-y-0 left-0 rounded-full bg-primary/80" style={{ width: `${w}%` }} />
      </span>
      <span className="w-24 shrink-0 text-right text-xs tabular text-muted-foreground">{label}</span>
    </>
  );
  return onClick
    ? <button type="button" onClick={onClick} title={title} className="flex w-full items-center gap-3 rounded-md px-1 py-1 text-left hover:bg-accent/50">{inner}</button>
    : <div className="flex items-center gap-3 px-1 py-1" title={title}>{inner}</div>;
}

function Dashboard({ d, onFilter, onOpen }: { d: PfSummary; onFilter: (f: Record<string, string>) => void; onOpen: (id: number) => void }) {
  const p = d.segments.particulier, e = d.segments.pro;
  const mono = p.mono + e.mono;
  const maxIns = Math.max(1, ...d.insurers.map((x) => x.contracts));
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile icon={<Users className="size-3.5" />} label="Clients" value={n(d.active_clients)}
          foot={<>{n(p.count)} particuliers · {n(e.count)} entreprises</>} />
        <Tile icon={<Briefcase className="size-3.5" />} label="Contrats en cours" value={n(d.contracts)}
          foot={<>{(d.contracts / Math.max(1, d.active_clients)).toFixed(1).replace(".", ",")} par client · {n(d.cancelled)} résiliés</>} />
        <Tile icon={<AlertTriangle className="size-3.5" />} label="Un seul produit chez le cabinet" value={`${pct(mono, d.active_clients)} %`}
          foot={<>{pct(p.mono, p.count)} % des particuliers · {pct(e.mono, e.count)} % des entreprises</>} />
        <Tile icon={<PhoneCall className="size-3.5" />} label="Joignables" value={<span className="text-xl">{n(d.reach.phone)} <span className="text-sm font-normal text-muted-foreground">par téléphone</span></span>}
          foot={<>{n(d.reach.email)} par email ({pct(d.reach.email, d.active_clients)} %) · dont {n(p.email)} particuliers</>} />
      </div>
      {(d.premium_total != null || d.due_60 > 0) && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {d.premium_total != null && <Tile icon={<Briefcase className="size-3.5" />} label="Primes en cours" value={`${n(Math.round(d.premium_total))} MAD`} />}
          {d.due_60 > 0 && <Tile icon={<CalendarClock className="size-3.5" />} label="Échéances dans 60 jours" value={n(d.due_60)} />}
        </div>
      )}
      {d.reach.email < d.active_clients / 3 && (
        <p className="flex items-start gap-2 rounded-xl border border-warning/40 bg-warning/5 p-3 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
          Seuls {n(d.reach.email)} clients sur {n(d.active_clients)} ont un email dans DIAMM. La vente croisée passera surtout par le téléphone :
          notez l'email pendant l'appel, le client devient alors joignable par les campagnes.
        </p>
      )}
      <Card>
        <CardHeader>
          <CardTitle>Équipement par famille</CardTitle>
          <CardDescription>Part des clients qui ont au moins un contrat en cours dans la famille. Un clic : la liste des clients.</CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full min-w-[34rem] text-sm">
            <thead><tr className="text-left text-xs text-muted-foreground">
              <th className="pb-2 font-medium">Famille</th>
              <th className="w-[38%] pb-2 font-medium">Particuliers ({n(p.count)})</th>
              <th className="w-[38%] pb-2 font-medium">Entreprises ({n(e.count)})</th>
            </tr></thead>
            <tbody>
              {d.families.map((f) => (
                <tr key={f.family} className="border-t">
                  <td className="py-1.5 pr-3">{f.family}</td>
                  {(["particulier", "pro"] as const).map((k) => (
                    <td key={k} className="py-1 pr-3">
                      <Bar value={f[k].pct} max={100} label={f[k].clients ? `${f[k].pct} % · ${n(f[k].clients)}` : "—"}
                        onClick={f[k].clients ? () => onFilter({ segment: k, has: f.family }) : undefined}
                        title={`${SEG[k]} avec ${f.family}`} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Familles détenues par client</CardTitle>
            <CardDescription>Combien de familles différentes chaque client a chez le cabinet.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-5 sm:grid-cols-2">
            {(["particulier", "pro"] as const).map((k) => {
              const rows = d.families_per_client[k] ?? {};
              const max = Math.max(1, ...Object.values(rows));
              return (
                <div key={k}>
                  <p className="mb-1 text-xs font-medium text-muted-foreground">{SEG[k]}</p>
                  {Object.entries(rows).map(([nb, count]) => (
                    <div key={nb} className="flex items-center gap-2">
                      <span className="w-14 shrink-0 text-xs">{nb === "6" ? "6 et +" : `${nb} famille${nb === "1" ? "" : "s"}`}</span>
                      <div className="flex-1"><Bar value={count} max={max} label={n(count)} /></div>
                    </div>
                  ))}
                </div>
              );
            })}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Compagnies</CardTitle>
            <CardDescription>Contrats en cours par compagnie.</CardDescription>
          </CardHeader>
          <CardContent>
            {d.insurers.slice(0, 10).map((x) => (
              <div key={x.insurer} className="flex items-center gap-2">
                <span className="w-40 shrink-0 truncate text-xs" title={x.insurer}>{x.insurer}</span>
                <div className="flex-1"><Bar value={x.contracts} max={maxIns} label={`${n(x.contracts)} · ${n(x.clients)} cl.`} title={`${x.clients} clients`} /></div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader><CardTitle>Principaux clients</CardTitle><CardDescription>Ceux qui ont le plus de contrats en cours.</CardDescription></CardHeader>
        <CardContent className="divide-y p-0">
          {d.top_clients.map((c) => (
            <button key={c.id} onClick={() => onOpen(c.id)} className="flex w-full items-center gap-3 px-6 py-2.5 text-left text-sm hover:bg-accent/40">
              {c.segment === "pro" ? <Building2 className="size-4 text-muted-foreground" /> : <User className="size-4 text-muted-foreground" />}
              <span className="min-w-0 flex-1 truncate">{c.name}</span>
              <span className="text-xs text-muted-foreground tabular">{c.contracts} contrats · {c.families} familles</span>
            </button>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

/* ================================================================ vente croisée */

function Opportunities({ d, onFilter }: { d: PfSummary; onFilter: (f: Record<string, string>) => void }) {
  const [making, setMaking] = useState<PfOpportunity | null>(null);
  const groups = (["particulier", "pro"] as const).map((k) => ({ k, items: d.opportunities.filter((o) => o.segment === k) }));  // ordre métier (les plus parlantes d'abord)
  return (
    <div className="space-y-6">
      <p className="text-sm text-muted-foreground">
        D'après les contrats placés chez le cabinet : le client a peut-être la garantie ailleurs, c'est l'occasion d'une mise en concurrence.
        Au téléphone, « Appeler » ouvre la liste d'appels (jamais appelés d'abord) ; par email, « Créer la liste » puis une séquence
        de <b>gestion</b> ou de <b>souscription</b> (la prospection n'est jamais envoyée aux clients).
      </p>
      {groups.map(({ k, items }) => (
        <section key={k} className="space-y-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold">{k === "pro" ? <Building2 className="size-4" /> : <User className="size-4" />}{SEG[k]}</h2>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {items.map((o) => (
              <Card key={o.key} className="flex flex-col p-4">
                <div className="flex items-baseline justify-between gap-3">
                  <p className="font-medium leading-snug">{o.label}</p>
                  <span className="text-2xl font-semibold tabular">{n(o.count)}</span>
                </div>
                <p className="mt-1 text-sm text-muted-foreground">{o.pitch}</p>
                <p className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1"><Phone className="size-3" />{n(o.phone)} avec téléphone</span>
                  <span className="inline-flex items-center gap-1"><Mail className="size-3" />{n(o.email)} avec email</span>
                </p>
                {o.called > 0 && (
                  <div className="mt-2">
                    <Bar value={o.called} max={o.count} label={`${n(o.called)} appelés`} />
                    <p className="text-xs text-success">{n(o.interested)} intéressé{o.interested > 1 ? "s" : ""}</p>
                  </div>
                )}
                <div className="mt-auto flex flex-wrap gap-2 pt-3">
                  <Button size="sm" onClick={() => onFilter({ rule: o.key, appel: "1", joignable: "phone" })} disabled={!o.phone}><PhoneCall /> Appeler ({n(o.phone)})</Button>
                  <Button size="sm" variant="outline" onClick={() => setMaking(o)} disabled={!o.email}><ListPlus /> Créer la liste ({n(o.email)})</Button>
                </div>
              </Card>
            ))}
          </div>
        </section>
      ))}
      <MakeListDialog opp={making} onClose={() => setMaking(null)} />
    </div>
  );
}

function MakeListDialog({ opp, filters, count, onClose }: { opp: PfOpportunity | null; filters?: Record<string, string>; count?: number; onClose: () => void }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const open = !!opp || !!filters;
  const [name, setName] = useState("");
  useEffect(() => {
    if (open) setName(opp ? `Clients · ${opp.label} · ${new Date().toLocaleDateString("fr-FR")}` : `Clients · sélection du ${new Date().toLocaleDateString("fr-FR")}`);
  }, [open, opp]);
  const make = useMutation({
    mutationFn: () => api.pfList({ name: name.trim(), ...(opp ? { rule: opp.key } : filters) }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["lists"] });
      onClose();
      toast.success(`Liste créée : ${r.added} client${r.added > 1 ? "s" : ""} avec email`, {
        description: r.without_email ? `${r.without_email} sans email : à travailler par téléphone.` : undefined,
        action: { label: "Envoyer une séquence", onClick: () => navigate(`/contacts?list_id=${r.list_id}`) },
      });
    },
    onError: (e) => toastError(e, "Liste non créée"),
  });
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Créer la liste pour une campagne</DialogTitle>
          <DialogDescription>
            {opp ? <>Les {n(opp.email)} clients « {opp.label} » qui ont un email.</> : <>Les {n(count)} clients filtrés qui ont un email.</>}
            {" "}Ensuite : page de la liste → « Envoyer une séquence », avec une séquence de gestion ou de souscription.
          </DialogDescription>
        </DialogHeader>
        <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} aria-label="Nom de la liste" />
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Annuler</Button>
          <Button disabled={!name.trim() || make.isPending} onClick={() => make.mutate()}>{make.isPending ? <Loader2 className="animate-spin" /> : <ListPlus />} Créer la liste</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ================================================================ clients */

function Clients({ d, onOpen }: { d: PfSummary; onOpen: (id: number) => void }) {
  const [q, setQ] = useUrlState<string>("q", "");
  const [segment, setSegment] = useUrlState<string>("segment", "");
  const [has, setHas] = useUrlState<string>("has", "");
  const [lacks, setLacks] = useUrlState<string>("lacks", "");
  const [rule, setRule] = useUrlState<string>("rule", "");
  const [reach, setReach] = useUrlState<string>("joignable", "");
  const [called, setCalled] = useUrlState<string>("appele", "");
  const [callMode] = useUrlState<string>("appel", "");
  const [limit, setLimit] = useState(100);
  const [making, setMaking] = useState(false);
  const filters = { q, segment, has, lacks, rule, reach, called };
  const calls = callMode === "1" || !!rule;
  const { data, isFetching } = useQuery({
    queryKey: ["pf-clients", filters, limit, calls],
    queryFn: () => api.pfClients({ ...filters, calls_first: calls, limit }),
    placeholderData: (p) => p,
  });
  const opp = d.opportunities.find((o) => o.key === rule);
  const any = Object.values(filters).some(Boolean);
  return (
    <div className="space-y-3">
      {opp && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-primary/30 bg-primary/5 p-3 text-sm">
          <PhoneCall className="size-4 text-primary" />
          <span className="flex-1"><b>Liste d'appels : {SEG1[opp.segment ?? ""] ?? ""} · {opp.label}</b> — {opp.pitch}. Jamais appelés d'abord ; notez le résultat sur la fiche.</span>
          <Button size="sm" variant="ghost" onClick={() => setRule("")}>Quitter la liste</Button>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <div className="relative min-w-[14rem] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-9" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Nom, email ou n° de police…" />
        </div>
        <NativeSelect className="w-auto" value={segment} onChange={(e) => setSegment(e.target.value)} aria-label="Segment">
          <option value="">Particuliers et entreprises</option><option value="particulier">Particuliers</option><option value="pro">Entreprises</option>
        </NativeSelect>
        <NativeSelect className="w-auto" value={has} onChange={(e) => setHas(e.target.value)} aria-label="A la famille">
          <option value="">A : toutes familles</option>
          {d.all_families.map((f) => <option key={f} value={f}>A : {f}</option>)}
        </NativeSelect>
        <NativeSelect className="w-auto" value={lacks} onChange={(e) => setLacks(e.target.value)} aria-label="N'a pas la famille">
          <option value="">N'a pas : —</option>
          {d.all_families.map((f) => <option key={f} value={f}>N'a pas : {f}</option>)}
        </NativeSelect>
        <NativeSelect className="w-auto" value={reach} onChange={(e) => setReach(e.target.value)} aria-label="Joignable">
          <option value="">Joignables ou non</option><option value="email">Avec email</option><option value="phone">Avec téléphone</option>
          <option value="phone_only">Téléphone, sans email</option>
        </NativeSelect>
        <NativeSelect className="w-auto" value={called} onChange={(e) => setCalled(e.target.value)} aria-label="Appelé">
          <option value="">Appelés ou non</option><option value="never">Jamais appelés</option><option value="yes">Déjà appelés</option>
        </NativeSelect>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
        <span><b className="text-foreground tabular">{n(data?.total)}</b> client{(data?.total ?? 0) > 1 ? "s" : ""} · {n(data?.phone)} avec téléphone · {n(data?.email)} avec email</span>
        {isFetching && <Loader2 className="size-4 animate-spin" />}
        <span className="flex-1" />
        {any && <Button size="sm" variant="ghost" onClick={() => { setQ(""); setSegment(""); setHas(""); setLacks(""); setRule(""); setReach(""); setCalled(""); }}>Effacer les filtres</Button>}
        <Button size="sm" variant="outline" disabled={!data?.email} onClick={() => setMaking(true)}><ListPlus /> Créer la liste ({n(data?.email)} avec email)</Button>
      </div>
      <Card className="overflow-hidden">
        <div className="hidden overflow-x-auto md:block">
          <table className="w-full text-sm">
            <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
              <tr><th className="px-4 py-2 font-medium">Client</th><th className="px-4 py-2 font-medium">Familles</th>
                <th className="px-4 py-2 font-medium">Contrats</th><th className="px-4 py-2 font-medium">Joindre</th><th className="px-4 py-2 font-medium">Dernier appel</th></tr>
            </thead>
            <tbody className="divide-y">
              {data?.items.map((c) => <ClientRow key={c.id} c={c} onOpen={onOpen} />)}
            </tbody>
          </table>
        </div>
        <div className="divide-y md:hidden">
          {data?.items.map((c) => (
            <button key={c.id} onClick={() => onOpen(c.id)} className="block w-full px-4 py-3 text-left">
              <p className="font-medium">{c.name}</p>
              <p className="text-xs text-muted-foreground">{SEG1[c.segment]} · {c.contracts} contrat{c.contracts > 1 ? "s" : ""} · {c.families.join(", ")}</p>
              <p className="text-xs text-muted-foreground">{c.phone ?? "sans téléphone"}{c.email ? ` · ${c.email}` : ""}{c.last_call ? ` · ${c.last_call.label}` : ""}</p>
            </button>
          ))}
        </div>
        {data && data.items.length === 0 && <p className="p-8 text-center text-sm text-muted-foreground">Aucun client ne correspond.</p>}
      </Card>
      {data && data.total > data.items.length && (
        <div className="text-center"><Button variant="outline" onClick={() => setLimit((l) => l + 200)}>Afficher plus ({n(data.total - data.items.length)} restants)</Button></div>
      )}
      <MakeListDialog opp={null} filters={making ? filters : undefined} count={data?.email} onClose={() => setMaking(false)} />
    </div>
  );
}

function ClientRow({ c, onOpen }: { c: PfRow; onOpen: (id: number) => void }) {
  return (
    <tr className="cursor-pointer hover:bg-accent/30" onClick={() => onOpen(c.id)}>
      <td className="px-4 py-2.5">
        <p className="font-medium">{c.name}</p>
        <p className="text-xs text-muted-foreground">{SEG1[c.segment]}{c.cancelled ? ` · ${c.cancelled} résilié${c.cancelled > 1 ? "s" : ""}` : ""}</p>
      </td>
      <td className="px-4 py-2.5">
        <div className="flex max-w-[22rem] flex-wrap gap-1">
          {c.families.slice(0, 4).map((f) => <Badge key={f} variant="secondary" className="font-normal">{f}</Badge>)}
          {c.families.length > 4 && <span className="text-xs text-muted-foreground">+{c.families.length - 4}</span>}
        </div>
      </td>
      <td className="px-4 py-2.5 tabular">{c.contracts}</td>
      <td className="px-4 py-2.5 text-xs" onClick={(e) => e.stopPropagation()}>
        {c.phone ? <a href={`tel:${c.phone.replace(/[^\d+]/g, "")}`} className="inline-flex items-center gap-1 text-primary hover:underline"><Phone className="size-3" />{c.phone}</a>
          : <span className="text-muted-foreground">—</span>}
        {c.email && <p className="mt-0.5 flex items-center gap-1 text-muted-foreground"><Mail className="size-3" />{c.email}</p>}
      </td>
      <td className="px-4 py-2.5 text-xs">
        {c.last_call ? <><span className={cn(c.last_call.outcome === "interested" && "text-success", c.last_call.outcome === "callback" && "text-warning")}>{c.last_call.label}</span>
          <span className="block text-muted-foreground">{c.last_call.at ? formatDayTime(c.last_call.at) : ""}{c.last_call.by ? ` · ${c.last_call.by}` : ""}</span></>
          : <span className="text-muted-foreground">Jamais appelé</span>}
      </td>
    </tr>
  );
}

/* ================================================================ fiche client + appel */

function ClientDialog({ id, rule, onClose }: { id: number | null; rule: string | null; onClose: () => void }) {
  const qc = useQueryClient();
  const { data: c, isLoading } = useQuery({ queryKey: ["pf-client", id], queryFn: () => api.pfClient(id!), enabled: !!id });
  const [outcome, setOutcome] = useState<string>("");
  const [note, setNote] = useState("");
  const [when, setWhen] = useState("");
  const [email, setEmail] = useState("");
  const noteRef = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { setOutcome(""); setNote(""); setEmail(""); const t = new Date(); t.setDate(t.getDate() + 1); setWhen(dayISO(t)); }, [id]);
  const refresh = (d: PfDetail) => {
    qc.setQueryData(["pf-client", id], d);
    ["pf-summary", "pf-clients", "pf-callbacks", "notifications"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  };
  const save = useMutation({
    mutationFn: () => api.pfCall(id!, { outcome, note, callback_on: outcome === "callback" || outcome === "interested" ? when || null : null,
      rule, email: email.trim() || null }),
    onSuccess: (d) => { refresh(d); setOutcome(""); setNote(""); setEmail(""); toast.success("Appel noté"); },
    onError: (e) => toastError(e, "Appel non noté"),
  });
  const saveEmail = useMutation({
    mutationFn: () => api.pfEmail(id!, email.trim() || null),
    onSuccess: (d) => { refresh(d); setEmail(""); toast.success("Email enregistré : le client peut recevoir les campagnes"); },
    onError: (e) => toastError(e, "Email non enregistré"),
  });
  return (
    <Dialog open={!!id} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[calc(100vh-2rem)] max-w-3xl overflow-y-auto">
        {isLoading || !c ? <><DialogTitle className="sr-only">Fiche client</DialogTitle><p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Chargement…</p></> : (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">{c.segment === "pro" ? <Building2 className="size-4" /> : <User className="size-4" />}{c.name}</DialogTitle>
              <DialogDescription>{SEG1[c.segment]} · {c.contracts} contrat{c.contracts > 1 ? "s" : ""} en cours{c.cancelled ? ` · ${c.cancelled} résilié${c.cancelled > 1 ? "s" : ""}` : ""}</DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2 text-sm">
                <p className="text-xs font-medium text-muted-foreground">Joindre</p>
                {c.phones.length ? c.phones.map((p) => (
                  <a key={p.number} href={`tel:${p.number.replace(/[^\d+]/g, "")}`} className="flex items-center gap-2 text-primary hover:underline">
                    <Phone className="size-3.5" />{p.number}{p.label && <span className="text-muted-foreground">· {p.label}</span>}
                  </a>
                )) : <p className="text-muted-foreground">Pas de téléphone dans DIAMM.</p>}
                {c.email ? (
                  <p className="flex items-center gap-2"><Mail className="size-3.5 text-muted-foreground" />{c.email}
                    {c.contact_id && <Link to={`/contacts?open=${c.contact_id}`} className="text-xs text-primary hover:underline">fiche contact</Link>}</p>
                ) : (
                  <div className="flex gap-2">
                    <Input className="h-8" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Ajouter son email (gardé avec l'appel)" />
                    <Button size="sm" variant="outline" disabled={!email.trim() || saveEmail.isPending} onClick={() => saveEmail.mutate()}>Enregistrer</Button>
                  </div>
                )}
                {c.note && <p className="text-xs text-muted-foreground">Note DIAMM : {c.note}</p>}
              </div>
              <div className="space-y-2 text-sm">
                <p className="text-xs font-medium text-muted-foreground">Ce qu'on peut lui proposer</p>
                {c.opportunities.length ? c.opportunities.map((o) => <p key={o.key}>• {o.pitch}</p>)
                  : <p className="text-muted-foreground">Rien de particulier d'après ses contrats.</p>}
                {c.missing.length > 0 && (
                  <div className="flex flex-wrap gap-1 pt-1">
                    <span className="text-xs text-muted-foreground">Pas chez le cabinet :</span>
                    {c.missing.map((f) => <Badge key={f} variant="outline" className="font-normal">{f}</Badge>)}
                  </div>
                )}
              </div>
            </div>
            <div className="rounded-xl border p-3">
              <p className="mb-2 text-sm font-medium">Noter un appel</p>
              <div className="flex flex-wrap gap-1.5">
                {OUTCOMES.map((o) => (
                  <button key={o.value} type="button" onClick={() => { setOutcome(o.value); requestAnimationFrame(() => noteRef.current?.focus()); }}
                    className={cn("rounded-full border px-3 py-1 text-sm transition-colors", outcome === o.value ? "border-primary bg-primary text-primary-foreground" : cn("hover:bg-accent", o.tone))}>
                    {o.label}
                  </button>
                ))}
              </div>
              {outcome && (
                <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto]">
                  <Textarea ref={noteRef} rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Ce qui s'est dit (facultatif)" />
                  <div className="space-y-2">
                    {(outcome === "callback" || outcome === "interested") && (
                      <label className="block text-xs text-muted-foreground">{outcome === "callback" ? "Rappeler le" : "Relancer le (facultatif)"}
                        <Input type="date" className="mt-1 h-8" value={when} onChange={(e) => setWhen(e.target.value)} />
                      </label>
                    )}
                  </div>
                  <div className="sm:col-span-2 flex justify-end">
                    <Button size="sm" disabled={save.isPending || (outcome === "callback" && !when)} onClick={() => save.mutate()}>
                      {save.isPending ? <Loader2 className="animate-spin" /> : <Send />} Enregistrer l'appel
                    </Button>
                  </div>
                </div>
              )}
              {c.calls.length > 0 && (
                <ul className="mt-3 space-y-1.5 border-t pt-2 text-xs">
                  {c.calls.map((x) => (
                    <li key={x.id}><b className={cn(x.outcome === "interested" && "text-success", x.outcome === "callback" && "text-warning")}>{x.label}</b>
                      <span className="text-muted-foreground"> · {x.at ? formatDayTime(x.at) : ""}{x.by ? ` · ${x.by}` : ""}{x.callback_on ? ` · rappel ${fmtDay(x.callback_on)}${x.callback_done ? " (fait)" : ""}` : ""}</span>
                      {x.note && <span className="block text-foreground">{x.note}</span>}</li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <p className="mb-2 text-sm font-medium">Contrats</p>
              <div className="overflow-x-auto rounded-lg border">
                <table className="w-full text-xs">
                  <thead className="bg-muted/40 text-left text-muted-foreground">
                    <tr><th className="px-3 py-1.5 font-medium">Famille</th><th className="px-3 py-1.5 font-medium">Branche</th>
                      <th className="px-3 py-1.5 font-medium">Compagnie</th><th className="px-3 py-1.5 font-medium">Police</th><th className="px-3 py-1.5 font-medium">État</th></tr>
                  </thead>
                  <tbody className="divide-y">
                    {c.items.map((x) => (
                      <tr key={x.id} className={cn(x.cancelled && "text-muted-foreground")}>
                        <td className="px-3 py-1.5">{x.family}</td><td className="px-3 py-1.5">{x.branch}{x.fleet ? " (flotte)" : ""}</td>
                        <td className="px-3 py-1.5">{x.insurer}</td><td className="px-3 py-1.5 font-mono">{x.policy}</td>
                        <td className="px-3 py-1.5">{x.cancelled ? `Résilié${x.cancelled_on ? ` le ${new Date(x.cancelled_on).toLocaleDateString("fr-FR")}` : ""}`
                          : x.due_date ? `Échéance ${new Date(x.due_date).toLocaleDateString("fr-FR")}` : x.fixed_term ? "Ferme" : "En cours"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

/* ================================================================ rappels */

function Callbacks({ onOpen }: { onOpen: (id: number) => void }) {
  const { data, isLoading } = useQuery({ queryKey: ["pf-callbacks"], queryFn: () => api.pfCallbacks(14) });
  const today = dayISO(new Date());
  const items = data?.items ?? [];
  if (isLoading) return <Skeleton className="h-48 rounded-xl" />;
  if (!items.length) return <EmptyState icon={CalendarClock} title="Aucun rappel prévu" text="Quand vous notez « À rappeler » sur un appel, il arrive ici et dans la cloche le jour venu." />;
  const groups = [
    { label: "En retard", items: items.filter((x) => x.callback_on! < today) },
    { label: "Aujourd'hui", items: items.filter((x) => x.callback_on === today) },
    { label: "Prochains jours", items: items.filter((x) => x.callback_on! > today) },
  ].filter((g) => g.items.length);
  return (
    <div className="space-y-4">
      {groups.map((g) => (
        <section key={g.label}>
          <h2 className="mb-2 text-sm font-semibold">{g.label} <span className="font-normal text-muted-foreground">({g.items.length})</span></h2>
          <Card className="divide-y overflow-hidden">
            {g.items.map((x) => (
              <button key={x.id} onClick={() => onOpen(x.client.id)} className="flex w-full items-center gap-3 px-4 py-3 text-left text-sm hover:bg-accent/30">
                <CalendarClock className={cn("size-4", g.label === "En retard" ? "text-destructive" : "text-warning")} />
                <span className="min-w-0 flex-1">
                  <span className="block font-medium">{x.client.name}</span>
                  <span className="block truncate text-xs text-muted-foreground">{fmtDay(x.callback_on!)}{x.by ? ` · noté par ${x.by}` : ""}{x.note ? ` · ${x.note}` : ""}</span>
                </span>
                {x.client.phone && <span className="text-xs text-primary">{x.client.phone}</span>}
              </button>
            ))}
          </Card>
        </section>
      ))}
    </div>
  );
}

/* ================================================================ import */

function ImportDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const run = useMutation({
    mutationFn: (f: File) => api.pfImport(f),
    onSuccess: () => ["pf-summary", "pf-clients", "contacts", "lists"].forEach((k) => qc.invalidateQueries({ queryKey: [k] })),
    onError: (e) => toastError(e, "Import impossible"),
  });
  const r = run.data;
  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) run.reset(); }}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Importer l'export DIAMM</DialogTitle>
          <DialogDescription>Le fichier du portefeuille tel quel (.xls, .xlsx ou .csv), une ligne par police. Réimporter met à jour, sans doublon ;
            les emails notés dans l'appli sont gardés.</DialogDescription>
        </DialogHeader>
        {!r ? (
          <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed p-8 text-center">
            <Upload className="size-6 text-muted-foreground" />
            <Button disabled={run.isPending} onClick={() => input.current?.click()}>
              {run.isPending ? <><Loader2 className="animate-spin" /> Import en cours…</> : "Choisir le fichier"}
            </Button>
            <input ref={input} type="file" accept=".xls,.xlsx,.xlsm,.csv" className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) run.mutate(f); e.target.value = ""; }} />
          </div>
        ) : (
          <div className="space-y-3 text-sm">
            <p className="font-medium text-success">Portefeuille importé : {n(r.rows)} lignes lues.</p>
            <ul className="grid gap-1 sm:grid-cols-2">
              <li>{n(r.clients_new + r.clients_updated)} clients ({n(r.clients_new)} nouveaux)</li>
              <li>{n(r.contracts_new + r.contracts_updated)} contrats ({n(r.contracts_new)} nouveaux, {n(r.cancelled)} résiliés)</li>
              <li>{n(r.particuliers)} particuliers · {n(r.pros)} entreprises</li>
              <li>{n(r.with_phone)} avec téléphone · {n(r.with_email)} avec email</li>
              <li className="sm:col-span-2">{n(r.contacts_created)} contacts « client » créés, {n(r.contacts_linked)} déjà présents{r.prospects_now_clients ? ` (dont ${r.prospects_now_clients} prospects devenus clients : leur prospection s'arrête)` : ""}</li>
            </ul>
            {!r.has_premium && !r.has_due && <p className="text-xs text-muted-foreground">Ni primes ni échéances dans ce fichier : ajoutez ces colonnes à l'export DIAMM pour le chiffre d'affaires et les renouvellements.</p>}
            {r.skipped > 0 && <p className="text-xs text-warning">{r.skipped} ligne{r.skipped > 1 ? "s" : ""} ignorée{r.skipped > 1 ? "s" : ""} (sans client, police ou compagnie).</p>}
            {r.unknown_branches.length > 0 && <p className="text-xs text-muted-foreground">Branches nouvelles, classées d'après leur catégorie : {r.unknown_branches.join(", ")}.</p>}
            {r.duplicates.length > 0 && (
              <details className="text-xs"><summary className="cursor-pointer text-warning">{r.duplicates.length} client{r.duplicates.length > 1 ? "s" : ""} peut-être écrit{r.duplicates.length > 1 ? "s" : ""} deux fois dans DIAMM</summary>
                <ul className="mt-1 list-disc pl-5 text-muted-foreground">{r.duplicates.map((g) => <li key={g.join("|")}>{g.join(" / ")}</li>)}</ul>
                <p className="mt-1 text-muted-foreground">À corriger dans DIAMM : au prochain import, ils seront réunis.</p></details>
            )}
          </div>
        )}
        <DialogFooter><Button variant="outline" onClick={() => onOpenChange(false)}>{r ? "Fermer" : "Annuler"}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
