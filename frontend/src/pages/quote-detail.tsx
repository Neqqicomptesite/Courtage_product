// Cotalis, phase 1 : la fiche d'un dossier de cotation. Compagnies consultées (demande, relance,
// réponse, offre), fiche de renseignements de la branche, documents, historique.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, ArrowDownLeft, ArrowLeft, ArrowUpRight, Building2, Check, CheckCircle2, Circle, ExternalLink, FilePlus2,
  FileText, Inbox, MailPlus, MessageSquarePlus, MoreHorizontal, Paperclip, Plus, RotateCw, Send, StickyNote, Trash2, Trophy, Upload, XCircle,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { ConfirmDialog, Field, PageHeader, toastError, useDebounced } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  api, ApiError, type BranchField, type InsurerStatus, type QuoteDetail, type QuoteEventRow, type QuoteInsurerRow, type QuoteStage,
} from "@/lib/api";
import { formatDayTime, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Logo } from "@/pages/companies";
import { LostDialog, mad, shortDate, STAGES, StageBadge } from "@/pages/quotes";

const INSURER: Record<InsurerStatus, { label: string; variant: "secondary" | "info" | "warning" | "success" | "destructive" | "outline" }> = {
  to_send: { label: "À envoyer", variant: "outline" }, sent: { label: "Envoyé", variant: "info" },
  reminded: { label: "Relancé", variant: "warning" }, replied: { label: "A répondu", variant: "secondary" },
  offer: { label: "Offre reçue", variant: "success" }, declined: { label: "Refus", variant: "destructive" },
};

export function QuoteDetailPage() {
  const id = Number(useParams().id);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data } = useQuery({ queryKey: ["quote", id], queryFn: () => api.quote(id) });
  const set = (d: QuoteDetail) => { qc.setQueryData(["quote", id], d); qc.invalidateQueries({ queryKey: ["quotes"] }); };
  const update = useMutation({ mutationFn: (b: Parameters<typeof api.quoteUpdate>[1]) => api.quoteUpdate(id, b), onSuccess: set, onError: (e) => toastError(e) });
  const del = useMutation({ mutationFn: () => api.quoteDelete(id), onSuccess: () => { qc.invalidateQueries({ queryKey: ["quotes"] }); navigate("/quotes"); }, onError: (e) => toastError(e) });
  const [lost, setLost] = useState(false);
  const [deleting, setDeleting] = useState(false);

  if (!data) return <Skeleton className="h-[32rem] rounded-xl" />;
  const goStage = (s: QuoteStage) => (s === "lost" ? setLost(true) : update.mutate({ stage: s }));

  return (
    <>
      <PageHeader back={<Button variant="ghost" size="sm" className="-ml-2" asChild><Link to="/quotes"><ArrowLeft /> Dossiers</Link></Button>}
        title={<span className="flex flex-wrap items-center gap-x-3 gap-y-1">{data.client_name}<StageBadge stage={data.stage} /></span>}
        description={<span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-medium text-foreground">{data.branch}</span><span className="tabular">{data.ref}</span>
          {data.owner_name && <span>Suivi par {data.owner_name}</span>}
          {data.due_on && <span className={cn(data.late && "font-medium text-destructive")}>Attendu le {shortDate(data.due_on)}</span>}
        </span>}
        actions={<>
          {data.stage !== "won" && data.stage !== "lost" ? <>
            <Button variant="outline" onClick={() => setLost(true)}><XCircle /> Perdu</Button>
            <Button onClick={() => update.mutate({ stage: "won" })}><Trophy /> Gagné</Button>
          </> : <Button variant="outline" onClick={() => update.mutate({ stage: "proposed" })}><RotateCw /> Rouvrir</Button>}
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button variant="outline" size="icon" aria-label="Plus d'actions"><MoreHorizontal /></Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem destructive onSelect={() => setDeleting(true)}><Trash2 /> Supprimer le dossier</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </>} />

      <StageStepper stage={data.stage} onPick={goStage} />

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-6">
          <InsurersCard q={data} onChange={set} />
          <BranchFormCard q={data} onChange={set} />
          <HistoryCard q={data} onChange={set} />
        </div>
        <div className="min-w-0 space-y-6">
          <InfoCard q={data} save={(b) => update.mutate(b)} />
          <FilesCard q={data} onChange={set} />
          <NotesCard q={data} />
        </div>
      </div>

      <LostDialog quote={lost ? data : null} onClose={() => setLost(false)} onConfirm={(r) => { setLost(false); update.mutate({ stage: "lost", lost_reason: r }); }} />
      <ConfirmDialog open={deleting} onOpenChange={setDeleting} title="Supprimer ce dossier ?" destructive confirmLabel="Supprimer"
        description="Le dossier, son historique et ses rappels sont supprimés. Les emails déjà envoyés restent dans votre boîte."
        onConfirm={() => del.mutate()} />
    </>
  );
}

function StageStepper({ stage, onPick }: { stage: QuoteStage; onPick: (s: QuoteStage) => void }) {
  const open = STAGES.slice(0, 5);
  const idx = open.findIndex((s) => s.key === stage);
  const closed = stage === "won" || stage === "lost";
  return (
    <div className="mb-6 flex overflow-x-auto rounded-xl border bg-card p-1">
      {open.map((s, i) => {
        const done = closed ? stage === "won" : i < idx;
        const current = s.key === stage;
        return (
          <button key={s.key} onClick={() => onPick(s.key)} title={`Passer à « ${s.label} »`}
            className={cn("flex min-w-[8.5rem] flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium transition-colors",
              current ? "bg-primary text-primary-foreground" : done ? "text-primary hover:bg-accent" : "text-muted-foreground hover:bg-muted")}>
            {done ? <Check className="size-3.5" /> : current ? <Circle className="size-3 fill-current" /> : <span className="tabular">{i + 1}</span>}
            {s.short}
          </button>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ compagnies */

function InsurersCard({ q, onChange }: { q: QuoteDetail; onChange: (d: QuoteDetail) => void }) {
  const [adding, setAdding] = useState(false);
  const [mailFor, setMailFor] = useState<QuoteInsurerRow | null>(null);
  const patch = useMutation({
    mutationFn: ({ iid, body }: { iid: number; body: Parameters<typeof api.quoteInsurerUpdate>[2] }) => api.quoteInsurerUpdate(q.id, iid, body),
    onSuccess: onChange, onError: (e) => toastError(e),
  });
  const remove = useMutation({ mutationFn: (iid: number) => api.quoteInsurerRemove(q.id, iid), onSuccess: onChange, onError: (e) => toastError(e) });
  const toSend = q.insurer_list.filter((i) => i.status === "to_send");

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>Compagnies consultées</CardTitle>
        <Button size="sm" variant="outline" onClick={() => setAdding(true)}><Plus /> Ajouter</Button>
      </CardHeader>
      <CardContent className="p-0">
        {q.insurer_list.length === 0 ? (
          <div className="px-6 pb-6 text-sm text-muted-foreground">
            Choisissez les compagnies à consulter : la demande de cotation est préparée pour chacune avec la fiche du dossier.
            {q.missing_labels.length > 0 && <p className="mt-2 flex items-center gap-1.5 text-warning"><AlertTriangle className="size-4" /> Il manque encore {q.missing_labels.length} info{q.missing_labels.length > 1 ? "s" : ""} dans la fiche.</p>}
          </div>
        ) : (
          <ul className="divide-y border-t">
            {q.insurer_list.map((i) => (
              <li key={i.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 sm:px-6">
                <div className="flex min-w-[14rem] flex-1 items-center gap-3">
                <Logo name={i.company} kind="insurer" src={i.logo} className="size-9" />
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-2 font-medium">{i.company}<Badge variant={INSURER[i.status].variant}>{INSURER[i.status].label}</Badge></p>
                  <p className="truncate text-xs text-muted-foreground">
                    {i.contact ? `${i.contact.name} · ${i.contact.email}` : <span className="text-warning">Aucun interlocuteur : ajoutez une personne à la fiche de la compagnie</span>}
                    {i.sent_at && ` · envoyé ${relativeTime(i.sent_at)}`}{i.reminders_sent > 0 && ` · ${i.reminders_sent} relance${i.reminders_sent > 1 ? "s" : ""}`}
                  </p>
                </div>
                </div>
                <div className="ml-auto flex items-center gap-2">
                {(i.status === "offer" || i.offer_premium != null) && (
                  <PremiumInput value={i.offer_premium} onSave={(v) => patch.mutate({ iid: i.id, body: { offer_premium: v } })} />
                )}
                {i.status === "to_send" && <Button size="sm" onClick={() => setMailFor(i)}><Send /> Préparer la demande</Button>}
                {(i.status === "sent" || i.status === "reminded") && <Button size="sm" variant="outline" onClick={() => setMailFor(i)}><MailPlus /> Relancer</Button>}
                {i.status === "replied" && <Button size="sm" variant="outline" onClick={() => patch.mutate({ iid: i.id, body: { status: "offer" } })}><CheckCircle2 /> Offre reçue</Button>}
                <DropdownMenu>
                  <DropdownMenuTrigger asChild><Button size="icon" variant="ghost" className="size-8" aria-label={`Actions ${i.company}`}><MoreHorizontal /></Button></DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    {i.status !== "to_send" && <DropdownMenuItem onSelect={() => setMailFor(i)}><MailPlus /> Écrire une relance</DropdownMenuItem>}
                    {(["replied", "offer", "declined"] as InsurerStatus[]).filter((s) => s !== i.status).map((s) => (
                      <DropdownMenuItem key={s} onSelect={() => patch.mutate({ iid: i.id, body: { status: s } })}>Marquer « {INSURER[s].label} »</DropdownMenuItem>
                    ))}
                    <DropdownMenuItem asChild><Link to={`/companies/${i.company_id}`}><Building2 /> Fiche de la compagnie</Link></DropdownMenuItem>
                    {i.status === "to_send" && <><DropdownMenuSeparator /><DropdownMenuItem destructive onSelect={() => remove.mutate(i.id)}><Trash2 /> Retirer du dossier</DropdownMenuItem></>}
                  </DropdownMenuContent>
                </DropdownMenu>
                </div>
              </li>
            ))}
          </ul>
        )}
        {toSend.length > 1 && (
          <p className="border-t px-6 py-2.5 text-xs text-muted-foreground">{toSend.length} demandes à préparer : chaque email se relit avant de partir.</p>
        )}
      </CardContent>
      <AddInsurersDialog q={q} open={adding} onOpenChange={setAdding} onChange={onChange} />
      <ConsultDialog q={q} insurer={mailFor} onClose={() => setMailFor(null)} onChange={onChange} />
    </Card>
  );
}

function PremiumInput({ value, onSave }: { value: number | null; onSave: (v: string) => void }) {
  const [v, setV] = useState(value != null ? value.toLocaleString("fr-FR") : "");
  useEffect(() => setV(value != null ? value.toLocaleString("fr-FR") : ""), [value]);
  return (
    <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
      Prime
      <Input value={v} onChange={(e) => setV(e.target.value)} onBlur={() => v !== (value?.toLocaleString("fr-FR") ?? "") && onSave(v)}
        className="h-8 w-28 text-right tabular" placeholder="0" aria-label="Prime proposée (MAD)" />
      MAD
    </label>
  );
}

function AddInsurersDialog({ q, open, onOpenChange, onChange }: { q: QuoteDetail; open: boolean; onOpenChange: (o: boolean) => void; onChange: (d: QuoteDetail) => void }) {
  const { data } = useQuery({ queryKey: ["insurer-companies"], queryFn: api.quoteInsurerCompanies, enabled: open });
  const [picked, setPicked] = useState<number[]>([]);
  const [needle, setNeedle] = useState("");
  useEffect(() => { if (open) { setPicked([]); setNeedle(""); } }, [open]);
  const have = new Set(q.insurer_list.map((i) => i.company_id));
  const add = useMutation({ mutationFn: () => api.quoteAddInsurers(q.id, picked), onSuccess: (d) => { onChange(d); onOpenChange(false); }, onError: (e) => toastError(e) });
  const list = (data?.items ?? []).filter((c) => c.name.toLowerCase().includes(needle.toLowerCase()));
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Compagnies à consulter</DialogTitle>
          <DialogDescription>Les compagnies d'assurance de vos Entreprises. La demande partira vers leur interlocuteur « souscription » s'il y en a un.</DialogDescription>
        </DialogHeader>
        <Input value={needle} onChange={(e) => setNeedle(e.target.value)} placeholder="Rechercher" aria-label="Rechercher une compagnie" />
        <div className="max-h-80 divide-y overflow-y-auto rounded-md border">
          {!data ? <Skeleton className="h-40" /> : list.length === 0 ? <p className="p-4 text-sm text-muted-foreground">Aucune compagnie. Ajoutez-les dans Entreprises (type « Assureur »).</p> : list.map((c) => {
            const already = have.has(c.id);
            return (
              <label key={c.id} className={cn("flex cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-muted/60", already && "cursor-default opacity-50")}>
                <Checkbox disabled={already} checked={already || picked.includes(c.id)}
                  onCheckedChange={(v) => setPicked((p) => (v ? [...p, c.id] : p.filter((x) => x !== c.id)))} />
                <Logo name={c.name} kind="insurer" src={c.logo} className="size-7" />
                <span className="flex-1">{c.name}</span>
                <span className="text-xs text-muted-foreground">{already ? "déjà dans le dossier" : c.contacts === 0 ? "aucun contact" : `${c.contacts} contact${c.contacts > 1 ? "s" : ""}`}</span>
              </label>
            );
          })}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Annuler</Button>
          <Button disabled={!picked.length || add.isPending} onClick={() => add.mutate()}>Ajouter {picked.length || ""}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ConsultDialog({ q, insurer, onClose, onChange }: { q: QuoteDetail; insurer: QuoteInsurerRow | null; onClose: () => void; onChange: (d: QuoteDetail) => void }) {
  const { data: draft, isFetching } = useQuery({
    queryKey: ["quote-draft", q.id, insurer?.id, insurer?.status, insurer?.reminders_sent],
    queryFn: () => api.quoteDraft(q.id, insurer!.id), enabled: !!insurer, gcTime: 0,
  });
  const [to, setTo] = useState(""); const [cc, setCc] = useState(""); const [subject, setSubject] = useState(""); const [body, setBody] = useState("");
  const [atts, setAtts] = useState<number[]>([]);
  const [confirm, setConfirm] = useState<string | null>(null);
  useEffect(() => {
    if (!draft) return;
    setTo(draft.to); setCc(""); setSubject(draft.subject); setBody(draft.body); setAtts(draft.attachments.map((a) => a.id));
  }, [draft]);
  const left = useMemo(() => [...new Set([...`${subject}\n${body}`.matchAll(/\[([^[\]\n]{2,60})\]/g)].map((m) => m[1]))], [subject, body]);
  const send = useMutation({
    mutationFn: (force: boolean) => api.quoteSend(q.id, insurer!.id, { to, cc, subject, body, attachment_ids: atts, force }),
    onSuccess: (d) => {
      onChange(d);
      toast.success(draft?.followup ? "Relance envoyée" : "Demande de cotation envoyée", { description: `À ${to}. Relance proposée dans l'Agenda si pas de réponse.` });
      onClose();
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409 && e.data.confirm) setConfirm(e.message);
      else toastError(e, "Email non envoyé");
    },
  });
  return (
    <Dialog open={!!insurer} onOpenChange={(o) => !o && onClose()}>
      <DialogContent side="right" className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{draft?.followup ? "Relance" : "Demande de cotation"} · {insurer?.company}</DialogTitle>
          <DialogDescription>Préparée avec le modèle « {q.branch} » et la fiche du dossier. Relisez, puis envoyez depuis votre boîte.</DialogDescription>
        </DialogHeader>
        {!draft || isFetching ? <Skeleton className="h-96" /> : (
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="À"><Input value={to} onChange={(e) => setTo(e.target.value)} /></Field>
              <Field label="Cc"><Input value={cc} onChange={(e) => setCc(e.target.value)} placeholder="Facultatif" /></Field>
            </div>
            <Field label="Objet"><Input value={subject} onChange={(e) => setSubject(e.target.value)} /></Field>
            <Field label="Message" hint="Votre signature est ajoutée automatiquement.">
              <Textarea rows={16} value={body} onChange={(e) => setBody(e.target.value)} className="font-[inherit] text-sm leading-relaxed" />
            </Field>
            {left.length > 0 && (
              <p className="flex items-start gap-2 rounded-md bg-warning/10 p-2.5 text-sm text-warning">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                <span>À compléter avant l'envoi : {left.map((p) => `[${p}]`).join(", ")}. Remplissez la fiche du dossier ou écrivez directement dans le message.</span>
              </p>
            )}
            {draft.attachments.length > 0 && (
              <div className="space-y-1.5">
                <p className="text-sm font-medium">Pièces jointes du dossier</p>
                {draft.attachments.map((a) => (
                  <label key={a.id} className="flex items-center gap-2 text-sm">
                    <Checkbox checked={atts.includes(a.id)} onCheckedChange={(v) => setAtts((p) => (v ? [...p, a.id] : p.filter((x) => x !== a.id)))} />
                    <Paperclip className="size-3.5 text-muted-foreground" />{a.label || a.name}<span className="text-xs text-muted-foreground">{a.label && a.name}</span>
                  </label>
                ))}
              </div>
            )}
            <DialogFooter className="pt-2">
              <Button variant="outline" onClick={onClose}>Annuler</Button>
              <Button disabled={!to.trim() || left.length > 0 || send.isPending} onClick={() => send.mutate(false)}>
                {send.isPending ? <RotateCw className="animate-spin" /> : <Send />} Envoyer
              </Button>
            </DialogFooter>
          </div>
        )}
        <ConfirmDialog open={!!confirm} onOpenChange={(o) => !o && setConfirm(null)} title="Adresse sur la liste d'exclusion" description={confirm}
          confirmLabel="Envoyer quand même" onConfirm={() => { setConfirm(null); send.mutate(true); }} />
      </DialogContent>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ fiche de la branche */

function BranchFormCard({ q, onChange }: { q: QuoteDetail; onChange: (d: QuoteDetail) => void }) {
  const [vals, setVals] = useState<Record<string, string>>(q.fields);
  useEffect(() => setVals(q.fields), [q.fields]);
  const dirty = q.branch_def.fields.some((f) => (vals[f.key] ?? "") !== (q.fields[f.key] ?? ""));
  const save = useMutation({
    mutationFn: () => api.quoteUpdate(q.id, { fields: Object.fromEntries(q.branch_def.fields.map((f) => [f.key, vals[f.key] ?? null])) }),
    onSuccess: (d) => { onChange(d); toast.success("Fiche enregistrée"); }, onError: (e) => toastError(e),
  });
  if (q.branch_def.fields.length === 0) {
    return (
      <Card>
        <CardHeader><CardTitle>Fiche de renseignements</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground">La branche « {q.branch} » n'a pas de fiche prédéfinie : notez les informations du client dans les notes du dossier.</CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="flex items-center gap-2">Fiche de renseignements
          {q.missing_labels.length > 0 ? <Badge variant="warning">{q.missing_labels.length} à compléter</Badge> : <Badge variant="success">Complète</Badge>}
        </CardTitle>
        {dirty && <Button size="sm" disabled={save.isPending} onClick={() => save.mutate()}>Enregistrer</Button>}
      </CardHeader>
      <CardContent>
        <form className="grid gap-4 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          {q.branch_def.fields.map((f) => (
            <BranchInput key={f.key} f={f} value={vals[f.key] ?? ""} onChange={(v) => setVals((p) => ({ ...p, [f.key]: v }))} />
          ))}
        </form>
        <p className="mt-4 text-xs text-muted-foreground">Ces informations remplissent automatiquement les demandes envoyées aux compagnies.</p>
      </CardContent>
    </Card>
  );
}

function BranchInput({ f, value, onChange }: { f: BranchField; value: string; onChange: (v: string) => void }) {
  const empty = !value.trim();
  const label = <span className="flex items-center gap-1.5">{f.label}{f.unit && <span className="font-normal text-muted-foreground">({f.unit})</span>}{empty && <span className="size-1.5 rounded-full bg-warning" title="À compléter" />}</span>;
  const wide = f.type === "textarea" || f.type === "choice" && (f.options?.join("").length ?? 0) > 30;
  return (
    <Field label={label} hint={f.hint} className={cn(wide && "sm:col-span-2")}>
      {f.type === "choice" ? (
        <div className="flex flex-wrap gap-1.5">
          {f.options!.map((o) => <Button key={o} type="button" size="sm" variant={value === o ? "default" : "outline"} onClick={() => onChange(value === o ? "" : o)}>{o}</Button>)}
        </div>
      ) : f.type === "textarea" ? (
        <Textarea rows={2} value={value} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <Input type={f.type === "date" ? "date" : "text"} inputMode={f.type === "number" ? "decimal" : undefined} value={value}
          onChange={(e) => onChange(e.target.value)} className={cn(f.type === "number" && "tabular", f.type === "date" && "w-44")} />
      )}
    </Field>
  );
}

/* ------------------------------------------------------------------ informations, documents, notes */

function InfoCard({ q, save }: { q: QuoteDetail; save: (b: Parameters<typeof api.quoteUpdate>[1]) => void }) {
  const { data: people } = useQuery({ queryKey: ["quote-people"], queryFn: api.quotePeople });
  const [premium, setPremium] = useState(q.current_premium != null ? q.current_premium.toLocaleString("fr-FR") : "");
  const [insurer, setInsurer] = useState(q.current_insurer ?? "");
  useEffect(() => { setPremium(q.current_premium != null ? q.current_premium.toLocaleString("fr-FR") : ""); setInsurer(q.current_insurer ?? ""); }, [q.current_premium, q.current_insurer]);
  return (
    <Card>
      <CardHeader><CardTitle>Dossier</CardTitle></CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div>
          <p className="text-xs text-muted-foreground">Client</p>
          {q.company ? <Link to={`/companies/${q.company.id}`} className="font-medium hover:text-primary hover:underline">{q.company.name}</Link> : <p className="font-medium">{q.client_name}</p>}
          {q.contact && <p className="text-muted-foreground">{q.contact.name} · {q.contact.email}</p>}
        </div>
        {(people?.items.length ?? 0) > 0 && (
          <Field label="Responsable">
            <NativeSelect value={q.owner_id ?? ""} onChange={(e) => save({ owner_id: e.target.value ? Number(e.target.value) : null })}>
              <option value="">—</option>
              {people!.items.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </NativeSelect>
          </Field>
        )}
        <Field label="Proposition attendue le">
          <Input type="date" defaultValue={q.due_on ?? ""} key={q.due_on ?? "x"} className="w-44" onBlur={(e) => e.target.value !== (q.due_on ?? "") && save({ due_on: e.target.value || null })} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Assureur actuel">
            <Input value={insurer} onChange={(e) => setInsurer(e.target.value)} onBlur={() => insurer !== (q.current_insurer ?? "") && save({ current_insurer: insurer })} placeholder="—" />
          </Field>
          <Field label="Prime actuelle (MAD)">
            <Input value={premium} onChange={(e) => setPremium(e.target.value)} className="tabular" placeholder="—"
              onBlur={() => premium !== (q.current_premium?.toLocaleString("fr-FR") ?? "") && save({ current_premium: premium || null })} />
          </Field>
        </div>
        {q.best_offer != null && (
          <p className="rounded-md bg-brand/10 px-3 py-2 text-brand">Meilleure offre : <b className="tabular">{mad(q.best_offer)}</b>
            {q.current_premium ? <span> ({q.best_offer <= q.current_premium ? "−" : "+"}{Math.abs(Math.round((q.best_offer / q.current_premium - 1) * 100))} % vs actuelle)</span> : null}</p>
        )}
      </CardContent>
    </Card>
  );
}

function FilesCard({ q, onChange }: { q: QuoteDetail; onChange: (d: QuoteDetail) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [label, setLabel] = useState("");
  const [kind, setKind] = useState<"client" | "offer" | "other">("client");
  const [insurerId, setInsurerId] = useState<number | null>(null);
  const upload = useMutation({
    mutationFn: async (f: File) => { const a = await api.uploadAttachment(f); return api.quoteAddFile(q.id, { attachment_id: a.id, kind, label, insurer_id: kind === "offer" ? insurerId : null }); },
    onSuccess: (d) => { onChange(d); setLabel(""); toast.success("Document ajouté"); }, onError: (e) => toastError(e, "Document non ajouté"),
  });
  const remove = useMutation({ mutationFn: (fid: number) => api.quoteRemoveFile(q.id, fid), onSuccess: onChange, onError: (e) => toastError(e) });
  const pick = (k: typeof kind, l = "", iid: number | null = null) => { setKind(k); setLabel(l); setInsurerId(iid); setTimeout(() => input.current?.click(), 0); };
  const have = new Set(q.files.filter((f) => f.kind === "client").map((f) => f.label));
  const insurers = new Map(q.insurer_list.map((i) => [i.id, i.company]));
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>Documents</CardTitle>
        <DropdownMenu>
          <DropdownMenuTrigger asChild><Button size="sm" variant="outline" disabled={upload.isPending}>{upload.isPending ? <RotateCw className="animate-spin" /> : <Upload />} Ajouter</Button></DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => pick("client")}><FilePlus2 /> Pièce du client</DropdownMenuItem>
            {q.insurer_list.filter((i) => i.status !== "to_send").map((i) => (
              <DropdownMenuItem key={i.id} onSelect={() => pick("offer", "", i.id)}><FileText /> Offre de {i.company}</DropdownMenuItem>
            ))}
            <DropdownMenuItem onSelect={() => pick("other")}><Paperclip /> Autre document</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <input ref={input} type="file" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
      </CardHeader>
      <CardContent className="space-y-4">
        {q.branch_def.docs.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground">À demander au client</p>
            {q.branch_def.docs.map((d) => (
              <div key={d} className="flex items-start gap-2 text-sm">
                {have.has(d) ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" /> : <Circle className="mt-0.5 size-4 shrink-0 text-muted-foreground" />}
                <span className={cn("flex-1", have.has(d) && "text-muted-foreground")}>{d}</span>
                {!have.has(d) && <button className="text-xs text-primary hover:underline" onClick={() => pick("client", d)}>Ajouter</button>}
              </div>
            ))}
          </div>
        )}
        {q.files.length === 0 ? <p className="text-sm text-muted-foreground">Aucun document pour l'instant. Les pièces du client sont proposées en pièce jointe des demandes.</p> : (
          <ul className="space-y-1.5">
            {q.files.map((f) => (
              <li key={f.file_id} className="group flex items-center gap-2 text-sm">
                <FileText className={cn("size-4 shrink-0", f.kind === "offer" ? "text-brand" : "text-muted-foreground")} />
                <a href={`/api/attachments/${f.id}?t=${f.token}`} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate hover:text-primary hover:underline" title={f.name}>
                  {f.label || f.name}
                </a>
                {f.kind === "offer" && <Badge variant="success">Offre{f.insurer_id && insurers.get(f.insurer_id) ? ` ${insurers.get(f.insurer_id)}` : ""}</Badge>}
                <button className="text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100" title="Retirer du dossier" onClick={() => remove.mutate(f.file_id)}><Trash2 className="size-3.5" /></button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function NotesCard({ q }: { q: QuoteDetail }) {
  const save = useMutation({ mutationFn: (n: string) => api.quoteUpdate(q.id, { notes: n }), onError: (e) => toastError(e) });
  const debounced = useDebounced((n: string) => save.mutate(n), 700);
  return (
    <Card>
      <CardHeader><CardTitle>Notes {save.isPending && <span className="text-xs font-normal text-muted-foreground">enregistrement…</span>}</CardTitle></CardHeader>
      <CardContent>
        <Textarea key={q.id} rows={5} defaultValue={q.notes} placeholder="Contexte, attentes du client, points d'attention…" onChange={(e) => debounced(e.target.value)} />
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------------ historique */

function HistoryCard({ q, onChange }: { q: QuoteDetail; onChange: (d: QuoteDetail) => void }) {
  const [note, setNote] = useState("");
  const add = useMutation({ mutationFn: () => api.quoteNote(q.id, note), onSuccess: (d) => { onChange(d); setNote(""); }, onError: (e) => toastError(e) });
  return (
    <Card>
      <CardHeader><CardTitle>Historique</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (note.trim()) add.mutate(); }}>
          <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Ajouter une note (appel, échange…)" aria-label="Note" />
          <Button type="submit" variant="outline" disabled={!note.trim() || add.isPending}><MessageSquarePlus /> Noter</Button>
        </form>
        <ol className="relative space-y-4 border-l pl-5">
          {q.events.map((e) => <EventItem key={e.id} e={e} q={q} onChange={onChange} />)}
        </ol>
      </CardContent>
    </Card>
  );
}

const EVENT_ICON: Record<QuoteEventRow["kind"], typeof Send> = {
  created: Plus, stage: ArrowUpRight, note: StickyNote, fields: FileText, email_out: Send, email_in: ArrowDownLeft,
  file: Paperclip, insurer: Building2, edit: FileText,
};

function EventItem({ e, q, onChange }: { e: QuoteEventRow; q: QuoteDetail; onChange: (d: QuoteDetail) => void }) {
  const [open, setOpen] = useState(false);
  const Icon = EVENT_ICON[e.kind];
  const store = useMutation({
    mutationFn: (index: number) => api.quoteFileFromMail(q.id, { folder: e.data!.folder!, uid: e.data!.uid!, index, kind: "offer", insurer_id: e.insurer_id }),
    onSuccess: (d) => { onChange(d); toast.success("Rangé dans les documents du dossier"); }, onError: (err) => toastError(err),
  });
  const email = e.kind === "email_in" || e.kind === "email_out";
  const stored = new Set(q.files.map((f) => f.name));
  return (
    <li className="relative">
      <span className={cn("absolute -left-[1.85rem] top-0 flex size-6 items-center justify-center rounded-full border bg-card",
        e.kind === "email_in" ? "text-brand" : e.kind === "note" ? "text-warning" : "text-muted-foreground")}><Icon className="size-3.5" /></span>
      <p className={cn("text-sm", e.kind === "note" && "whitespace-pre-wrap rounded-md bg-muted/60 px-3 py-2")}>{e.text}</p>
      {email && e.data?.subject && (
        <div className="mt-1.5 rounded-md border px-3 py-2 text-sm">
          <button className="w-full text-left font-medium hover:text-primary" onClick={() => setOpen(!open)}>{e.data.subject}</button>
          {open && e.data.body && <p className="mt-2 whitespace-pre-wrap text-muted-foreground">{e.data.body}</p>}
          {e.kind === "email_in" && (e.data.attachments?.length ?? 0) > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {e.data.attachments!.map((a) => {
                const name = typeof a === "string" ? a : a.name;
                const can = typeof a !== "string" && e.mine && e.data?.uid != null;
                return (
                  <span key={name} className="inline-flex items-center gap-1.5 rounded-md bg-muted px-2 py-1 text-xs">
                    <Paperclip className="size-3" />{name}
                    {stored.has(name) ? <Check className="size-3 text-success" /> : can && (
                      <button className="font-medium text-primary hover:underline" disabled={store.isPending} onClick={() => store.mutate((a as { index: number }).index)}>Ranger comme offre</button>
                    )}
                  </span>
                );
              })}
            </div>
          )}
          {e.kind === "email_in" && e.mine && e.data.uid != null && (
            <Link to={`/inbox?folder=${encodeURIComponent(e.data.folder ?? "INBOX")}&uid=${e.data.uid}`} className="mt-2 inline-flex items-center gap-1 text-xs text-primary hover:underline">
              <Inbox className="size-3" /> Ouvrir dans la boîte mail <ExternalLink className="size-3" />
            </Link>
          )}
        </div>
      )}
      <p className="mt-1 text-xs text-muted-foreground">{formatDayTime(e.ts)}{e.user_name && ` · ${e.user_name}`}</p>
    </li>
  );
}
