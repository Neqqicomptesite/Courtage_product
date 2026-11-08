// Agenda (V2.8) : un calendrier de rappels. « Rappeler dans 3 jours », « relancer le devis
// dans 1 semaine », « renouvellement le 15 »… Chaque rappel arrive dans les notifications le
// jour venu (et y reste tant qu'il n'est pas coché). Les « À rappeler plus tard » posés depuis
// une réponse y apparaissent aussi, en lecture seule.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Building2, CalendarClock, CalendarDays, Check, ChevronLeft, ChevronRight, FileSignature, Handshake, Mail,
  PhoneCall, Plus, RefreshCcw, StickyNote, Trash2, UserRound,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { Field, PageHeader, fieldError, toastError } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api, type ContactRef, type ReminderItem, type ReminderKind } from "@/lib/api";
import { fullName } from "@/lib/format";
import { cn } from "@/lib/utils";

export const REMINDER_KINDS: { value: ReminderKind; label: string; icon: typeof PhoneCall; title: string }[] = [
  { value: "call", label: "Appeler", icon: PhoneCall, title: "Appeler" },
  { value: "email", label: "Envoyer un email", icon: Mail, title: "Écrire à" },
  { value: "quote", label: "Relancer un devis", icon: FileSignature, title: "Relancer le devis de" },
  { value: "meeting", label: "Rendez-vous", icon: Handshake, title: "Rendez-vous avec" },
  { value: "renewal", label: "Renouvellement", icon: RefreshCcw, title: "Renouvellement du contrat de" },
  { value: "other", label: "Autre (libre)", icon: StickyNote, title: "" },
];
const KIND = Object.fromEntries(REMINDER_KINDS.map((k) => [k.value, k])) as Record<ReminderKind, (typeof REMINDER_KINDS)[number]>;
const KIND_TONE: Record<ReminderKind, string> = {
  call: "bg-primary/10 text-primary", email: "bg-sky-500/10 text-sky-600 dark:text-sky-400",
  quote: "bg-warning/15 text-warning", meeting: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
  renewal: "bg-success/15 text-success", other: "bg-muted text-muted-foreground",
};
const PRESETS = [
  { label: "Demain", days: 1 }, { label: "Dans 3 jours", days: 3 }, { label: "Dans 1 semaine", days: 7 },
  { label: "Dans 2 semaines", days: 14 }, { label: "Dans 1 mois", days: 30 }, { label: "Dans 3 mois", days: 91 },
];
const WEEKDAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."];

// ----------------------------------------------------------------- dates locales (sans fuseau)
const pad = (n: number) => String(n).padStart(2, "0");
export const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const parse = (s: string) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const addDays = (s: string, n: number) => { const d = parse(s); d.setDate(d.getDate() + n); return ymd(d); };
const longDay = (s: string) => parse(s).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
const monthLabel = (d: Date) => d.toLocaleDateString("fr-FR", { month: "long", year: "numeric" });

// ----------------------------------------------------------------- ouverture depuis n'importe où
export type ReminderRequest = {
  contact?: ContactRef | null; company?: { id: number; name: string } | null; kind?: ReminderKind; due_on?: string;
  edit?: ReminderItem;          // V2.11 : modifier un rappel existant
  contacts?: ContactRef[];      // V2.11 : un rappel pour chacune des personnes sélectionnées
};
export function openReminder(req: ReminderRequest = {}) {
  window.dispatchEvent(new CustomEvent<ReminderRequest>("oddo-reminder", { detail: req }));
}

/** Fenêtre « Ajouter un rappel », montée une seule fois dans la mise en page. */
export function ReminderDialog() {
  const qc = useQueryClient();
  const today = ymd(new Date());
  const [open, setOpen] = useState(false);
  const [req, setReq] = useState<ReminderRequest>({});
  const [kind, setKind] = useState<ReminderKind>("call");
  const [title, setTitle] = useState("");
  const [titleTouched, setTitleTouched] = useState(false);
  const [due, setDue] = useState(today);
  const [time, setTime] = useState("");
  const [notes, setNotes] = useState("");
  const [contact, setContact] = useState<ContactRef | null>(null);
  const [q, setQ] = useState("");
  const picker = useQuery({ queryKey: ["picker", q], queryFn: () => api.picker(q), enabled: open && !contact && q.length >= 2 });
  const many = (req.contacts?.length ?? 0) > 1 ? req.contacts! : null;
  const who = many ? "" : contact ? fullName(contact) : req.company?.name ?? "";
  const editing = req.edit;

  useEffect(() => {
    const on = (e: Event) => {
      const r = (e as CustomEvent<ReminderRequest>).detail ?? {};
      setQ("");
      if (r.edit) {
        const x = r.edit;
        setReq({ ...r, company: x.contact ? null : x.company });
        setKind(x.kind); setContact(x.contact); setDue(x.due_on); setTime(x.due_time ?? ""); setNotes(x.notes);
        setTitle(x.title); setTitleTouched(true);
      } else {
        const one = r.contacts?.length === 1 ? r.contacts[0] : r.contact ?? null;
        setReq(r);
        setKind(r.kind ?? (one || r.company || r.contacts?.length ? "call" : "other"));
        setContact(one);
        setDue(r.due_on ?? addDays(today, 3));
        setTime(""); setNotes(""); setTitle(""); setTitleTouched(false);
      }
      setOpen(true);
    };
    window.addEventListener("oddo-reminder", on);
    return () => window.removeEventListener("oddo-reminder", on);
  }, [today]);
  // Titre proposé selon le type et la personne, tant qu'il n'a pas été retouché à la main.
  useEffect(() => {
    if (!titleTouched) setTitle(kind === "other" ? "" : `${KIND[kind].title}${who ? ` ${who}` : ""}`.trim());
  }, [kind, who, titleTouched]);

  const save = useMutation({
    mutationFn: async () => {
      const base = { kind, notes, due_on: due, due_time: time || null };
      if (editing) return [await api.reminderUpdate(editing.id, { ...base, title, contact_id: contact?.id ?? null, company_id: contact ? null : req.company?.id ?? null })];
      if (many) {
        // un rappel par personne ; le titre proposé reprend son nom
        return Promise.all(many.map((c) => api.reminderCreate({
          ...base, title: titleTouched ? title : `${KIND[kind].title} ${fullName(c)}`.trim(), contact_id: c.id,
        })));
      }
      return [await api.reminderCreate({ ...base, title, contact_id: contact?.id ?? null, company_id: contact ? null : req.company?.id ?? null })];
    },
    onSuccess: (list) => {
      setOpen(false);
      ["reminders", "notifications"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      const r = list[0];
      toast.success(editing ? "Rappel modifié" : list.length > 1 ? `${list.length} rappels ajoutés` : "Rappel ajouté",
        { description: r ? `${longDay(r.due_on)}${r.due_time ? ` à ${r.due_time}` : ""}` : undefined });
    },
    onError: (e) => toastError(e, "Rappel non enregistré"),
  });
  const remove = useMutation({
    mutationFn: () => api.reminderDelete(editing!.id),
    onSuccess: () => { setOpen(false); ["reminders", "notifications"].forEach((k) => qc.invalidateQueries({ queryKey: [k] })); toast.success("Rappel supprimé"); },
    onError: (e) => toastError(e),
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? "Modifier le rappel" : many ? `Ajouter un rappel pour ${many.length} personnes` : "Ajouter un rappel"}</DialogTitle>
          <DialogDescription>{many ? "Un rappel par personne, à son nom. " : ""}Il apparaîtra dans vos notifications le jour venu.</DialogDescription>
        </DialogHeader>
        <form id="reminder-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <div className="grid grid-cols-3 gap-2">
            {REMINDER_KINDS.map((k) => (
              <button type="button" key={k.value} onClick={() => setKind(k.value)}
                className={cn("flex flex-col items-center gap-1 rounded-lg border px-2 py-2.5 text-xs transition-colors",
                  kind === k.value ? "border-primary bg-primary/5 font-medium text-foreground" : "text-muted-foreground hover:bg-accent/40")}>
                <k.icon className="size-4" />{k.label}
              </button>
            ))}
          </div>

          <Field label="Pour qui ?" hint={many ? undefined : "Facultatif : un contact (son entreprise suit), ou rien pour un rappel libre."}>
            {many ? (
              <div className="flex max-h-24 flex-wrap gap-1 overflow-y-auto rounded-md border p-2">
                {many.map((c) => <span key={c.id} className="rounded-full bg-accent/60 px-2 py-0.5 text-xs">{fullName(c)}</span>)}
              </div>
            ) : contact ? (
              <div className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm">
                <UserRound className="size-4 text-muted-foreground" />
                <span className="flex-1 truncate">{fullName(contact)}{contact.company && <span className="text-muted-foreground"> · {contact.company}</span>}</span>
                <button type="button" className="text-xs text-muted-foreground hover:text-foreground" onClick={() => setContact(null)}>Changer</button>
              </div>
            ) : req.company ? (
              <div className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm">
                <Building2 className="size-4 text-muted-foreground" /><span className="flex-1 truncate">{req.company.name}</span>
                <button type="button" className="text-xs text-muted-foreground hover:text-foreground" onClick={() => setReq((r) => ({ ...r, company: null }))}>Retirer</button>
              </div>
            ) : (
              <div className="relative">
                <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Nom, email ou entreprise…" />
                {q.length >= 2 && (picker.data?.length ?? 0) > 0 && (
                  <ul className="absolute z-10 mt-1 max-h-56 w-full overflow-y-auto rounded-md border bg-popover shadow-lg">
                    {picker.data!.slice(0, 8).map((c) => (
                      <li key={c.id}>
                        <button type="button" className="w-full px-3 py-2 text-left text-sm hover:bg-accent/50" onClick={() => { setContact(c); setQ(""); }}>
                          {fullName(c)} <span className="text-muted-foreground">{c.company ? `· ${c.company}` : c.email}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </Field>

          <Field label="À faire" error={fieldError(save.error, "title")} hint={many && !titleTouched && kind !== "other" ? "Le nom de chaque personne est ajouté au titre." : undefined}>
            <Input value={many && !titleTouched && kind !== "other" ? KIND[kind].title : title} onChange={(e) => { setTitle(e.target.value); setTitleTouched(true); }} required
              placeholder={kind === "other" ? "ex. Préparer le dossier sinistre" : undefined} autoFocus={kind === "other"} />
          </Field>

          <div className="space-y-2">
            <div className="flex flex-wrap gap-1.5">
              {PRESETS.map((p) => {
                const d = addDays(today, p.days);
                return (
                  <button type="button" key={p.days} onClick={() => setDue(d)}
                    className={cn("rounded-full border px-2.5 py-1 text-xs transition-colors", due === d ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:bg-accent/40")}>
                    {p.label}
                  </button>
                );
              })}
            </div>
            <div className="grid grid-cols-[1fr_8rem] gap-3">
              <Field label="Le" error={fieldError(save.error, "due_on")}><Input type="date" value={due} onChange={(e) => setDue(e.target.value)} required /></Field>
              <Field label="Heure (facultatif)"><Input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></Field>
            </div>
            <p className="text-xs text-muted-foreground first-letter:uppercase">{longDay(due)}</p>
          </div>

          <Field label="Note"><Textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="ex. demander l'attestation, échéance au 31/12…" /></Field>
        </form>
        <DialogFooter className="gap-2 sm:justify-between">
          <div>{editing && <Button variant="ghost" className="text-destructive hover:text-destructive" disabled={remove.isPending} onClick={() => remove.mutate()}><Trash2 /> Supprimer</Button>}</div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => setOpen(false)}>Annuler</Button>
            <Button type="submit" form="reminder-form" disabled={save.isPending}>{editing ? <><Check /> Enregistrer</> : <><Plus /> Ajouter</>}</Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ----------------------------------------------------------------- une ligne de rappel
export function ReminderRow({ r, compact, onToggled }: { r: ReminderItem; compact?: boolean; onToggled?: (id: number) => void }) {
  const qc = useQueryClient();
  const today = ymd(new Date());
  const K = r.source === "callback" ? KIND.call : KIND[r.kind];
  const late = !r.done && r.due_on < today;
  const refresh = () => ["reminders", "notifications"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const toggle = useMutation({
    mutationFn: () => api.reminderUpdate(r.id, { done: !r.done }),
    onMutate: () => onToggled?.(r.id),
    onSuccess: refresh, onError: (e) => toastError(e),
  });
  const remove = useMutation({ mutationFn: () => api.reminderDelete(r.id), onSuccess: () => { refresh(); toast.success("Rappel supprimé"); }, onError: (e) => toastError(e) });

  return (
    <div className={cn("group flex items-start gap-3 px-4 py-3", r.done && "opacity-60")}>
      {r.source === "reminder" ? (
        <button onClick={() => toggle.mutate()} aria-label={r.done ? "Marquer à faire" : "Marquer fait"}
          className={cn("mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border transition-colors",
            r.done ? "border-success bg-success text-white" : "hover:border-primary")}>
          {r.done && <Check className="size-3" />}
        </button>
      ) : <span className="mt-0.5 size-5 shrink-0" />}
      <span className={cn("mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md", KIND_TONE[r.kind])}><K.icon className="size-3.5" /></span>
      <div className="min-w-0 flex-1">
        {r.source === "reminder" ? (
          <button onClick={() => openReminder({ edit: r })} title="Modifier" className={cn("text-left text-sm hover:text-primary hover:underline", r.done && "line-through")}>{r.title}</button>
        ) : <p className="text-sm">{r.title}</p>}
        <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
          {!compact && <span className={cn(late && "font-medium text-destructive")}>{late ? "En retard · " : ""}{longDay(r.due_on)}</span>}
          {r.due_time && <span>{r.due_time}</span>}
          {r.contact && <Link to={`/contacts?open=${r.contact.id}`} state={{ back: window.location.pathname.replace(/^\/v2/, "") + window.location.search }} className="hover:text-foreground hover:underline">{fullName(r.contact)}</Link>}
          {r.company && <Link to={`/companies/${r.company.id}`} className="hover:text-foreground hover:underline">{r.company.name}</Link>}
          {r.source === "callback" && <Link to="/replies?f=later" className="text-primary hover:underline">depuis sa réponse</Link>}
          {r.quote_case_id && <Link to={`/quotes/${r.quote_case_id}`} className="font-medium text-primary hover:underline">Ouvrir le dossier</Link>}
        </p>
        {r.notes && <p className="mt-0.5 whitespace-pre-line text-xs text-muted-foreground">{r.notes}</p>}
      </div>
      {r.source === "reminder" && (
        <button onClick={() => remove.mutate()} aria-label="Supprimer" className="rounded p-1 text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100 focus:opacity-100">
          <Trash2 className="size-3.5" />
        </button>
      )}
    </div>
  );
}

/** Rappels d'un contact ou d'une entreprise (fiche contact, page entreprise). */
export function RemindersPanel({ contact, company }: { contact?: ContactRef; company?: { id: number; name: string } }) {
  const today = ymd(new Date());
  const f = { start: addDays(today, -365), end: addDays(today, 730), contact_id: contact?.id, company_id: company?.id };
  const { data } = useQuery({ queryKey: ["reminders", "for", contact?.id ?? null, company?.id ?? null], queryFn: () => api.reminders(f) });
  const [touched, setTouched] = useState<Set<number>>(new Set());
  const items = (data?.items ?? []).filter((r) => !r.done || touched.has(r.id));
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-sm font-medium"><CalendarClock className="size-4 text-muted-foreground" />Rappels</h3>
        <Button size="sm" variant="outline" onClick={() => openReminder({ contact: contact ?? null, company: company ?? null })}><Plus /> Rappel</Button>
      </div>
      {items.length ? <Card className="divide-y overflow-hidden">{items.map((r) => <ReminderRow key={`${r.source}${r.id}`} r={r} onToggled={(id) => setTouched((t) => new Set(t).add(id))} />)}</Card>
        : <p className="text-xs text-muted-foreground">Aucun rappel prévu.</p>}
    </div>
  );
}

// ----------------------------------------------------------------- la page
export function AgendaPage() {
  const [params, setParams] = useSearchParams();
  const today = ymd(new Date());
  const selected = params.get("d") ?? today;
  const [month, setMonth] = useState(() => { const d = parse(selected); return new Date(d.getFullYear(), d.getMonth(), 1); });

  // grille du mois : du lundi précédant le 1er au dimanche suivant le dernier jour
  const grid = useMemo(() => {
    const first = new Date(month);
    const start = new Date(first); start.setDate(1 - ((first.getDay() + 6) % 7));
    const last = new Date(month.getFullYear(), month.getMonth() + 1, 0);
    const end = new Date(last); end.setDate(last.getDate() + (6 - ((last.getDay() + 6) % 7)));
    const days: string[] = [];
    for (const d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) days.push(ymd(d));
    return days;
  }, [month]);
  const range = { start: grid[0] < addDays(today, -60) ? grid[0] : addDays(today, -60), end: grid[grid.length - 1] > addDays(today, 60) ? grid[grid.length - 1] : addDays(today, 60) };
  const { data } = useQuery({ queryKey: ["reminders", "range", range.start, range.end], queryFn: () => api.reminders(range), placeholderData: (p) => p });
  const items = data?.items ?? [];
  const byDay = useMemo(() => {
    const m: Record<string, ReminderItem[]> = {};
    items.forEach((r) => (m[r.due_on] ??= []).push(r));
    return m;
  }, [items]);
  // Cochés pendant cette visite : ils restent visibles (barrés) là où on les a cochés.
  const [touched, setTouched] = useState<Set<number>>(new Set());
  const onToggled = (id: number) => setTouched((t) => new Set(t).add(id));
  const keep = (r: ReminderItem) => !r.done || (r.source === "reminder" && touched.has(r.id));
  const late = items.filter((r) => keep(r) && r.due_on < today);
  const upcoming = items.filter((r) => keep(r) && r.due_on > today && r.due_on <= addDays(today, 14));
  // un rappel coché reste affiché (barré) dans sa journée
  const dayItems = [...(byDay[selected] ?? [])].sort((a, b) => Number(a.done) - Number(b.done));

  useEffect(() => {
    if (params.get("new") === "1") {
      openReminder({ due_on: params.get("d") ?? undefined });
      setParams((p) => { const n = new URLSearchParams(p); n.delete("new"); return n; }, { replace: true });
    }
  }, [params, setParams]);
  const pick = (d: string) => setParams((p) => { const n = new URLSearchParams(p); n.set("d", d); n.delete("r"); return n; }, { replace: true });
  const shift = (n: number) => setMonth((m) => new Date(m.getFullYear(), m.getMonth() + n, 1));

  return (
    <>
      <PageHeader title="Agenda" description="Vos rappels : appeler, relancer un devis, un renouvellement… Ils arrivent dans les notifications le jour venu."
        actions={<Button onClick={() => openReminder({ due_on: selected >= today ? selected : undefined })}><Plus /> Ajouter un rappel</Button>} />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <Card className="overflow-hidden">
          <div className="flex items-center gap-2 border-b px-4 py-3">
            <h2 className="flex-1 text-base font-semibold first-letter:uppercase">{monthLabel(month)}</h2>
            <Button variant="outline" size="sm" onClick={() => { const d = new Date(); setMonth(new Date(d.getFullYear(), d.getMonth(), 1)); pick(today); }}>Aujourd'hui</Button>
            <Button variant="ghost" size="icon" onClick={() => shift(-1)} aria-label="Mois précédent"><ChevronLeft /></Button>
            <Button variant="ghost" size="icon" onClick={() => shift(1)} aria-label="Mois suivant"><ChevronRight /></Button>
          </div>
          <div className="grid grid-cols-7 border-b bg-muted/30 text-center text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {WEEKDAYS.map((w) => <div key={w} className="py-2">{w}</div>)}
          </div>
          <div className="grid grid-cols-7">
            {grid.map((d, i) => {
              const list = byDay[d] ?? [];
              const open = list.filter((r) => !r.done);
              const shown = [...open, ...list.filter((r) => r.done)];
              const inMonth = parse(d).getMonth() === month.getMonth();
              const weekend = i % 7 >= 5;
              return (
                <div key={d} role="button" tabIndex={0} onClick={() => pick(d)} onKeyDown={(e) => e.key === "Enter" && pick(d)}
                  className={cn("group flex min-h-20 cursor-pointer flex-col items-stretch gap-1 border-b border-r p-1.5 text-left transition-colors sm:min-h-24",
                    (i + 1) % 7 === 0 && "border-r-0", !inMonth && "bg-muted/20 text-muted-foreground/60", weekend && inMonth && "bg-muted/10",
                    d === selected ? "ring-2 ring-inset ring-primary" : "hover:bg-accent/30")}>
                  <span className="flex items-center justify-end gap-0.5">
                    {d >= today && (
                      <button onClick={(e) => { e.stopPropagation(); pick(d); openReminder({ due_on: d }); }} aria-label={`Ajouter un rappel le ${longDay(d)}`} title="Ajouter un rappel ce jour-là"
                        className="flex size-6 items-center justify-center rounded-full text-muted-foreground transition-opacity hover:bg-primary/10 hover:text-primary focus:opacity-100 sm:opacity-0 sm:group-hover:opacity-100">
                        <Plus className="size-3.5" />
                      </button>
                    )}
                    <span className={cn("flex size-6 items-center justify-center rounded-full text-xs tabular",
                      d === today && "bg-primary font-semibold text-primary-foreground")}>{parse(d).getDate()}</span>
                  </span>
                  <span className="hidden space-y-0.5 sm:block">
                    {shown.slice(0, 2).map((r) => (
                      <span key={`${r.source}${r.id}`} className={cn("block truncate rounded px-1 py-0.5 text-[11px]", KIND_TONE[r.kind],
                        r.done ? "line-through opacity-50" : d < today && "ring-1 ring-destructive/40")}>
                        {r.due_time ? `${r.due_time} ` : ""}{r.title}
                      </span>
                    ))}
                    {shown.length > 2 && <span className="block px-1 text-[11px] text-muted-foreground">+{shown.length - 2} autre(s)</span>}
                  </span>
                  {shown.length > 0 && <span className="flex gap-0.5 sm:hidden">{shown.slice(0, 3).map((r) => <span key={`${r.source}${r.id}`} className={cn("size-1.5 rounded-full", r.done ? "bg-muted-foreground/40" : "bg-primary")} />)}</span>}
                </div>
              );
            })}
          </div>
        </Card>

        <div className="space-y-6">
          <section className="space-y-2">
            <div className="flex items-center gap-2">
              <h2 className="flex-1 text-sm font-semibold first-letter:uppercase">{selected === today ? "Aujourd'hui" : longDay(selected)}</h2>
              {dayItems.some((r) => r.done) && <span className="text-xs text-muted-foreground">{dayItems.filter((r) => r.done).length} fait{dayItems.filter((r) => r.done).length > 1 ? "s" : ""}</span>}
            </div>
            {dayItems.length ? <Card className="divide-y overflow-hidden">{dayItems.map((r) => <ReminderRow key={`${r.source}${r.id}`} r={r} compact onToggled={onToggled} />)}</Card> : (
              <Card className="flex flex-col items-center gap-2 p-6 text-center text-sm text-muted-foreground">
                <CalendarDays className="size-5" />Rien ce jour-là.
                <Button size="sm" variant="outline" onClick={() => openReminder({ due_on: selected >= today ? selected : undefined })}><Plus /> Ajouter</Button>
              </Card>
            )}
          </section>
          {late.length > 0 && (
            <section className="space-y-2">
              <h2 className="text-sm font-semibold text-destructive">En retard · {late.filter((r) => !r.done).length}</h2>
              <Card className="divide-y overflow-hidden">{late.map((r) => <ReminderRow key={`${r.source}${r.id}`} r={r} onToggled={onToggled} />)}</Card>
            </section>
          )}
          <section className="space-y-2">
            <h2 className="text-sm font-semibold">Dans les 2 semaines · {upcoming.filter((r) => !r.done).length}</h2>
            {upcoming.length ? <Card className="divide-y overflow-hidden">{upcoming.map((r) => <ReminderRow key={`${r.source}${r.id}`} r={r} onToggled={onToggled} />)}</Card>
              : <p className="text-xs text-muted-foreground">Rien de prévu.</p>}
          </section>
        </div>
      </div>
    </>
  );
}
