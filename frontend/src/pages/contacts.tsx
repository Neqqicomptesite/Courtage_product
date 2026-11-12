import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownLeft, ArrowUpRight, Ban, CalendarPlus, StickyNote, Download, ExternalLink, FileSpreadsheet, Linkedin, Mail, MoreHorizontal, Paperclip, Pencil,
  ListChecks, Phone, Rocket, RotateCcw, Search, Send, ShieldOff, Trash2, Upload, UserCheck, UserMinus, UserPlus, Users, X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { openComposer } from "@/components/composer";
import { openSendSequence } from "@/components/send-sequence";
import { ContactForm } from "@/components/contact-form";
import { BackButton, ConfirmDialog, ContactStatus, KindBadge, EmptyState, EnrollmentStatus, PageHeader, ReliabilityDot, toastError, useDebounced } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, api, type ContactDetail, type ContactList, type Kind, type Vocab } from "@/lib/api";
import { formatDayTime, fullName, lot } from "@/lib/format";
import { KindCards } from "@/components/kind-cards";
import { AddToListMenu } from "@/pages/lists";
import { RemindersPanel, openReminder } from "@/pages/agenda";
import { DEPARTMENTS, SENIORITIES } from "@/pages/companies";
import { QuotesPanel } from "@/pages/quotes";
import { ContractsPanel } from "@/pages/contracts";
import { cn, safeUrl } from "@/lib/utils";
import { useMe } from "@/pages/login";

/** V2.23 : une personne qui a répondu peut encore recevoir une séquence envoyée à l'unité (P2 après le rendez-vous). */
const canSend = (status: string) => status === "active" || status === "replied";

// V2.18 : les filtres suivent l'onglet choisi (Prospects : fonction, secteur… ; Assureurs : compagnie,
// service, niveau ; Clients et Partenaires : entreprise). Changer d'onglet retire les filtres qui n'y ont plus de sens.
type FilterDef = { key: string; label: string };
const STATUS_F = { key: "status", label: "Statut" };
const CAMPAIGN_F = { key: "campaign_id", label: "Campagne" };
const FILTERS_BY_KIND: Record<string, FilterDef[]> = {
  "": [STATUS_F, CAMPAIGN_F],
  prospect: [STATUS_F, { key: "target_segment", label: "Fonction" }, { key: "sector_family", label: "Secteur" }, CAMPAIGN_F],
  insurer: [{ key: "company_id", label: "Compagnie" }, { key: "department", label: "Service" }, { key: "seniority", label: "Niveau" }, STATUS_F],
  client: [{ key: "company_id", label: "Entreprise" }, STATUS_F, CAMPAIGN_F],
  partner: [{ key: "company_id", label: "Entreprise" }, STATUS_F, CAMPAIGN_F],
};
const KEEP_PARAMS = ["q", "kind", "open", "new", "owner", "list_id"];

/** V3 : « Suivi par » d'un prospect (appli en ligne). */
function OwnerBadge({ owner }: { owner?: { name: string; me: boolean } | null }) {
  if (!owner) return null;
  return <Badge variant={owner.me ? "info" : "secondary"} className="font-normal">{owner.me ? "Suivi par vous" : `Suivi par ${owner.name}`}</Badge>;
}

/** V3 : l'administrateur attribue des contacts à un employé (ou les libère). */
function AssignMenu({ ids, onDone, size = "sm" }: { ids: number[]; onDone?: () => void; size?: "sm" | "icon" }) {
  const me = useMe();
  const qc = useQueryClient();
  const { data: team } = useQuery({ queryKey: ["team"], queryFn: api.team, enabled: !!me?.server_mode && me.role === "admin" });
  const assign = useMutation({
    mutationFn: (uid: number | null) => api.contactsSetOwner(ids, uid),
    onSuccess: (r, uid) => {
      toast.success(uid === null ? `${r.updated} contact${r.updated > 1 ? "s" : ""} libéré${r.updated > 1 ? "s" : ""}` : `${r.updated} contact${r.updated > 1 ? "s" : ""} attribué${r.updated > 1 ? "s" : ""}`);
      qc.invalidateQueries({ queryKey: ["contacts"] });
      qc.invalidateQueries({ queryKey: ["contact"] });
      onDone?.();
    },
    onError: (e) => toastError(e),
  });
  if (!me?.server_mode || me.role !== "admin") return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild><Button size="sm" variant="outline" className={size === "icon" ? "h-8" : undefined}><UserCheck /> Attribuer</Button></DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {(team ?? []).filter((u) => u.active).map((u) => (
          <DropdownMenuItem key={u.id} onSelect={() => assign.mutate(u.id)}>{u.full_name || u.email}</DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => assign.mutate(null)}>Personne (prospect libre)</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function optionsFor(o: ContactList["options"] | undefined, key: string, kind: string): { value: string; label: string }[] {
  if (!o) return [];
  if (key === "company_id") return o.companies_by_kind?.[kind as Kind] ?? [];
  if (key === "department") return (o.department ?? []).map((v) => ({ value: v, label: DEPARTMENTS.find((d) => d.value === v)?.label ?? v }));
  if (key === "seniority") return (o.seniority ?? []).map((v) => ({ value: v, label: SENIORITIES.find((d) => d.value === v)?.label ?? v }));
  const v = (o as unknown as Record<string, (string | { value: string; label: string })[]>)[key === "campaign_id" ? "campaigns" : key] ?? [];
  return v.map((x) => (typeof x === "string" ? { value: x, label: x } : x));
}


export function ContactsPage() {
  const me = useMe();
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const [q, setQ] = useState(params.get("q") ?? "");
  const filters = useMemo(() => {
    const f: Record<string, string> = {};
    params.forEach((v, k) => !["open", "new", "company", "email", "first_name", "last_name", ...(params.get("new") ? ["department"] : [])].includes(k) && v && (f[k] = v));
    return f;
  }, [params]);
  const { data } = useQuery({ queryKey: ["contacts", filters], queryFn: () => api.contacts(filters), placeholderData: (p) => p });
  const openId = params.get("open") ? Number(params.get("open")) : null;
  const creating = params.get("new") === "1";
  // V2.21 : « Ajouter une personne » depuis la fiche d'une entreprise : on y revient ensuite
  const qcList = useQueryClient();
  const closeNew = (id?: number) => {
    const back = (location.state as { back?: string } | null)?.back;
    if (back) { void qcList.invalidateQueries(); navigate(back, { replace: true }); return; }
    setParams((p) => {
      const n = new URLSearchParams(p);
      ["new", "company", "email", "first_name", "last_name", "department"].forEach((k) => n.delete(k));
      if (id) n.set("open", String(id));
      return n;
    }, { replace: true });
  };

  const setParam = (k: string, v: string) => setParams((p) => {
    const n = new URLSearchParams(p);
    if (v) n.set(k, v); else n.delete(k);
    return n;
  }, { replace: true });
  const debouncedQ = useDebounced((v: string) => setParam("q", v.trim()), 300);
  const active = Object.keys(filters).filter((k) => k !== "q" && k !== "kind");
  const isInsurer = filters.kind === "insurer";  // V2.18 : colonnes Service et Niveau pour les assureurs
  const serverMode = !!useMe()?.server_mode;
  // V2.11 : sélection multiple (envoyer une séquence, ajouter un rappel à plusieurs personnes)
  const [sel, setSel] = useState<Set<number>>(new Set());
  const rows = data?.items ?? [];
  const chosen = rows.filter((c) => sel.has(c.id));
  const allShown = rows.length > 0 && rows.every((c) => sel.has(c.id));
  const toggle = (id: number) => setSel((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const toggleAll = () => setSel((s) => { const n = new Set(s); rows.forEach((c) => (allShown ? n.delete(c.id) : n.add(c.id))); return n; });
  // V3.6 : listes (filtre, « Ajouter à une liste », « Retirer de la liste » quand on regarde une liste)
  const qc = useQueryClient();
  const { data: lists } = useQuery({ queryKey: ["lists"], queryFn: api.lists });
  const currentList = lists?.items.find((l) => String(l.id) === filters.list_id);
  const removeFromList = useMutation({
    mutationFn: () => api.listRemove(currentList!.id, chosen.map((c) => c.id)),
    onSuccess: (r) => { toast.success(`${r.removed} retiré${r.removed > 1 ? "s" : ""} de « ${r.name} »`); setSel(new Set()); qc.invalidateQueries({ queryKey: ["contacts"] }); qc.invalidateQueries({ queryKey: ["lists"] }); },
    onError: (e) => toastError(e),
  });

  // V4 : quand on regarde une liste, la page devient celle de la liste : son nom, ses chiffres,
  // ses actions ; les compteurs généraux (« 256 prospects »…) et les boutons de la page Contacts disparaissent
  const inList = !!filters.list_id;
  const listShown = currentList ? currentList.count : null;
  // V3.9 : les campagnes lancées sur cette liste
  const { data: allCamps } = useQuery({ queryKey: ["campaigns"], queryFn: api.campaigns, enabled: inList });
  const listCamps = (allCamps ?? []).filter((c) => !c.direct && c.filters?.list_id === filters.list_id);
  return (
    <>
      {inList ? (
        <PageHeader back={<BackButton to="/contacts/lists" label="Listes" />}
          title={currentList ? currentList.name : "Liste"}
          description={currentList ? <>
            {listShown} contact{listShown === 1 ? "" : "s"}{currentList.lot ? ` · lot ${currentList.lot}` : ""}
            {` · ${currentList.shared ? "partagée avec l'équipe" : "perso"}`}
            {currentList.assigned_by && currentList.mine ? ` · confiée par ${currentList.assigned_by}` : ""}
            {listCamps.length > 0 && (
              <span className="mt-1 block">Campagne{listCamps.length > 1 ? "s" : ""} sur cette liste :{" "}
                {listCamps.map((c, i) => <span key={c.id}>{i > 0 ? ", " : ""}<Link to={`/campaigns/${c.id}`} className="text-primary hover:underline">{c.name}</Link>{c.status === "draft" ? " (brouillon)" : c.status === "paused" ? " (en pause)" : c.status === "finished" ? " (terminée)" : ""}</span>)}
              </span>
            )}
          </> : undefined}
          actions={<>
            <Button variant="ghost" onClick={() => setParam("list_id", "")}><X /> Voir tous les contacts</Button>
            {currentList && <Button disabled={!currentList.count} onClick={() => navigate(`/campaigns/new?list_id=${currentList.id}`)}><Send /> Envoyer une séquence</Button>}
          </>} />
      ) : (
      <PageHeader title="Contacts" description={data ? `${data.total} contacts au total` : undefined}
        actions={<>
          <Button variant="ghost" asChild><Link to="/contacts/exclusions"><ShieldOff /> Exclusions</Link></Button>
          <Button variant="outline" asChild><Link to="/contacts/lists"><ListChecks /> Listes</Link></Button>
          {me && (!me.server_mode || me.role === "admin") && <Button variant="outline" asChild><Link to="/contacts/prospecting"><Search /> Trouver des prospects</Link></Button>}
          <Button variant="outline" asChild><a href="/api/export"><Download /> Exporter</a></Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button variant="outline"><Upload /> Importer</Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem asChild><Link to="/contacts/import"><Upload /> Importer un fichier Excel ou CSV</Link></DropdownMenuItem>
              <DropdownMenuItem asChild><a href="/api/contacts/template" download><FileSpreadsheet /> Télécharger le modèle Excel</a></DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button onClick={() => setParam("new", "1")}><UserPlus /> Nouveau contact</Button>
        </>} />
      )}

      {data && !inList && <KindCards counts={data.kind_counts} value={filters.kind ?? ""} allLabel="Tous les contacts"
        onChange={(k) => setParams((p) => {
          const allowed = new Set([...KEEP_PARAMS, ...(FILTERS_BY_KIND[k] ?? []).map((f) => f.key)]);
          const n = new URLSearchParams();
          p.forEach((v, key) => allowed.has(key) && n.set(key, v));
          if (k) n.set("kind", k); else n.delete("kind");
          return n;
        }, { replace: true })} />}
      <div className="mb-4 space-y-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-9" value={q} placeholder="Rechercher un nom, une entreprise, un email…"
            onChange={(e) => { setQ(e.target.value); debouncedQ(e.target.value); }} />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {(FILTERS_BY_KIND[filters.kind ?? ""] ?? FILTERS_BY_KIND[""]).map((f) => {
            const opts = optionsFor(data?.options, f.key, filters.kind ?? "");
            if (!opts.length) return null;
            const val = filters[f.key] ?? "";
            return (
              <NativeSelect key={f.key} value={val} onChange={(e) => setParam(f.key, e.target.value)}
                className={cn("h-8 w-auto rounded-full pr-8 text-xs", val && "border-primary bg-accent font-medium text-accent-foreground")}>
                <option value="">{f.label}</option>
                {opts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </NativeSelect>
            );
          })}
          {lists && lists.items.length > 0 && (
            <NativeSelect value={filters.list_id ?? ""} onChange={(e) => setParam("list_id", e.target.value)} aria-label="Liste"
              className={cn("h-8 w-auto max-w-[16rem] rounded-full pr-8 text-xs", filters.list_id && "border-primary bg-accent font-medium text-accent-foreground")}>
              <option value="">Toutes les listes</option>
              {lists.items.map((l) => <option key={l.id} value={String(l.id)}>{l.name} ({l.count})</option>)}
            </NativeSelect>
          )}
          {serverMode && (
            <NativeSelect value={filters.owner ?? ""} onChange={(e) => setParam("owner", e.target.value)} aria-label="Suivi par"
              className={cn("h-8 w-auto rounded-full pr-8 text-xs", filters.owner && "border-primary bg-accent font-medium text-accent-foreground")}>
              <option value="">Suivi : tout le monde</option>
              <option value="me">Mes prospects</option>
              <option value="none">Prospects libres</option>
            </NativeSelect>
          )}
          {active.length > 0 && (
            <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={() => { setQ(""); setParams({}, { replace: true }); }}><X /> Effacer les filtres</Button>
          )}
          {data && <span className="ml-auto text-xs text-muted-foreground tabular">{data.items.length} affiché{data.items.length > 1 ? "s" : ""}</span>}
        </div>
      </div>

      {!data ? <Skeleton className="h-96 rounded-xl" /> : data.total === 0 ? (
        <EmptyState icon={Users} title="Aucun contact" text="Importez votre fichier Excel de prospects : l'application reconnaît les colonnes toute seule."
          action={<div className="flex flex-wrap justify-center gap-2">
            <Button asChild><Link to="/contacts/import"><Upload /> Importer un fichier</Link></Button>
            <Button variant="outline" asChild><a href="/api/contacts/template" download><FileSpreadsheet /> Modèle Excel</a></Button>
            <Button variant="outline" onClick={() => setParam("new", "1")}><UserPlus /> Ajouter à la main</Button>
          </div>} />
      ) : data.items.length === 0 ? (
        <EmptyState icon={Search} title="Aucun contact ne correspond" text="Essayez d'autres filtres." />
      ) : (
        <Card className="relative overflow-hidden">
          {sel.size > 0 && (
            <div className="flex flex-wrap items-center gap-2 border-b bg-primary/5 px-4 py-2 text-sm">
              <span className="font-medium">{sel.size} sélectionné{sel.size > 1 ? "s" : ""}</span>
              <span className="flex-1" />
              <Button size="sm" onClick={() => openSendSequence({ contacts: chosen.filter((c) => canSend(c.status)) })} disabled={!chosen.some((c) => canSend(c.status))}>
                <Send /> {inList ? "Envoyer à la sélection" : "Envoyer une séquence"}
              </Button>
              <Button size="sm" variant="outline" onClick={() => openReminder({ contacts: chosen })}><CalendarPlus /> Ajouter un rappel</Button>
              <AssignMenu ids={chosen.map((c) => c.id)} onDone={() => setSel(new Set())} />
              <AddToListMenu ids={chosen.map((c) => c.id)} onDone={() => setSel(new Set())} />
              {currentList?.editable && (
                <Button size="sm" variant="outline" onClick={() => removeFromList.mutate()}><X /> Retirer de « {currentList.name} »</Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => setSel(new Set())}><X /> Désélectionner</Button>
            </div>
          )}
          {/* Tableau sur grand écran, cartes empilées sur téléphone */}
          <div className="hidden max-h-[calc(100vh-17rem)] overflow-auto md:block">
            <table className="w-full text-sm">
              <thead className="sticky top-0 z-10 bg-card text-left text-xs text-muted-foreground shadow-[0_1px_0_hsl(var(--border))]">
                <tr>
                  <th className="w-10 py-2.5 pl-4"><input type="checkbox" className="accent-[hsl(var(--primary))]" checked={allShown} onChange={toggleAll} aria-label="Tout sélectionner" /></th>
                  {(isInsurer ? ["Contact", "Email", "Compagnie", "Service", "Niveau", "Statut"] : ["Contact", "Email", "Entreprise", "Profil", "Lot", "Qualité email", "Statut"]).map((h) => <th key={h} className="px-4 py-2.5 font-medium">{h}</th>)}
                </tr>
              </thead>
              <tbody className="divide-y">
                {data.items.map((c) => (
                  <tr key={c.id} onClick={() => setParam("open", String(c.id))}
                    className={cn("cursor-pointer transition-colors hover:bg-accent/40", openId === c.id && "bg-accent/60", sel.has(c.id) && "bg-primary/5")}>
                    <td className="py-2.5 pl-4" onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" className="accent-[hsl(var(--primary))]" checked={sel.has(c.id)} onChange={() => toggle(c.id)} aria-label={`Sélectionner ${fullName(c)}`} />
                    </td>
                    <td className="max-w-[16rem] px-4 py-2.5">
                      <div className="truncate font-medium">{fullName(c)}</div>
                      {c.job_title && <div className="truncate text-xs text-muted-foreground">{c.job_title}</div>}
                      {c.owner && <div className="mt-1"><OwnerBadge owner={c.owner} /></div>}
                    </td>
                    {/* V3.5 : l'adresse en clair (barrée si elle a rebondi) */}
                    <td className="max-w-[16rem] px-4 py-2.5" title={c.status === "bounced" ? "Adresse invalide : un email a rebondi" : c.email}>
                      <span className={cn("block truncate text-xs", c.status === "bounced" ? "text-destructive line-through" : "text-muted-foreground")}>{c.email}</span>
                    </td>
                    <td className="max-w-[14rem] px-4 py-2.5">
                      <div className="flex items-center gap-1.5">
                        {c.company_id ? <Link to={`/companies/${c.company_id}`} onClick={(e) => e.stopPropagation()} className="truncate hover:text-primary hover:underline">{c.company}</Link> : <span className="truncate">{c.company}</span>}
                        <KindBadge kind={c.kind} hideProspect />
                      </div>
                    </td>
                    {isInsurer ? <>
                      <td className="px-4 py-2.5 text-xs text-muted-foreground">{DEPARTMENTS.find((d) => d.value === c.department)?.label}</td>
                      <td className="px-4 py-2.5 text-xs text-muted-foreground">{SENIORITIES.find((d) => d.value === c.seniority)?.label}</td>
                    </> : <>
                      <td className="px-4 py-2.5"><code className="text-xs text-muted-foreground">{c.sequence_code}</code></td>
                      <td className="px-4 py-2.5 text-xs text-muted-foreground">{c.lot_number ? `Lot ${c.lot_number}` : lot(c.wave)}</td>
                      <td className="px-4 py-2.5"><ReliabilityDot value={c.reliability} /></td>
                    </>}
                    <td className="px-4 py-2.5"><ContactStatus status={c.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="divide-y md:hidden">
            {data.items.map((c) => (
              <div key={c.id} className="flex items-center gap-3 p-4">
                <input type="checkbox" className="accent-[hsl(var(--primary))]" checked={sel.has(c.id)} onChange={() => toggle(c.id)} aria-label={`Sélectionner ${fullName(c)}`} />
                <button onClick={() => setParam("open", String(c.id))} className="min-w-0 flex-1 text-left">
                  <div className="flex items-center justify-between gap-2"><span className="truncate font-medium">{fullName(c)}</span><ContactStatus status={c.status} /></div>
                  <p className="truncate text-xs text-muted-foreground">{c.company} · {c.sequence_code}</p>
                </button>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Dialog open={openId !== null} onOpenChange={(o) => {
        if (o) return;
        // V2.13 : fiche ouverte depuis une entreprise, l'agenda ou la boîte mail -> on y revient
        const back = (location.state as { back?: string } | null)?.back;
        if (back) navigate(back); else setParam("open", "");
      }}>
        <DialogContent side="right" aria-describedby={undefined}>
          {/* titre pour les lecteurs d'écran le temps que la liste charge (avertissement Radix) */}
          {openId !== null && !data && <DialogTitle className="sr-only">Contact</DialogTitle>}
          {openId !== null && data && <ContactSheet key={openId} id={openId} vocab={data.vocab} companies={data.companies} companyKinds={data.company_kinds} onClosed={() => setParam("open", "")} />}
        </DialogContent>
      </Dialog>

      <Dialog open={creating} onOpenChange={(o) => !o && closeNew()}>
        <DialogContent side="right" aria-describedby={undefined}>
          <DialogTitle>Nouveau contact</DialogTitle>
          {creating && data && (
            <ContactForm vocab={data.vocab} companies={data.companies} companyKinds={data.company_kinds}
              initial={{ company: params.get("company") ?? "", email: params.get("email") ?? "", first_name: params.get("first_name") ?? "", last_name: params.get("last_name") ?? "", department: params.get("department") ?? "" }}
              onCancel={() => closeNew()}
              onDone={(id) => closeNew(id)}
              onExisting={(id) => closeNew(id)} />
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

/** V3.5 : l'adresse a rebondi. On le dit clairement, et on propose d'enregistrer la bonne adresse
 * (une nouvelle fiche reprend tout ; celle-ci garde son historique). */
function BounceBanner({ c }: { c: ContactDetail }) {
  const qc = useQueryClient();
  const [, setParams] = useSearchParams();
  const [email, setEmail] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: () => api.contactNewAddress(c.id, email.trim()),
    onSuccess: (r) => {
      toast.success("Nouvelle fiche créée avec la bonne adresse");
      qc.invalidateQueries({ queryKey: ["contacts"] });
      setParams((p) => { p.set("open", String(r.id)); return p; });
    },
    onError: (e) => setErr(e instanceof ApiError ? (e.fields?.email ?? e.message) : String(e)),
  });
  return (
    <div className="space-y-3 rounded-xl border border-destructive/40 bg-destructive/5 p-4 text-sm">
      <p className="flex items-start gap-2"><Ban className="mt-0.5 size-4 shrink-0 text-destructive" />
        <span><b>Cette adresse n'est pas la bonne.</b> Un email envoyé à {c.email} a rebondi{c.bounced_at ? ` le ${new Date(c.bounced_at).toLocaleDateString("fr-FR")}` : ""} : elle n'existe pas ou plus.
          Plus aucun email ne lui partira.</span></p>
      <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); setErr(null); create.mutate(); }}>
        <Input className="min-w-[14rem] flex-1 bg-card" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="La bonne adresse, si vous l'avez trouvée" />
        <Button size="sm" className="h-9" disabled={!email.includes("@") || create.isPending}>Créer la fiche avec cette adresse</Button>
      </form>
      {err && <p className="text-xs text-destructive">{err}</p>}
    </div>
  );
}

function ContactSheet({ id, vocab, companies, companyKinds, onClosed }: { id: number; vocab: Vocab; companies: string[]; companyKinds: Record<string, Kind>; onClosed: () => void }) {
  const qc = useQueryClient();
  const { data: c } = useQuery({ queryKey: ["contact", id], queryFn: () => api.contact(id) });
  const [erase, setErase] = useState(false);
  const [editing, setEditing] = useState(false);
  const [enrolling, setEnrolling] = useState(false);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["contact", id] }); qc.invalidateQueries({ queryKey: ["contacts"] }); };

  const act = useMutation({
    mutationFn: (a: "do-not-contact" | "reactivate") => api.contactAction(id, a),
    onSuccess: (_, a) => { toast.success(a === "reactivate" ? "Contact réactivé" : "Contact marqué « Ne plus contacter » : ses séquences sont arrêtées"); refresh(); },
    onError: (e) => toastError(e),
  });
  const del = useMutation({
    mutationFn: (typed: string) => api.contactErase(id, typed),
    onSuccess: () => { toast.success("Contact effacé. Son adresse reste bloquée pour ne jamais être réimportée."); setErase(false); onClosed(); qc.invalidateQueries(); },
    onError: (e) => toastError(e),
  });
  const remove = useMutation({
    mutationFn: (eid: number) => api.removeEnrollment(id, eid),
    onSuccess: () => { toast.success("Retiré de la campagne"); refresh(); },
    onError: (e) => toastError(e),
  });

  if (!c) return <div className="space-y-3"><DialogTitle className="sr-only">Contact</DialogTitle><Skeleton className="h-12" /><Skeleton className="h-64" /></div>;
  if (editing) return (
    <div className="space-y-5">
      <DialogTitle>Modifier {fullName(c)}</DialogTitle>
      <ContactForm contact={c} vocab={vocab} companies={companies} companyKinds={companyKinds} onCancel={() => setEditing(false)} onDone={() => setEditing(false)} />
    </div>
  );
  return (
    <div className="space-y-6">
      <div className="flex items-start gap-3 pr-12">
        <div className="flex size-12 shrink-0 items-center justify-center rounded-full bg-accent text-base font-semibold text-accent-foreground">
          {(c.first_name?.[0] ?? c.email[0]).toUpperCase()}{c.last_name?.[0]?.toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <DialogTitle className="truncate">{fullName(c)}</DialogTitle>
          <p className="truncate text-sm text-muted-foreground">
            {c.job_title}{c.job_title && c.company && " · "}
            {c.company_ref ? <Link to={`/companies/${c.company_ref.id}`} className="font-medium text-foreground hover:text-primary hover:underline">{c.company_ref.name}</Link> : c.company}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5"><KindBadge kind={c.kind} /><ContactStatus status={c.status} />{c.suppressed && <Badge variant="destructive">Adresse bloquée</Badge>}<OwnerBadge owner={c.owner} /></div>
        </div>
        <AssignMenu ids={[c.id]} size="icon" />
        <Button variant="outline" size="sm" className="h-8" onClick={() => setEditing(true)}><Pencil /> Modifier</Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild><Button variant="outline" size="icon" className="size-8" aria-label="Actions"><MoreHorizontal /></Button></DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {c.status === "active" && <DropdownMenuItem onSelect={() => act.mutate("do-not-contact")}><Ban /> Ne plus contacter</DropdownMenuItem>}
            {c.status === "do_not_contact" && <DropdownMenuItem onSelect={() => act.mutate("reactivate")}><RotateCcw /> Réactiver</DropdownMenuItem>}
            <DropdownMenuSeparator />
            <DropdownMenuItem destructive onSelect={() => setErase(true)}><Trash2 /> Effacer définitivement</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {c.status === "bounced" && <BounceBanner c={c} />}
      {/* V3.6 : ses listes */}
      {c.lists && c.lists.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <ListChecks className="size-3.5 text-muted-foreground" />
          {c.lists.map((l) => <Link key={l.id} to={`/contacts?list_id=${l.id}`} className="rounded-full border px-2 py-0.5 hover:bg-accent">{l.name}</Link>)}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {canSend(c.status) && !c.suppressed && <Button size="sm" onClick={() => openSendSequence({ contacts: [c] })}><Send /> Envoyer une séquence</Button>}
        <Button size="sm" variant="outline" onClick={() => openComposer({ to: c.email })} title="Écrire depuis l'application"><Mail /> {c.email}</Button>
        {c.phone && <Button size="sm" variant="outline" asChild><a href={`tel:${c.phone}`}><Phone /> {c.phone}</a></Button>}
        {safeUrl(c.linkedin_url) && <Button size="sm" variant="outline" asChild><a href={safeUrl(c.linkedin_url)} target="_blank" rel="noreferrer noopener"><Linkedin /> LinkedIn</a></Button>}
        {safeUrl(c.website) && <Button size="sm" variant="outline" asChild><a href={safeUrl(c.website)} target="_blank" rel="noreferrer noopener"><ExternalLink /> Site</a></Button>}
      </div>

      {/* Service et niveau (assureurs) restent visibles ; le reste du fichier importé est replié */}
      {(c.department || c.seniority) && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-xl border p-4 text-sm">
          {[["Service", DEPARTMENTS.find((d) => d.value === c.department)?.label], ["Niveau", SENIORITIES.find((d) => d.value === c.seniority)?.label]].map(([k, v]) => v ? (
            <div key={k as string} className="min-w-0"><dt className="text-xs text-muted-foreground">{k}</dt><dd className="truncate">{v}</dd></div>
          ) : null)}
        </dl>
      )}
      {(() => {
        const infos = ([["Profil", c.sequence_code], ["Lot d'envoi", c.lot_number ? `Lot ${c.lot_number}${c.wave ? ` · ${lot(c.wave)}` : ""}` : lot(c.wave)], ["Fonction", c.target_segment], ["Secteur", c.sector_family],
          ["Activité", c.sector], ["Taille", c.size_bucket], ["Qualité de l'email", c.email_reliability_detail]] as [string, string | null | undefined][])
          .filter(([, v]) => v).concat(c.custom.map((f) => [f.label, f.value] as [string, string]));
        if (!infos.length) return null;
        return (
          <details className="rounded-lg border px-3 py-2 text-sm">
            <summary className="cursor-pointer select-none text-xs text-muted-foreground hover:text-foreground">
              Plus d'informations ({infos.length})
            </summary>
            <dl className="mt-2 grid gap-x-6 gap-y-2 sm:grid-cols-2">
              {infos.map(([k, v]) => (
                <div key={k} className="min-w-0"><dt className="text-xs text-muted-foreground">{k}</dt><dd className="whitespace-pre-wrap break-words">{v}</dd></div>
              ))}
            </dl>
          </details>
        );
      })()}

      <section className="space-y-2">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-medium">Campagnes</h3>
          {c.status === "active" && !c.suppressed &&
            <Button size="sm" variant="outline" className="h-7" onClick={() => setEnrolling(true)}><Rocket /> Ajouter à une campagne</Button>}
        </div>
        {c.kind !== "prospect" && <p className="text-xs text-muted-foreground">{KIND_NOTE[c.kind]}</p>}
        {c.enrollments.length === 0 && c.kind === "prospect" && <p className="text-xs text-muted-foreground">Dans aucune campagne pour l'instant.</p>}
          {c.enrollments.map((e) => (
            <div key={e.id} className="flex items-center gap-2 rounded-lg border p-3 text-sm">
              <Link to={`/campaigns/${e.campaign.id}`} className="min-w-0 flex-1 truncate font-medium hover:text-primary">{e.campaign.name}</Link>
              <EnrollmentStatus status={e.status} />
              {e.active && <Button size="icon" variant="ghost" className="size-7" aria-label="Retirer de la campagne" onClick={() => remove.mutate(e.id)}><UserMinus /></Button>}
            </div>
          ))}
      </section>
      <EnrollDialog open={enrolling} onOpenChange={setEnrolling} contactId={c.id} name={fullName(c)} kind={c.kind} />

      {c.kind !== "insurer" && <QuotesPanel contact={{ id: c.id, name: fullName(c), company: c.company_ref }} />}
      {c.kind !== "insurer" && <ContractsPanel contact={{ id: c.id, name: fullName(c), company: c.company_ref }} />}
      <RemindersPanel contact={c} />

      <Notes c={c} />

      <RecentMails email={c.email} />

      <ConfirmDialog open={erase} onOpenChange={setErase} destructive typed="EFFACER" pending={del.isPending}
        title={`Effacer ${fullName(c)} ?`}
        description={<>Toutes ses données et ses emails sont supprimés. Une empreinte de l'adresse est gardée pour qu'elle ne soit jamais réimportée (droit à l'effacement, loi 09-08). <b>Irréversible.</b></>}
        confirmLabel="Effacer définitivement" onConfirm={(v) => del.mutate(v.trim().toUpperCase())} />
    </div>
  );
}

const CATEGORY_LABEL: Record<string, string> = { prospection: "Prospection", gestion: "Gestion", souscription: "Souscription" };
const KIND_NOTE: Record<string, string> = {
  client: "Client : jamais de prospection, mais des séquences de gestion ou de souscription.",
  insurer: "Assureur : jamais de prospection, mais des séquences de gestion ou de souscription.",
  partner: "Partenaire : jamais de prospection, mais des séquences de gestion ou de souscription.",
};

/** Ajouter ce contact à une campagne en cours, avec les mêmes contrôles qu'un lancement. */
export function EnrollDialog({ open, onOpenChange, contactId, name, kind = "prospect" }: { open: boolean; onOpenChange: (o: boolean) => void; contactId: number; name: string; kind?: Kind }) {
  const qc = useQueryClient();
  const { data: all } = useQuery({ queryKey: ["campaigns-open"], queryFn: api.openCampaigns, enabled: open });
  // un client, un assureur ou un partenaire n'entre que dans une campagne de gestion ou de souscription
  const camps = all?.filter((k) => kind === "prospect" || k.category !== "prospection");
  const [campId, setCampId] = useState<number | null>(null);
  const [refusal, setRefusal] = useState<ApiError | null>(null);
  const enroll = useMutation({
    mutationFn: (overlap: boolean) => api.enroll(campId!, contactId, overlap),
    onSuccess: (r) => {
      toast.success(`${name} ajouté à la campagne`, { description: r.paused ? "La campagne est en pause : le premier email partira à sa reprise." : "Premier email à la prochaine plage d'envoi." });
      qc.invalidateQueries({ queryKey: ["contact", contactId] });
      qc.invalidateQueries({ queryKey: ["campaign"] });
      onOpenChange(false);
    },
    onError: (e) => (e instanceof ApiError && e.status === 409 ? setRefusal(e) : toastError(e)),
  });
  useEffect(() => { if (campId === null && camps?.length) setCampId(camps[0].id); }, [camps, campId]);
  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); setRefusal(null); }}>
      <DialogContent>
        <DialogTitle>Ajouter {name} à une campagne</DialogTitle>
        {!camps ? <Skeleton className="h-24" /> : camps.length === 0 ? (
          <p className="text-sm text-muted-foreground">Aucune campagne {kind === "prospect" ? "" : "de gestion ou de souscription "}en cours. <Link to="/campaigns/new" className="text-primary hover:underline">Créer une campagne</Link></p>
        ) : (
          <div className="space-y-2">
            {camps.map((k) => (
              <button key={k.id} onClick={() => { setCampId(k.id); setRefusal(null); }}
                className={cn("flex w-full items-center justify-between rounded-lg border p-3 text-left text-sm", campId === k.id ? "border-primary ring-2 ring-primary/15" : "hover:bg-accent/40")}>
                <span className="font-medium">{k.name} <span className="ml-1 text-xs font-normal text-muted-foreground">{CATEGORY_LABEL[k.category]}</span></span><Badge variant={k.status === "active" ? "success" : "warning"}>{k.status === "active" ? "En cours" : "En pause"}</Badge>
              </button>
            ))}
          </div>
        )}
        {refusal && (
          <div className="space-y-2 rounded-lg border border-warning/40 bg-warning/5 p-3 text-sm">
            <p className="font-medium">{refusal.message}</p>
            {refusal.data.problems && refusal.data.problems.length > 0 && <ul className="text-xs text-muted-foreground">{refusal.data.problems.map((p) => <li key={p}>• {p}</li>)}</ul>}
            {refusal.data.overlap && refusal.data.overlap.length > 0 && <p className="text-xs text-muted-foreground">En cours dans : {refusal.data.overlap.join(", ")}. Il recevrait les emails des deux campagnes.</p>}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Annuler</Button>
          {refusal?.data.overlap?.length ? (
            <Button variant="brand" disabled={enroll.isPending} onClick={() => enroll.mutate(true)}><Rocket /> Ajouter quand même</Button>
          ) : (
            <Button variant="brand" disabled={!campId || enroll.isPending || !!refusal} onClick={() => enroll.mutate(false)}><Rocket /> Ajouter</Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Notes({ c }: { c: ContactDetail }) {
  const [notes, setNotes] = useState(c.notes ?? "");
  const save = useMutation({ mutationFn: (n: string) => api.contactNotes(c.id, n), onError: (e) => toastError(e) });
  const debounced = useDebounced((n: string) => save.mutate(n), 700);
  return (
    <section className="space-y-2">
      <h3 className="flex items-center gap-2 text-sm font-medium"><StickyNote className="size-4 text-muted-foreground" />Notes {save.isPending && <span className="text-xs font-normal text-muted-foreground">enregistrement…</span>}</h3>
      <Textarea rows={3} value={notes} placeholder="Échéance du contrat, assureur actuel, interlocuteur…" onChange={(e) => { setNotes(e.target.value); debounced(e.target.value); }} />
    </section>
  );
}

/** V2.14 : les derniers emails échangés avec la personne (boîte de réception et Envoyés).
 *  Un clic ouvre l'email dans la boîte mail. */
function RecentMails({ email }: { email: string }) {
  const { data, isLoading, error } = useQuery({ queryKey: ["mail", "with", email], queryFn: () => api.mailsWith(email), retry: false, staleTime: 60_000 });
  const location = useLocation();
  return (
    <section className="space-y-2">
      <h3 className="flex items-center gap-2 text-sm font-medium"><Mail className="size-4 text-muted-foreground" />Derniers emails</h3>
      {isLoading ? <Skeleton className="h-20 rounded-lg" /> : error ? (
        <p className="text-xs text-muted-foreground">Boîte mail injoignable pour l'instant.</p>
      ) : !data?.items.length ? (
        <p className="text-xs text-muted-foreground">Aucun email échangé ces 12 derniers mois.</p>
      ) : (
        <ul className="divide-y overflow-hidden rounded-lg border">
          {data.items.map((m) => (
            <li key={`${m.folder}-${m.uid}`}>
              <Link to={`/inbox?folder=${encodeURIComponent(m.folder)}&days=365&q=${encodeURIComponent(email)}&uid=${m.uid}`} state={{ back: location.pathname + location.search }}
                className="flex items-center gap-3 px-3 py-2 text-sm transition-colors hover:bg-accent/40">
                {m.direction === "in" ? <ArrowDownLeft className="size-4 shrink-0 text-brand" /> : <ArrowUpRight className="size-4 shrink-0 text-primary" />}
                <span className="min-w-0 flex-1 truncate">{m.subject || "(sans objet)"}</span>
                {m.has_attachments && <Paperclip className="size-3.5 shrink-0 text-muted-foreground" />}
                <span className="shrink-0 text-xs text-muted-foreground">{m.date ? formatDayTime(m.date) : ""}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
