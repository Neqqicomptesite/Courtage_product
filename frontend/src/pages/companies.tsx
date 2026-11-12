import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownLeft, ArrowUpRight, Building2, ExternalLink, GitMerge, Globe, Mail, MoreHorizontal, Pencil, Phone,
  CalendarPlus, ImagePlus, Plus, Search, Send, ShieldCheck, SlidersHorizontal, Trash2, UserPlus,
} from "lucide-react";
import { useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { openComposer } from "@/components/composer";
import { KindCards } from "@/components/kind-cards";
import { ConfirmDialog, ContactStatus, EmptyState, Field, KindBadge, PageHeader, fieldError, toastError, useDebounced, BackButton, useUrlState } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { NativeSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, api, type CompanyDetail, type CompanyInput, type Department, type Kind, type Seniority } from "@/lib/api";
import { RemindersPanel, openReminder } from "@/pages/agenda";
import { QuotesPanel } from "@/pages/quotes";
import { ContractsPanel } from "@/pages/contracts";
import { openSendSequence } from "@/components/send-sequence";
import { formatDayTime, fullName } from "@/lib/format";
import { cn, safeUrl } from "@/lib/utils";

export const KINDS: { value: Kind; label: string; hint: string }[] = [
  { value: "prospect", label: "Prospect", hint: "Peut recevoir des campagnes" },
  { value: "client", label: "Client", hint: "Jamais prospecté ; séquences de gestion possibles" },
  { value: "insurer", label: "Assureur", hint: "Compagnie partenaire, jamais prospectée ; séquences de gestion et de souscription possibles" },
  { value: "partner", label: "Partenaire", hint: "Expert, apporteur, banque… jamais prospecté" },
];
const AVATAR: Record<Kind, string> = {
  prospect: "bg-accent text-accent-foreground", client: "bg-success/15 text-success",
  insurer: "bg-primary text-primary-foreground", partner: "bg-warning/15 text-warning",
};

export const DEPARTMENTS: { value: Department; label: string }[] = [
  { value: "souscription", label: "Souscription" }, { value: "gestion", label: "Gestion" },
  { value: "production", label: "Production" }, { value: "maritime_transport", label: "Maritime / transport" },
  { value: "autre", label: "Autre" },
];
export const SENIORITIES: { value: Seniority; label: string }[] = [
  { value: "directeur", label: "Directeur de département" }, { value: "senior", label: "Senior" }, { value: "junior", label: "Junior" },
];

export function Logo({ name, kind, src, className }: { name: string; kind: Kind; src?: string | null; className?: string }) {
  if (src) {
    return (
      <div className={cn("flex size-10 shrink-0 items-center justify-center overflow-hidden rounded-lg border bg-white p-1", className)}>
        <img src={src} alt={`Logo ${name}`} className="max-h-full max-w-full object-contain" />
      </div>
    );
  }
  const initials = name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  return <div className={cn("flex size-10 shrink-0 items-center justify-center rounded-lg text-sm font-semibold", AVATAR[kind], className)}>{initials || "?"}</div>;
}

/* =============================================================== liste */

export function CompaniesPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const kind = params.get("kind") ?? "";
  const [q, setQ] = useState(params.get("q") ?? "");
  const setParam = (k: string, v: string) => setParams((p) => { const n = new URLSearchParams(p); if (v) n.set(k, v); else n.delete(k); return n; }, { replace: true });
  const debouncedQ = useDebounced((v: string) => setParam("q", v.trim()), 250);
  const { data } = useQuery({ queryKey: ["companies", params.get("q") ?? "", kind], queryFn: () => api.companies({ q: params.get("q") ?? "", kind }), placeholderData: (p) => p });
  const [creating, setCreating] = useState(false);

  return (
    <>
      <PageHeader title="Entreprises" description="Prospects, clients, assureurs et partenaires, avec les personnes de chaque entreprise."
        actions={<Button onClick={() => setCreating(true)}><Plus /> Nouvelle entreprise</Button>} />
      {data && <KindCards counts={Object.fromEntries(data.kinds.map((k) => [k.value, k.count]))} value={kind}
        onChange={(k) => setParam("kind", k)} allLabel="Toutes les entreprises" />}
      <div className="mb-4 space-y-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-9" value={q} placeholder="Nom d'entreprise, domaine, ou une personne : « sanlam », « gestionnaire »…"
            onChange={(e) => { setQ(e.target.value); debouncedQ(e.target.value); }} />
        </div>

      </div>

      {!data ? <Skeleton className="h-96 rounded-xl" /> : data.items.length === 0 ? (
        data.total === 0 ? <EmptyState icon={Building2} title="Aucune entreprise" text="Les entreprises se créent toutes seules à l'import et à la saisie des contacts."
          action={<Button onClick={() => setCreating(true)}><Plus /> Nouvelle entreprise</Button>} />
          : <EmptyState icon={Search} title="Aucune entreprise ne correspond" />
      ) : (
        <Card className="divide-y overflow-hidden">
          {data.items.map((c) => (
            <Link key={c.id} to={`/companies/${c.id}`} className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-accent/40">
              <Logo name={c.name} kind={c.kind} src={c.logo} className="size-9" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2"><span className="truncate font-medium">{c.name}</span><KindBadge kind={c.kind} hideProspect /></div>
                <p className="truncate text-xs text-muted-foreground">{[c.domain, c.sector].filter(Boolean).join(" · ") || "—"}</p>
              </div>
              <span className="shrink-0 text-xs text-muted-foreground tabular">{c.people} personne{c.people > 1 ? "s" : ""}</span>
            </Link>
          ))}
        </Card>
      )}
      <CompanyDialog open={creating} onOpenChange={setCreating} onDone={(id) => navigate(`/companies/${id}`)} />
    </>
  );
}


/** Création ou modification des informations d'une entreprise. */
function CompanyDialog({ open, onOpenChange, company, onDone }: { open: boolean; onOpenChange: (o: boolean) => void; company?: CompanyDetail; onDone?: (id: number) => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const blank: CompanyInput = { name: "", kind: "prospect", domain: "", website: "", phone: "", sector: "" };
  const [v, setV] = useState<CompanyInput>(company ?? blank);
  const set = (k: keyof CompanyInput) => (e: React.ChangeEvent<HTMLInputElement>) => setV((x) => ({ ...x, [k]: e.target.value }));
  const save = useMutation({
    mutationFn: async () => {
      const body = { name: v.name, domain: v.domain, website: v.website, phone: v.phone, sector: v.sector };
      if (company) { await api.companyUpdate(company.id, body); return { id: company.id }; }
      return api.companyCreate({ ...body, kind: v.kind });
    },
    onSuccess: ({ id }) => { qc.invalidateQueries({ queryKey: ["companies"] }); qc.invalidateQueries({ queryKey: ["company", id] }); qc.invalidateQueries({ queryKey: ["contacts"] }); onOpenChange(false); onDone?.(id); },
    onError: (e) => {
      if (e instanceof ApiError && e.existingId) {
        toast.error(e.message, { action: { label: "Ouvrir", onClick: () => { onOpenChange(false); navigate(`/companies/${e.existingId}`); } } });
      } else if (!(e instanceof ApiError && Object.keys(e.fields).length)) toastError(e);
    },
  });
  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (o) setV(company ?? blank); }}>
      <DialogContent>
        <DialogHeader><DialogTitle>{company ? "Modifier l'entreprise" : "Nouvelle entreprise"}</DialogTitle></DialogHeader>
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <Field label="Nom" error={fieldError(save.error, "name")}><Input autoFocus value={v.name ?? ""} onChange={set("name")} required /></Field>
          {!company && <KindPicker value={(v.kind ?? "prospect") as Kind} onChange={(k) => setV((x) => ({ ...x, kind: k }))} />}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Domaine email" hint="ex. sanlam.ma"><Input value={v.domain ?? ""} onChange={set("domain")} /></Field>
            <Field label="Téléphone"><Input value={v.phone ?? ""} onChange={set("phone")} /></Field>
            <Field label="Site web"><Input value={v.website ?? ""} onChange={set("website")} /></Field>
            <Field label="Secteur"><Input value={v.sector ?? ""} onChange={set("sector")} /></Field>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Annuler</Button>
            <Button type="submit" disabled={save.isPending}>{company ? "Enregistrer" : "Créer"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function KindPicker({ value, onChange, hint }: { value: Kind; onChange: (k: Kind) => void; hint?: string }) {
  return (
    <div className="space-y-1.5">
      <span className="text-sm font-medium">Type de relation</span>
      <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
        {KINDS.map((k) => (
          <button key={k.value} type="button" onClick={() => onChange(k.value)} title={k.hint}
            className={cn("rounded-lg border px-3 py-2 text-sm transition-colors", value === k.value ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent")}>
            {k.label}
          </button>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">{hint ?? KINDS.find((k) => k.value === value)?.hint}</p>
    </div>
  );
}

/* =============================================================== fiche */

export function CompanyPage() {
  const location = useLocation();
  const id = Number(useParams().id);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data } = useQuery({ queryKey: ["company", id], queryFn: () => api.company(id) });
  const [editing, setEditing] = useState(false);
  const [kindTo, setKindTo] = useState<Kind | null>(null);
  const [merging, setMerging] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["company", id] }); qc.invalidateQueries({ queryKey: ["companies"] }); qc.invalidateQueries({ queryKey: ["contacts"] }); };

  const setKind = useMutation({
    mutationFn: (k: Kind) => api.companyUpdate(id, { kind: k }),
    onSuccess: (r, k) => {
      setKindTo(null);
      toast.success(`Type : ${KINDS.find((x) => x.value === k)?.label}`, { description: r.stopped ? `${r.stopped} séquence${r.stopped > 1 ? "s" : ""} en cours arrêtée${r.stopped > 1 ? "s" : ""}.` : undefined });
      refresh();
    },
    onError: (e) => toastError(e),
  });
  const notes = useMutation({ mutationFn: (n: string) => api.companyUpdate(id, { notes: n }), onError: (e) => toastError(e) });
  const debouncedNotes = useDebounced((n: string) => notes.mutate(n), 700);
  const del = useMutation({ mutationFn: () => api.companyDelete(id), onSuccess: () => { refresh(); navigate("/companies"); }, onError: (e) => toastError(e) });
  const logoInput = useRef<HTMLInputElement>(null);
  const logo = useMutation({
    mutationFn: (f: File | null) => (f ? api.companyLogo(id, f) : api.companyLogoDelete(id)),
    onSuccess: (_r, f) => { refresh(); toast.success(f ? "Logo enregistré" : "Logo retiré"); },
    onError: (e) => toastError(e, "Logo non enregistré"),
  });

  if (!data) return <Skeleton className="h-96 rounded-xl" />;
  const running = data.people.filter((p) => p.campaign).length;
  const pickKind = (k: Kind) => {
    if (k === data.kind) return;
    if (k !== "prospect" && running) setKindTo(k); else setKind.mutate(k);
  };

  return (
    <>
      <PageHeader back={<BackButton to="/companies" label="Entreprises" />}
        title={<span className="flex items-center gap-3">
          <button type="button" onClick={() => logoInput.current?.click()} title={data.logo ? "Changer le logo" : "Ajouter le logo"} className="group relative rounded-lg">
            <Logo name={data.name} kind={data.kind} src={data.logo} className="size-12" />
            <span className="absolute inset-0 flex items-center justify-center rounded-lg bg-black/45 text-white opacity-0 transition-opacity group-hover:opacity-100"><ImagePlus className="size-4" /></span>
          </button>
          {data.name}
          <input ref={logoInput} type="file" accept=".png,.jpg,.jpeg,.webp,.svg" className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) logo.mutate(f); e.target.value = ""; }} />
        </span>}
        description={<span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {data.domain && <span className="inline-flex items-center gap-1"><Globe className="size-3.5" />{data.domain}</span>}
          {data.phone && <a href={`tel:${data.phone}`} className="inline-flex items-center gap-1 hover:text-primary"><Phone className="size-3.5" />{data.phone}</a>}
          {safeUrl(data.website) && <a href={safeUrl(data.website)} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 hover:text-primary"><ExternalLink className="size-3.5" />Site</a>}
          {data.sector && <span>{data.sector}</span>}
        </span>}
        actions={<>
          <Button variant="outline" onClick={() => setEditing(true)}><Pencil /> Modifier</Button>
          <Button onClick={() => navigate(`/contacts?new=1&company=${encodeURIComponent(data.name)}`, { state: { back: location.pathname } })}><UserPlus /> Ajouter une personne</Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button variant="outline" size="icon" aria-label="Plus d'actions"><MoreHorizontal /></Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => openReminder({ company: { id: data.id, name: data.name } })}><CalendarPlus /> Ajouter un rappel</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => logoInput.current?.click()}><ImagePlus /> {data.logo ? "Changer le logo" : "Ajouter le logo"}</DropdownMenuItem>
              {data.logo && <DropdownMenuItem onSelect={() => logo.mutate(null)}><Trash2 /> Retirer le logo</DropdownMenuItem>}
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => setMerging(true)}><GitMerge /> Fusionner avec une autre fiche…</DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem destructive disabled={data.people.length > 0} onSelect={() => setDeleting(true)}><Trash2 /> Supprimer la fiche</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </>}
      />

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="space-y-6">
          <PeopleCard company={data} onChanged={refresh} />

          <Card>
            <CardHeader><CardTitle>Derniers échanges</CardTitle></CardHeader>
            <CardContent>
              {data.activity.length === 0 ? <p className="text-sm text-muted-foreground">Aucun email échangé avec cette entreprise.</p> : (
                <ol className="space-y-3">
                  {data.activity.map((m) => (
                    <li key={m.id} className="flex items-start gap-3 text-sm">
                      <span className={cn("mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border", m.direction === "in" ? "text-brand" : "text-primary")}>
                        {m.direction === "in" ? <ArrowDownLeft className="size-3.5" /> : <ArrowUpRight className="size-3.5" />}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate">{m.subject || "(sans objet)"}</p>
                        <p className="text-xs text-muted-foreground">{m.direction === "in" ? "De" : "À"} {fullName(m.contact)} · {formatDayTime(m.ts)}</p>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </CardContent>
          </Card>
          {/* contrats : colonne large, le tableau a besoin de place */}
          {data.kind === "insurer" ? <ContractsPanel insurer={{ id: data.id, name: data.name }} /> : <ContractsPanel company={{ id: data.id, name: data.name }} />}
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="size-4 text-muted-foreground" />Relation</CardTitle></CardHeader>
            <CardContent>
              <KindPicker value={data.kind} onChange={pickKind} />
              <p className="mt-3 text-xs text-muted-foreground">Le type s'applique à toutes les personnes de l'entreprise. Seuls les prospects reçoivent des séquences de prospection.</p>
            </CardContent>
          </Card>
          {data.kind !== "insurer" && <QuotesPanel company={{ id: data.id, name: data.name }} />}
          <RemindersPanel company={{ id: data.id, name: data.name }} />
          <Card>
            <CardHeader><CardTitle>Notes {notes.isPending && <span className="text-xs font-normal text-muted-foreground">enregistrement…</span>}</CardTitle></CardHeader>
            <CardContent>
              <Textarea key={data.id} rows={6} defaultValue={data.notes} placeholder="Contrats en cours, échéances, interlocuteurs, historique de la relation…"
                onChange={(e) => debouncedNotes(e.target.value)} />
            </CardContent>
          </Card>
        </div>
      </div>

      <CompanyDialog open={editing} onOpenChange={setEditing} company={data} />
      <ConfirmDialog open={!!kindTo} onOpenChange={(o) => !o && setKindTo(null)} destructive
        title={`Passer ${data.name} en « ${KINDS.find((k) => k.value === kindTo)?.label} » ?`}
        description={`${running} personne${running > 1 ? "s sont" : " est"} en ce moment dans une campagne : les séquences de prospection seront arrêtées immédiatement (les séquences de gestion ou de souscription continuent).`}
        confirmLabel="Confirmer" pending={setKind.isPending} onConfirm={() => kindTo && setKind.mutate(kindTo)} />
      <MergeDialog open={merging} onOpenChange={setMerging} company={data} onDone={(target) => { refresh(); navigate(`/companies/${target}`); }} />
      <ConfirmDialog open={deleting} onOpenChange={setDeleting} destructive title={`Supprimer la fiche ${data.name} ?`}
        confirmLabel="Supprimer" pending={del.isPending} onConfirm={() => del.mutate()} />
    </>
  );
}

function MergeDialog({ open, onOpenChange, company, onDone }: { open: boolean; onOpenChange: (o: boolean) => void; company: CompanyDetail; onDone: (id: number) => void }) {
  const [q, setQ] = useUrlState<string>("q", "");
  const [target, setTarget] = useState<number | null>(null);
  const { data } = useQuery({ queryKey: ["companies", q, "merge"], queryFn: () => api.companies({ q }), enabled: open, placeholderData: (p) => p });
  const merge = useMutation({
    mutationFn: () => api.companyMerge(company.id, target!),
    onSuccess: (r) => { toast.success(`${r.moved} personne${r.moved > 1 ? "s" : ""} déplacée${r.moved > 1 ? "s" : ""}`); onOpenChange(false); onDone(r.id); },
    onError: (e) => toastError(e),
  });
  const chosen = data?.items.find((c) => c.id === target);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Fusionner « {company.name} »</DialogTitle>
          <DialogDescription>Pour deux fiches de la même entreprise (orthographe différente). Les personnes et les notes passent dans la fiche choisie, qui garde son nom et son type.</DialogDescription>
        </DialogHeader>
        <Input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Rechercher la fiche à garder…" />
        <div className="max-h-64 divide-y overflow-y-auto rounded-lg border">
          {data?.items.filter((c) => c.id !== company.id).map((c) => (
            <button key={c.id} onClick={() => setTarget(c.id)} className={cn("flex w-full items-center gap-2 px-3 py-2 text-left text-sm", target === c.id ? "bg-accent" : "hover:bg-accent/50")}>
              <span className="flex-1 truncate">{c.name}</span><KindBadge kind={c.kind} hideProspect /><span className="text-xs text-muted-foreground">{c.people}</span>
            </button>
          ))}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Annuler</Button>
          <Button disabled={!target || merge.isPending} onClick={() => merge.mutate()}><GitMerge /> {chosen ? `Fusionner dans ${chosen.name}` : "Fusionner"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* =============================================================== personnes (V2.8) */

type Person = CompanyDetail["people"][number];

function PersonRow({ p }: { p: Person }) {
  const location = useLocation();
  return (
    <li className="flex flex-wrap items-center gap-3 px-5 py-3">
      <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold">
        {(p.first_name?.[0] ?? p.email[0]).toUpperCase()}{p.last_name?.[0]?.toUpperCase()}
      </div>
      <Link to={`/contacts?open=${p.id}`} state={{ back: location.pathname }} className="min-w-0 flex-1 hover:text-primary">
        <p className="truncate text-sm font-medium">{fullName(p)}</p>
        <p className="truncate text-xs text-muted-foreground">{p.job_title ?? p.email}</p>
      </Link>
      <div className="flex items-center gap-1.5">
        {p.campaign && <Badge variant="info" className="hidden sm:inline-flex">{p.campaign}</Badge>}
        {p.status !== "active" && <ContactStatus status={p.status} />}
        <Button size="icon" variant="ghost" className="size-8" title={`Écrire à ${p.email}`} aria-label="Écrire" onClick={() => openComposer({ to: p.email })}><Mail /></Button>
        {p.phone && <Button size="icon" variant="ghost" className="size-8" asChild title={p.phone}><a href={`tel:${p.phone}`} aria-label="Appeler"><Phone /></a></Button>}
        <Button size="icon" variant="ghost" className="size-8" title="Ajouter un rappel" aria-label="Ajouter un rappel" onClick={() => openReminder({ contact: p })}><CalendarPlus /></Button>
        <PlacePerson p={p} />
      </div>
    </li>
  );
}

/** Ranger une personne : service et niveau, enregistrés aussitôt. */
function PlacePerson({ p }: { p: Person }) {
  const qc = useQueryClient();
  const save = useMutation({
    mutationFn: (body: { department?: string; seniority?: string }) => api.contactUpdate(p.id, body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["company"] }); qc.invalidateQueries({ queryKey: ["contact", p.id] }); },
    onError: (e) => toastError(e),
  });
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button size="icon" variant="ghost" className="size-8" title="Service et niveau" aria-label="Service et niveau"><SlidersHorizontal /></Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 space-y-3">
        <p className="text-sm font-medium">Ranger {fullName(p)}</p>
        <Field label="Service">
          <NativeSelect value={p.department ?? ""} onChange={(e) => save.mutate({ department: e.target.value })}>
            <option value="">—</option>
            {DEPARTMENTS.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
          </NativeSelect>
        </Field>
        <Field label="Niveau">
          <NativeSelect value={p.seniority ?? ""} onChange={(e) => save.mutate({ seniority: e.target.value })}>
            <option value="">—</option>
            {SENIORITIES.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
          </NativeSelect>
        </Field>
      </PopoverContent>
    </Popover>
  );
}

/** Les personnes de l'entreprise. Chez un assureur : un onglet par service, et dans chaque
 *  service les personnes rangées par niveau (directeur, senior, junior). */
function PeopleCard({ company }: { company: CompanyDetail; onChanged: () => void }) {
  const navigate = useNavigate();
  const location = useLocation();
  const people = company.people;
  const byService = company.kind === "insurer" || people.some((p) => p.department);
  const [tab, setTab] = useUrlState<string>("service", "all");
  const count = (d: string) => people.filter((p) => (d === "none" ? !p.department : p.department === d)).length;
  const tabs = [
    { value: "all", label: "Tous", n: people.length },
    ...DEPARTMENTS.map((d) => ({ value: d.value as string, label: d.label, n: count(d.value) })).filter((t) => t.n > 0 || t.value !== "autre"),
    ...(count("none") ? [{ value: "none", label: "Sans service", n: count("none") }] : []),
  ];
  const shown = tab === "all" ? people : people.filter((p) => (tab === "none" ? !p.department : p.department === tab));
  const levels = [...SENIORITIES, { value: null, label: "Niveau non précisé" }];
  // V2.11 : les personnes affichées (onglet en cours) qui peuvent recevoir un email
  const sendable = (byService ? shown : people).filter((p) => p.status === "active" || p.status === "replied");
  const addUrl = `/contacts?new=1&company=${encodeURIComponent(company.name)}${DEPARTMENTS.some((d) => d.value === tab) ? `&department=${tab}` : ""}`;

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 space-y-0">
        <CardTitle>Personnes <span className="ml-1 text-sm font-normal text-muted-foreground">{people.length}</span></CardTitle>
        <div className="flex flex-wrap gap-2">
          {sendable.length > 0 && (
            <Button size="sm" onClick={() => openSendSequence({ contacts: sendable })}
              title={`Envoyer une séquence aux ${sendable.length} personne(s) affichée(s)`}>
              <Send /> {byService && DEPARTMENTS.some((d) => d.value === tab) ? `Séquence au service ${DEPARTMENTS.find((d) => d.value === tab)?.label}` : `Séquence à ${sendable.length > 1 ? `ces ${sendable.length} personnes` : "cette personne"}`}
            </Button>
          )}
          {byService && <Button size="sm" variant="outline" onClick={() => navigate(addUrl, { state: { back: location.pathname } })}><UserPlus /> Ajouter{tab !== "all" && tab !== "none" ? ` en ${DEPARTMENTS.find((d) => d.value === tab)?.label}` : ""}</Button>}
        </div>
      </CardHeader>
      {byService && (
        <div className="flex gap-1 overflow-x-auto border-t px-4 py-2">
          {tabs.map((t) => (
            <button key={t.value} onClick={() => setTab(t.value)}
              className={cn("shrink-0 rounded-full px-3 py-1 text-sm transition-colors", tab === t.value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent")}>
              {t.label} <span className={cn("ml-0.5 text-xs tabular", tab === t.value ? "opacity-80" : "")}>{t.n}</span>
            </button>
          ))}
        </div>
      )}
      <CardContent className="p-0">
        {people.length === 0 ? <p className="px-6 pb-6 text-sm text-muted-foreground">Personne pour l'instant.</p>
          : !byService ? <ul className="divide-y border-t">{people.map((p) => <PersonRow key={p.id} p={p} />)}</ul>
            : shown.length === 0 ? (
              <div className="border-t px-6 py-8 text-center text-sm text-muted-foreground">
                Personne dans ce service. Rangez une personne avec <SlidersHorizontal className="inline size-3.5" />, ou ajoutez-en une.
              </div>
            ) : (
              <div className="border-t">
                {levels.map((lv) => {
                  const list = shown.filter((p) => (p.seniority ?? null) === lv.value);
                  if (!list.length) return null;
                  return (
                    <section key={lv.label}>
                      <p className="bg-muted/40 px-5 py-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{lv.label} · {list.length}</p>
                      <ul className="divide-y">
                        {list.map((p) => <PersonRow key={p.id} p={p} />)}
                      </ul>
                    </section>
                  );
                })}
              </div>
            )}
      </CardContent>
    </Card>
  );
}
