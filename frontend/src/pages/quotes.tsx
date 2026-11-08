// Dossiers de cotation. Vue en colonnes (une par étape, glisser-déposer) ou en
// liste, création d'un dossier (depuis ce bouton, une fiche entreprise / contact ou un email reçu).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CalendarClock, Columns3, FileStack, List, Plus, Search } from "lucide-react";
import { useEffect, useMemo, useState, type DragEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { EmptyState, Field, FieldGroup, PageHeader, fieldError, toastError, useDebounced } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type QuoteStage, type QuoteSummary } from "@/lib/api";
import { cn } from "@/lib/utils";

export const STAGES: { key: QuoteStage; label: string; short: string }[] = [
  { key: "new", label: "Nouveau", short: "Nouveau" },
  { key: "info", label: "Infos client à réunir", short: "Infos client" },
  { key: "consulting", label: "Consultation des compagnies", short: "Consultation" },
  { key: "partial", label: "Offres partielles", short: "Offres partielles" },
  { key: "offers", label: "Toutes les offres reçues", short: "Toutes reçues" },
  { key: "proposed", label: "Proposition envoyée", short: "Proposition" },
  { key: "won", label: "Gagné", short: "Gagné" },
  { key: "lost", label: "Perdu", short: "Perdu" },
];
export const stageLabel = (k: QuoteStage) => STAGES.find((s) => s.key === k)?.label ?? k;
export const STAGE_TONE: Record<QuoteStage, string> = {
  new: "bg-secondary text-secondary-foreground", info: "bg-warning/15 text-warning", consulting: "bg-accent text-accent-foreground",
  partial: "bg-brand/10 text-brand", offers: "bg-brand/15 text-brand", proposed: "bg-primary/10 text-primary", won: "bg-success/10 text-success", lost: "bg-destructive/10 text-destructive",
};

export const mad = (n: number | null | undefined) => (n == null ? "—" : `${n.toLocaleString("fr-FR")} MAD`);
export const shortDate = (iso: string | null) => (iso ? new Date(iso + (iso.length === 10 ? "T12:00:00" : "")).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", year: "numeric" }) : "—");

/** Rappelle la fenêtre « Nouveau dossier » depuis n'importe quel écran (fiche, email…). */
export type NewQuoteRequest = { company?: { id: number; name: string } | null; contact?: { id: number; name: string } | null; client_name?: string };
export function openNewQuote(req: NewQuoteRequest = {}) {
  window.dispatchEvent(new CustomEvent<NewQuoteRequest>("app-new-quote", { detail: req }));
}

export function QuotesPage() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const view = params.get("vue") === "liste" ? "list" : "board";
  const branch = params.get("branche") ?? "";
  const owner = params.get("resp") ?? "";
  const [q, setQ] = useState("");
  const [showClosed, setShowClosed] = useState(false);
  const setParam = (k: string, v: string) => setParams((p) => { const n = new URLSearchParams(p); if (v) n.set(k, v); else n.delete(k); return n; }, { replace: true });
  const { data } = useQuery({ queryKey: ["quotes"], queryFn: () => api.quotes() });
  const { data: people } = useQuery({ queryKey: ["quote-people"], queryFn: api.quotePeople });
  const [lostFor, setLostFor] = useState<QuoteSummary | null>(null);

  const move = useMutation({
    mutationFn: ({ id, stage, lost_reason }: { id: number; stage: QuoteStage; lost_reason?: string }) => api.quoteUpdate(id, { stage, lost_reason }),
    onMutate: async ({ id, stage }) => {
      await qc.cancelQueries({ queryKey: ["quotes"] });
      qc.setQueryData(["quotes"], (old: typeof data) => old && { ...old, items: old.items.map((c) => (c.id === id ? { ...c, stage } : c)) });
    },
    onError: (e) => toastError(e, "Étape non modifiée"),
    onSettled: () => qc.invalidateQueries({ queryKey: ["quotes"] }),
  });
  const onDrop = (c: QuoteSummary, stage: QuoteStage) => {
    if (c.stage === stage) return;
    if (stage === "lost") setLostFor(c);
    else move.mutate({ id: c.id, stage });
  };

  const items = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (data?.items ?? []).filter((c) => (!branch || c.branches.includes(branch)) && (!owner || String(c.owner_id) === owner)
      && (!needle || `${c.ref} ${c.client_name} ${c.title} ${c.branch_label}`.toLowerCase().includes(needle)));
  }, [data, q, branch, owner]);
  const open = items.filter((c) => !["won", "lost"].includes(c.stage));
  const late = open.filter((c) => c.late).length;

  return (
    <>
      <PageHeader title="Dossiers de cotation"
        description={data ? <span>{open.length} dossier{open.length > 1 ? "s" : ""} en cours{late > 0 && <span className="text-destructive"> · {late} en retard</span>}</span> : undefined}
        actions={<Button onClick={() => openNewQuote()}><Plus /> Nouveau dossier</Button>} />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative w-full sm:w-64">
          <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Client, référence…" className="pl-8" aria-label="Rechercher un dossier" />
        </div>
        <NativeSelect className="w-auto" value={branch} onChange={(e) => setParam("branche", e.target.value)} aria-label="Branche">
          <option value="">Toutes les branches</option>
          {(data?.branches ?? []).map((b) => <option key={b} value={b}>{b}</option>)}
        </NativeSelect>
        {(people?.items.length ?? 0) > 1 && (
          <NativeSelect className="w-auto" value={owner} onChange={(e) => setParam("resp", e.target.value)} aria-label="Responsable">
            <option value="">Tous les responsables</option>
            {people!.items.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </NativeSelect>
        )}
        <div className="ml-auto flex rounded-md border bg-card p-0.5">
          <Button size="sm" variant={view === "board" ? "secondary" : "ghost"} onClick={() => setParam("vue", "")}><Columns3 /> Colonnes</Button>
          <Button size="sm" variant={view === "list" ? "secondary" : "ghost"} onClick={() => setParam("vue", "liste")}><List /> Liste</Button>
        </div>
      </div>

      {!data ? <Skeleton className="h-96 rounded-xl" /> : data.items.length === 0 ? (
        <EmptyState icon={FileStack} title="Aucun dossier pour l'instant"
          text="Un dossier suit une demande de cotation : la fiche du client, les documents, les compagnies consultées et leurs offres."
          action={<Button onClick={() => openNewQuote()}><Plus /> Créer le premier dossier</Button>} />
      ) : view === "board" ? (
        <Board items={items} showClosed={showClosed} setShowClosed={setShowClosed} onDrop={onDrop} />
      ) : (
        <QuoteTable items={items} />
      )}

      <LostDialog quote={lostFor} onClose={() => setLostFor(null)}
        onConfirm={(reason) => { if (lostFor) move.mutate({ id: lostFor.id, stage: "lost", lost_reason: reason }); setLostFor(null); }} />
    </>
  );
}

function Board({ items, showClosed, setShowClosed, onDrop }: {
  items: QuoteSummary[]; showClosed: boolean; setShowClosed: (v: boolean) => void; onDrop: (c: QuoteSummary, s: QuoteStage) => void;
}) {
  const [over, setOver] = useState<QuoteStage | null>(null);
  const cols = STAGES.filter((s) => showClosed || !["won", "lost"].includes(s.key));
  const closed = items.filter((c) => ["won", "lost"].includes(c.stage)).length;
  const drop = (e: DragEvent, stage: QuoteStage) => {
    e.preventDefault();
    setOver(null);
    const id = Number(e.dataTransfer.getData("text/quote"));
    const c = items.find((x) => x.id === id);
    if (c) onDrop(c, stage);
  };
  return (
    <>
      <div className="-mx-4 overflow-x-auto px-4 pb-2 sm:-mx-6 sm:px-6">
        <div className={cn("grid grid-flow-col gap-3", showClosed ? "auto-cols-[minmax(12rem,1fr)]" : "auto-cols-[minmax(10.5rem,1fr)]")}>
          {cols.map((s) => {
            const here = items.filter((c) => c.stage === s.key);
            return (
              <div key={s.key} onDragOver={(e) => { e.preventDefault(); setOver(s.key); }} onDragLeave={() => setOver(null)} onDrop={(e) => drop(e, s.key)}
                className={cn("flex min-w-0 flex-col rounded-xl border bg-muted/40 transition-colors", over === s.key && "border-primary bg-accent/60")}>
                <div className="flex items-center justify-between px-3 py-2.5">
                  <span className="text-sm font-medium leading-tight">{s.short}</span>
                  <span className="rounded-full bg-background px-2 text-xs tabular text-muted-foreground">{here.length}</span>
                </div>
                <div className="flex min-h-24 flex-1 flex-col gap-2 px-2 pb-2">
                  {here.map((c) => <QuoteCard key={c.id} c={c} />)}
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <button className="mt-2 text-xs text-muted-foreground hover:text-foreground hover:underline" onClick={() => setShowClosed(!showClosed)}>
        {showClosed ? "Masquer les dossiers clos" : `Afficher les dossiers clos (${closed})`}
      </button>
    </>
  );
}

function InsurerProgress({ c }: { c: QuoteSummary }) {
  if (!c.insurers) return <span className="text-muted-foreground">Aucune compagnie</span>;
  const answered = c.insurer_counts.replied + c.insurer_counts.offer + c.insurer_counts.declined;
  const sent = c.insurers - c.insurer_counts.to_send;
  return (
    <span>{c.insurer_counts.offer > 0 ? <b className="font-medium text-brand">{c.insurer_counts.offer} offre{c.insurer_counts.offer > 1 ? "s" : ""}</b> : `${answered}/${sent || c.insurers} réponse${answered > 1 ? "s" : ""}`}
      <span className="text-muted-foreground"> · {c.insurers} cie{c.insurers > 1 ? "s" : ""}</span></span>
  );
}

function QuoteCard({ c }: { c: QuoteSummary }) {
  return (
    <Link to={`/quotes/${c.id}`} draggable onDragStart={(e) => { e.dataTransfer.setData("text/quote", String(c.id)); e.dataTransfer.effectAllowed = "move"; }}
      className="block rounded-lg border bg-card p-3 text-sm shadow-sm transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 font-medium leading-snug">{c.client_name}</p>
        <span className="shrink-0 text-[11px] tabular text-muted-foreground">{c.ref.replace(/^COT-\d{4}-/, "#")}</span>
      </div>
      <p className="mt-0.5 text-xs text-muted-foreground">{c.branch_label}</p>
      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        <InsurerProgress c={c} />
        {c.missing > 0 && <span className="inline-flex items-center gap-1 text-warning"><AlertTriangle className="size-3" />{c.missing} info{c.missing > 1 ? "s" : ""}</span>}
      </div>
      {(c.due_on || c.owner_name) && (
        <div className="mt-2 flex items-center justify-between gap-2 border-t pt-2 text-xs text-muted-foreground">
          {c.due_on ? <span className={cn("inline-flex items-center gap-1", c.late && "font-medium text-destructive")}><CalendarClock className="size-3" />{shortDate(c.due_on)}</span> : <span />}
          {c.owner_name && <span className="truncate">{c.owner_name}</span>}
        </div>
      )}
      {c.stage === "lost" && c.lost_reason && <p className="mt-1.5 text-xs text-destructive">{c.lost_reason}</p>}
    </Link>
  );
}

function QuoteTable({ items }: { items: QuoteSummary[] }) {
  const navigate = useNavigate();
  return (
    <Card className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="border-b text-left text-xs text-muted-foreground">
          <tr>
            <th className="px-4 py-2.5 font-medium">Dossier</th><th className="px-3 py-2.5 font-medium">Branche</th>
            <th className="px-3 py-2.5 font-medium">Étape</th><th className="px-3 py-2.5 font-medium">Compagnies</th>
            <th className="px-3 py-2.5 font-medium">Meilleure offre</th><th className="px-3 py-2.5 font-medium">Attendu le</th>
            <th className="px-3 py-2.5 font-medium">Responsable</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {items.map((c) => (
            <tr key={c.id} className="cursor-pointer hover:bg-muted/50" onClick={() => navigate(`/quotes/${c.id}`)}>
              <td className="px-4 py-2.5"><p className="font-medium">{c.client_name}</p><p className="text-xs text-muted-foreground tabular">{c.ref}</p></td>
              <td className="px-3 py-2.5">{c.branch_label}</td>
              <td className="px-3 py-2.5"><span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", STAGE_TONE[c.stage])}>{stageLabel(c.stage)}</span></td>
              <td className="px-3 py-2.5 text-xs"><InsurerProgress c={c} /></td>
              <td className="px-3 py-2.5 tabular">{mad(c.best_offer)}</td>
              <td className={cn("px-3 py-2.5 tabular", c.late && "font-medium text-destructive")}>{shortDate(c.due_on)}</td>
              <td className="px-3 py-2.5 text-muted-foreground">{c.owner_name ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {items.length === 0 && <p className="p-6 text-center text-sm text-muted-foreground">Aucun dossier ne correspond aux filtres.</p>}
    </Card>
  );
}

export function LostDialog({ quote, onClose, onConfirm }: { quote: { client_name: string } | null; onClose: () => void; onConfirm: (reason: string) => void }) {
  const [reason, setReason] = useState("");
  useEffect(() => setReason(""), [quote]);
  const presets = ["Prix trop élevé", "Garanties insuffisantes", "Resté chez son assureur", "Pas de réponse du client", "Projet abandonné"];
  return (
    <Dialog open={!!quote} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Dossier perdu : {quote?.client_name}</DialogTitle>
          <DialogDescription>Le motif sert plus tard aux statistiques du cabinet.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-wrap gap-1.5">
          {presets.map((p) => <Button key={p} type="button" size="sm" variant={reason === p ? "secondary" : "outline"} onClick={() => setReason(p)}>{p}</Button>)}
        </div>
        <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Ou écrivez le motif" aria-label="Motif" />
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Annuler</Button>
          <Button variant="destructive" disabled={!reason.trim()} onClick={() => onConfirm(reason.trim())}>Marquer perdu</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Fenêtre « Nouveau dossier », montée une fois dans la mise en page (voir layout.tsx). */
export function NewQuoteHost() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  const [company, setCompany] = useState<{ id: number; name: string } | null>(null);
  const [contact, setContact] = useState<{ id: number; name: string } | null>(null);
  const [clientName, setClientName] = useState("");
  const [due, setDue] = useState("");
  const [search, setSearch] = useState("");
  const [needle, setNeedle] = useState("");
  const debounced = useDebounced((v: string) => setNeedle(v.trim()), 250);

  useEffect(() => {
    const on = (e: Event) => {
      const r = (e as CustomEvent<NewQuoteRequest>).detail ?? {};
      setCompany(r.company ?? null); setContact(r.contact ?? null); setClientName(r.client_name ?? "");
      setPicked([]); setDue(""); setSearch(""); setNeedle(""); setOpen(true);
    };
    window.addEventListener("app-new-quote", on);
    return () => window.removeEventListener("app-new-quote", on);
  }, []);

  const { data: branches } = useQuery({ queryKey: ["quote-branches"], queryFn: api.quoteBranches, enabled: open });
  const { data: found } = useQuery({ queryKey: ["companies", needle, "pick"], queryFn: () => api.companies({ q: needle }), enabled: open && needle.length >= 2 });
  const create = useMutation({
    mutationFn: () => api.quoteCreate({ branches: picked, company_id: company?.id ?? null, contact_id: contact?.id ?? null,
      client_name: company || contact ? undefined : clientName.trim(), due_on: due || null }),
    onSuccess: (c) => {
      qc.invalidateQueries({ queryKey: ["quotes"] });
      setOpen(false);
      toast.success(`Dossier ${c.ref} créé`);
      navigate(`/quotes/${c.id}`);
    },
    onError: (e) => toastError(e, "Dossier non créé"),
  });

  const clientChosen = company || contact || clientName.trim();
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Nouveau dossier de cotation</DialogTitle>
          <DialogDescription>Le client, la branche et la date à laquelle il attend sa proposition. Le reste se complète dans le dossier.</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <FieldGroup label="Client" error={fieldError(create.error, "client_name")}>
            {company || contact ? (
              <div className="flex items-center justify-between rounded-md border bg-muted/40 px-3 py-2 text-sm">
                <span><b className="font-medium">{company?.name ?? contact?.name}</b>{company && contact && <span className="text-muted-foreground"> · {contact.name}</span>}</span>
                <Button type="button" size="sm" variant="ghost" onClick={() => { setCompany(null); setContact(null); }}>Changer</Button>
              </div>
            ) : (
              <div className="space-y-2">
                <Input autoFocus value={search} onChange={(e) => { setSearch(e.target.value); setClientName(e.target.value); debounced(e.target.value); }}
                  placeholder="Nom de l'entreprise ou du particulier" />
                {needle.length >= 2 && (found?.items.length ?? 0) > 0 && (
                  <div className="max-h-40 overflow-y-auto rounded-md border">
                    {found!.items.filter((c) => c.kind !== "insurer").slice(0, 8).map((c) => (
                      <button type="button" key={c.id} onClick={() => setCompany({ id: c.id, name: c.name })}
                        className="flex w-full items-center justify-between px-3 py-1.5 text-left text-sm hover:bg-muted">
                        {c.name}<span className="text-xs text-muted-foreground">{c.people} contact{c.people > 1 ? "s" : ""}</span>
                      </button>
                    ))}
                  </div>
                )}
                {search.trim() && <p className="text-xs text-muted-foreground">Pas dans la liste ? Le dossier sera créé au nom « {search.trim()} ».</p>}
              </div>
            )}
          </FieldGroup>
          <FieldGroup label="Branche(s)" hint="Plusieurs branches possibles : la fiche regroupe leurs informations, chaque compagnie est consultée par branche." error={fieldError(create.error, "branch")}>
            <div className="flex flex-wrap gap-1.5">
              {(branches?.items ?? []).map((b) => {
                const on = picked.includes(b.name);
                return <Button key={b.name} type="button" size="sm" variant={on ? "default" : "outline"}
                  onClick={() => setPicked((p) => (on ? p.filter((x) => x !== b.name) : [...p, b.name]))}>{b.name}</Button>;
              })}
            </div>
          </FieldGroup>
          <Field label="Proposition attendue par le client le" hint="Facultatif. Le dossier passe en rouge si la date est dépassée.">
            <Input type="date" value={due} onChange={(e) => setDue(e.target.value)} className="w-48" />
          </Field>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>Annuler</Button>
            <Button type="submit" disabled={!picked.length || !clientChosen || create.isPending}>Créer le dossier</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function StageBadge({ stage }: { stage: QuoteStage }) {
  return <Badge variant="outline" className={cn("border-transparent", STAGE_TONE[stage])}>{stageLabel(stage)}</Badge>;
}

/** Dossiers d'une entreprise ou d'un contact (fiches Entreprise et Contact). */
export function QuotesPanel({ company, contact }: { company?: { id: number; name: string }; contact?: { id: number; name: string; company?: { id: number; name: string } | null } }) {
  const f = company ? { company_id: company.id } : { contact_id: contact!.id };
  const { data } = useQuery({ queryKey: ["quotes", f], queryFn: () => api.quotes(f) });
  const items = data?.items ?? [];
  return (
    <Card>
      <div className="flex items-center justify-between px-6 pb-2 pt-5">
        <h3 className="font-semibold leading-none tracking-tight">Dossiers de cotation</h3>
        <Button size="sm" variant="outline" onClick={() => openNewQuote(company ? { company } : { contact: contact!, company: contact!.company ?? null })}><Plus /> Dossier</Button>
      </div>
      <div className="px-6 pb-5">
        {items.length === 0 ? <p className="text-sm text-muted-foreground">Aucun dossier.</p> : (
          <ul className="space-y-2">
            {items.slice(0, 6).map((c) => (
              <li key={c.id}>
                <Link to={`/quotes/${c.id}`} className="flex items-center justify-between gap-2 text-sm hover:text-primary">
                  <span className="min-w-0 truncate">{c.branch_label} <span className="text-xs text-muted-foreground tabular">{c.ref}</span></span>
                  <StageBadge stage={c.stage} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}
