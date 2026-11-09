import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  AlertTriangle, Archive, Ban, Building2, CalendarClock, CalendarPlus, CheckCheck, Clock, FileStack, Forward, Phone, Inbox, Loader2, Mail, Paperclip, PenSquare, RefreshCw, Reply, ReplyAll, Rocket, Search, Send, UserPlus, Users,
} from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Link, NavLink, useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { KindBadge, PageHeader, toastError } from "@/components/common";
import { Linkified } from "@/components/linkified";
import { MailAttachments, MailHtml } from "@/components/mail-body";
import { forwardSubject, openComposer, replySubject } from "@/components/composer";
import { useStatus } from "@/components/layout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, api, type AwaitingItem, type Followup, type MailItem } from "@/lib/api";
import { formatDayTime, fullName, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { openReminder } from "@/pages/agenda";
import { openNewQuote } from "@/pages/quotes";
import { openSendSequence } from "@/components/send-sequence";
import { EnrollDialog } from "@/pages/contacts";

/** Onglets communs à la boîte complète et aux réponses de campagne. */
export function MailTabs() {
  const { data: status } = useStatus();
  const { data: follow } = useQuery({ queryKey: ["followups"], queryFn: api.followups, refetchInterval: 120_000 });
  const { data: awaiting } = useQuery({ queryKey: ["awaiting"], queryFn: () => api.awaiting(), refetchInterval: 300_000, retry: false });
  const tab = ({ isActive }: { isActive: boolean }) => cn("inline-flex items-center gap-2 border-b-2 px-1 pb-2.5 text-sm transition-colors",
    isActive ? "border-primary font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground");
  return (
    <div className="mb-3 flex gap-6 border-b">
      <NavLink to="/inbox" end className={tab}><Inbox className="size-4" /><span className="sm:hidden">Réception</span><span className="hidden sm:inline">Boîte de réception</span></NavLink>
      <NavLink to="/inbox/awaiting" className={tab}>
        <Reply className="size-4" /><span className="sm:hidden">À répondre</span><span className="hidden sm:inline">À répondre</span>
        {!!awaiting?.items.length && <span className="rounded-full bg-primary/15 px-1.5 text-[11px] font-semibold text-primary tabular">{awaiting.items.length}</span>}
      </NavLink>
      <NavLink to="/inbox/followups" className={tab}>
        <Clock className="size-4" /><span className="sm:hidden">Sans réponse</span><span className="hidden sm:inline">Envoyés sans réponse</span>
        {!!follow?.length && <span className="rounded-full bg-warning/15 px-1.5 text-[11px] font-semibold text-warning tabular">{follow.length}</span>}
      </NavLink>
      <NavLink to="/replies" className={tab}>
        <Mail className="size-4" /><span className="sm:hidden">Campagnes</span><span className="hidden sm:inline">Réponses aux campagnes</span>
        {!!status?.to_classify && <span className="rounded-full bg-destructive px-1.5 text-[11px] font-semibold text-destructive-foreground tabular">{status.to_classify}</span>}
      </NavLink>
    </div>
  );
}

const CLASS_LABEL: Record<string, string> = {
  interested: "Intéressé", later: "À rappeler", not_interested: "Pas intéressé", out_of_office: "Absent",
  wrong_contact: "Mauvais interlocuteur", unsubscribe: "STOP",
};

export function InboxPage() {
  const [params, setParams] = useSearchParams();
  const folder = params.get("folder") ?? "INBOX";
  const days = Number(params.get("days") ?? 30);
  const [q, setQ] = useState("");
  // ?uid=… : arrivée depuis la fiche d'un contact (« Derniers emails ») -> cet email est ouvert
  const [selected, setSelected] = useState<number | null>(params.get("uid") ? Number(params.get("uid")) : null);
  const [refreshing, setRefreshing] = useState(false);
  // V2.11 : « Mes contacts seulement » masque newsletters, reçus et notifications (choix mémorisé)
  const [onlyContacts, setOnlyContacts] = useState(() => { try { return localStorage.getItem("oddo-inbox-only-contacts") === "1"; } catch { return false; } });
  const toggleOnly = () => setOnlyContacts((v) => { try { localStorage.setItem("oddo-inbox-only-contacts", v ? "0" : "1"); } catch { /* navigateur sans stockage */ } return !v; });
  const set = (k: string, v: string) => setParams((p) => { const n = new URLSearchParams(p); n.set(k, v); return n; }, { replace: true });

  const { data: folders } = useQuery({ queryKey: ["mail", "folders"], queryFn: api.mailFolders, staleTime: 5 * 60_000, retry: false });
  const list = useQuery({ queryKey: ["mail", "list", folder, days], queryFn: () => api.mailList(folder, days), retry: false, refetchInterval: 120_000 });
  const isSent = !!folders?.sent && folder === folders.sent;

  const [hidden, setHidden] = useState<Set<number>>(new Set());  // V2.20 : emails archivés à l'instant
  const items = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    return (list.data?.items ?? []).filter((m) => {
      if (hidden.has(m.uid)) return false;
      if (onlyContacts && !m.contact) return false;
      const hay = `${m.from_name} ${m.from_email} ${m.to.join(" ")} ${m.subject} ${m.contact?.company ?? ""}`.toLowerCase();
      return words.every((w) => hay.includes(w));
    });
  }, [list.data, q, onlyContacts, hidden]);
  useEffect(() => {
    if (items.length && !items.some((m) => m.uid === selected)) setSelected(items[0].uid);
  }, [items, selected]);
  useEffect(() => {
    const u = params.get("uid");
    if (u && items.some((m) => m.uid === Number(u))) document.getElementById(`mail-${u}`)?.scrollIntoView({ block: "center" });
  }, [items, params]);
  const refresh = async () => {
    setRefreshing(true);
    try { await api.mailList(folder, days, true); await list.refetch(); } finally { setRefreshing(false); }
  };
  const current = items.find((m) => m.uid === selected) ?? null;
  // V2.20 : après « Archiver », l'email suivant s'ouvre (comme dans Outlook)
  useEffect(() => {
    const onArchived = (e: Event) => {
      const uid = (e as CustomEvent<{ uid: number }>).detail.uid;
      const i = items.findIndex((m) => m.uid === uid);
      const next = items[i + 1] ?? items[i - 1];
      setHidden((h) => new Set(h).add(uid));
      if (next) setSelected(next.uid);
    };
    window.addEventListener("oddo-mail-archived", onArchived);
    return () => window.removeEventListener("oddo-mail-archived", onArchived);
  }, [items]);

  // V2.11 : raccourcis clavier (hors saisie) : ↑/↓ ou K/J naviguer, R répondre, S envoyer une séquence
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.ctrlKey || e.metaKey || e.altKey || t.closest("input, textarea, select, [contenteditable=true], [role=dialog]")) return;
      const i = items.findIndex((m) => m.uid === selected);
      if (e.key === "ArrowDown" || e.key === "j") { e.preventDefault(); const n = items[Math.min(items.length - 1, i + 1)]; if (n) { setSelected(n.uid); document.getElementById(`mail-${n.uid}`)?.scrollIntoView({ block: "nearest" }); } }
      else if (e.key === "ArrowUp" || e.key === "k") { e.preventDefault(); const n = items[Math.max(0, i - 1)]; if (n) { setSelected(n.uid); document.getElementById(`mail-${n.uid}`)?.scrollIntoView({ block: "nearest" }); } }
      else if (e.key === "R" && e.shiftKey) { e.preventDefault(); window.dispatchEvent(new Event("oddo-inbox-reply-all")); }
      else if (e.key === "r" || e.key === "R") { e.preventDefault(); window.dispatchEvent(new Event("oddo-inbox-reply")); }
      else if (e.key === "f" || e.key === "F") { e.preventDefault(); window.dispatchEvent(new Event("oddo-inbox-forward")); }
      else if (e.key === "e" || e.key === "E") { e.preventDefault(); window.dispatchEvent(new Event("oddo-inbox-archive")); }
      else if (e.key === "s" || e.key === "S") { e.preventDefault(); window.dispatchEvent(new Event("oddo-inbox-sequence")); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items, selected]);

  return (
    <>
      <PageHeader title="Boîte mail" className="-mt-2 mb-3 lg:-mt-4"
        actions={<Button onClick={() => openComposer()}><PenSquare /> Nouveau message</Button>} />
      <MailTabs />

      <div className="mb-3 flex flex-col gap-2 sm:flex-row">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input className="pl-9" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filtrer par expéditeur, objet, entreprise…" />
        </div>
        <NativeSelect className="sm:w-52" value={folder} onChange={(e) => { setSelected(null); set("folder", e.target.value); }}>
          {(folders?.items ?? [{ raw: "INBOX", display: "INBOX", label: "Boîte de réception", rank: 0 }]).map((f) => (
            <option key={f.raw} value={f.raw}>{f.label}</option>
          ))}
        </NativeSelect>
        <NativeSelect className="sm:w-40" value={String(days)} onChange={(e) => set("days", e.target.value)}>
          <option value="7">7 derniers jours</option><option value="30">30 derniers jours</option><option value="90">90 derniers jours</option>
        </NativeSelect>
        <Button variant={onlyContacts ? "default" : "outline"} onClick={toggleOnly} title="Masquer les newsletters, reçus et notifications : seulement les personnes de vos contacts">
          <Users /> Mes contacts
        </Button>
        <Button variant="outline" onClick={refresh} disabled={refreshing || list.isFetching}>
          <RefreshCw className={cn((refreshing || list.isFetching) && "animate-spin")} /> Actualiser
        </Button>
      </div>

      {list.error ? (
        <Card className="flex items-start gap-3 border-destructive/40 p-4 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
          <div><p className="font-medium">Boîte illisible pour l'instant</p><p className="text-muted-foreground">{(list.error as ApiError).message}</p>
            <Button size="sm" variant="outline" className="mt-3" asChild><Link to="/settings">Vérifier les réglages</Link></Button></div>
        </Card>
      ) : !list.data ? (
        <Card className="flex h-[480px] items-center justify-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" />Lecture de la boîte sur le serveur…</Card>
      ) : (
        <Card className="grid overflow-hidden lg:h-[calc(100vh-13.5rem)] lg:min-h-[480px] lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)] lg:grid-rows-[minmax(0,1fr)]">
          <div className="flex min-h-0 flex-col border-b lg:border-b-0 lg:border-r">
            <div className="max-h-96 flex-1 divide-y overflow-y-auto lg:max-h-none">
              {items.length === 0 && <p className="p-8 text-center text-sm text-muted-foreground">{onlyContacts ? "Aucun email de vos contacts sur cette période." : "Aucun email sur cette période."}</p>}
              {items.map((m) => <Row key={m.uid} m={m} active={m.uid === selected} sent={isSent} onClick={() => setSelected(m.uid)} />)}
            </div>
            <p className="border-t px-4 py-2 text-[11px] text-muted-foreground">
              {onlyContacts ? `${items.length} de vos contacts sur ${list.data.found}` : `${list.data.found} email${list.data.found > 1 ? "s" : ""}`}{list.data.truncated && ` · les ${list.data.items.length} plus récents affichés`} · lu {relativeTime(list.data.fetched_at)}
              <span className="ml-1 hidden lg:inline" title="Raccourcis clavier"> · ↑↓ naviguer · R répondre · F transférer · E archiver · S séquence</span>
            </p>
          </div>
          {current ? <Reader key={`${folder}-${current.uid}`} item={current} folder={folder} /> : <div className="hidden lg:block" />}
        </Card>
      )}
    </>
  );
}

function Row({ m, active, sent, onClick }: { m: MailItem; active: boolean; sent: boolean; onClick: () => void }) {
  const who = sent ? `À : ${m.contact ? fullName(m.contact) : m.to[0] ?? "—"}` : (m.contact ? fullName(m.contact) : m.from_name);
  return (
    <button id={`mail-${m.uid}`} onClick={onClick} className={cn("block w-full px-4 py-3 text-left transition-colors", active ? "bg-accent/70" : "hover:bg-accent/30")}>
      <div className="flex items-center gap-2">
        {!m.seen && !sent && <span className="size-2 shrink-0 rounded-full bg-primary" title="Non lu" />}
        <span className={cn("truncate text-sm", !m.seen && !sent && "font-semibold")}>{who}</span>
        <span className="ml-auto shrink-0 text-xs text-muted-foreground">{m.date ? relativeTime(m.date) : ""}</span>
      </div>
      <p className="truncate text-sm text-muted-foreground">{m.subject || "(sans objet)"}</p>
      <div className="mt-1 flex flex-wrap items-center gap-1">
        {m.contact?.company && <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground"><Building2 className="size-3" />{m.contact.company}</span>}
        {m.contact && <KindBadge kind={m.contact.kind} hideProspect />}
        {m.campaign_reply && <Badge variant="success" className="text-[10px]">Réponse campagne{m.campaign_reply.classification ? ` · ${CLASS_LABEL[m.campaign_reply.classification] ?? ""}` : ""}</Badge>}
        {m.has_attachments && <Paperclip className="size-3 text-muted-foreground" />}
      </div>
    </button>
  );
}

function Reader({ item, folder, actions }: { item: MailItem; folder: string; actions?: ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();
  const qc = useQueryClient();
  const { data: m, error } = useQuery({ queryKey: ["mail", "message", folder, item.uid], queryFn: () => api.mailMessage(folder, item.uid), retry: false });
  const [full, setFull] = useState(false);
  const [asText, setAsText] = useState(false);
  const [enrolling, setEnrolling] = useState(false);
  const person = item.contact;

  const createContact = () => {
    const [first, ...rest] = (item.from_name && item.from_name !== item.from_email ? item.from_name : "").split(" ");
    const p = new URLSearchParams({ new: "1", email: item.from_email });
    if (first) p.set("first_name", first);
    if (rest.length) p.set("last_name", rest.join(" "));
    navigate(`/contacts?${p}`);
  };
  // Expéditeur inconnu : on crée sa fiche (nom tiré de l'email) puis on choisit la séquence.
  const [quickCreating, setQuickCreating] = useState(false);
  const sendToUnknown = async () => {
    const [first, ...rest] = (item.from_name && item.from_name !== item.from_email ? item.from_name : "").split(" ");
    setQuickCreating(true);
    try {
      const r = await api.contactCreate({ email: item.from_email, first_name: first || "", last_name: rest.join(" ") });
      const c = await api.contact(r.id);
      qc.invalidateQueries({ queryKey: ["mail"] });
      toast.success(`Fiche créée pour ${fullName(c)}`);
      openSendSequence({ contacts: [c] });
    } catch (e) {
      if (e instanceof ApiError && e.existingId) { const c = await api.contact(e.existingId); openSendSequence({ contacts: [c] }); }
      else toastError(e, "Fiche non créée");
    } finally { setQuickCreating(false); }
  };
  const reply = () => m && openComposer({
    to: m.from_email, subject: replySubject(m.subject), inReplyTo: m.message_id,
    references: [...m.references.filter((r) => r !== m.message_id), ...(m.message_id ? [m.message_id] : [])],
    quote: { from: m.from_name || m.from_email, date: m.date, text: m.text },
  });
  // « Répondre à tous » : l'expéditeur en destinataire, les autres destinataires et copies en Cc
  // (sans votre propre adresse).
  const { data: status } = useQuery({ queryKey: ["status"], queryFn: api.status, staleTime: 60_000 });
  const me = (status?.mailbox.email ?? "").toLowerCase();
  const others = m ? [...new Set([...m.to, ...m.cc].map((a) => a.toLowerCase()))].filter((a) => a && a !== me && a !== m.from_email.toLowerCase()) : [];
  const replyAll = () => m && openComposer({
    to: m.from_email, cc: others.join(", "), subject: replySubject(m.subject), inReplyTo: m.message_id,
    references: [...m.references.filter((r) => r !== m.message_id), ...(m.message_id ? [m.message_id] : [])],
    quote: { from: m.from_name || m.from_email, date: m.date, text: m.text },
  });
  // V2.19 : transférer, comme dans Outlook : « TR: objet », message d'origine sous le curseur,
  // pièces jointes (et photos du corps) reprises.
  const [forwarding, setForwarding] = useState(false);
  const forward = async () => {
    if (!m || forwarding) return;
    setForwarding(true);
    try {
      const r = m.attachments.length || m.html ? await api.mailForward(folder, item.uid) : { attachments: [], skipped: [] };
      r.skipped.forEach((x) => toast.error("Pièce jointe non reprise", { description: x }));
      const head = [
        "", "", "---------- Message transféré ----------",
        `De : ${m.from_name && m.from_name !== m.from_email ? `${m.from_name} <${m.from_email}>` : m.from_email}`,
        `Date : ${m.date ? formatDayTime(m.date) : "—"}`,
        `Objet : ${m.subject || "(sans objet)"}`,
        `À : ${m.to.join(", ")}`, ...(m.cc.length ? [`Cc : ${m.cc.join(", ")}`] : []), "", "",
      ].join("\n");
      openComposer({ subject: forwardSubject(m.subject || ""), body: head + (m.full || m.text), attachments: r.attachments, forward: true });
    } catch (e) {
      toastError(e, "Transfert impossible");
    } finally { setForwarding(false); }
  };
  // V2.20 : archiver, comme dans Outlook : l'email part dans le dossier Archives du serveur (annulable)
  const [archiving, setArchiving] = useState(false);
  const archive = async () => {
    if (archiving || folder.toLowerCase().includes("archive")) return;
    setArchiving(true);
    try {
      const r = await api.mailArchive(folder, item.uid);
      window.dispatchEvent(new CustomEvent("oddo-mail-archived", { detail: { uid: item.uid } }));
      qc.invalidateQueries({ queryKey: ["mail"] });
      qc.invalidateQueries({ queryKey: ["awaiting"] });
      toast.success("Email archivé", {
        description: item.subject || undefined,
        action: r.message_id ? { label: "Annuler", onClick: () => void api.mailUnarchive(r.message_id, folder)
          .then(() => { qc.invalidateQueries({ queryKey: ["mail"] }); qc.invalidateQueries({ queryKey: ["awaiting"] }); toast.success("Email remis dans la boîte"); })
          .catch((e) => toastError(e, "Annulation impossible")) } : undefined,
      });
    } catch (e) {
      toastError(e, "Archivage impossible");
    } finally { setArchiving(false); }
  };
  // V3 : « Spam » : l'email part dans les Indésirables de la boîte (annulable), comme dans Outlook
  const [junking, setJunking] = useState(false);
  const isJunkFolder = /junk|spam|ind[ée]sirable/i.test(folder);
  const spam = async () => {
    if (junking || isJunkFolder) return;
    setJunking(true);
    try {
      const r = await api.mailSpam(folder, item.uid);
      window.dispatchEvent(new CustomEvent("oddo-mail-archived", { detail: { uid: item.uid } }));
      qc.invalidateQueries({ queryKey: ["mail"] });
      qc.invalidateQueries({ queryKey: ["awaiting"] });
      toast.success("Email mis dans les indésirables", {
        description: item.subject || undefined,
        action: r.message_id ? { label: "Annuler", onClick: () => void api.mailUnarchive(r.message_id, folder, "junk")
          .then(() => { qc.invalidateQueries({ queryKey: ["mail"] }); qc.invalidateQueries({ queryKey: ["awaiting"] }); toast.success("Email remis dans la boîte"); })
          .catch((e) => toastError(e, "Annulation impossible")) } : undefined,
      });
    } catch (e) {
      toastError(e, "Impossible de le mettre en spam");
    } finally { setJunking(false); }
  };
  // raccourcis R et S envoyés par la liste (V2.11)
  useEffect(() => {
    const onArchive = () => void archive();
    window.addEventListener("oddo-inbox-archive", onArchive);
    const onReply = () => reply();
    const onReplyAll = () => (others.length ? replyAll() : reply());
    window.addEventListener("oddo-inbox-reply-all", onReplyAll);
    const onSeq = () => { if (person) openSendSequence({ contacts: [person] }); else void sendToUnknown(); };
    const onForward = () => void forward();
    window.addEventListener("oddo-inbox-forward", onForward);
    window.addEventListener("oddo-inbox-reply", onReply);
    window.addEventListener("oddo-inbox-sequence", onSeq);
    return () => { window.removeEventListener("oddo-inbox-reply-all", onReplyAll); window.removeEventListener("oddo-inbox-reply", onReply); window.removeEventListener("oddo-inbox-sequence", onSeq); window.removeEventListener("oddo-inbox-forward", onForward); window.removeEventListener("oddo-inbox-archive", onArchive); };
  });

  return (
    <div className="flex min-h-0 flex-col">
      <div className="flex flex-wrap items-start gap-3 border-b p-4">
        <div className="min-w-0 flex-1">
          <p className="font-medium">{item.subject || "(sans objet)"}</p>
          <p className="truncate text-sm text-muted-foreground">De {item.from_name} &lt;{item.from_email}&gt;</p>
          <p className="text-xs text-muted-foreground">{item.date && formatDayTime(item.date)}{m && m.to.length > 0 && <> · à {m.to.join(", ")}</>}{m && m.cc.length > 0 && <> · cc {m.cc.join(", ")}</>}</p>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-2">
          {actions}
          {item.contact?.kind !== "insurer" && (
            <Button variant="outline" title="Créer un dossier de cotation pour cet expéditeur"
              onClick={() => openNewQuote(item.contact
                ? { contact: { id: item.contact.id, name: fullName(item.contact) }, company: item.contact.company_ref }
                : { client_name: item.from_name || item.from_email })}>
              <FileStack /> Dossier
            </Button>
          )}
          {!folder.toLowerCase().includes("archive") && (
            <Button variant="outline" onClick={() => void archive()} disabled={archiving} title="Ranger dans le dossier Archives (touche E)">
              {archiving ? <Loader2 className="animate-spin" /> : <Archive />} Archiver
            </Button>
          )}
          {!isJunkFolder && (
            <Button variant="outline" onClick={() => void spam()} disabled={junking} title="Mettre dans le dossier Indésirables (annulable)">
              {junking ? <Loader2 className="animate-spin" /> : <Ban />} Spam
            </Button>
          )}
          <Button variant="outline" onClick={() => void forward()} disabled={!m || forwarding} title="Transférer à quelqu'un, avec les pièces jointes (touche F)">
            {forwarding ? <Loader2 className="animate-spin" /> : <Forward />} Transférer
          </Button>
          {others.length > 0 && (
            <Button variant="outline" onClick={replyAll} title={`Répondre aussi à : ${others.join(", ")} (Maj + R)`}><ReplyAll /> Répondre à tous</Button>
          )}
          <Button onClick={reply} disabled={!m} title="Répondre à l'expéditeur (touche R)"><Reply /> Répondre</Button>
        </div>
      </div>

      {/* Bandeau « qui est-ce » : relie l'email au CRM */}
      <div className="flex flex-wrap items-center gap-2 border-b bg-muted/30 px-5 py-2.5 text-sm">
        {person ? <>
          <Link to={`/contacts?open=${person.id}`} state={{ back: location.pathname + location.search }} className="font-medium hover:text-primary">{fullName(person)}</Link>
          {person.company_ref && <Link to={`/companies/${person.company_ref.id}`} className="inline-flex items-center gap-1 text-muted-foreground hover:text-primary"><Building2 className="size-3.5" />{person.company_ref.name}</Link>}
          <KindBadge kind={person.kind} />
          <span className="flex-1" />
          <Button size="sm" className="h-7" onClick={() => openSendSequence({ contacts: [person] })}><Send /> Envoyer une séquence</Button>
          <Button size="sm" variant="outline" className="h-7" onClick={() => openReminder({ contact: person })}><CalendarPlus /> Rappel</Button>
          {person.status === "active" && <Button size="sm" variant="ghost" className="h-7" onClick={() => setEnrolling(true)} title="Ajouter à une campagne déjà lancée"><Rocket /> Campagne</Button>}
          <EnrollDialog open={enrolling} onOpenChange={setEnrolling} contactId={person.id} name={fullName(person)} kind={person.kind} />
        </> : <>
          <span className="text-muted-foreground">Expéditeur inconnu de vos contacts.</span>
          <span className="flex-1" />
          <Button size="sm" variant="outline" className="h-7" onClick={createContact}><UserPlus /> Créer le contact</Button>
          <Button size="sm" className="h-7" disabled={quickCreating} onClick={() => void sendToUnknown()}><Send /> Envoyer une séquence</Button>
        </>}
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        {error ? <p className="text-sm text-destructive">{(error as ApiError).message}</p> : !m ? <Skeleton className="h-40" /> : <>
          {m.kind !== "reply" && <Badge variant="secondary">{{ auto_reply: "Message automatique", bounce_hard: "Rebond", bounce_soft: "Rebond temporaire", unsubscribe: "Demande STOP" }[m.kind] ?? m.kind}</Badge>}
          {m.html && !asText ? <>
            <MailHtml key={`${folder}-${item.uid}`} html={m.html} remoteImages={m.remote_images} />
            <button className="text-xs text-muted-foreground hover:text-primary hover:underline" onClick={() => setAsText(true)}>Afficher en texte seul</button>
          </> : <>
            <div className="whitespace-pre-wrap break-words text-sm leading-relaxed"><Linkified text={full ? m.full : m.text || m.full} /></div>
            {m.full && m.full !== m.text && <button className="text-xs text-primary hover:underline" onClick={() => setFull(!full)}>{full ? "Masquer l'historique" : "Afficher l'historique de la conversation"}</button>}
            {m.html && <button className="ml-3 text-xs text-muted-foreground hover:text-primary hover:underline" onClick={() => setAsText(false)}>Afficher la mise en forme</button>}
          </>}
          <MailAttachments items={m.attachments} />
        </>}
      </div>
    </div>
  );
}

/* =============================================================== envoyés sans réponse */

/** Emails partis il y a au moins N jours ouvrés (Réglages), sans réponse : relancer depuis ici. */
/** V2.12 : emails reçus auxquels je n'ai pas répondu depuis N jours ouvrés (le pendant de
 *  « Envoyés sans réponse »). Clic : l'email s'ouvre à droite, avec Répondre / Séquence / Rappel. */
export function AwaitingPage() {
  const { data, isLoading, error, refetch, isFetching } = useQuery({ queryKey: ["awaiting"], queryFn: () => api.awaiting(), retry: false });
  const [params] = useSearchParams();
  const [selected, setSelected] = useState<number | null>(params.get("uid") ? Number(params.get("uid")) : null);
  const items = data?.items ?? [];
  const current = items.find((m) => m.uid === selected) ?? items[0] ?? null;
  const days = data?.days ?? 3;
  // V2.13 : « Marquer comme répondu » (un, plusieurs ou tous) pour vider la liste, avec Annuler
  const qc = useQueryClient();
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const allChecked = items.length > 0 && items.every((m) => checked.has(m.uid));
  const dismiss = async (list: AwaitingItem[]) => {
    if (!list.length) return;
    try {
      await api.awaitingDismiss(list.map((m) => ({ from_email: m.from_email, date: m.date })));
      setChecked(new Set());
      qc.invalidateQueries({ queryKey: ["awaiting"] });
      toast.success(list.length > 1 ? `${list.length} emails marqués comme répondus` : "Marqué comme répondu", {
        description: "Ils reviendront si la personne vous écrit de nouveau.",
        action: { label: "Annuler", onClick: () => void api.awaitingRestore(list.map((m) => m.from_email)).then(() => qc.invalidateQueries({ queryKey: ["awaiting"] })) },
      });
    } catch (e) { toastError(e, "Impossible de ranger ces emails"); }
  };
  return (
    <>
      <PageHeader title="Boîte mail" className="-mt-2 mb-3 lg:-mt-4"
        description={<>Emails reçus restés <b>sans réponse de votre part</b> depuis au moins {days} jours ouvrés (newsletters et envois automatiques exclus). <Link to="/settings?s=sending" className="text-primary hover:underline">Changer le délai</Link></>}
        actions={<>
          <Button variant="outline" onClick={() => void api.awaiting(true).then(() => refetch())} disabled={isFetching}><RefreshCw className={cn(isFetching && "animate-spin")} /> Actualiser</Button>
          <Button onClick={() => openComposer()}><PenSquare /> Nouveau message</Button>
        </>} />
      <MailTabs />
      {isLoading ? <Skeleton className="h-[480px] rounded-xl" /> : error ? (
        <Card className="p-8 text-center text-sm text-muted-foreground">{error instanceof Error ? error.message : "Boîte mail injoignable."}</Card>
      ) : items.length === 0 ? (
        <Card className="flex flex-col items-center gap-2 p-12 text-center">
          <Reply className="size-8 text-muted-foreground" />
          <p className="font-medium">Rien en attente</p>
          <p className="max-w-md text-sm text-muted-foreground">Vous avez répondu à tous les emails de plus de {days} jours ouvrés (sur les {data?.window_days ?? 30} derniers jours).</p>
        </Card>
      ) : (
        <Card className="grid overflow-hidden lg:h-[calc(100vh-15.5rem)] lg:min-h-[480px] lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)] lg:grid-rows-[minmax(0,1fr)]">
          <div className="flex max-h-96 min-h-0 flex-col border-b lg:max-h-none lg:border-b-0 lg:border-r">
            <div className="flex items-center gap-2 border-b bg-muted/30 px-4 py-2 text-xs">
              <input type="checkbox" className="accent-[hsl(var(--primary))]" checked={allChecked} aria-label="Tout sélectionner"
                onChange={() => setChecked(allChecked ? new Set() : new Set(items.map((m) => m.uid)))} />
              <span className="text-muted-foreground">{checked.size ? `${checked.size} sélectionné${checked.size > 1 ? "s" : ""}` : "Tout sélectionner"}</span>
              <span className="flex-1" />
              {checked.size > 0 && (
                <Button size="sm" variant="outline" className="h-7" onClick={() => void dismiss(items.filter((m) => checked.has(m.uid)))}>
                  <CheckCheck /> Marquer comme répondu{checked.size > 1 ? ` (${checked.size})` : ""}
                </Button>
              )}
            </div>
            <div className="min-h-0 flex-1 divide-y overflow-y-auto">
            {items.map((m) => (
              <div key={m.uid} className={cn("flex items-start gap-3 px-4 py-3 transition-colors", current?.uid === m.uid ? "bg-accent/70" : "hover:bg-accent/30")}>
                <input type="checkbox" className="mt-1 accent-[hsl(var(--primary))]" checked={checked.has(m.uid)} aria-label="Sélectionner"
                  onChange={() => setChecked((s) => { const n = new Set(s); if (n.has(m.uid)) n.delete(m.uid); else n.add(m.uid); return n; })} />
              <button onClick={() => setSelected(m.uid)} className="min-w-0 flex-1 text-left">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium">{m.contact ? fullName(m.contact) : m.from_name || m.from_email}</span>
                  <span className={cn("ml-auto shrink-0 rounded-full px-2 text-[11px] font-medium tabular", m.business_days >= days * 2 ? "bg-destructive/10 text-destructive" : "bg-primary/10 text-primary")}>
                    {m.business_days} j
                  </span>
                </div>
                <p className="truncate text-sm text-muted-foreground">{m.subject || "(sans objet)"}</p>
                <p className="mt-1 truncate text-[11px] text-muted-foreground">
                  {m.contact?.company ? <><Building2 className="mr-1 inline size-3" />{m.contact.company}</> : m.from_email}
                  {m.date && ` · reçu ${formatDayTime(m.date)}`}
                </p>
              </button>
              </div>
            ))}
            </div>
          </div>
          {current && <Reader key={current.uid} item={current} folder="INBOX"
            actions={<Button variant="outline" onClick={() => void dismiss([current])} title="Retirer de « À répondre » : déjà traité, ou pas de réponse à faire"><CheckCheck /> Marquer comme répondu</Button>} />}
        </Card>
      )}
    </>
  );
}

export function FollowupsPage() {
  const { data, isLoading } = useQuery({ queryKey: ["followups"], queryFn: api.followups, refetchInterval: 120_000 });
  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: api.settings, staleTime: 60_000 });
  // ?contact=ID : arrivée depuis une notification ou le tableau de bord, la personne est ouverte
  const [params] = useSearchParams();
  const wanted = params.get("contact");
  const [selected, setSelected] = useState<number | null>(wanted ? Number(wanted) : null);
  useEffect(() => { if (wanted) setSelected(Number(wanted)); }, [wanted]);
  useEffect(() => {
    if (wanted) document.getElementById(`fu-${wanted}`)?.scrollIntoView({ block: "nearest" });
  }, [wanted, data]);
  const items = data ?? [];
  const current = items.find((r) => r.contact.id === selected) ?? items[0] ?? null;
  const days = settings?.sending.followup_days ?? items[0]?.days ?? 3;

  return (
    <>
      <PageHeader title="Boîte mail" className="-mt-2 mb-3 lg:-mt-4" description={<>Emails envoyés sans réponse depuis au moins <b>{days} jours ouvrés</b>, du plus ancien au plus récent. <Link to="/settings?s=sending" className="text-primary hover:underline">Changer le délai</Link></>}
        actions={<Button onClick={() => openComposer()}><PenSquare /> Nouveau message</Button>} />
      <MailTabs />
      {isLoading ? <Skeleton className="h-[480px] rounded-xl" /> : items.length === 0 ? (
        <Card className="flex flex-col items-center gap-2 p-12 text-center">
          <Clock className="size-8 text-muted-foreground" />
          <p className="font-medium">Personne à relancer</p>
          <p className="max-w-md text-sm text-muted-foreground">Tous vos emails de plus de {days} jours ouvrés ont reçu une réponse, ou vos contacts sont encore dans le délai.</p>
        </Card>
      ) : (
        <Card className="grid overflow-hidden lg:h-[calc(100vh-15.5rem)] lg:min-h-[480px] lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)] lg:grid-rows-[minmax(0,1fr)]">
          <div className="max-h-96 divide-y overflow-y-auto border-b lg:max-h-none lg:border-b-0 lg:border-r">
            {items.map((r) => (
              <button key={r.contact.id} id={`fu-${r.contact.id}`} onClick={() => setSelected(r.contact.id)}
                className={cn("block w-full px-4 py-3 text-left transition-colors", current?.contact.id === r.contact.id ? "bg-accent/70" : "hover:bg-accent/30")}>
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium">{fullName(r.contact)}</span>
                  <span className={cn("ml-auto shrink-0 rounded-full px-2 text-[11px] font-medium tabular", r.business_days >= days * 2 ? "bg-destructive/10 text-destructive" : "bg-warning/15 text-warning")}>
                    {r.business_days} j
                  </span>
                </div>
                <p className="truncate text-sm text-muted-foreground">{r.subject || "(sans objet)"}</p>
                <p className="mt-1 truncate text-[11px] text-muted-foreground">
                  {r.contact.company && <><Building2 className="mr-1 inline size-3" />{r.contact.company} · </>}
                  {r.campaign ? r.campaign.name : "Email écrit à la main"}
                </p>
                {r.next_due_at && (
                  <p className="mt-1.5 inline-flex max-w-full items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                    <CalendarClock className="size-3 shrink-0" />
                    <span className="truncate">{nextLabel(r.next_step)} prévue {formatDayTime(r.next_due_at)}</span>
                  </p>
                )}
              </button>
            ))}
          </div>
          {current && <FollowupReader key={current.contact.id} r={current} />}
        </Card>
      )}
    </>
  );
}

function FollowupReader({ r }: { r: Followup }) {
  const me = useStatus().data?.mailbox.display_name ?? "";
  const relaunch = () => openComposer({
    to: r.contact.email, subject: replySubject(r.subject),
    inReplyTo: r.message?.message_id ?? null,
    references: [...(r.message?.references ?? []), ...(r.message?.message_id ? [r.message.message_id] : [])],
    quote: r.message?.body ? { from: me || "moi", date: r.last_sent, text: r.message.body } : undefined,
  });
  return (
    <div className="flex min-h-0 flex-col">
      <div className="flex flex-wrap items-start gap-3 border-b p-4">
        <div className="min-w-0 flex-1">
          <p className="font-medium">{r.subject || "(sans objet)"}</p>
          <p className="truncate text-sm text-muted-foreground">À {fullName(r.contact)} &lt;{r.contact.email}&gt;</p>
          <p className="text-xs text-muted-foreground">Envoyé {formatDayTime(r.last_sent)} · il y a {r.business_days} jours ouvrés{r.step ? ` · email n°${r.step}` : ""}</p>
        </div>
        <div className="flex gap-2">
          {r.contact.phone && <Button variant="outline" asChild><a href={`tel:${r.contact.phone}`}><Phone /> Appeler</a></Button>}
          <Button variant="outline" onClick={() => openReminder({ contact: r.contact, kind: "call" })} title="Ajouter un rappel à l'agenda"><CalendarPlus /> Rappel</Button>
          <Button onClick={relaunch}><Reply /> Relancer</Button>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 border-b bg-muted/30 px-5 py-2.5 text-sm">
        <Link to={`/contacts?open=${r.contact.id}`} className="font-medium hover:text-primary">{fullName(r.contact)}</Link>
        {r.contact.job_title && <span className="text-muted-foreground">{r.contact.job_title}</span>}
        {r.contact.company && <span className="inline-flex items-center gap-1 text-muted-foreground"><Building2 className="size-3.5" />{r.contact.company}</span>}
        <span className="flex-1" />
        {r.campaign && <Link to={`/campaigns/${r.campaign.id}`} className="text-xs text-muted-foreground hover:text-primary">{r.campaign.name}</Link>}
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        {r.next_due_at ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-primary/20 bg-primary/5 p-3 text-sm">
            <CalendarClock className="size-5 shrink-0 text-primary" />
            <div className="min-w-0 flex-1">
              <p className="font-medium">{nextLabel(r.next_step)} prévue {formatDayTime(r.next_due_at)}</p>
              <p className="text-xs text-muted-foreground">
                Elle partira toute seule si {r.contact.first_name || "la personne"} ne répond pas{r.next_campaign ? <> ({r.next_campaign.name})</> : null}. Vous pouvez aussi appeler ou relancer vous-même avant.
              </p>
            </div>
            {r.next_campaign && <Link to={`/campaigns/${r.next_campaign.id}`} className="shrink-0 text-xs font-medium text-primary hover:underline">Voir le suivi</Link>}
          </div>
        ) : (
          <p className="flex items-center gap-2 rounded-lg bg-warning/10 p-3 text-sm">
            <CalendarClock className="size-4 shrink-0" />
            Plus de relance automatique prévue : un appel ou un email personnel est le bon moment.
          </p>
        )}
        <div className="whitespace-pre-wrap break-words text-sm leading-relaxed text-muted-foreground"><Linkified text={r.message?.body ?? ""} /></div>
      </div>
    </div>
  );
}

/** V2.25.1 : « Relance 1 » / « 1er email » pour le prochain email automatique prévu. */
function nextLabel(step?: number | null): string {
  return !step || step <= 1 ? "1er email" : `Relance ${step - 1}`;
}
