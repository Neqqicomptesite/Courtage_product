// « Envoyer une séquence » (V2.9) : depuis la boîte mail, une fiche contact ou la page Séquences.
// 1. quelle séquence (si elle n'est pas déjà choisie) ; 2. à qui (si personne n'est déjà choisi) ;
// 3. pour une seule personne : tel quel, ou personnaliser d'abord ses emails ; 4. envoi.
// Les personnes entrent dans la campagne « à l'unité » de la séquence (mêmes contrôles qu'une campagne).
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, ArrowLeft, ArrowRight, CalendarClock, CheckCircle2, Eye, FlaskConical, Mail, Loader2, Paperclip, PenLine, Rocket, RotateCcw, Search, Send, Users, X, XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { toastError } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { api, type Attachment, type ContactRef, type ReviewEmail, type SendPayload, type Kind, type SendResult, type SequenceCategory } from "@/lib/api";
import { AttachmentChips, uploadFiles } from "@/components/composer";
import { formatDayTime, fullName } from "@/lib/format";
import { cn } from "@/lib/utils";

type Person = ContactRef & { kind?: Kind };
export type SendRequest = { contacts?: Person[]; sequenceId?: number };
type Step = "sequence" | "people" | "common" | "mode" | "personalize" | "review" | "result";
type Edit = Record<string, { subject?: string; body?: string; attachments?: Attachment[] }>;
const HOLE_RE = /\[([^[\]\n]{2,60})\]/g;  // V2.14 : « [N° de police] » à compléter avant l'envoi
const holes = (t: string) => [...new Set([...t.matchAll(HOLE_RE)].map((m) => m[1].trim()))];

const CATS: { value: SequenceCategory; label: string }[] = [
  { value: "prospection", label: "Prospection" }, { value: "gestion", label: "Gestion" }, { value: "souscription", label: "Souscription" },
];

export function openSendSequence(req: SendRequest = {}) {
  window.dispatchEvent(new CustomEvent<SendRequest>("oddo-send-sequence", { detail: req }));
}

export function SendSequenceDialog() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<Step>("sequence");
  const [people, setPeople] = useState<Person[]>([]);
  const [fixedPeople, setFixedPeople] = useState(false);
  const [seqId, setSeqId] = useState<number | null>(null);
  const [cat, setCat] = useState<SequenceCategory>("prospection");
  const [edits, setEdits] = useState<Edit>({});
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<SendResult | null>(null);
  // V2.23 : plusieurs personnes (3 compagnies pour une cotation) : les [champs] remplis une fois pour toutes
  const [fills, setFills] = useState<Record<string, string>>({});
  const [sharedAtts, setSharedAtts] = useState<Attachment[]>([]);
  // V2.24 : n'envoyer que les N premiers emails (null = toute la séquence)
  const [upTo, setUpTo] = useState<number | null>(null);
  // V2.25 : tout envoi passe par « Vérifier avant d'envoyer » (les emails exacts) ; on revient d'où on venait
  const [reviewFrom, setReviewFrom] = useState<Step>("mode");
  // V3.5 : combien recevront vraiment la séquence, d'après la vérification (null = pas encore calculé)
  const [reviewOk, setReviewOk] = useState<number | null>(null);
  const review = (from: Step) => { setReviewFrom(from); setReviewOk(null); setStep("review"); };
  const { data: holesData } = useQuery({ queryKey: ["holes", seqId, upTo], queryFn: () => api.sequenceHoles(seqId!, upTo), enabled: open && !!seqId });
  const seqHoles = holesData?.holes ?? [];

  const { data: seqs } = useQuery({ queryKey: ["sequences"], queryFn: api.sequences, enabled: open });
  const seq = seqs?.items.find((q) => q.id === seqId);
  const nonProspect = people.some((p) => p.kind && p.kind !== "prospect");

  useEffect(() => {
    const on = (e: Event) => {
      const r = (e as CustomEvent<SendRequest>).detail ?? {};
      const ps = r.contacts ?? [];
      setPeople(ps);
      setFixedPeople(ps.length > 0);
      setSeqId(r.sequenceId ?? null);
      setCat(ps.some((p) => p.kind && p.kind !== "prospect") ? "gestion" : "prospection");
      setEdits({});
      setFills({}); setSharedAtts([]); setUpTo(null);
      setResult(null);
      setStep(r.sequenceId ? (ps.length ? (ps.length === 1 ? "mode" : "common") : "people") : "sequence");
      setOpen(true);
    };
    window.addEventListener("oddo-send-sequence", on);
    return () => window.removeEventListener("oddo-send-sequence", on);
  }, []);

  const next = () => setStep(people.length === 1 ? "mode" : fixedPeople && people.length > 1 ? "common" : "people");
  const payload = (ids: number[]) => {
    const overrides = ids.length === 1 && Object.keys(edits).length
      ? Object.fromEntries(Object.entries(edits).map(([k, v]) => [k, { subject: v.subject, body: v.body, attachment_ids: v.attachments?.map((a) => a.id) }]))
      : undefined;
    const sh = ids.length > 1 || !overrides
      ? { fills: Object.fromEntries(Object.entries(fills).filter(([, v]) => v.trim())), attachment_ids: sharedAtts.map((a) => a.id) }
      : undefined;
    return { overrides, shared: sh && (Object.keys(sh.fills).length || sh.attachment_ids.length) ? sh : undefined };
  };
  const send = async (overlap = false, ids = people.map((p) => p.id)) => {
    if (!seqId || !ids.length) return;
    setSending(true);
    try {
      const { overrides, shared } = payload(ids);
      const r = await api.sequenceSend(seqId, ids, overlap, overrides, shared, upTo);
      ["contact", "contacts", "campaigns", "campaign", "dashboard", "notifications", "company"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      if (!r.refused.length) {
        setOpen(false);
        const first = r.sent[0]?.next_due_at;
        toast.success(r.sent.length === 1 ? `Séquence envoyée à ${fullName(r.sent[0].contact)}` : `Séquence envoyée à ${r.sent.length} personnes`, {
          description: `${seq?.name ?? ""}${upTo ? ` (${partLabel(upTo).toLowerCase()})` : ""}${first ? ` · 1er email ${formatDayTime(first)} au plus tôt` : " · 1er email à la prochaine plage d'envoi"}`,
          action: { label: "Voir", onClick: () => navigate(`/campaigns/${r.campaign.id}`) },
        });
      } else {
        setResult(r);
        setStep("result");
      }
    } catch (e) {
      toastError(e, "Envoi impossible");
    } finally {
      setSending(false);
    }
  };

  const back: Step | null = step === "review" ? reviewFrom : step === "personalize" ? "mode" : step === "mode" ? (fixedPeople ? "sequence" : "people")
    : step === "common" ? (fixedPeople ? "sequence" : "people") : step === "people" ? "sequence" : null;
  const fillsMissing = seqHoles.filter((h) => !(fills[h] ?? "").trim());
  const title = step === "sequence" ? "Quelle séquence envoyer ?" : step === "people" ? `Envoyer « ${seq?.name ?? ""} »`
    : step === "mode" || step === "personalize" ? `${seq?.name ?? "Séquence"} → ${people[0] ? fullName(people[0]) : ""}`
    : step === "common" ? `${seq?.name ?? "Séquence"} → ${people.length} personnes`
    : step === "review" ? "Vérifier avant d'envoyer" : "Résultat de l'envoi";

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className={cn("max-w-xl", step === "personalize" && "max-w-3xl", step === "review" && "max-h-[calc(100vh-2rem)] max-w-5xl overflow-y-auto")}>
        <DialogHeader>
          <DialogTitle className="pr-6">{title}</DialogTitle>
          {step === "sequence" && people.length > 0 && (
            <DialogDescription>Pour {people.length === 1 ? fullName(people[0]) : `${people.length} personnes`}{people[0]?.company ? ` · ${people[0].company}` : ""}</DialogDescription>
          )}
        </DialogHeader>

        {/* ---------------------------------------------------- 1. la séquence */}
        {step === "sequence" && (
          <div className="space-y-3">
            <div className="inline-flex w-full rounded-lg border bg-card p-0.5">
              {CATS.map((c) => (
                <button key={c.value} onClick={() => setCat(c.value)}
                  className={cn("flex-1 rounded-md px-3 py-1.5 text-sm", cat === c.value ? "bg-primary font-medium text-primary-foreground" : "text-muted-foreground hover:bg-accent")}>
                  {c.label} <span className="text-xs opacity-75">{seqs?.items.filter((q) => (q.category ?? "prospection") === c.value).length ?? ""}</span>
                </button>
              ))}
            </div>
            {cat === "prospection" && nonProspect && (
              <p className="rounded-lg bg-warning/10 px-3 py-2 text-xs text-warning">Client, assureur ou partenaire : jamais de prospection. Choisissez une séquence de gestion ou de souscription.</p>
            )}
            <div className="max-h-80 space-y-2 overflow-y-auto">
              {!seqs ? <Skeleton className="h-24" /> : seqs.items.filter((q) => (q.category ?? "prospection") === cat).map((q) => (
                <button key={q.id} disabled={cat === "prospection" && nonProspect}
                  onClick={() => { setSeqId(q.id); setEdits({}); setUpTo(null); next(); }}
                  className="flex w-full items-center gap-3 rounded-xl border p-3 text-left transition-colors hover:border-primary/50 hover:bg-accent/30 disabled:cursor-not-allowed disabled:opacity-50">
                  <Send className="size-4 shrink-0 text-primary" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{q.name}</span>
                    <span className="text-xs text-muted-foreground">{q.steps} email{q.steps > 1 ? "s" : ""} sur {q.total_days} jours</span>
                  </span>
                  <ArrowRight className="size-4 text-muted-foreground" />
                </button>
              ))}
              {seqs && !seqs.items.some((q) => (q.category ?? "prospection") === cat) && (
                <p className="py-6 text-center text-sm text-muted-foreground">Aucune séquence de ce type pour l'instant.</p>
              )}
            </div>
          </div>
        )}

        {/* ---------------------------------------------------- 2. à qui */}
        {step === "people" && seqId && (
          <>
            <PeoplePicker people={people} setPeople={setPeople} locked={fixedPeople}
              onGroup={() => { setOpen(false); navigate(`/campaigns/new?sequence=${seqId}`); }} />
            <StepsChoice seqId={seqId} total={seq?.steps ?? 0} upTo={upTo} setUpTo={setUpTo} />
          </>
        )}

        {/* ---------------------------------------------------- 2 bis. plusieurs personnes : les [champs] une fois */}
        {step === "common" && seqId && <StepsChoice seqId={seqId} total={seq?.steps ?? 0} upTo={upTo} setUpTo={setUpTo} />}
        {step === "common" && seqId && (
          <CommonFields holes={seqHoles} fills={fills} setFills={setFills} atts={sharedAtts} setAtts={setSharedAtts} people={people} />
        )}

        {/* ---------------------------------------------------- 3. tel quel ou personnalisé */}
        {step === "mode" && seqId && people[0] && <StepsChoice seqId={seqId} total={seq?.steps ?? 0} upTo={upTo} setUpTo={setUpTo} />}
        {step === "mode" && seqId && people[0] && (
          <div className="grid gap-3 sm:grid-cols-2">
            <button onClick={() => setStep("personalize")}
              className="flex flex-col items-start gap-2 rounded-xl border-2 border-primary/30 bg-primary/5 p-4 text-left transition-colors hover:border-primary">
              <PenLine className="size-5 text-primary" />
              <span className="font-medium">Personnaliser d'abord</span>
              <span className="text-xs text-muted-foreground">Relire et retoucher les emails écrits pour {people[0].first_name || fullName(people[0])}, pour lui seul. La séquence elle-même ne change pas.</span>
            </button>
            <button onClick={() => review("mode")} disabled={sending}
              className="flex flex-col items-start gap-2 rounded-xl border p-4 text-left transition-colors hover:border-primary/50 hover:bg-accent/30">
              <Rocket className="size-5 text-muted-foreground" />
              <span className="font-medium">Envoyer tel quel</span>
              <span className="text-xs text-muted-foreground">{upTo === 1 ? "Le 1er email" : "Les emails choisis"} de la séquence, avec son nom et son entreprise.</span>
            </button>
          </div>
        )}

        {step === "personalize" && seqId && people[0] && (
          <Personalize seqId={seqId} contact={people[0]} edits={edits} setEdits={setEdits} upTo={upTo} />
        )}

        {/* ---------------------------------------------------- V2.25 : vérifier les emails exacts */}
        {step === "review" && seqId && (
          <ReviewView seqId={seqId} onReady={setReviewOk}
            onRemove={people.length > 1 ? (ids) => { setReviewOk(null); setPeople(people.filter((p) => !ids.includes(p.id))); } : undefined} body={{ contact_ids: people.map((p) => p.id), ...(() => { const pl = payload(people.map((p) => p.id)); return { overrides: pl.overrides, ...(pl.shared ?? {}) }; })(), max_steps: upTo }} />
        )}

        {/* ---------------------------------------------------- résultat partiel */}
        {step === "result" && result && <ResultView result={result} />}

        <DialogFooter className="items-center gap-2 sm:justify-between">
          <div>
            {back && <Button variant="ghost" onClick={() => setStep(back)}><ArrowLeft /> {back === "sequence" ? "Autre séquence" : "Retour"}</Button>}
          </div>
          <div className="flex gap-2">
            {step === "people" && (
              <Button disabled={!people.length || sending} onClick={() => (people.length === 1 ? setStep("mode") : setStep("common"))}>
                <ArrowRight /> Continuer
              </Button>
            )}
            {step === "common" && (
              <Button disabled={sending || fillsMissing.length > 0} title={fillsMissing.length ? `À compléter : ${fillsMissing.map((h) => `[${h}]`).join(", ")}` : undefined}
                onClick={() => review("common")}>
                <Eye /> Vérifier les emails
              </Button>
            )}
            {step === "personalize" && (
              <Button onClick={() => review("personalize")}><Eye /> Vérifier avant d'envoyer</Button>
            )}
            {step === "review" && (
              <>
                {reviewOk === 0 && seqId && (
                  <Button variant="outline" asChild><Link to={`/sequences/${seqId}`} onClick={() => setOpen(false)}>Compléter la séquence</Link></Button>
                )}
                {/* V3.5 : le bouton annonçait « Envoyer à 36 personnes » alors qu'aucune ne recevrait rien */}
                <Button disabled={sending || reviewOk === null || reviewOk === 0} onClick={() => void send()}
                  title={reviewOk === 0 ? "Aucun email ne peut partir : corrigez d'abord ce qui est signalé en rouge" : undefined}>
                  {sending ? <Loader2 className="animate-spin" /> : <Send />}
                  {reviewOk === 0 ? "Rien à envoyer" : people.length > 1 ? `Envoyer à ${reviewOk ?? people.length} personne${(reviewOk ?? people.length) > 1 ? "s" : ""}` : "Confirmer l'envoi"}
                </Button>
              </>
            )}
            {step === "result" && result && (
              <>
                {result.refused.some((r) => r.overlap.length) && (
                  <Button variant="outline" disabled={sending} onClick={() => void send(true, result.refused.filter((r) => r.overlap.length).map((r) => r.contact.id))}>
                    Envoyer quand même aux personnes déjà en campagne
                  </Button>
                )}
                {result.refused.length === 1 && result.refused[0].problems.length > 0 && people.length === 1 && (
                  <Button variant="outline" onClick={() => setStep("personalize")}><PenLine /> Personnaliser pour corriger</Button>
                )}
                <Button onClick={() => setOpen(false)}>Fermer</Button>
              </>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PeoplePicker({ people, setPeople, locked, onGroup }: { people: Person[]; setPeople: (p: Person[]) => void; locked: boolean; onGroup: () => void }) {
  const [q, setQ] = useState("");
  const { data } = useQuery({ queryKey: ["picker", q], queryFn: () => api.picker(q), enabled: !locked });
  const chosen = new Set(people.map((p) => p.id));
  return (
    <div className="space-y-3">
      {!locked && (
        <button onClick={onGroup} className="flex w-full items-center gap-3 rounded-xl border border-dashed p-3 text-left text-sm transition-colors hover:border-primary/50 hover:bg-accent/30">
          <Users className="size-4 text-primary" />
          <span className="flex-1"><span className="font-medium">Un groupe entier</span><span className="block text-xs text-muted-foreground">Par fonction, secteur, lot… avec la vérification complète d'une campagne</span></span>
          <ArrowRight className="size-4 text-muted-foreground" />
        </button>
      )}
      {people.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {people.map((p) => (
            <span key={p.id} className="inline-flex items-center gap-1 rounded-full border bg-accent/40 py-0.5 pl-2.5 pr-1 text-xs">
              {fullName(p)}{p.company && <span className="text-muted-foreground"> · {p.company}</span>}
              {!locked && <button className="rounded-full p-0.5 hover:bg-accent" aria-label={`Retirer ${fullName(p)}`} onClick={() => setPeople(people.filter((x) => x.id !== p.id))}><X className="size-3" /></button>}
            </span>
          ))}
        </div>
      )}
      {!locked && (
        <>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input autoFocus className="pl-9" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ou des personnes précises : nom, email, entreprise…" />
          </div>
          <div className="max-h-64 divide-y overflow-y-auto rounded-lg border">
            {(data ?? []).slice(0, 30).map((c) => (
              <label key={c.id} className="flex cursor-pointer items-center gap-3 px-3 py-2 text-sm hover:bg-accent/30">
                <input type="checkbox" className="accent-[hsl(var(--primary))]" checked={chosen.has(c.id)}
                  onChange={(e) => setPeople(e.target.checked ? [...people, c] : people.filter((x) => x.id !== c.id))} />
                <span className="min-w-0 flex-1 truncate">{fullName(c)} <span className="text-muted-foreground">{c.company ? `· ${c.company}` : c.email}</span></span>
              </label>
            ))}
            {data && data.length === 0 && <p className="px-3 py-4 text-center text-sm text-muted-foreground">Personne ne correspond.</p>}
          </div>
        </>
      )}
    </div>
  );
}

function Personalize({ seqId, contact, edits, setEdits, upTo }: { seqId: number; contact: Person; edits: Edit; setEdits: (e: Edit) => void; upTo: number | null }) {
  const { data } = useQuery({ queryKey: ["draft", seqId, contact.id], queryFn: () => api.sequenceDraft(seqId, contact.id) });
  const [pos, setPos] = useState(1);
  const total = data?.steps.length ?? 0;
  const st = data?.steps.find((s) => s.position === pos);
  const key = String(pos);
  const value = useMemo(() => ({ subject: edits[key]?.subject ?? st?.subject ?? "", body: edits[key]?.body ?? st?.body ?? "" }), [edits, key, st]);
  if (!data) return <Skeleton className="h-80" />;
  const set = (patch: { subject?: string; body?: string; attachments?: Attachment[] }) => {
    const v = { ...value, attachments: edits[key]?.attachments, ...patch };
    const changed: Edit[string] = {};
    if (st?.own_subject && v.subject !== st.subject) changed.subject = v.subject;
    if (v.body !== st?.body) changed.body = v.body;
    if (v.attachments?.length) changed.attachments = v.attachments;
    const n = { ...edits };
    if (Object.keys(changed).length) n[key] = changed; else delete n[key];
    setEdits(n);
  };
  const missing = holes(`${st?.own_subject ? value.subject : ""}\n${value.body}`);
  const mine = edits[key]?.attachments ?? [];
  let day = 0;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1">
        {data.steps.filter((s) => !upTo || s.position <= upTo).map((s) => {
          day += s.position === 1 ? 0 : s.delay_days;
          return (
            <button key={s.position} onClick={() => setPos(s.position)}
              className={cn("shrink-0 rounded-full border px-3 py-1 text-xs transition-colors", pos === s.position ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent")}>
              {s.position === 1 ? "1er email" : `Relance ${s.position - 1} · J+${day}`}{edits[String(s.position)] && " ✎"}
              {s.problems.length > 0 && !edits[String(s.position)] && <span className="ml-1 inline-block size-1.5 rounded-full bg-warning" />}
            </button>
          );
        })}
        {upTo && upTo < total && (
          <span className="ml-1 text-xs text-muted-foreground">
            {upTo === 1 ? "Pas de relance automatique" : `Les ${total - upTo} dernière${total - upTo > 1 ? "s" : ""} relance${total - upTo > 1 ? "s" : ""} ne partiront pas`}
          </span>
        )}
      </div>
      {st && (
        <div className="space-y-2">
          {st.own_subject ? (
            <Input value={value.subject} onChange={(e) => set({ subject: e.target.value })} placeholder="Objet" aria-label="Objet" />
          ) : <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">Objet « Re: … » : la relance arrive dans la même conversation.</p>}
          <Textarea value={value.body} onChange={(e) => set({ body: e.target.value })} className="min-h-[260px] text-sm leading-relaxed" aria-label="Message" />
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>Signature ajoutée à l'envoi.</span>
            {pos === 1 && data.attachments.length > 0 && <span className="inline-flex items-center gap-1"><Paperclip className="size-3" />{data.attachments.map((a) => a.name).join(", ")}</span>}
            <label className="inline-flex cursor-pointer items-center gap-1 text-primary hover:underline">
              <Paperclip className="size-3" /> Joindre un fichier pour cette personne
              <input type="file" multiple className="hidden" onChange={async (e) => {
                // V2.23 : copier la liste AVANT de vider le champ (sinon elle est vidée aussi : rien n'était joint)
                const files = Array.from(e.target.files ?? []); e.target.value = "";
                if (files.length) { const done = await uploadFiles(files); if (done.length) set({ attachments: [...mine, ...done] }); }
              }} />
            </label>
            {edits[key] && <button className="ml-auto inline-flex items-center gap-1 text-primary hover:underline" onClick={() => { const n = { ...edits }; delete n[key]; setEdits(n); }}><RotateCcw className="size-3" /> Revenir au texte de la séquence</button>}
          </div>
          {mine.length > 0 && <AttachmentChips items={mine} onRemove={(id) => set({ attachments: mine.filter((a) => a.id !== id) })} />}
          {missing.length > 0 && (
            <p className="rounded-md bg-warning/10 px-3 py-2 text-xs text-warning">
              À compléter avant l'envoi : {missing.map((h) => <b key={h} className="mr-1">[{h}]</b>)} remplacez chaque crochet par l'information (n° de police, banque…).
            </p>
          )}
          {st.problems.length > 0 && !edits[key] && !missing.length && (
            <p className="rounded-md bg-warning/10 px-3 py-2 text-xs text-warning">À compléter : {st.problems.join(" · ")}. Corrigez le texte ci-dessus pour cette personne.</p>
          )}
        </div>
      )}
    </div>
  );
}

/** V2.23 : la même demande à plusieurs personnes : chaque [champ] rempli une seule fois, le
 *  reste (prénom, entreprise) reste propre à chacun. Les relances reprennent ces valeurs. */
function CommonFields({ holes: hs, fills, setFills, atts, setAtts, people }: {
  holes: string[]; fills: Record<string, string>; setFills: (f: Record<string, string>) => void;
  atts: Attachment[]; setAtts: (a: Attachment[]) => void; people: Person[];
}) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1.5">
        {people.map((p) => (
          <span key={p.id} className="inline-flex items-center rounded-full border bg-accent/40 px-2.5 py-0.5 text-xs">
            {fullName(p)}{p.company && <span className="text-muted-foreground">&nbsp;· {p.company}</span>}
          </span>
        ))}
      </div>
      {hs.length > 0 ? (
        <div className="space-y-2.5">
          <p className="text-sm text-muted-foreground">Remplissez une fois : chaque personne reçoit son propre email, à son nom, avec ces informations.</p>
          {hs.map((h) => (
            <label key={h} className="grid gap-1 sm:grid-cols-[11rem_1fr] sm:items-center sm:gap-3">
              <span className="text-sm font-medium">[{h}]</span>
              <Input value={fills[h] ?? ""} onChange={(e) => setFills({ ...fills, [h]: e.target.value })} aria-label={h} />
            </label>
          ))}
        </div>
      ) : <p className="text-sm text-muted-foreground">Rien à compléter : les emails partent tels quels, chacun à son nom.</p>}
      <div className="space-y-2">
        <label className="inline-flex cursor-pointer items-center gap-1 text-xs text-primary hover:underline">
          <Paperclip className="size-3" /> Joindre un fichier pour ces {people.length} personnes
          <input type="file" multiple className="hidden" onChange={async (e) => {
            const files = Array.from(e.target.files ?? []); e.target.value = "";
            if (files.length) { const done = await uploadFiles(files); if (done.length) setAtts([...atts, ...done]); }
          }} />
        </label>
        {atts.length > 0 && <AttachmentChips items={atts} onRemove={(id) => setAtts(atts.filter((a) => a.id !== id))} />}
      </div>
    </div>
  );
}

function ResultView({ result }: { result: SendResult }) {
  return (
    <div className="space-y-3 text-sm">
      {result.sent.length > 0 && (
        <p className="flex items-center gap-2 text-success"><CheckCircle2 className="size-4" />Envoyée à {result.sent.length} personne{result.sent.length > 1 ? "s" : ""}.</p>
      )}
      <div className="max-h-72 space-y-2 overflow-y-auto">
        {result.refused.map((r) => (
          <div key={r.contact.id} className="rounded-lg border p-3">
            <p className="flex items-center gap-2 font-medium"><XCircle className="size-4 text-destructive" />{fullName(r.contact)}</p>
            <p className="text-xs text-muted-foreground">{r.reason}</p>
            {r.overlap.length > 0 && <div className="mt-1 flex flex-wrap gap-1">{r.overlap.map((o) => <Badge key={o} variant="secondary">{o}</Badge>)}</div>}
            {r.problems.length > 0 && <ul className="mt-1 text-xs text-muted-foreground">{r.problems.slice(0, 4).map((p) => <li key={p}>• {p}</li>)}</ul>}
          </div>
        ))}
      </div>
    </div>
  );
}

export function partLabel(k: number, total = 0): string {
  if (total && k >= total) return `Toute la séquence (${total} emails)`;
  return k === 1 ? "1er email seulement" : `1er email + ${k - 1} relance${k > 2 ? "s" : ""}`;
}

/** V2.24 : envoyer toute la séquence, ou seulement les premiers emails (ex. G1 : la demande
 *  d'avenant sans relance automatique). Puis les dates indicatives des emails qui partiront. */
function StepsChoice({ seqId, total, upTo, setUpTo }: { seqId: number; total: number; upTo: number | null; setUpTo: (n: number | null) => void }) {
  return (
    <div className="space-y-2">
      {total > 1 && (
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-muted-foreground">Que faut-il envoyer ?</p>
          <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Emails à envoyer">
            {Array.from({ length: total }, (_, i) => total - i).map((k) => {
              const on = (upTo ?? total) === k;
              return (
                <button key={k} role="radio" aria-checked={on} onClick={() => setUpTo(k >= total ? null : k)}
                  className={cn("rounded-full border px-3 py-1 text-xs transition-colors", on ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent")}>
                  {partLabel(k, total)}
                </button>
              );
            })}
          </div>
          {upTo === 1 && <p className="text-xs text-muted-foreground">Un seul email, sans relance automatique : à vous de relancer si besoin.</p>}
        </div>
      )}
      <Schedule seqId={seqId} upTo={upTo} />
    </div>
  );
}

/** V2.11 : quand partira chaque email si on envoie maintenant (indicatif). */
function Schedule({ seqId, upTo = null }: { seqId: number; upTo?: number | null }) {
  const { data: all } = useQuery({ queryKey: ["schedule", seqId], queryFn: () => api.sequenceSchedule(seqId) });
  const data = all?.filter((x) => !upTo || x.position <= upTo);
  if (!data?.length) return null;
  return (
    <div className="rounded-lg bg-muted/40 px-3 py-2 text-xs">
      <p className="mb-1 font-medium text-muted-foreground">Si vous envoyez maintenant (dates indicatives, sans réponse entre-temps) :</p>
      <ol className="flex flex-wrap gap-x-4 gap-y-1">
        {data.map((x) => (
          <li key={x.position} className="inline-flex items-center gap-1.5">
            <span className="flex size-4 items-center justify-center rounded-full bg-primary/15 text-[10px] font-semibold text-primary">{x.position}</span>
            {x.position === 1 ? "1er email" : `Relance ${x.position - 1}`} : <span className="font-medium">{x.planned_at ? formatDayTime(x.planned_at) : "—"}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}


/** V2.25 : « Vérifier avant d'envoyer » : les emails EXACTS qui partiront, personne par personne
 *  (objet, texte avec signature, pièces jointes, date prévue), calculés par le serveur comme à l'envoi. */
function ReviewView({ seqId, body, onReady, onRemove }: { seqId: number; body: SendPayload; onReady?: (ok: number) => void; onRemove?: (ids: number[]) => void }) {
  const key = JSON.stringify(body);
  const { data, isLoading, error } = useQuery({ queryKey: ["review", seqId, key], queryFn: () => api.sequenceReview(seqId, body), staleTime: 0 });
  useEffect(() => { if (data) onReady?.(data.people.filter((p) => !p.refused).length); }, [data, onReady]);
  const [sel, setSel] = useState(0);
  const [pos, setPos] = useState(1);
  if (isLoading) return <div className="grid gap-3 md:grid-cols-[14rem_1fr]"><Skeleton className="h-64" /><Skeleton className="h-96" /></div>;
  if (error || !data) return <p className="rounded-lg bg-destructive/10 px-3 py-2 text-sm text-destructive">Aperçu impossible : {(error as Error)?.message ?? "erreur"}</p>;
  const ok = data.people.filter((p) => !p.refused);
  const nEmails = ok.reduce((n, p) => n + p.emails.length, 0);
  const dates = ok.flatMap((p) => p.emails.map((e) => e.planned_at)).filter(Boolean).sort() as string[];
  const person = data.people[Math.min(sel, data.people.length - 1)];
  const email = person?.emails.find((e) => e.position === pos) ?? person?.emails[0];
  const many = data.people.length > 1;
  const refused = data.people.filter((p) => p.refused);
  // V3.5 : tout le monde bloqué pour les mêmes raisons = la séquence elle-même est incomplète
  const sameForAll = refused.length === data.people.length && refused.length > 1
    && refused.every((p) => p.problems.join("|") === refused[0].problems.join("|")) && refused[0].problems.length > 0;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <span className="inline-flex items-center gap-1.5 font-medium"><Mail className="size-4 text-primary" />
          {nEmails} email{nEmails > 1 ? "s" : ""} · {ok.length} personne{ok.length > 1 ? "s" : ""}</span>
        {dates.length > 0 && <span className="inline-flex items-center gap-1.5 text-muted-foreground"><CalendarClock className="size-4" />
          {dates.length > 1 ? <>du {formatDayTime(dates[0])} au {formatDayTime(dates[dates.length - 1])}</> : formatDayTime(dates[0])}</span>}
        {data.steps < data.total_steps && <Badge variant="secondary">{partLabel(data.steps, data.total_steps)}</Badge>}
      </div>
      {data.test_mode && (
        <p className="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning">
          <FlaskConical className="mt-0.5 size-4 shrink-0" />
          <span><b>Mode test</b> : rien ne part chez les destinataires. Chaque email arrive dans votre boîte{data.from ? ` (${data.from.email})` : ""}, avec le vrai destinataire dans l'objet.</span>
        </p>
      )}
      {sameForAll && (
        <p className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span><b>Le problème vient de la séquence, pas des contacts</b> : ses emails sont incomplets ({refused[0].problems.join(" · ")}). Complétez la séquence, puis revenez ici.</span>
        </p>
      )}
      {onRemove && refused.length > 0 && refused.length < data.people.length && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-sm">
          <span>{refused.length} personne{refused.length > 1 ? "s" : ""} ne recevr{refused.length > 1 ? "ont" : "a"} rien. Retirez-l{refused.length > 1 ? "es" : "a"} pour envoyer aux autres.</span>
          <Button size="sm" variant="outline" onClick={() => { setSel(0); onRemove(refused.map((p) => p.contact.id)); }}><X /> Retirer de l'envoi</Button>
        </div>
      )}
      <div className={cn("grid gap-3", many && "md:grid-cols-[15rem_1fr]")}>
        {many && (
          <ul className="max-h-[60vh] space-y-1 overflow-y-auto" aria-label="Destinataires">
            {data.people.map((p, i) => (
              <li key={p.contact.id} className="group relative">
                {onRemove && (
                  <button type="button" aria-label={`Retirer ${fullName(p.contact)} de l'envoi`} title="Retirer de cet envoi"
                    onClick={() => { setSel(0); onRemove([p.contact.id]); }}
                    className="absolute right-1.5 top-1.5 z-10 rounded-md p-1 text-muted-foreground opacity-60 transition hover:bg-destructive/10 hover:text-destructive hover:opacity-100 group-hover:opacity-100">
                    <X className="size-3.5" />
                  </button>
                )}
                <button onClick={() => { setSel(i); setPos(1); }}
                  className={cn("w-full rounded-lg border px-3 py-2 pr-8 text-left text-sm transition-colors", i === sel ? "border-primary bg-primary/5" : "hover:bg-accent/40")}>
                  <span className="flex items-center gap-1.5 font-medium">
                    {p.refused ? <XCircle className="size-3.5 shrink-0 text-destructive" /> : <CheckCircle2 className="size-3.5 shrink-0 text-success" />}
                    <span className="truncate">{fullName(p.contact)}</span>
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">{p.contact.company || p.to}</span>
                  {p.contact.company && <span className="block truncate text-xs text-muted-foreground">{p.to}</span>}
                  <span className={cn("block text-xs", p.refused ? "text-destructive" : "text-muted-foreground")}>
                    {p.refused ? "Ne partira pas" : `${p.emails.length} email${p.emails.length > 1 ? "s" : ""}`}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {person && (
          <div className="min-w-0 space-y-3">
            {person.refused && (
              <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
                <p className="flex items-center gap-1.5 font-medium"><AlertTriangle className="size-4" /> {person.refused}</p>
                {person.problems.length > 0 && <ul className="mt-1 list-disc pl-5 text-xs">{person.problems.map((x) => <li key={x}>{x}</li>)}</ul>}
              </div>
            )}
            {person.emails.length > 1 && (
              <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Emails de la séquence">
                {person.emails.map((e) => (
                  <button key={e.position} role="tab" aria-selected={e.position === email?.position} onClick={() => setPos(e.position)}
                    className={cn("rounded-lg border px-3 py-1.5 text-left text-xs transition-colors", e.position === email?.position ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent")}>
                    <span className="block font-medium">{e.position === 1 ? "1er email" : `Relance ${e.position - 1}`}{e.problems.length ? " ⚠" : ""}</span>
                    {e.planned_at && <span className="block opacity-80">{formatDayTime(e.planned_at)}</span>}
                  </button>
                ))}
              </div>
            )}
            {email && <EmailCard email={email} to={person.to} name={fullName(person.contact)} from={data.from} ab={data.ab_subjects && email.position === 1} />}
          </div>
        )}
      </div>
    </div>
  );
}

export function EmailCard({ email, to, name, from, ab, sentAt, abNote }: {
  email: ReviewEmail; to: string; name: string; from: { name: string; email: string } | null; ab: boolean; sentAt?: string; abNote?: string;
}) {
  return (
    <article className="overflow-hidden rounded-xl border bg-card shadow-sm" aria-label={`Aperçu : ${email.subject}`}>
      <header className="space-y-1 border-b bg-muted/30 px-4 py-3 text-sm">
        <h3 className="text-base font-semibold leading-snug">{email.subject || <span className="text-destructive">(objet manquant)</span>}</h3>
        <dl className="grid grid-cols-[3rem_1fr] gap-x-2 gap-y-0.5 text-xs">
          <dt className="text-muted-foreground">De</dt><dd className="truncate">{from ? `${from.name} <${from.email}>` : "votre boîte mail"}</dd>
          <dt className="text-muted-foreground">À</dt><dd className="truncate">{name} &lt;{to}&gt;</dd>
          {sentAt && <><dt className="text-muted-foreground">Envoyé</dt><dd>{formatDayTime(sentAt)}</dd></>}
          {email.planned_at && <><dt className="text-muted-foreground">Prévu</dt><dd>{formatDayTime(email.planned_at)}{email.position > 1 ? " · seulement s'il n'y a pas de réponse" : ""}</dd></>}
        </dl>
        {email.same_thread && email.position > 1 && <p className="text-xs text-muted-foreground">Dans la même conversation que le 1er email (« Re: »).</p>}
        {ab && <p className="text-xs text-muted-foreground">{abNote ?? "Objet A/B : chaque personne reçoit l'objet A ou B, tiré au sort. L'aperçu montre l'objet A."}</p>}
      </header>
      <div className="max-h-[34vh] overflow-y-auto whitespace-pre-wrap px-4 py-3 text-sm leading-relaxed">{email.body}</div>
      {(email.attachments.length > 0 || email.problems.length > 0 || email.warnings.length > 0) && (
        <footer className="space-y-2 border-t px-4 py-3">
          {email.attachments.length > 0 && <AttachmentChips items={email.attachments} />}
          {email.problems.length > 0 && (
            <ul className="space-y-0.5 rounded-lg bg-destructive/10 px-3 py-2 text-xs text-destructive">{email.problems.map((x) => <li key={x}>⚠ {x}</li>)}</ul>
          )}
          {email.warnings.length > 0 && (
            <ul className="space-y-0.5 rounded-lg bg-warning/10 px-3 py-2 text-xs text-warning">{email.warnings.map((x) => <li key={x}>{x}</li>)}</ul>
          )}
        </footer>
      )}
    </article>
  );
}
