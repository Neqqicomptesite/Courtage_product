// Contrats et échéances : portefeuille, préavis, renouvellements (voir app/contracts.py).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlarmClock, ArrowLeft, BellRing, CalendarCheck2, CalendarClock, FileCheck2, FileStack, History, MoreHorizontal,
  Plus, RefreshCw, RotateCw, Search, Trash2, Wallet, XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { ConfirmDialog, EmptyState, Field, PageHeader, toastError, useDebounced } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api, type Contract, type ContractDraftItem, type ContractInput, type ContractUrgency } from "@/lib/api";
import { cn } from "@/lib/utils";
import { mad, shortDate } from "@/pages/quotes";

const URGENCY: Record<ContractUrgency, { label: (c: Contract) => string; tone: string }> = {
  ok: { label: (c) => `Préavis dans ${c.days_to_deadline} j`, tone: "bg-muted text-muted-foreground" },
  soon: { label: (c) => `Préavis dans ${c.days_to_deadline} j`, tone: "bg-accent text-accent-foreground" },
  urgent: { label: (c) => (c.days_to_deadline === 0 ? "Préavis aujourd'hui" : `Préavis dans ${c.days_to_deadline} j`), tone: "bg-warning/15 text-warning" },
  past_notice: { label: () => "Préavis dépassé", tone: "bg-destructive/10 text-destructive" },
  expired: { label: () => "Échu", tone: "bg-destructive/10 text-destructive" },
  ended: { label: (c) => c.status_label, tone: "bg-muted text-muted-foreground" },
};

/** Ajoute un an moins un jour à une date ISO (échéance par défaut). */
export function endFrom(start: string): string {
  const d = new Date(start + "T12:00:00");
  if (Number.isNaN(d.getTime())) return "";
  const e = new Date(d);
  e.setFullYear(d.getFullYear() + 1);
  if (e.getDate() !== d.getDate()) e.setDate(0); // 29 février
  e.setDate(e.getDate() - 1);
  return e.toISOString().slice(0, 10);
}

export function UrgencyBadge({ c }: { c: Contract }) {
  const u = URGENCY[c.urgency];
  return <span className={cn("inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium", u.tone)}>{u.label(c)}</span>;
}

/* ------------------------------------------------------------------ liste */

export function ContractsPage() {
  const [params, setParams] = useSearchParams();
  const f = params.get("f") ?? "upcoming";
  const branch = params.get("branche") ?? "";
  const [q, setQ] = useState("");
  const [needle, setNeedle] = useState("");
  const debounced = useDebounced((v: string) => setNeedle(v.trim()), 250);
  const [creating, setCreating] = useState(false);
  const { data } = useQuery({ queryKey: ["contracts", f, branch, needle], queryFn: () => api.contracts({ f, branch, q: needle }), placeholderData: (p) => p });
  const set = (k: string, v: string) => setParams((p) => { const n = new URLSearchParams(p); if (v) n.set(k, v); else n.delete(k); return n; }, { replace: true });
  const sm = data?.summary;

  return (
    <>
      <PageHeader title="Contrats" description="Le portefeuille du cabinet : échéances, préavis et renouvellements. Les rappels arrivent 2 semaines puis 1 semaine avant chaque date limite de préavis."
        actions={<Button onClick={() => setCreating(true)}><Plus /> Nouveau contrat</Button>} />

      {sm && (
        <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Tile icon={FileCheck2} label="Contrats en cours" value={String(sm.active)} sub={sm.premium ? `${mad(sm.premium)} de primes` : undefined} />
          <Tile icon={Wallet} label="Commissions annuelles" value={sm.commission ? mad(sm.commission) : "—"} sub="Sur les contrats en cours" />
          <Tile icon={AlarmClock} label="Préavis dans 30 jours" value={String(sm.due_30)} sub={`${sm.due_90} dans les 90 jours`} tone={sm.due_30 ? "warning" : undefined}
            onClick={() => set("f", "upcoming")} />
          <Tile icon={BellRing} label="Préavis dépassé" value={String(sm.past_notice)} sub={`${sm.renewing} renouvellement${sm.renewing > 1 ? "s" : ""} en cours`}
            tone={sm.past_notice ? "destructive" : undefined} onClick={() => set("f", "upcoming")} />
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex gap-1.5 overflow-x-auto pb-1 sm:flex-wrap sm:overflow-visible">
          {data?.filters.map((x) => (
            <button key={x.key} onClick={() => set("f", x.key === "upcoming" ? "" : x.key)}
              className={cn("shrink-0 rounded-full border px-3 py-1 text-sm transition-colors", f === x.key ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent")}>
              {x.label}
            </button>
          ))}
        </div>
        <div className="flex w-full gap-2 sm:ml-auto sm:w-auto">
          <div className="relative flex-1 sm:w-56">
            <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
            <Input value={q} onChange={(e) => { setQ(e.target.value); debounced(e.target.value); }} placeholder="Client, police, compagnie…" className="pl-8" aria-label="Rechercher un contrat" />
          </div>
          <NativeSelect className="w-auto" value={branch} onChange={(e) => set("branche", e.target.value)} aria-label="Branche">
            <option value="">Toutes les branches</option>
            {(data?.branches ?? []).map((b) => <option key={b} value={b}>{b}</option>)}
          </NativeSelect>
        </div>
      </div>

      {!data ? <Skeleton className="h-80 rounded-xl" /> : data.items.length === 0 ? (
        sm && sm.active + sm.ended === 0 ? (
          <EmptyState icon={FileCheck2} title="Aucun contrat pour l'instant"
            text="Un contrat se crée quand un dossier de cotation est gagné. Vous pouvez aussi saisir vos contrats en cours, un par un."
            action={<Button onClick={() => setCreating(true)}><Plus /> Ajouter un contrat</Button>} />
        ) : (
          <EmptyState icon={CalendarCheck2} title={f === "upcoming" ? "Rien à renouveler dans les 90 jours" : "Aucun contrat ici"}
            text={f === "upcoming" ? "Les contrats apparaissent ici quand leur date limite de préavis approche." : undefined} />
        )
      ) : (
        <ContractTable items={data.items} />
      )}

      <ContractDialog open={creating} onClose={() => setCreating(false)} branches={data?.branches ?? []} noticeDays={data?.notice_days ?? 60} />
    </>
  );
}

function Tile({ icon: Icon, label, value, sub, tone, onClick }: {
  icon: typeof FileCheck2; label: string; value: string; sub?: string; tone?: "warning" | "destructive"; onClick?: () => void;
}) {
  return (
    <Card className={cn("p-4", onClick && "cursor-pointer transition-colors hover:border-primary/40")} onClick={onClick}>
      <p className="flex items-center gap-1.5 text-xs text-muted-foreground"><Icon className="size-3.5" />{label}</p>
      <p className={cn("mt-1 text-xl font-semibold tabular", tone === "warning" && "text-warning", tone === "destructive" && "text-destructive")}>{value}</p>
      {sub && <p className="mt-0.5 truncate text-xs text-muted-foreground">{sub}</p>}
    </Card>
  );
}

function ContractTable({ items }: { items: Contract[] }) {
  const navigate = useNavigate();
  return (
    <>
      <Card className="hidden overflow-x-auto md:block">
        <table className="w-full text-sm">
          <thead className="border-b text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-4 py-2.5 font-medium">Client</th><th className="px-3 py-2.5 font-medium">Branche</th>
              <th className="px-3 py-2.5 font-medium">Compagnie</th><th className="px-3 py-2.5 text-right font-medium">Prime</th>
              <th className="px-3 py-2.5 font-medium">Échéance</th><th className="px-3 py-2.5 font-medium">Date limite de préavis</th>
              <th className="px-3 py-2.5 font-medium">Gestionnaire</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {items.map((c) => (
              <tr key={c.id} className="cursor-pointer hover:bg-muted/50" onClick={() => navigate(`/contracts/${c.id}`)}>
                <td className="px-4 py-2.5">
                  <p className="font-medium">{c.client_name}</p>
                  <p className="text-xs text-muted-foreground tabular">{c.policy_number || "Police non renseignée"}</p>
                </td>
                <td className="px-3 py-2.5">{c.branch}</td>
                <td className="px-3 py-2.5">{c.insurer_name}</td>
                <td className="px-3 py-2.5 text-right tabular">{mad(c.premium)}</td>
                <td className="px-3 py-2.5 tabular">{shortDate(c.end_date)}</td>
                <td className="px-3 py-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="tabular">{shortDate(c.deadline)}</span>
                    {c.status === "renewing" ? <Badge variant="info">Renouvellement en cours</Badge> : <UrgencyBadge c={c} />}
                  </div>
                </td>
                <td className="px-3 py-2.5 text-muted-foreground">{c.owner?.name ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <div className="space-y-2 md:hidden">
        {items.map((c) => (
          <Link key={c.id} to={`/contracts/${c.id}`} className="block rounded-xl border bg-card p-3 text-sm">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0"><p className="truncate font-medium">{c.client_name}</p><p className="text-xs text-muted-foreground">{c.branch} · {c.insurer_name}</p></div>
              {c.status === "renewing" ? <Badge variant="info">En renouvellement</Badge> : <UrgencyBadge c={c} />}
            </div>
            <div className="mt-2 flex justify-between text-xs text-muted-foreground">
              <span>Préavis avant le <span className="tabular text-foreground">{shortDate(c.deadline)}</span></span><span className="tabular">{mad(c.premium)}</span>
            </div>
          </Link>
        ))}
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ saisie */

type Form = Record<keyof Omit<ContractInput, "tacit" | "company_id" | "contact_id" | "insurer_id" | "owner_id">, string> & {
  tacit: boolean; insurer_id: string; owner_id: string;
};

function toForm(c: Contract | null, noticeDays: number): Form {
  return {
    client_name: c?.client_name ?? "", insurer_id: c?.insurer_id ? String(c.insurer_id) : "", insurer_name: c?.insurer_id ? "" : c?.insurer_name ?? "",
    branch: c?.branch ?? "", policy_number: c?.policy_number ?? "", premium: c?.premium != null ? String(c.premium) : "",
    rate: c?.rate ?? "", commission_rate: c?.commission_rate != null ? String(c.commission_rate).replace(".", ",") : "",
    start_date: c?.start_date ?? "", end_date: c?.end_date ?? "", notice_days: String(c?.notice_days ?? noticeDays),
    tacit: c?.tacit ?? true, owner_id: c?.owner ? String(c.owner.id) : "", notes: c?.notes ?? "",
  };
}

function toInput(f: Form): ContractInput {
  return {
    client_name: f.client_name, insurer_id: f.insurer_id ? Number(f.insurer_id) : null, insurer_name: f.insurer_id ? "" : f.insurer_name,
    branch: f.branch, policy_number: f.policy_number, premium: f.premium, rate: f.rate, commission_rate: f.commission_rate,
    start_date: f.start_date || null, end_date: f.end_date || null, notice_days: f.notice_days, tacit: f.tacit,
    ...(f.owner_id ? { owner_id: Number(f.owner_id) } : {}), notes: f.notes,
  };
}

function ContractFields({ f, set, branches, errors, withClient = true }: {
  f: Form; set: (patch: Partial<Form>) => void; branches: string[]; errors?: Record<string, string>; withClient?: boolean;
}) {
  const { data: insurers } = useQuery({ queryKey: ["quote-insurers"], queryFn: api.quoteInsurerCompanies });
  const { data: people } = useQuery({ queryKey: ["quote-people"], queryFn: api.quotePeople });
  const deadline = useMemo(() => {
    if (!f.end_date || f.notice_days === "") return null;
    const d = new Date(f.end_date + "T12:00:00");
    d.setDate(d.getDate() - Number(f.notice_days || 0));
    return Number.isNaN(d.getTime()) ? null : d.toISOString().slice(0, 10);
  }, [f.end_date, f.notice_days]);
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {withClient && <Field label="Client" error={errors?.client_name} className="sm:col-span-2"><Input value={f.client_name} onChange={(e) => set({ client_name: e.target.value })} placeholder="Entreprise ou particulier" /></Field>}
      <Field label="Compagnie" error={errors?.insurer_id}>
        <NativeSelect value={f.insurer_id} onChange={(e) => set({ insurer_id: e.target.value })}>
          <option value="">Autre (à saisir)</option>
          {insurers?.items.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
        </NativeSelect>
      </Field>
      {!f.insurer_id ? (
        <Field label="Nom de la compagnie"><Input value={f.insurer_name} onChange={(e) => set({ insurer_name: e.target.value })} /></Field>
      ) : <span className="hidden sm:block" />}
      <Field label="Branche" error={errors?.branch}>
        <Input list="contract-branches" value={f.branch} onChange={(e) => set({ branch: e.target.value })} />
        <datalist id="contract-branches">{branches.map((b) => <option key={b} value={b} />)}</datalist>
      </Field>
      <Field label="N° de police"><Input value={f.policy_number} onChange={(e) => set({ policy_number: e.target.value })} className="tabular" /></Field>
      <Field label="Prime annuelle (MAD)" error={errors?.premium}><Input inputMode="decimal" value={f.premium} onChange={(e) => set({ premium: e.target.value })} className="tabular" /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Taux"><Input value={f.rate} onChange={(e) => set({ rate: e.target.value })} placeholder="ex. 2,1 %" className="tabular" /></Field>
        <Field label="Commission (%)" error={errors?.commission_rate}><Input inputMode="decimal" value={f.commission_rate} onChange={(e) => set({ commission_rate: e.target.value })} className="tabular" /></Field>
      </div>
      <Field label="Date d'effet">
        <Input type="date" value={f.start_date} onChange={(e) => set({ start_date: e.target.value, ...(e.target.value && !f.end_date ? { end_date: endFrom(e.target.value) } : {}) })} />
      </Field>
      <Field label="Échéance" error={errors?.end_date}><Input type="date" value={f.end_date} onChange={(e) => set({ end_date: e.target.value })} /></Field>
      <Field label="Préavis de résiliation (jours)" error={errors?.notice_days}
        hint={deadline ? `Date limite : ${shortDate(deadline)}. Rappels 2 semaines puis 1 semaine avant.` : undefined}>
        <Input inputMode="numeric" value={f.notice_days} onChange={(e) => set({ notice_days: e.target.value })} className="w-28 tabular" />
      </Field>
      <div className="space-y-3">
        {(people?.items.length ?? 0) > 1 && (
          <Field label="Gestionnaire">
            <NativeSelect value={f.owner_id} onChange={(e) => set({ owner_id: e.target.value })}>
              <option value="">—</option>
              {people!.items.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </NativeSelect>
          </Field>
        )}
        <div className="flex items-center gap-2 pt-1 text-sm">
          <Switch checked={f.tacit} onCheckedChange={(v) => set({ tacit: v })} aria-label="Tacite reconduction" />
          <span>Tacite reconduction <span className="text-muted-foreground">(reconduit d'un an si rien n'est fait)</span></span>
        </div>
      </div>
    </div>
  );
}

function errorsOf(e: unknown): Record<string, string> | undefined {
  const d = (e as { detail?: { errors?: Record<string, string> } })?.detail;
  return d?.errors;
}

function ContractDialog({ open, onClose, branches, noticeDays }: { open: boolean; onClose: () => void; branches: string[]; noticeDays: number }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [f, setF] = useState<Form>(() => toForm(null, noticeDays));
  const [errors, setErrors] = useState<Record<string, string>>();
  useEffect(() => { if (open) { setF(toForm(null, noticeDays)); setErrors(undefined); } }, [open, noticeDays]);
  const create = useMutation({
    mutationFn: () => api.contractCreate(toInput(f)),
    onSuccess: (c) => { toast.success("Contrat enregistré", { description: "Les rappels de préavis sont dans l'Agenda." }); qc.invalidateQueries({ queryKey: ["contracts"] }); onClose(); navigate(`/contracts/${c.id}`); },
    onError: (e) => { setErrors(errorsOf(e)); if (!errorsOf(e)) toastError(e); },
  });
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Nouveau contrat</DialogTitle>
          <DialogDescription>Pour un contrat déjà en cours. Les contrats des dossiers gagnés se créent d'eux-mêmes.</DialogDescription>
        </DialogHeader>
        <form onSubmit={(e) => { e.preventDefault(); create.mutate(); }} className="space-y-4">
          <ContractFields f={f} set={(p) => setF((x) => ({ ...x, ...p }))} branches={branches} errors={errors} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>Annuler</Button>
            <Button type="submit" disabled={create.isPending}><Plus /> Enregistrer</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ fiche */

export function ContractDetailPage() {
  const id = Number(useParams().id);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data: c } = useQuery({ queryKey: ["contract", id], queryFn: () => api.contract(id) });
  const { data: br } = useQuery({ queryKey: ["quote-branches"], queryFn: api.quoteBranches });
  const [f, setF] = useState<Form | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>();
  const [renewing, setRenewing] = useState(false);
  const [ending, setEnding] = useState(false);
  const [deleting, setDeleting] = useState(false);
  useEffect(() => { if (c) setF(toForm(c, c.notice_days)); }, [c]);
  const done = (x: Contract) => { qc.setQueryData(["contract", id], x); qc.invalidateQueries({ queryKey: ["contracts"] }); };
  const save = useMutation({
    mutationFn: () => api.contractUpdate(id, toInput(f!)),
    onSuccess: (x) => { done(x); setErrors(undefined); toast.success("Contrat enregistré"); },
    onError: (e) => { setErrors(errorsOf(e)); if (!errorsOf(e)) toastError(e); },
  });
  const start = useMutation({
    mutationFn: () => api.contractStartRenewal(id),
    onSuccess: (r) => { done(r.contract); qc.invalidateQueries({ queryKey: ["quotes"] }); toast.success("Dossier de renouvellement ouvert", { description: "La compagnie actuelle est déjà ajoutée : demandez ses conditions, et consultez-en d'autres si besoin." }); navigate(`/quotes/${r.quote_id}`); },
    onError: (e) => toastError(e),
  });
  const end = useMutation({ mutationFn: (reason: string) => api.contractEnd(id, reason), onSuccess: (x) => { done(x); setEnding(false); }, onError: (e) => toastError(e) });
  const del = useMutation({ mutationFn: () => api.contractDelete(id), onSuccess: () => { qc.invalidateQueries({ queryKey: ["contracts"] }); navigate("/contracts"); }, onError: (e) => toastError(e) });

  if (!c || !f) return <Skeleton className="h-[32rem] rounded-xl" />;
  const dirty = JSON.stringify(toInput(f)) !== JSON.stringify(toInput(toForm(c, c.notice_days)));

  return (
    <>
      <PageHeader back={<Button variant="ghost" size="sm" className="-ml-2" asChild><Link to="/contracts"><ArrowLeft /> Contrats</Link></Button>}
        title={<span className="flex flex-wrap items-center gap-x-3 gap-y-1">{c.client_name}
          {c.status === "renewing" ? <Badge variant="info">Renouvellement en cours</Badge> : <UrgencyBadge c={c} />}</span>}
        description={<span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-medium text-foreground">{c.branch}</span><span>{c.insurer_name}</span>
          {c.policy_number && <span className="tabular">Police {c.policy_number}</span>}
          {c.owner && <span>Gestionnaire : {c.owner.name}</span>}
        </span>}
        actions={<>
          {c.status === "active" && <>
            <Button variant="outline" onClick={() => setRenewing(true)}><RotateCw /> Renouvelé à l'identique</Button>
            <Button onClick={() => start.mutate()} disabled={start.isPending}><RefreshCw /> Lancer le renouvellement</Button>
          </>}
          {c.status === "renewing" && c.renewal_case && <Button asChild><Link to={`/quotes/${c.renewal_case.id}`}><FileStack /> Dossier {c.renewal_case.ref}</Link></Button>}
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button variant="outline" size="icon" aria-label="Plus d'actions"><MoreHorizontal /></Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {c.status !== "ended" && <DropdownMenuItem onSelect={() => setEnding(true)}><XCircle /> Terminer le contrat</DropdownMenuItem>}
              {c.status === "renewing" && <DropdownMenuItem onSelect={() => setRenewing(true)}><RotateCw /> Renouvelé à l'identique</DropdownMenuItem>}
              <DropdownMenuSeparator />
              <DropdownMenuItem destructive onSelect={() => setDeleting(true)}><Trash2 /> Supprimer</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </>} />

      <StatusBanner c={c} />

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Card className="p-4">
          <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }} className="space-y-4">
            <ContractFields f={f} set={(p) => setF((x) => ({ ...x!, ...p }))} branches={br?.items.map((b) => b.name) ?? []} errors={errors} />
            <Field label="Notes"><Textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
            <div className="flex justify-end gap-2">
              {dirty && <Button type="button" variant="ghost" onClick={() => { setF(toForm(c, c.notice_days)); setErrors(undefined); }}>Annuler</Button>}
              <Button type="submit" disabled={!dirty || save.isPending}>Enregistrer</Button>
            </div>
          </form>
        </Card>
        <div className="min-w-0 space-y-6">
          <Timeline c={c} />
          <Card className="p-4">
            <p className="mb-3 flex items-center gap-2 font-medium"><History className="size-4 text-muted-foreground" />Historique</p>
            {c.quote_case && <p className="mb-2 text-sm">Issu du dossier <Link className="font-medium text-primary hover:underline" to={`/quotes/${c.quote_case.id}`}>{c.quote_case.ref}</Link></p>}
            {c.previous_id && <p className="mb-2 text-sm">Remplace le <Link className="font-medium text-primary hover:underline" to={`/contracts/${c.previous_id}`}>contrat précédent</Link></p>}
            <ul className="space-y-2 text-sm">
              {c.history.map((h, i) => (
                <li key={i} className="flex gap-3"><span className="w-20 shrink-0 text-xs text-muted-foreground tabular">{shortDate(h.ts.slice(0, 10))}</span><span>{h.text}</span></li>
              ))}
            </ul>
          </Card>
        </div>
      </div>

      <RenewDialog c={renewing ? c : null} onClose={() => setRenewing(false)} onDone={(x) => { done(x); setRenewing(false); toast.success("Contrat renouvelé", { description: `Nouvelle échéance : ${shortDate(x.end_date)}.` }); }} />
      <EndDialog open={ending} onClose={() => setEnding(false)} onConfirm={(r) => end.mutate(r)} />
      <ConfirmDialog open={deleting} onOpenChange={setDeleting} title="Supprimer ce contrat ?" destructive confirmLabel="Supprimer"
        description="Le contrat et ses rappels sont supprimés. Pour un contrat résilié, préférez « Terminer le contrat » : il reste dans l'historique."
        onConfirm={() => del.mutate()} />
    </>
  );
}

function StatusBanner({ c }: { c: Contract }) {
  let text: React.ReactNode = null;
  let tone = "border-primary/30 bg-accent/40";
  if (c.status === "ended") { text = <>Contrat terminé{c.end_reason && <> : {c.end_reason}</>}.</>; tone = "border-border bg-muted/40"; }
  else if (c.urgency === "expired") { text = <>Échu le {shortDate(c.end_date)}{c.tacit ? ", la reconduction sera enregistrée d'ici quelques heures." : " sans tacite reconduction : renouvelez-le ou terminez-le."}</>; tone = "border-destructive/40 bg-destructive/5"; }
  else if (c.urgency === "past_notice") { text = <>Date limite de préavis dépassée ({shortDate(c.deadline)}). {c.tacit ? `Sans action, le contrat sera reconduit le ${shortDate(c.end_date)}.` : `Échéance le ${shortDate(c.end_date)}.`}</>; tone = "border-destructive/40 bg-destructive/5"; }
  else if (c.urgency === "urgent") { text = <>Date limite de préavis {c.days_to_deadline === 0 ? "aujourd'hui" : `dans ${c.days_to_deadline} jours`} ({shortDate(c.deadline)}) : lancez le renouvellement ou prévenez le client.</>; tone = "border-warning/40 bg-warning/5"; }
  else if (c.status === "renewing") { text = <>Renouvellement en cours dans le dossier {c.renewal_case?.ref}. Gagné, il mettra ce contrat à jour ; perdu, il le terminera.</>; }
  if (!text) return null;
  return <div className={cn("mb-5 rounded-lg border px-4 py-3 text-sm", tone)}>{text}</div>;
}

function Timeline({ c }: { c: Contract }) {
  const today = new Date().toISOString().slice(0, 10);
  const dl = new Date(c.deadline + "T12:00:00");
  const minus = (n: number) => { const d = new Date(dl); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };
  // comme le serveur : un rappel déjà passé au moment de la saisie est posé aujourd'hui
  const r1 = minus(14) < today ? today : minus(14);
  const r2 = minus(7) < today ? today : minus(7);
  const live = c.status !== "ended" && c.deadline >= today;
  const steps = [
    c.start_date && { date: c.start_date, label: "Date d'effet" },
    live && r1 !== r2 && { date: r1, label: r1 === minus(14) ? "Rappel : 2 semaines avant la date limite" : "Rappel (aujourd'hui)" },
    live && { date: r2, label: r2 === minus(7) ? "Rappel : 1 semaine avant" : "Rappel (aujourd'hui)" },
    { date: c.deadline, label: `Date limite de préavis (${c.notice_days} jours)`, strong: true },
    { date: c.end_date, label: c.tacit ? "Échéance (tacite reconduction)" : "Échéance" },
  ].filter(Boolean) as { date: string; label: string; strong?: boolean }[];
  return (
    <Card className="p-4">
      <p className="mb-3 flex items-center gap-2 font-medium"><CalendarClock className="size-4 text-muted-foreground" />Échéance</p>
      <ol className="relative space-y-3 border-l pl-4">
        {steps.map((s) => (
          <li key={s.label} className="relative text-sm">
            <span className={cn("absolute -left-[1.4rem] top-1 size-2.5 rounded-full border-2 bg-card", s.date < today ? "border-muted-foreground/40" : s.strong ? "border-warning" : "border-primary")} />
            <span className={cn("mr-2 tabular", s.date < today && "text-muted-foreground", s.strong && "font-semibold")}>{shortDate(s.date)}</span>
            <span className={cn(s.date < today && "text-muted-foreground")}>{s.label}</span>
          </li>
        ))}
      </ol>
      {c.premium != null && (
        <div className="mt-4 grid grid-cols-2 gap-2 border-t pt-3 text-sm">
          <span className="text-muted-foreground">Prime annuelle</span><span className="text-right tabular">{mad(c.premium)}</span>
          {c.commission != null && <><span className="text-muted-foreground">Commission ({String(c.commission_rate).replace(".", ",")} %)</span><span className="text-right tabular">{mad(c.commission)}</span></>}
        </div>
      )}
    </Card>
  );
}

function RenewDialog({ c, onClose, onDone }: { c: Contract | null; onClose: () => void; onDone: (x: Contract) => void }) {
  const [premium, setPremium] = useState("");
  const [rate, setRate] = useState("");
  const [policy, setPolicy] = useState("");
  useEffect(() => { if (c) { setPremium(c.premium != null ? String(c.premium) : ""); setRate(c.rate ?? ""); setPolicy(c.policy_number); } }, [c]);
  const next = c ? (() => { const d = new Date(c.end_date + "T12:00:00"); d.setDate(d.getDate() + 1); return d.toISOString().slice(0, 10); })() : "";
  const renew = useMutation({ mutationFn: () => api.contractRenew(c!.id, { premium, rate, policy_number: policy }), onSuccess: onDone, onError: (e) => toastError(e) });
  return (
    <Dialog open={!!c} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Renouvelé chez {c?.insurer_name}</DialogTitle>
          <DialogDescription>Nouvelle période du {shortDate(next)} au {shortDate(next ? endFrom(next) : null)}. Les rappels de préavis sont replacés.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Prime (MAD)"><Input inputMode="decimal" value={premium} onChange={(e) => setPremium(e.target.value)} className="tabular" /></Field>
          <Field label="Taux"><Input value={rate} onChange={(e) => setRate(e.target.value)} className="tabular" /></Field>
          <Field label="N° de police"><Input value={policy} onChange={(e) => setPolicy(e.target.value)} className="tabular" /></Field>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Annuler</Button>
          <Button onClick={() => renew.mutate()} disabled={renew.isPending}><RotateCw /> Renouveler</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function EndDialog({ open, onClose, onConfirm }: { open: boolean; onClose: () => void; onConfirm: (reason: string) => void }) {
  const [reason, setReason] = useState("");
  useEffect(() => setReason(""), [open]);
  const presets = ["Résilié par le client", "Parti chez un concurrent", "Résilié par la compagnie", "Activité arrêtée"];
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>Terminer le contrat</DialogTitle><DialogDescription>Il reste dans l'historique ; ses rappels sont retirés.</DialogDescription></DialogHeader>
        <div className="flex flex-wrap gap-1.5">
          {presets.map((p) => <Button key={p} type="button" size="sm" variant={reason === p ? "secondary" : "outline"} onClick={() => setReason(p)}>{p}</Button>)}
        </div>
        <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Ou écrivez le motif" aria-label="Motif" />
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Annuler</Button>
          <Button variant="destructive" disabled={!reason.trim()} onClick={() => onConfirm(reason.trim())}>Terminer</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ dossier gagné → contrat(s) */

export function WonDialog({ quoteId, clientName, onClose, onDone }: {
  quoteId: number | null; clientName: string; onClose: () => void; onDone: (r: Awaited<ReturnType<typeof api.quoteWin>>) => void;
}) {
  const { data } = useQuery({ queryKey: ["contract-draft", quoteId], queryFn: () => api.quoteContractDraft(quoteId!), enabled: quoteId != null, gcTime: 0 });
  const [items, setItems] = useState<ContractDraftItem[]>([]);
  const [keep, setKeep] = useState<Record<string, boolean>>({});
  useEffect(() => { if (data) { setItems(data.items); setKeep(Object.fromEntries(data.items.map((i) => [i.branch, true]))); } }, [data]);
  const win = useMutation({
    mutationFn: (withContracts: boolean) => api.quoteWin(quoteId!, withContracts ? items.filter((i) => keep[i.branch]) : []),
    onSuccess: onDone, onError: (e) => toastError(e),
  });
  const patch = (b: string, p: Partial<ContractDraftItem>) => setItems((xs) => xs.map((x) => (x.branch === b ? { ...x, ...p } : x)));
  const ren = data?.renewal_of;
  return (
    <Dialog open={quoteId != null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Dossier gagné : {clientName}</DialogTitle>
          <DialogDescription>Enregistrez le contrat signé : l'appli vous rappellera son préavis 2 semaines puis 1 semaine avant la date limite.</DialogDescription>
        </DialogHeader>
        {!data ? <Skeleton className="h-40" /> : (
          <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
            {ren && (
              <p className="rounded-lg border border-primary/30 bg-accent/40 px-3 py-2 text-sm">
                Renouvellement du contrat {ren.policy_number || ""} chez <b>{ren.insurer_name}</b> (échéance {shortDate(ren.end_date)}).
                Même compagnie : le contrat passe à la période suivante. Autre compagnie : il est remplacé par le nouveau.
              </p>
            )}
            {items.map((it) => (
              <div key={it.branch} className="space-y-3 rounded-lg border p-3">
                <label className="flex items-center gap-2 font-medium">
                  <input type="checkbox" className="size-4 accent-primary" checked={!!keep[it.branch]} onChange={(e) => setKeep({ ...keep, [it.branch]: e.target.checked })} />
                  {it.branch}
                </label>
                {keep[it.branch] && (
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="Compagnie retenue" className="sm:col-span-2">
                      <NativeSelect value={it.insurer_id ?? ""} onChange={(e) => {
                        const ch = it.choices.find((x) => String(x.company_id) === e.target.value);
                        patch(it.branch, { insurer_id: ch ? ch.company_id : null, premium: ch?.premium ?? it.premium, rate: ch?.rate ?? it.rate });
                      }}>
                        {it.choices.length === 0 && <option value="">Aucune compagnie consultée</option>}
                        {it.choices.map((x) => <option key={x.company_id} value={x.company_id}>{x.name}{x.premium != null ? ` · ${mad(x.premium)}` : ""}{x.rate ? ` · ${x.rate}` : ""}</option>)}
                      </NativeSelect>
                    </Field>
                    <Field label="Prime (MAD)"><Input inputMode="decimal" value={it.premium ?? ""} onChange={(e) => patch(it.branch, { premium: e.target.value as unknown as number })} className="tabular" /></Field>
                    <Field label="N° de police"><Input value={it.policy_number} onChange={(e) => patch(it.branch, { policy_number: e.target.value })} className="tabular" /></Field>
                    <Field label="Date d'effet"><Input type="date" value={it.start_date ?? ""} onChange={(e) => patch(it.branch, { start_date: e.target.value, end_date: e.target.value ? endFrom(e.target.value) : it.end_date })} /></Field>
                    <Field label="Échéance"><Input type="date" value={it.end_date ?? ""} onChange={(e) => patch(it.branch, { end_date: e.target.value })} /></Field>
                    <Field label="Préavis (jours)"><Input inputMode="numeric" value={it.notice_days} onChange={(e) => patch(it.branch, { notice_days: e.target.value as unknown as number })} className="w-28 tabular" /></Field>
                    <Field label="Commission (%)"><Input inputMode="decimal" value={it.commission_rate ?? ""} onChange={(e) => patch(it.branch, { commission_rate: e.target.value as unknown as number })} className="w-28 tabular" /></Field>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        <DialogFooter className="gap-2 sm:justify-between">
          <Button variant="ghost" onClick={() => win.mutate(false)} disabled={win.isPending}>Gagné, sans contrat pour l'instant</Button>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onClose}>Annuler</Button>
            <Button onClick={() => win.mutate(true)} disabled={win.isPending || !data || !items.some((i) => keep[i.branch] && i.insurer_id && i.end_date)}>
              <FileCheck2 /> Enregistrer et marquer gagné
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
