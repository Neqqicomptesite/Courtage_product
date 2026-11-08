// La fiche d'un dossier de cotation : compagnies consultées (par branche ; email commun ou par
// branche, plusieurs destinataires, envoi à toutes), fiche de renseignements, documents (pièces du
// client, conditions actuelles, offres), rappels, historique.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, ArrowDownLeft, ArrowLeft, ArrowUpRight, Bell, Building2, CalendarPlus, Check, CheckCircle2, Circle, ExternalLink,
  FileText, Inbox, MailPlus, MessageSquarePlus, MoreHorizontal, Paperclip, Plus, RotateCw, Send, SendHorizontal, StickyNote, Trash2,
  Trophy, Upload, X, XCircle,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { ConfirmDialog, Field, FieldGroup, PageHeader, toastError, useDebounced } from "@/components/common";
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
  api, ApiError, type BranchField, type InsurerStatus, type QuoteCompany, type QuoteDetail, type QuoteEventRow, type QuoteFileKind,
  type QuoteRow, type QuoteStage, type SendAllReport,
} from "@/lib/api";
import { formatDayTime, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Logo } from "@/pages/companies";
import { LostDialog, mad, shortDate, STAGES, StageBadge } from "@/pages/quotes";

const INSURER: Record<InsurerStatus, { label: string; variant: "secondary" | "info" | "warning" | "success" | "destructive" | "outline" }> = {
  to_send: { label: "À envoyer", variant: "outline" }, sent: { label: "Envoyé", variant: "info" },
  reminded: { label: "Relancé", variant: "warning" }, replied: { label: "A répondu", variant: "secondary" },
  offer: { label: "Offre reçue", variant: "success" }, renegotiate: { label: "À renégocier", variant: "warning" },
  declined: { label: "Refus", variant: "destructive" },
};
const MARKS: InsurerStatus[] = ["replied", "offer", "renegotiate", "declined"];

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
          <span className="font-medium text-foreground">{data.branch_label}</span><span className="tabular">{data.ref}</span>
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
          <RemindersCard q={data} onChange={set} />
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
  const open = STAGES.slice(0, 6);
  const idx = open.findIndex((s) => s.key === stage);
  const closed = stage === "won" || stage === "lost";
  return (
    <div className="mb-6 flex overflow-x-auto rounded-xl border bg-card p-1">
      {open.map((s, i) => {
        const done = closed ? stage === "won" : i < idx;
        const current = s.key === stage;
        return (
          <button key={s.key} onClick={() => onPick(s.key)} title={`Passer à « ${s.label} »`}
            className={cn("flex min-w-[7.5rem] flex-1 items-center justify-center gap-1.5 rounded-lg px-2.5 py-2 text-xs font-medium transition-colors",
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

type MailTarget = { company: QuoteCompany; ids: number[] };

function InsurersCard({ q, onChange }: { q: QuoteDetail; onChange: (d: QuoteDetail) => void }) {
  const [adding, setAdding] = useState(false);
  const [mail, setMail] = useState<MailTarget | null>(null);
  const [all, setAll] = useState(false);
  const multi = q.branches.length > 1;
  const pending = q.companies.filter((c) => c.rows.some((r) => r.status === "to_send"));

  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 space-y-0">
        <CardTitle>Compagnies consultées</CardTitle>
        <div className="flex gap-2">
          {pending.length > 1 && <Button size="sm" onClick={() => setAll(true)}><SendHorizontal /> Envoyer à toutes ({pending.length})</Button>}
          <Button size="sm" variant="outline" onClick={() => setAdding(true)}><Plus /> Ajouter</Button>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {q.companies.length === 0 ? (
          <div className="px-6 pb-6 text-sm text-muted-foreground">
            Choisissez les compagnies à consulter : la demande de cotation est préparée pour chacune avec la fiche du dossier.
            {q.missing_labels.length > 0 && <p className="mt-2 flex items-center gap-1.5 text-warning"><AlertTriangle className="size-4" /> Il manque encore {q.missing_labels.length} info{q.missing_labels.length > 1 ? "s" : ""} dans la fiche.</p>}
          </div>
        ) : (
          <ul className="divide-y border-t">
            {q.companies.map((c) => <CompanyItem key={c.company_id} q={q} c={c} multi={multi} onChange={onChange} onMail={setMail} />)}
          </ul>
        )}
      </CardContent>
      <AddInsurersDialog q={q} open={adding} onOpenChange={setAdding} onChange={onChange} />
      <ConsultDialog q={q} target={mail} onClose={() => setMail(null)} onChange={onChange} />
      <SendAllDialog q={q} open={all} onOpenChange={setAll} onChange={onChange} />
    </Card>
  );
}

function CompanyItem({ q, c, multi, onChange, onMail }: {
  q: QuoteDetail; c: QuoteCompany; multi: boolean; onChange: (d: QuoteDetail) => void; onMail: (t: MailTarget) => void;
}) {
  const patch = useMutation({
    mutationFn: ({ iid, body }: { iid: number; body: Parameters<typeof api.quoteInsurerUpdate>[2] }) => api.quoteInsurerUpdate(q.id, iid, body),
    onSuccess: onChange, onError: (e) => toastError(e),
  });
  const remove = useMutation({ mutationFn: (iid: number) => api.quoteInsurerRemove(q.id, iid), onSuccess: onChange, onError: (e) => toastError(e) });
  const toSend = c.rows.filter((r) => r.status === "to_send");
  // relance : les branches parties dans le même email que la ligne choisie
  const thread = (r: QuoteRow) => c.rows.filter((x) => x.last_message_id && x.last_message_id === r.last_message_id).map((x) => x.id);
  const waiting = c.rows.find((r) => r.status === "sent" || r.status === "reminded");
  const recipients = [...new Set(c.rows.flatMap((r) => r.recipients))];
  return (
    <li className="px-4 py-3 sm:px-6">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="flex min-w-[14rem] flex-1 items-center gap-3">
          <Logo name={c.company} kind="insurer" src={c.logo} className="size-9" />
          <div className="min-w-0 flex-1">
            <p className="flex flex-wrap items-center gap-2 font-medium">{c.company}
              {!multi && <Badge variant={INSURER[c.rows[0].status].variant}>{INSURER[c.rows[0].status].label}</Badge>}</p>
            <p className="truncate text-xs text-muted-foreground">
              {recipients.length ? recipients.join(", ") : c.contacts.length ? `${c.contacts[0].name} · ${c.contacts[0].email}`
                : <span className="text-warning">Aucun interlocuteur : ajoutez une personne à la fiche de la compagnie</span>}
              {!multi && c.rows[0].sent_at && ` · envoyé ${relativeTime(c.rows[0].sent_at)}`}
              {!multi && c.rows[0].reminders_sent > 0 && ` · ${c.rows[0].reminders_sent} relance${c.rows[0].reminders_sent > 1 ? "s" : ""}`}
            </p>
          </div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {!multi && <OfferInputs r={c.rows[0]} onSave={(body) => patch.mutate({ iid: c.rows[0].id, body })} />}
          {toSend.length > 0 && <Button size="sm" onClick={() => onMail({ company: c, ids: toSend.map((r) => r.id) })}><Send /> Préparer la demande</Button>}
          {toSend.length === 0 && waiting && <Button size="sm" variant="outline" onClick={() => onMail({ company: c, ids: thread(waiting) })}><MailPlus /> Relancer</Button>}
          {!multi && c.rows[0].status === "renegotiate" && <Button size="sm" variant="outline" onClick={() => onMail({ company: c, ids: thread(c.rows[0]) })}><MailPlus /> Renégocier</Button>}
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button size="icon" variant="ghost" className="size-8" aria-label={`Actions ${c.company}`}><MoreHorizontal /></Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {!multi && <>
                {c.rows[0].status !== "to_send" && <DropdownMenuItem onSelect={() => onMail({ company: c, ids: thread(c.rows[0]) })}><MailPlus /> Écrire dans le fil</DropdownMenuItem>}
                {MARKS.filter((s) => s !== c.rows[0].status).map((s) => (
                  <DropdownMenuItem key={s} onSelect={() => patch.mutate({ iid: c.rows[0].id, body: { status: s } })}>Marquer « {INSURER[s].label} »</DropdownMenuItem>
                ))}
              </>}
              <DropdownMenuItem asChild><Link to={`/companies/${c.company_id}`}><Building2 /> Fiche de la compagnie</Link></DropdownMenuItem>
              {!multi && c.rows[0].status === "to_send" && <><DropdownMenuSeparator /><DropdownMenuItem destructive onSelect={() => remove.mutate(c.rows[0].id)}><Trash2 /> Retirer du dossier</DropdownMenuItem></>}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
      {multi && (
        <ul className="mt-2.5 space-y-1.5 pl-12">
          {c.rows.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-2 text-sm">
              <span className="min-w-[9rem] font-medium">{r.branch}</span>
              <Badge variant={INSURER[r.status].variant}>{INSURER[r.status].label}</Badge>
              {r.sent_at && <span className="text-xs text-muted-foreground">envoyé {relativeTime(r.sent_at)}{r.reminders_sent > 0 && ` · ${r.reminders_sent} relance${r.reminders_sent > 1 ? "s" : ""}`}</span>}
              <span className="ml-auto flex items-center gap-1.5">
                <OfferInputs r={r} onSave={(body) => patch.mutate({ iid: r.id, body })} compact />
                <DropdownMenu>
                  <DropdownMenuTrigger asChild><Button size="icon" variant="ghost" className="size-7" aria-label={`Statut ${c.company} ${r.branch}`}><MoreHorizontal /></Button></DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    {r.status === "to_send" && <DropdownMenuItem onSelect={() => onMail({ company: c, ids: [r.id] })}><Send /> Envoyer cette branche seule</DropdownMenuItem>}
                    {r.status !== "to_send" && <DropdownMenuItem onSelect={() => onMail({ company: c, ids: thread(r) })}><MailPlus /> {r.status === "renegotiate" ? "Renégocier" : "Relancer"}</DropdownMenuItem>}
                    {MARKS.filter((s) => s !== r.status).map((s) => (
                      <DropdownMenuItem key={s} onSelect={() => patch.mutate({ iid: r.id, body: { status: s } })}>Marquer « {INSURER[s].label} »</DropdownMenuItem>
                    ))}
                    {r.status === "to_send" && <><DropdownMenuSeparator /><DropdownMenuItem destructive onSelect={() => remove.mutate(r.id)}><Trash2 /> Ne pas consulter pour cette branche</DropdownMenuItem></>}
                  </DropdownMenuContent>
                </DropdownMenu>
              </span>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function OfferInputs({ r, onSave, compact }: { r: QuoteRow; onSave: (b: { offer_premium?: string; offer_rate?: string }) => void; compact?: boolean }) {
  const fmt = (n: number | null) => (n != null ? n.toLocaleString("fr-FR") : "");
  const [p, setP] = useState(fmt(r.offer_premium));
  const [t, setT] = useState(r.offer_rate ?? "");
  useEffect(() => { setP(fmt(r.offer_premium)); setT(r.offer_rate ?? ""); }, [r.offer_premium, r.offer_rate]);
  if (!(r.status === "offer" || r.status === "renegotiate" || r.offer_premium != null)) return null;
  return (
    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
      {!compact && "Prime"}
      <Input value={p} onChange={(e) => setP(e.target.value)} onBlur={() => p !== fmt(r.offer_premium) && onSave({ offer_premium: p })}
        className={cn("h-8 text-right tabular", compact ? "w-24" : "w-28")} placeholder="Prime" aria-label="Prime proposée (MAD)" />
      MAD
      <Input value={t} onChange={(e) => setT(e.target.value)} onBlur={() => t !== (r.offer_rate ?? "") && onSave({ offer_rate: t })}
        className="h-8 w-16 text-right tabular" placeholder="Taux" aria-label="Taux proposé" />
    </span>
  );
}

function AddInsurersDialog({ q, open, onOpenChange, onChange }: { q: QuoteDetail; open: boolean; onOpenChange: (o: boolean) => void; onChange: (d: QuoteDetail) => void }) {
  const { data } = useQuery({ queryKey: ["insurer-companies"], queryFn: api.quoteInsurerCompanies, enabled: open });
  const [picked, setPicked] = useState<number[]>([]);
  const [branches, setBranches] = useState<string[]>(q.branches);
  const [needle, setNeedle] = useState("");
  useEffect(() => { if (open) { setPicked([]); setNeedle(""); setBranches(q.branches); } }, [open, q.branches]);
  const have = new Map(q.companies.map((c) => [c.company_id, new Set(c.rows.map((r) => r.branch))]));
  const full = (id: number) => q.branches.every((b) => have.get(id)?.has(b));
  const add = useMutation({ mutationFn: () => api.quoteAddInsurers(q.id, picked, branches), onSuccess: (d) => { onChange(d); onOpenChange(false); }, onError: (e) => toastError(e) });
  const list = (data?.items ?? []).filter((c) => c.name.toLowerCase().includes(needle.toLowerCase()));
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Compagnies à consulter</DialogTitle>
          <DialogDescription>Les compagnies d'assurance de vos Entreprises. La demande partira vers leur interlocuteur « souscription » s'il y en a un.</DialogDescription>
        </DialogHeader>
        {q.branches.length > 1 && (
          <div className="flex flex-wrap items-center gap-1.5 text-sm">
            <span className="mr-1 text-muted-foreground">Pour :</span>
            {q.branches.map((b) => {
              const on = branches.includes(b);
              return <Button key={b} size="sm" variant={on ? "default" : "outline"} onClick={() => setBranches((p) => (on ? p.filter((x) => x !== b) : [...p, b]))}>{b}</Button>;
            })}
          </div>
        )}
        <Input value={needle} onChange={(e) => setNeedle(e.target.value)} placeholder="Rechercher" aria-label="Rechercher une compagnie" />
        <div className="max-h-80 divide-y overflow-y-auto rounded-md border">
          {!data ? <Skeleton className="h-40" /> : list.length === 0 ? <p className="p-4 text-sm text-muted-foreground">Aucune compagnie. Ajoutez-les dans Entreprises (type « Assureur »).</p> : list.map((c) => {
            const already = full(c.id);
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
          <Button disabled={!picked.length || !branches.length || add.isPending} onClick={() => add.mutate()}>Ajouter {picked.length || ""}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Choix des destinataires : les interlocuteurs de la compagnie (souscription d'abord) + une adresse libre. */
function RecipientPicker({ options, value, onChange }: { options: { email: string; name: string; department: string | null }[]; value: string[]; onChange: (v: string[]) => void }) {
  const [extra, setExtra] = useState("");
  const toggle = (e: string) => onChange(value.includes(e) ? value.filter((x) => x !== e) : [...value, e]);
  const others = value.filter((e) => !options.some((o) => o.email === e));
  const addExtra = () => { const e = extra.trim().toLowerCase(); if (/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(e) && !value.includes(e)) onChange([...value, e]); setExtra(""); };
  return (
    <div className="space-y-1.5">
      <div className="max-h-40 overflow-y-auto rounded-md border">
        {options.map((o) => (
          <label key={o.email} className="flex cursor-pointer items-center gap-2.5 px-3 py-1.5 text-sm hover:bg-muted/60">
            <Checkbox checked={value.includes(o.email)} onCheckedChange={() => toggle(o.email)} />
            <span className="min-w-0 flex-1 truncate">{o.name} <span className="text-muted-foreground">· {o.email}</span></span>
            {o.department && <span className={cn("text-xs", o.department === "souscription" ? "font-medium text-primary" : "text-muted-foreground")}>{o.department}</span>}
          </label>
        ))}
        {options.length === 0 && <p className="px-3 py-2 text-xs text-muted-foreground">Aucun contact enregistré pour cette compagnie.</p>}
      </div>
      {others.map((e) => (
        <span key={e} className="mr-1.5 inline-flex items-center gap-1 rounded-md bg-muted px-2 py-0.5 text-xs">{e}
          <button onClick={() => toggle(e)} aria-label={`Retirer ${e}`}><X className="size-3" /></button></span>
      ))}
      <div className="flex gap-2">
        <Input value={extra} onChange={(e) => setExtra(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addExtra(); } }}
          placeholder="Autre adresse" className="h-8" aria-label="Ajouter une adresse" />
        <Button type="button" size="sm" variant="outline" onClick={addExtra} disabled={!extra.trim()}>Ajouter</Button>
      </div>
    </div>
  );
}

function ConsultDialog({ q, target, onClose, onChange }: { q: QuoteDetail; target: MailTarget | null; onClose: () => void; onChange: (d: QuoteDetail) => void }) {
  const [ids, setIds] = useState<number[]>([]);
  const [to, setTo] = useState<string[] | null>(null);  // null = destinataires proposés par le serveur
  useEffect(() => { if (target) { setIds(target.ids); setTo(null); } }, [target]);
  const { data: draft, isFetching } = useQuery({
    queryKey: ["quote-draft", q.id, ids.join(","), to?.join(",") ?? ""],
    queryFn: () => api.quoteDraft(q.id, { insurer_ids: ids, ...(to ? { to } : {}) }),
    enabled: !!target && ids.length > 0, gcTime: 0, placeholderData: (p) => p,
  });
  const [cc, setCc] = useState(""); const [subject, setSubject] = useState(""); const [body, setBody] = useState("");
  const [atts, setAtts] = useState<number[]>([]);
  const [confirm, setConfirm] = useState<string | null>(null);
  useEffect(() => {
    if (!draft) return;
    setSubject(draft.subject); setBody(draft.body); setAtts(draft.attachments.filter((a) => a.checked).map((a) => a.id));
    if (to === null) setTo(draft.to);
  }, [draft]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (target) setCc(""); }, [target]);
  const left = useMemo(() => [...new Set([...`${subject}\n${body}`.matchAll(/\[([^[\]\n]{2,60})\]/g)].map((m) => m[1]))], [subject, body]);
  // branches que l'on peut regrouper dans cet email (même nature d'envoi que la sélection de départ)
  const rows = target?.company.rows ?? [];
  const choosable = target ? rows.filter((r) => (rows.find((x) => x.id === target.ids[0])?.status === "to_send" ? r.status === "to_send"
    : r.last_message_id && r.last_message_id === rows.find((x) => x.id === target.ids[0])?.last_message_id)) : [];
  const send = useMutation({
    mutationFn: (force: boolean) => api.quoteSend(q.id, { insurer_ids: ids, to: to ?? [], cc, subject, body, attachment_ids: atts, force }),
    onSuccess: (d) => {
      onChange(d);
      toast.success(draft?.kind === "request" ? "Demande de cotation envoyée" : draft?.kind === "renegotiate" ? "Demande de renégociation envoyée" : "Relance envoyée",
        { description: `À ${(to ?? []).join(", ")}. Relance proposée dans l'Agenda si pas de réponse.` });
      onClose();
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409 && e.data.confirm) setConfirm(e.message);
      else toastError(e, "Email non envoyé");
    },
  });
  const title = draft?.kind === "renegotiate" ? "Renégociation" : draft?.followup ? "Relance" : "Demande de cotation";
  return (
    <Dialog open={!!target} onOpenChange={(o) => !o && onClose()}>
      <DialogContent side="right" className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title} · {target?.company.company}</DialogTitle>
          <DialogDescription>Préparée avec {ids.length > 1 ? "les modèles des branches" : "le modèle de la branche"} et la fiche du dossier. Relisez, puis envoyez depuis votre boîte.</DialogDescription>
        </DialogHeader>
        {!draft ? <Skeleton className="h-96" /> : (
          <div className={cn("space-y-3", isFetching && "opacity-60")}>
            {choosable.length > 1 && (
              <FieldGroup label="Branches dans cet email" hint={ids.length > 1 ? "Un seul email pour ces branches. Décochez pour envoyer une branche à part (à d'autres personnes, par exemple)." : "Cochez plusieurs branches pour un email commun."}>
                <div className="flex flex-wrap gap-1.5">
                  {choosable.map((r) => {
                    const on = ids.includes(r.id);
                    return <Button key={r.id} type="button" size="sm" variant={on ? "default" : "outline"}
                      onClick={() => setIds((p) => (on ? (p.length > 1 ? p.filter((x) => x !== r.id) : p) : [...p, r.id]))}>{r.branch}</Button>;
                  })}
                </div>
              </FieldGroup>
            )}
            <FieldGroup label="À" hint="Plusieurs personnes possibles : la formule d'appel s'adapte (« Bonjour Nadia et Rachid »).">
              <RecipientPicker options={draft.options} value={to ?? []} onChange={setTo} />
            </FieldGroup>
            <Field label="Cc"><Input value={cc} onChange={(e) => setCc(e.target.value)} placeholder="Facultatif" /></Field>
            <Field label="Objet"><Input value={subject} onChange={(e) => setSubject(e.target.value)} /></Field>
            <Field label="Message" hint="Votre signature est ajoutée automatiquement. Changer les branches ou les destinataires régénère le texte.">
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
                    <Paperclip className="size-3.5 text-muted-foreground" />{a.label || a.name}
                    <span className="text-xs text-muted-foreground">{a.kind === "current" ? "conditions actuelles" : a.label && a.name}</span>
                  </label>
                ))}
              </div>
            )}
            <DialogFooter className="pt-2">
              <Button variant="outline" onClick={onClose}>Annuler</Button>
              <Button disabled={!(to ?? []).length || left.length > 0 || send.isPending || isFetching} onClick={() => send.mutate(false)}>
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

function SendAllDialog({ q, open, onOpenChange, onChange }: { q: QuoteDetail; open: boolean; onOpenChange: (o: boolean) => void; onChange: (d: QuoteDetail) => void }) {
  const pending = q.companies.filter((c) => c.rows.some((r) => r.status === "to_send"));
  const [report, setReport] = useState<SendAllReport | null>(null);
  useEffect(() => { if (open) setReport(null); }, [open]);
  const go = useMutation({
    mutationFn: () => api.quoteSendAll(q.id),
    onSuccess: (r) => { onChange(r.quote); setReport(r.report); const ok = r.report.filter((x) => x.ok).length; toast.success(`${ok} demande${ok > 1 ? "s" : ""} envoyée${ok > 1 ? "s" : ""}`); },
    onError: (e) => toastError(e),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Envoyer à toutes les compagnies</DialogTitle>
          <DialogDescription>Un email par compagnie{q.branches.length > 1 ? ", commun à toutes ses branches" : ""}, préparé avec la fiche du dossier, vers les destinataires ci-dessous. Pour relire ou modifier un email, utilisez plutôt « Préparer la demande ».</DialogDescription>
        </DialogHeader>
        {report ? (
          <ul className="space-y-1.5 text-sm">
            {report.map((r) => (
              <li key={r.company} className="flex items-start gap-2">
                {r.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" /> : <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />}
                <span><b className="font-medium">{r.company}</b> · {r.ok ? `envoyé à ${r.to?.join(", ")}` : r.reason}</span>
              </li>
            ))}
          </ul>
        ) : (
          <ul className="divide-y rounded-md border text-sm">
            {pending.map((c) => {
              const rows = c.rows.filter((r) => r.status === "to_send");
              const to = [...new Set(rows.flatMap((r) => r.recipients))];
              return (
                <li key={c.company_id} className="px-3 py-2">
                  <p className="font-medium">{c.company}{q.branches.length > 1 && <span className="font-normal text-muted-foreground"> · {rows.map((r) => r.branch).join(", ")}</span>}</p>
                  <p className={cn("text-xs", to.length ? "text-muted-foreground" : "text-warning")}>{to.length ? to.join(", ") : "Aucun destinataire : sera laissée de côté"}</p>
                </li>
              );
            })}
          </ul>
        )}
        {q.missing_labels.length > 0 && !report && (
          <p className="flex items-start gap-2 rounded-md bg-warning/10 p-2.5 text-sm text-warning"><AlertTriangle className="mt-0.5 size-4 shrink-0" />
            La fiche n'est pas complète : les emails qui contiendraient encore un [champ] à compléter ne partiront pas.</p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>{report ? "Fermer" : "Annuler"}</Button>
          {!report && <Button disabled={go.isPending} onClick={() => go.mutate()}>{go.isPending ? <RotateCw className="animate-spin" /> : <SendHorizontal />} Envoyer {pending.length} email{pending.length > 1 ? "s" : ""}</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ fiche de renseignements */

function BranchFormCard({ q, onChange }: { q: QuoteDetail; onChange: (d: QuoteDetail) => void }) {
  const [vals, setVals] = useState<Record<string, string>>(q.fields);
  useEffect(() => setVals(q.fields), [q.fields]);
  const dirty = q.field_defs.some((f) => (vals[f.key] ?? "") !== (q.fields[f.key] ?? ""));
  const save = useMutation({
    mutationFn: () => api.quoteUpdate(q.id, { fields: Object.fromEntries(q.field_defs.map((f) => [f.key, vals[f.key] ?? null])) }),
    onSuccess: (d) => { onChange(d); toast.success("Fiche enregistrée"); }, onError: (e) => toastError(e),
  });
  if (q.field_defs.length === 0) {
    return (
      <Card>
        <CardHeader><CardTitle>Fiche de renseignements</CardTitle></CardHeader>
        <CardContent className="text-sm text-muted-foreground">La branche « {q.branch_label} » n'a pas de fiche prédéfinie : notez les informations du client dans les notes du dossier.</CardContent>
      </Card>
    );
  }
  const multi = q.branches.length > 1;
  const groups: { title: string | null; fields: BranchField[] }[] = multi
    ? [{ title: "Commun à plusieurs branches", fields: q.field_defs.filter((f) => (f.branches?.length ?? 0) > 1) },
       ...q.branches.map((b) => ({ title: b, fields: q.field_defs.filter((f) => f.branches?.length === 1 && f.branches[0] === b) }))]
    : [{ title: null, fields: q.field_defs }];
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="flex items-center gap-2">Fiche de renseignements
          {q.missing_labels.length > 0 ? <Badge variant="warning">{q.missing_labels.length} à compléter</Badge> : <Badge variant="success">Complète</Badge>}
        </CardTitle>
        {dirty && <Button size="sm" disabled={save.isPending} onClick={() => save.mutate()}>Enregistrer</Button>}
      </CardHeader>
      <CardContent className="space-y-6">
        {groups.filter((g) => g.fields.length).map((g) => (
          <div key={g.title ?? "x"}>
            {g.title && <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{g.title}</p>}
            <div className="grid gap-4 sm:grid-cols-2">
              {g.fields.map((f) => <BranchInput key={f.key} f={f} value={vals[f.key] ?? ""} onChange={(v) => setVals((p) => ({ ...p, [f.key]: v }))} />)}
            </div>
          </div>
        ))}
        <p className="text-xs text-muted-foreground">Ces informations remplissent automatiquement les demandes envoyées aux compagnies. Un champ facultatif laissé vide est retiré de l'email.</p>
        {dirty && <div className="flex justify-end"><Button size="sm" disabled={save.isPending} onClick={() => save.mutate()}>Enregistrer la fiche</Button></div>}
      </CardContent>
    </Card>
  );
}

function BranchInput({ f, value, onChange }: { f: BranchField; value: string; onChange: (v: string) => void }) {
  const empty = !value.trim();
  const label = <span className="flex items-center gap-1.5">{f.label}{f.unit && <span className="font-normal text-muted-foreground">({f.unit})</span>}
    {f.optional ? <span className="font-normal text-muted-foreground">· facultatif</span> : empty && <span className="size-1.5 rounded-full bg-warning" title="À compléter" />}</span>;
  const wide = f.type === "textarea" || (f.type === "choice" && (f.options?.join("").length ?? 0) > 30);
  if (f.type === "choice") {
    return (
      <FieldGroup label={label} hint={f.hint} className={cn(wide && "sm:col-span-2")}>
        <div className="flex flex-wrap gap-1.5">
          {f.options!.map((o) => <Button key={o} type="button" size="sm" variant={value === o ? "default" : "outline"} onClick={() => onChange(value === o ? "" : o)}>{o}</Button>)}
        </div>
      </FieldGroup>
    );
  }
  return (
    <Field label={label} hint={f.hint} className={cn(wide && "sm:col-span-2")}>
      {f.type === "textarea" ? (
        <Textarea rows={2} value={value} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <Input type={f.type === "date" ? "date" : "text"} inputMode={f.type === "number" ? "decimal" : undefined} value={value}
          onChange={(e) => onChange(e.target.value)} className={cn(f.type === "number" && "tabular", f.type === "date" && "w-44")} />
      )}
    </Field>
  );
}

/* ------------------------------------------------------------------ dossier, rappels, documents, notes */

function InfoCard({ q, save }: { q: QuoteDetail; save: (b: Parameters<typeof api.quoteUpdate>[1]) => void }) {
  const { data: people } = useQuery({ queryKey: ["quote-people"], queryFn: api.quotePeople });
  const fmt = (n: number | null) => (n != null ? n.toLocaleString("fr-FR") : "");
  const [premium, setPremium] = useState(fmt(q.current_premium));
  const [insurer, setInsurer] = useState(q.current_insurer ?? "");
  const [rate, setRate] = useState(q.current_rate ?? "");
  useEffect(() => { setPremium(fmt(q.current_premium)); setInsurer(q.current_insurer ?? ""); setRate(q.current_rate ?? ""); }, [q.current_premium, q.current_insurer, q.current_rate]);
  const others = q.all_branches.filter((b) => !q.branches.includes(b));
  return (
    <Card>
      <CardHeader><CardTitle>Dossier</CardTitle></CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div>
          <p className="text-xs text-muted-foreground">Client</p>
          {q.company ? <Link to={`/companies/${q.company.id}`} className="font-medium hover:text-primary hover:underline">{q.company.name}</Link> : <p className="font-medium">{q.client_name}</p>}
          {q.contact && <p className="text-muted-foreground">{q.contact.name} · {q.contact.email}</p>}
        </div>
        <div>
          <p className="mb-1.5 text-xs text-muted-foreground">Branches</p>
          <div className="flex flex-wrap items-center gap-1.5">
            {q.branches.map((b) => (
              <span key={b} className="inline-flex items-center gap-1 rounded-md bg-secondary px-2 py-1 text-xs font-medium">{b}
                {q.branches.length > 1 && <button title={`Retirer ${b}`} onClick={() => save({ branches: q.branches.filter((x) => x !== b) })}><X className="size-3" /></button>}
              </span>
            ))}
            {others.length > 0 && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild><Button size="sm" variant="ghost" className="h-7 px-2 text-xs"><Plus /> Branche</Button></DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                  {others.map((b) => <DropdownMenuItem key={b} onSelect={() => save({ branches: [...q.branches, b] })}>{b}</DropdownMenuItem>)}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
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
        <Field label="Assureur actuel">
          <Input value={insurer} onChange={(e) => setInsurer(e.target.value)} onBlur={() => insurer !== (q.current_insurer ?? "") && save({ current_insurer: insurer })} placeholder="—" />
        </Field>
        <div className="grid grid-cols-[1fr_6.5rem] gap-3">
          <Field label="Prime actuelle (MAD)">
            <Input value={premium} onChange={(e) => setPremium(e.target.value)} className="tabular" placeholder="—"
              onBlur={() => premium !== fmt(q.current_premium) && save({ current_premium: premium || null })} />
          </Field>
          <Field label="Taux actuel">
            <Input value={rate} onChange={(e) => setRate(e.target.value)} className="tabular" placeholder="ex. 2,5 %"
              onBlur={() => rate !== (q.current_rate ?? "") && save({ current_rate: rate })} />
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

const REMINDER_PRESETS: Partial<Record<QuoteStage, string>> = {
  new: "Réunir les infos client", info: "Réunir les infos client", consulting: "Relancer les compagnies",
  partial: "Relancer les compagnies sans réponse", offers: "Envoyer la proposition au client", proposed: "Relancer le client sur la proposition",
};

function RemindersCard({ q, onChange }: { q: QuoteDetail; onChange: (d: QuoteDetail) => void }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(""); const [due, setDue] = useState(""); const [time, setTime] = useState("");
  const start = () => { setTitle(REMINDER_PRESETS[q.stage] ?? ""); setDue(""); setTime(""); setOpen(true); };
  const add = useMutation({
    mutationFn: () => api.quoteReminder(q.id, { title, due_on: due, due_time: time || null }),
    onSuccess: (d) => { onChange(d); setOpen(false); qc.invalidateQueries({ queryKey: ["reminders"] }); toast.success("Rappel ajouté à l'agenda", { description: "Une alerte apparaîtra dans la cloche le jour venu." }); },
    onError: (e) => toastError(e),
  });
  const toggle = useMutation({
    mutationFn: ({ id, done }: { id: number; done: boolean }) => api.reminderUpdate(id, { done }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["quote", q.id] }), onError: (e) => toastError(e),
  });
  const today = new Date().toISOString().slice(0, 10);
  const open_ = q.reminders.filter((r) => !r.done);
  const done = q.reminders.filter((r) => r.done);
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle className="flex items-center gap-2"><Bell className="size-4 text-muted-foreground" />Rappels</CardTitle>
        <Button size="sm" variant="outline" onClick={start}><CalendarPlus /> Rappel</Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {open && (
          <form className="space-y-2 rounded-md border bg-muted/30 p-3" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
            <Input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ce qu'il faut faire" aria-label="Rappel" />
            <div className="flex flex-wrap gap-1.5">
              {[["Demain", 1], ["Dans 3 jours", 3], ["Dans 1 semaine", 7]].map(([l, n]) => (
                <Button key={l} type="button" size="sm" variant="outline" className="h-7 text-xs"
                  onClick={() => { const d = new Date(); d.setDate(d.getDate() + Number(n)); setDue(d.toISOString().slice(0, 10)); }}>{l}</Button>
              ))}
            </div>
            <div className="flex gap-2">
              <Input type="date" value={due} min={today} onChange={(e) => setDue(e.target.value)} className="w-40" aria-label="Date" />
              <Input type="time" value={time} onChange={(e) => setTime(e.target.value)} className="w-28" aria-label="Heure (facultatif)" />
            </div>
            <div className="flex justify-end gap-2">
              <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)}>Annuler</Button>
              <Button type="submit" size="sm" disabled={!title.trim() || !due || add.isPending}>Ajouter</Button>
            </div>
          </form>
        )}
        {q.reminders.length === 0 && !open && <p className="text-sm text-muted-foreground">Aucun rappel. Ajoutez une échéance (réunir les infos, relancer le client…) : elle s'affiche dans l'Agenda et déclenche une alerte.</p>}
        {[...open_, ...done].map((r) => (
          <div key={r.id} className={cn("flex items-start gap-2.5 text-sm", r.done && "opacity-60")}>
            <button disabled={!r.mine} onClick={() => toggle.mutate({ id: r.id, done: !r.done })} aria-label={r.done ? "Marquer à faire" : "Marquer fait"}
              title={r.mine ? undefined : `Rappel de ${r.user_name ?? "un collègue"}`}
              className={cn("mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border", r.done ? "border-success bg-success text-white" : "hover:border-primary")}>
              {r.done && <Check className="size-2.5" />}
            </button>
            <div className="min-w-0 flex-1">
              <p className={cn(r.done && "line-through")}>{r.title}</p>
              <p className={cn("text-xs", !r.done && r.due_on < today ? "font-medium text-destructive" : "text-muted-foreground")}>
                {shortDate(r.due_on)}{r.due_time && ` à ${r.due_time}`}{!r.mine && r.user_name && ` · ${r.user_name}`}</p>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

const FILE_TABS: { kind: QuoteFileKind; label: string; empty: string }[] = [
  { kind: "client", label: "Pièces du client", empty: "Les pièces du client sont proposées en pièce jointe des demandes." },
  { kind: "current", label: "Conditions actuelles", empty: "Ancienne police, conditions particulières, avenants, anciennes cotations… Aussi proposées en pièce jointe des demandes." },
  { kind: "offer", label: "Offres", empty: "Les offres reçues des compagnies (ou « Ranger comme offre » depuis une réponse)." },
];

function FilesCard({ q, onChange }: { q: QuoteDetail; onChange: (d: QuoteDetail) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [tab, setTab] = useState<QuoteFileKind>("client");
  const [label, setLabel] = useState("");
  const [insurerId, setInsurerId] = useState<number | null>(null);
  const upload = useMutation({
    mutationFn: async (f: File) => { const a = await api.uploadAttachment(f); return api.quoteAddFile(q.id, { attachment_id: a.id, kind: tab, label, insurer_id: tab === "offer" ? insurerId : null }); },
    onSuccess: (d) => { onChange(d); setLabel(""); toast.success("Document ajouté"); }, onError: (e) => toastError(e, "Document non ajouté"),
  });
  const remove = useMutation({ mutationFn: (fid: number) => api.quoteRemoveFile(q.id, fid), onSuccess: onChange, onError: (e) => toastError(e) });
  const pick = (l = "", iid: number | null = null) => { setLabel(l); setInsurerId(iid); setTimeout(() => input.current?.click(), 0); };
  const have = new Set(q.files.filter((f) => f.kind === "client").map((f) => f.label));
  const rowName = new Map(q.companies.flatMap((c) => c.rows.map((r) => [r.id, q.branches.length > 1 ? `${c.company} · ${r.branch}` : c.company] as const)));
  const consulted = q.companies.flatMap((c) => c.rows.filter((r) => r.status !== "to_send").map((r) => ({ id: r.id, name: rowName.get(r.id)! })));
  const list = q.files.filter((f) => (tab === "client" ? f.kind === "client" || f.kind === "other" : f.kind === tab));
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle>Documents</CardTitle>
        {tab === "offer" && consulted.length > 0 ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild><Button size="sm" variant="outline" disabled={upload.isPending}>{upload.isPending ? <RotateCw className="animate-spin" /> : <Upload />} Ajouter</Button></DropdownMenuTrigger>
            <DropdownMenuContent align="end">{consulted.map((c) => <DropdownMenuItem key={c.id} onSelect={() => pick("", c.id)}>Offre de {c.name}</DropdownMenuItem>)}</DropdownMenuContent>
          </DropdownMenu>
        ) : <Button size="sm" variant="outline" disabled={upload.isPending} onClick={() => pick()}>{upload.isPending ? <RotateCw className="animate-spin" /> : <Upload />} Ajouter</Button>}
        <input ref={input} type="file" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-1 rounded-lg bg-muted p-1">
          {FILE_TABS.map((t) => {
            const n = q.files.filter((f) => (t.kind === "client" ? f.kind === "client" || f.kind === "other" : f.kind === t.kind)).length;
            return (
              <button key={t.kind} onClick={() => setTab(t.kind)}
                className={cn("flex-1 rounded-md px-2 py-1.5 text-xs font-medium transition-colors", tab === t.kind ? "bg-card shadow-sm" : "text-muted-foreground hover:text-foreground")}>
                {t.label}{n > 0 && <span className="ml-1 tabular text-muted-foreground">{n}</span>}
              </button>
            );
          })}
        </div>
        {tab === "client" && q.docs.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground">À demander au client</p>
            {q.docs.map((d) => (
              <div key={d} className="flex items-start gap-2 text-sm">
                {have.has(d) ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" /> : <Circle className="mt-0.5 size-4 shrink-0 text-muted-foreground" />}
                <span className={cn("flex-1", have.has(d) && "text-muted-foreground")}>{d}</span>
                {!have.has(d) && <button className="text-xs text-primary hover:underline" onClick={() => pick(d)}>Ajouter</button>}
              </div>
            ))}
          </div>
        )}
        {list.length === 0 ? <p className="text-sm text-muted-foreground">{FILE_TABS.find((t) => t.kind === tab)!.empty}</p> : (
          <ul className="space-y-1.5">
            {list.map((f) => (
              <li key={f.file_id} className="group flex items-center gap-2 text-sm">
                <FileText className={cn("size-4 shrink-0", f.kind === "offer" ? "text-brand" : "text-muted-foreground")} />
                <a href={`/api/attachments/${f.id}?t=${f.token}`} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate hover:text-primary hover:underline" title={f.name}>
                  {f.label || f.name}
                </a>
                {f.kind === "offer" && f.insurer_id && rowName.get(f.insurer_id) && <Badge variant="success">{rowName.get(f.insurer_id)}</Badge>}
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
    onSuccess: (d) => { onChange(d); toast.success("Rangé dans les offres du dossier"); }, onError: (err) => toastError(err),
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
