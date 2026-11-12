import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Check, CheckCheck, Inbox, Keyboard, Link2, Mail, MailOpen, Phone, RefreshCw, UserSearch, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { openComposer, replySubject } from "@/components/composer";
import { EmptyState, PageHeader, toastError, useDebounced, useUrlState } from "@/components/common";
import { Linkified } from "@/components/linkified";
import { useSyncNow } from "@/components/layout";
import { MailTabs } from "@/pages/inbox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { api, type ContactRef, type Replies, type Reply } from "@/lib/api";
import { formatDayTime, fullName, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

// Couleur de chaque classement : même code partout (liste, boutons, badges).
const TONE: Record<string, string> = {
  interested: "bg-success/10 text-success border-success/30",
  later: "bg-primary/10 text-primary border-primary/30",
  not_interested: "bg-muted text-muted-foreground border-border",
  out_of_office: "bg-warning/10 text-warning border-warning/30",
  wrong_contact: "bg-muted text-muted-foreground border-border",
  unsubscribe: "bg-destructive/10 text-destructive border-destructive/30",
};
const KIND_LABEL: Record<string, string> = { reply: "Réponse", unsubscribe: "Demande STOP", auto_reply: "Réponse automatique" };

function inDays(n: number) {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

export function RepliesPage() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const filter = params.get("f") ?? "unclassified";
  const { data } = useQuery({ queryKey: ["replies", filter], queryFn: () => api.replies(filter), placeholderData: (p) => p });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [laterFor, setLaterFor] = useState<Reply | null>(null);
  const sync = useSyncNow();

  const items = data?.items ?? [];
  const selected = items.find((r) => r.id === selectedId) ?? items[0] ?? null;
  useEffect(() => {
    if (selected && selected.id !== selectedId) setSelectedId(selected.id);
  }, [selected, selectedId]);

  const classify = useMutation({
    mutationFn: ({ r, cls, callback }: { r: Reply; cls: string; callback?: string }) => api.classify(r.id, cls, callback),
    onSuccess: (_, { r, cls }) => {
      const label = data?.classes.find((c) => c.key === cls)?.label ?? cls;
      toast.success(`${fullName(r.contact)} : ${label}`);
      // En vue « Non classées », la réponse disparaît : on passe à la suivante.
      if (filter === "unclassified") {
        const idx = items.findIndex((x) => x.id === r.id);
        setSelectedId(items[idx + 1]?.id ?? items[idx - 1]?.id ?? null);
      }
      qc.invalidateQueries({ queryKey: ["replies"] });
      qc.invalidateQueries({ queryKey: ["status"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e) => toastError(e),
  });
  // « Marquer comme lu » : la réponse quitte « Non classées » et la notification, sans être classée.
  const seen = useMutation({
    mutationFn: ({ ids, value }: { ids: number[] | null; value: boolean }) => api.repliesSeen(ids, value),
    onSuccess: (res, { ids, value }) => {
      if (ids === null) toast.success(res.count ? `${res.count} réponse(s) marquée(s) comme lue(s)` : "Rien à marquer");
      else toast.success(value ? "Marquée comme lue : retrouvez-la dans « Lues, non classées »" : "Remise dans « Non classées »");
      if (ids && ids.length === 1 && (filter === "unclassified" || filter === "seen")) {
        const idx = items.findIndex((x) => x.id === ids[0]);
        setSelectedId(items[idx + 1]?.id ?? items[idx - 1]?.id ?? null);
      }
      qc.invalidateQueries({ queryKey: ["replies"] });
      qc.invalidateQueries({ queryKey: ["status"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
    onError: (e) => toastError(e),
  });
  const toggleSeen = useCallback((r: Reply) => {
    if (!r.classification) seen.mutate({ ids: [r.id], value: !r.seen });
  }, [seen]);

  const doClassify = useCallback((r: Reply, cls: string) => {
    if (cls === "later") setLaterFor(r);
    else classify.mutate({ r, cls });
  }, [classify]);

  // Raccourcis clavier façon boîte mail : J/K pour naviguer, 1 à 6 pour classer.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("input, textarea, select, [contenteditable]") || e.ctrlKey || e.metaKey || e.altKey || laterFor) return;
      const idx = items.findIndex((x) => x.id === selected?.id);
      if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); setSelectedId(items[Math.min(idx + 1, items.length - 1)]?.id ?? null); }
      if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); setSelectedId(items[Math.max(idx - 1, 0)]?.id ?? null); }
      if (selected && (e.key === "l" || e.key === "L")) { e.preventDefault(); toggleSeen(selected); }
      const n = Number(e.key);
      if (selected && n >= 1 && n <= (data?.classes.length ?? 0)) doClassify(selected, data!.classes[n - 1].key);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items, selected, data, doClassify, laterFor, toggleSeen]);

  return (
    <>
      <PageHeader title="Boîte mail" className="-mt-2 mb-3 lg:-mt-4" description="Réponses à vos campagnes : classez-les, la séquence du contact s'est déjà arrêtée."
        actions={<Button variant="outline" onClick={() => sync.mutate()} disabled={sync.isPending}><RefreshCw className={cn(sync.isPending && "animate-spin")} /> Lire la boîte</Button>} />
      <MailTabs />

      {data && data.unmatched.length > 0 && <Unmatched items={data.unmatched} />}

      <div className="mb-4 flex items-center gap-1.5 overflow-x-auto pb-1 sm:flex-wrap sm:overflow-visible">
        {data?.filters.map((f) => (
          <button key={f.key} onClick={() => setParams(f.key === "unclassified" ? {} : { f: f.key })}
            className={cn("inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1 text-sm transition-colors",
              filter === f.key ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent")}>
            {f.label}
            <span className={cn("rounded-full px-1.5 text-xs tabular", filter === f.key ? "bg-primary-foreground/20" : "bg-muted text-muted-foreground")}>{f.count}</span>
          </button>
        ))}
        {filter === "unclassified" && items.some((r) => !r.classification && !r.seen) && (
          <Button variant="ghost" size="sm" className="ml-auto shrink-0" disabled={seen.isPending}
            onClick={() => seen.mutate({ ids: null, value: true })}><CheckCheck /> Tout marquer comme lu</Button>
        )}
      </div>

      {!data ? <Skeleton className="h-[480px] rounded-xl" /> : items.length === 0 ? (
        <EmptyState icon={Inbox} title={filter === "unclassified" ? "Tout est classé" : "Aucune réponse ici"}
          text={filter === "unclassified" ? "Les nouvelles réponses apparaîtront ici après la prochaine lecture de la boîte." : undefined} />
      ) : (
        <Card className="grid overflow-hidden lg:h-[calc(100vh-15rem)] lg:min-h-[480px] lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] lg:grid-rows-[minmax(0,1fr)]">
          <div className="max-h-80 divide-y overflow-y-auto border-b lg:max-h-none lg:border-b-0 lg:border-r">
            {items.map((r) => {
              const cls = data.classes.find((c) => c.key === r.classification);
              return (
                <button key={r.id} onClick={() => setSelectedId(r.id)}
                  className={cn("block w-full px-4 py-3 text-left transition-colors", selected?.id === r.id ? "bg-accent/70" : "hover:bg-accent/30")}>
                  <div className="flex items-center gap-2">
                    {!r.classification && !r.seen && <span className="size-2 shrink-0 rounded-full bg-primary" />}
                    <span className={cn("truncate text-sm", !r.classification && !r.seen && "font-semibold")}>{fullName(r.contact)}</span>
                    <span className="ml-auto shrink-0 text-xs text-muted-foreground">{relativeTime(r.received_at)}</span>
                  </div>
                  <p className="truncate text-xs text-muted-foreground">{r.contact.company}</p>
                  <p className="mt-1 line-clamp-2 text-xs text-muted-foreground/90">{r.text}</p>
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {r.kind !== "reply" && <Badge variant="outline" className="text-[10px]">{KIND_LABEL[r.kind]}</Badge>}
                    {cls && <span className={cn("rounded-full border px-2 text-[10px] font-medium", TONE[cls.key])}>{cls.label}</span>}
                    {r.test_mode && <Badge variant="warning" className="text-[10px]">Test</Badge>}
                  </div>
                </button>
              );
            })}
          </div>
          {selected && <Reader key={selected.id} r={selected} classes={data.classes} onClassify={doClassify} pending={classify.isPending}
            onToggleSeen={toggleSeen} seenPending={seen.isPending} />}
        </Card>
      )}

      <p className="mt-3 hidden items-center gap-2 text-xs text-muted-foreground lg:flex">
        <Keyboard className="size-3.5" /> <kbd className="rounded border px-1">J</kbd>/<kbd className="rounded border px-1">K</kbd> réponse suivante / précédente ·
        <kbd className="rounded border px-1">1</kbd>–<kbd className="rounded border px-1">6</kbd> classer ·
        <kbd className="rounded border px-1">L</kbd> marquer comme lu
      </p>

      <LaterDialog reply={laterFor} onClose={() => setLaterFor(null)}
        onConfirm={(date) => { classify.mutate({ r: laterFor!, cls: "later", callback: date }); setLaterFor(null); }} />
    </>
  );
}

function Reader({ r, classes, onClassify, pending, onToggleSeen, seenPending }: {
  r: Reply; classes: Replies["classes"]; onClassify: (r: Reply, c: string) => void; pending: boolean;
  onToggleSeen: (r: Reply) => void; seenPending: boolean;
}) {
  const [note, setNote] = useState(r.note ?? "");
  const [full, setFull] = useState(false);
  const save = useMutation({ mutationFn: (n: string) => api.replyNote(r.id, n), onError: (e) => toastError(e) });
  const debounced = useDebounced((n: string) => save.mutate(n), 700);

  return (
    <div className="flex min-h-0 flex-col">
      <div className="flex flex-wrap items-start gap-3 border-b p-4">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-accent text-sm font-semibold text-accent-foreground">
          {(r.contact.first_name?.[0] ?? r.contact.email[0]).toUpperCase()}{r.contact.last_name?.[0]?.toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <Link to={`/contacts?open=${r.contact.id}`} className="font-medium hover:text-primary">{fullName(r.contact)}</Link>
          <p className="truncate text-sm text-muted-foreground">{r.contact.company} · {r.contact.email}</p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {!r.classification && (
            <Button variant="outline" size="sm" disabled={seenPending} onClick={() => onToggleSeen(r)}
              title={r.seen ? "La remettre dans « Non classées »" : "Enlever la notification sans classer la réponse"}>
              {r.seen ? <><Mail /> Marquer non lu</> : <><MailOpen /> Marquer comme lu</>}
            </Button>
          )}
          {r.contact.phone && <Button variant="outline" size="sm" asChild><a href={`tel:${r.contact.phone}`}><Phone /> Appeler</a></Button>}
          <Button variant="outline" size="sm" onClick={() => openComposer({
            to: r.contact.email, subject: replySubject(r.subject), inReplyTo: r.message_id,
            references: [...r.references.filter((x) => x !== r.message_id), ...(r.message_id ? [r.message_id] : [])],
            quote: { from: fullName(r.contact), date: r.received_at, text: r.text },
          })}><Mail /> Répondre</Button>
        </div>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        <div>
          <p className="font-medium">{r.subject || "(sans objet)"}</p>
          <p className="text-xs text-muted-foreground">{KIND_LABEL[r.kind]} · reçue le {formatDayTime(r.received_at)}
            {r.return_date && <> · de retour le {new Date(r.return_date).toLocaleDateString("fr-FR")}</>}</p>
        </div>
        <div className="whitespace-pre-wrap break-words rounded-xl bg-muted/40 p-4 text-sm leading-relaxed"><Linkified text={full && r.full ? r.full : r.text} /></div>
        {r.full && r.full !== r.text && (
          <button className="text-xs text-primary hover:underline" onClick={() => setFull(!full)}>{full ? "Masquer l'historique" : "Afficher le message complet (avec l'historique)"}</button>
        )}
        {r.callback_on && <p className="flex items-center gap-2 text-sm text-primary"><CalendarClock className="size-4" />Rappel prévu le {new Date(r.callback_on).toLocaleDateString("fr-FR")}</p>}
        <label className="block space-y-1.5">
          <span className="text-xs font-medium text-muted-foreground">Note privée {save.isPending && "· enregistrement…"}</span>
          <Textarea rows={2} value={note} placeholder="ex. Rappeler après le renouvellement de mars…" onChange={(e) => { setNote(e.target.value); debounced(e.target.value); }} />
        </label>
      </div>
      <div className="border-t p-4">
        <p className="mb-2 text-xs font-medium text-muted-foreground">Classer cette réponse{!r.classification && r.seen && " (lue, pas encore classée)"}</p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {classes.map((c, i) => (
            <button key={c.key} disabled={pending} onClick={() => onClassify(r, c.key)}
              className={cn("flex items-center gap-2 rounded-lg border px-3 py-2 text-left text-sm transition-all hover:shadow-sm disabled:opacity-50",
                r.classification === c.key ? TONE[c.key] + " font-medium" : "hover:bg-accent")}>
              <kbd className="hidden rounded border bg-background px-1.5 text-[10px] text-muted-foreground lg:inline">{i + 1}</kbd>
              <span className="truncate">{c.label}</span>
              {r.classification === c.key && <Check className="ml-auto size-3.5 shrink-0" />}
            </button>
          ))}
        </div>
        {r.test_mode && <p className="mt-2 text-xs text-muted-foreground">Réponse reçue en mode test : la classer ne bloque pas le vrai contact.</p>}
      </div>
    </div>
  );
}

function LaterDialog({ reply, onClose, onConfirm }: { reply: Reply | null; onClose: () => void; onConfirm: (d: string) => void }) {
  const [date, setDate] = useState(inDays(14));
  useEffect(() => setDate(inDays(14)), [reply]);
  const presets = useMemo(() => [["Dans 1 semaine", 7], ["Dans 2 semaines", 14], ["Dans 1 mois", 30], ["Dans 3 mois", 91]] as const, []);
  return (
    <Dialog open={!!reply} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>Rappeler {reply && fullName(reply.contact)} quand ?</DialogTitle></DialogHeader>
        <div className="flex flex-wrap gap-2">
          {presets.map(([label, n]) => (
            <Button key={n} size="sm" variant={date === inDays(n) ? "default" : "outline"} onClick={() => setDate(inDays(n))}>{label}</Button>
          ))}
        </div>
        <Input type="date" value={date} min={inDays(0)} onChange={(e) => setDate(e.target.value)} />
        <p className="text-xs text-muted-foreground">Le rappel apparaîtra sur le tableau de bord et dans le résumé du matin ce jour-là.</p>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Annuler</Button>
          <Button disabled={!date} onClick={() => onConfirm(date)}><CalendarClock /> Programmer le rappel</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Emails reçus d'expéditeurs inconnus : on peut les rattacher à un contact ou les ignorer. */
function Unmatched({ items }: { items: Replies["unmatched"] }) {
  const qc = useQueryClient();
  const [picking, setPicking] = useState<number | null>(null);
  const done = () => { qc.invalidateQueries({ queryKey: ["replies"] }); qc.invalidateQueries({ queryKey: ["dashboard"] }); };
  const attach = useMutation({
    mutationFn: ({ id, cid }: { id: number; cid: number }) => api.attach(id, cid),
    onSuccess: () => { toast.success("Email rattaché : la séquence du contact est arrêtée"); setPicking(null); done(); },
    onError: (e) => toastError(e),
  });
  const dismiss = useMutation({ mutationFn: api.dismiss, onSuccess: () => { toast.success("Email ignoré"); done(); }, onError: (e) => toastError(e) });

  return (
    <Card className="mb-5 border-warning/40">
      <div className="flex items-center gap-2 border-b px-4 py-3 text-sm">
        <UserSearch className="size-4 text-warning" />
        <span className="font-medium">{items.length} email{items.length > 1 ? "s" : ""} d'un expéditeur inconnu</span>
        <span className="text-muted-foreground">: une réponse venue d'une autre adresse ?</span>
      </div>
      <div className="divide-y">
        {items.map((m) => (
          <div key={m.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium">{m.subject || "(sans objet)"}</p>
              <p className="line-clamp-1 text-xs text-muted-foreground">{formatDayTime(m.received_at)} · {m.text}</p>
            </div>
            {m.suggestion && (
              <Button size="sm" variant="outline" onClick={() => attach.mutate({ id: m.id, cid: m.suggestion!.id })}>
                <Link2 /> {fullName(m.suggestion)} ?
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={() => setPicking(m.id)}>Autre contact…</Button>
            <Button size="icon" variant="ghost" className="size-8" aria-label="Ignorer" onClick={() => dismiss.mutate(m.id)}><X /></Button>
          </div>
        ))}
      </div>
      <ContactPicker open={picking !== null} onClose={() => setPicking(null)} onPick={(c) => attach.mutate({ id: picking!, cid: c.id })} />
    </Card>
  );
}

export function ContactPicker({ open, onClose, onPick }: { open: boolean; onClose: () => void; onPick: (c: ContactRef) => void }) {
  const [q, setQ] = useUrlState<string>("q", "");
  const { data } = useQuery({ queryKey: ["picker", q], queryFn: () => api.picker(q), enabled: open, placeholderData: (p) => p });
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader><DialogTitle>Choisir le contact</DialogTitle></DialogHeader>
        <Input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Nom, entreprise ou email…" />
        <div className="max-h-72 divide-y overflow-y-auto rounded-lg border">
          {data?.map((c) => (
            <button key={c.id} onClick={() => onPick(c)} className="block w-full px-3 py-2 text-left text-sm hover:bg-accent">
              <span className="font-medium">{fullName(c)}</span> <span className="text-muted-foreground">· {c.company} · {c.email}</span>
            </button>
          ))}
          {data?.length === 0 && <p className="p-4 text-center text-sm text-muted-foreground">Aucun contact trouvé.</p>}
        </div>
      </DialogContent>
    </Dialog>
  );
}
