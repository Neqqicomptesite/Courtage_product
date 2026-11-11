// Écrire un email depuis n'importe où : boîte mail, fiche contact, fiche entreprise, réponses.
// V2.7 : fenêtre ancrée en bas à droite (comme une messagerie), réductible, et envoi « en
// arrière-plan » : la fenêtre se ferme tout de suite, un bandeau suit l'envoi, et en cas d'échec
// le brouillon revient intact.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, FileText, FlaskConical, Loader2, Maximize2, Minimize2, Paperclip, Send, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog, toastError } from "@/components/common";
import { useStatus } from "@/components/layout";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { ApiError, api, type Attachment, type MailDraft } from "@/lib/api";
import { formatDayTime } from "@/lib/format";
import { joinAddresses, RecipientInput, type RecipientInputHandle, splitAddresses } from "@/components/recipient-input";
import { cn } from "@/lib/utils";

export type ComposeRequest = {
  to?: string;
  cc?: string;
  bcc?: string;
  subject?: string;
  body?: string;
  inReplyTo?: string | null;
  references?: string[];
  /** message d'origine, cité sous la réponse si l'utilisateur le souhaite */
  quote?: { from: string; date: string | null; text: string };
  /** V2.19 : pièces jointes déjà prêtes (transfert d'un email) */
  attachments?: Attachment[];
  forward?: boolean;
};

export function openComposer(req: ComposeRequest = {}) {
  window.dispatchEvent(new CustomEvent<ComposeRequest>("oddo-compose", { detail: req }));
}

const PLACEHOLDER_RE = /\[([^[\]\n]{2,60})\]/g;  // même règle que le serveur (render.PLACEHOLDER_RE)

export function forwardSubject(subject: string) {
  return /^(tr|fwd?)\s*:/i.test(subject.trim()) ? subject.trim() : `TR: ${subject.trim()}`;
}

export function replySubject(subject: string) {
  return /^(re|tr|fwd?)\s*:/i.test(subject.trim()) ? subject.trim() : `RE: ${subject.trim()}`;
}

function quoted(q: NonNullable<ComposeRequest["quote"]>) {
  const head = `Le ${q.date ? formatDayTime(q.date) : "—"}, ${q.from} a écrit :`;
  return `\n\n${head}\n${q.text.split("\n").map((l) => `> ${l}`).join("\n")}`;
}

type Drafts = { to: string; cc: string; bcc: string };  // V3.7 : texte tapé pas encore devenu pastille
const NO_DRAFTS: Drafts = { to: "", cc: "", bcc: "" };
type State = { req: ComposeRequest; d: MailDraft; showCc: boolean; showBcc: boolean; drafts: Drafts; withQuote: boolean; signature: boolean; atts: Attachment[] };
const MAX_BYTES = 10 * 1024 * 1024;
export const fileSize = (n: number) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1).replace(".", ",")} Mo` : `${Math.max(1, Math.round(n / 1024))} Ko`);

/** Dépose des fichiers et renvoie les pièces jointes enregistrées (les refus s'affichent en message). */
export async function uploadFiles(files: FileList | File[]): Promise<Attachment[]> {
  const out: Attachment[] = [];
  for (const f of Array.from(files)) {
    try { out.push(await api.uploadAttachment(f)); } catch (e) { toast.error(`${f.name} non ajouté`, { description: e instanceof Error ? e.message : undefined }); }
  }
  return out;
}

export function AttachmentChips({ items, onRemove }: { items: Attachment[]; onRemove?: (id: number) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((a) => (
        <span key={a.id} className="inline-flex max-w-full items-center gap-1.5 rounded-md border bg-muted/40 py-1 pl-2 pr-1 text-xs">
          <Paperclip className="size-3 shrink-0 text-muted-foreground" />
          <a href={`/api/attachments/${a.id}?t=${encodeURIComponent(a.token ?? "")}`} target="_blank" rel="noreferrer" className="truncate hover:underline">{a.name}</a>
          <span className="shrink-0 text-muted-foreground">{fileSize(a.size)}</span>
          {onRemove && <button type="button" className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground" aria-label={`Retirer ${a.name}`} onClick={() => onRemove(a.id)}><X className="size-3" /></button>}
        </span>
      ))}
    </div>
  );
}

export function Composer() {
  const qc = useQueryClient();
  const { data: status } = useStatus();
  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: api.settings, staleTime: 5 * 60_000 });
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"normal" | "min" | "max">("normal");
  const [st, setSt] = useState<State>({ req: {}, d: { to: "", subject: "", body: "" }, showCc: false, showBcc: false, drafts: NO_DRAFTS, withQuote: true, signature: true, atts: [] });
  const [uploading, setUploading] = useState(0);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const addFiles = async (files: FileList | File[]) => {
    const list = Array.from(files);
    if (!list.length) return;
    setUploading((n) => n + list.length);
    try {
      const done = await uploadFiles(list);
      setSt((x) => ({ ...x, atts: [...x.atts, ...done.filter((a) => !x.atts.some((b) => b.id === a.id))] }));
    } finally { setUploading((n) => n - list.length); }
  };
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [confirm, setConfirm] = useState<{ message: string; state: State } | null>(null);
  const [warn, setWarn] = useState<{ message: string; state: State; force: boolean } | null>(null);
  const { data: seqs } = useQuery({ queryKey: ["sequences"], queryFn: api.sequences, staleTime: 60_000, enabled: open });
  const [inserting, setInserting] = useState(false);
  // V2.21 : « Modèles » : le 1er email d'une séquence, écrit pour le destinataire s'il est connu
  const insertTemplate = async (id: number) => {
    setInserting(true);
    try {
      const tpl = await api.sequenceTemplate(id, splitAddresses(st.d.to)[0] ?? st.drafts.to.trim());
      setSt((x) => ({
        ...x,
        d: { ...x.d, subject: x.d.subject.trim() && (x.req.inReplyTo || x.req.forward) ? x.d.subject : tpl.subject,
             body: x.d.body.trim() ? `${tpl.body}\n\n${x.d.body}` : tpl.body },
        atts: [...x.atts, ...tpl.attachments.filter((a) => !x.atts.some((b) => b.id === a.id))],
      }));
      if (!tpl.contact && (st.d.to.trim() || st.drafts.to.trim())) toast.info("Destinataire absent de vos contacts : le modèle commence par « Madame, Monsieur ».");
      requestAnimationFrame(() => body.current?.focus());
    } catch (e) { toastError(e, "Modèle non inséré"); } finally { setInserting(false); }
  };
  const body = useRef<HTMLTextAreaElement>(null);
  const toInput = useRef<RecipientInputHandle>(null);

  useEffect(() => {
    const onCompose = (e: Event) => {
      const r = (e as CustomEvent<ComposeRequest>).detail ?? {};
      setSt({ req: r, d: { to: r.to ?? "", cc: r.cc ?? "", bcc: r.bcc ?? "", subject: r.subject ?? "", body: r.body ?? "" },
              showCc: !!r.cc, showBcc: !!r.bcc, drafts: NO_DRAFTS, withQuote: true, signature: true, atts: r.attachments ?? [] });
      setErrors({});
      setMode("normal");
      setOpen(true);
      requestAnimationFrame(() => {
        const el = r.to ? body.current : toInput.current;
        el?.focus();
        if (el === body.current && body.current) body.current.setSelectionRange(0, 0);  // écrire au-dessus du message transféré
      });
    };
    window.addEventListener("oddo-compose", onCompose);
    return () => window.removeEventListener("oddo-compose", onCompose);
  }, []);

  // Envoi en arrière-plan : on ferme tout de suite, on rouvre le brouillon si ça échoue.
  const send = useCallback(async (raw: State, force = false, checked = false) => {
    // V3.7 : une adresse tapée mais pas encore devenue pastille part aussi
    const merge = (k: "to" | "cc" | "bcc") => joinAddresses([...splitAddresses(raw.d[k]), ...splitAddresses(raw.drafts[k])]);
    const state: State = { ...raw, d: { ...raw.d, to: merge("to"), cc: merge("cc"), bcc: merge("bcc") }, drafts: NO_DRAFTS };
    const { d, req } = state;
    const local: Record<string, string> = {};
    if (!d.to.trim()) local.to = "Indiquez un destinataire.";
    if (!d.body.trim()) local.body = "Le message est vide.";
    if (state.atts.reduce((n, a) => n + a.size, 0) > MAX_BYTES) local.attachments = "Pièces jointes trop lourdes : 10 Mo au maximum au total.";
    if (Object.keys(local).length) { setErrors(local); return; }
    // V2.21 : comme Gmail, on prévient au lieu de bloquer (objet vide, [champs] pas remplis)
    if (!checked) {
      const holes = [...new Set([...`${d.subject}\n${d.body}`.matchAll(PLACEHOLDER_RE)].map((m) => m[0]))];
      const issues = [
        ...(!d.subject.trim() ? ["Cet email n'a pas d'objet."] : []),
        ...(holes.length ? [`Il reste ${holes.length > 1 ? "des champs" : "un champ"} à compléter : ${holes.slice(0, 4).join(", ")}${holes.length > 4 ? "…" : ""}.`] : []),
      ];
      if (issues.length) { setWarn({ message: issues.join(" "), state, force }); return; }
    }
    setOpen(false);
    const others = splitAddresses(d.cc).length + splitAddresses(d.bcc).length;
    const id = toast.loading(`Envoi à ${d.to}${others ? ` (+ ${others} en copie)` : ""}…`);
    try {
      const r = await api.mailSend({
        ...d, body: d.body + (req.quote && state.withQuote ? quoted(req.quote) : ""), signature: state.signature, force,
        in_reply_to: req.inReplyTo ?? null, references: req.references ?? [], attachment_ids: state.atts.map((a) => a.id),
      });
      toast.success(r.test_mode ? "Envoyé vers votre propre adresse (mode test)" : `Envoyé à ${r.to}`, { id });
      ["mail", "contact", "company", "followups"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
    } catch (e) {
      toast.dismiss(id);
      if (e instanceof ApiError && e.data.confirm) { setConfirm({ message: e.message, state }); return; }
      setSt(state);
      setErrors(e instanceof ApiError ? e.fields : {});
      setOpen(true);
      toast.error("Email non envoyé", { description: e instanceof Error ? e.message : undefined });
    }
  }, [qc]);

  const set = (patch: Partial<MailDraft>) => setSt((x) => ({ ...x, d: { ...x.d, ...patch } }));
  const setDraft = (k: "to" | "cc" | "bcc", v: string) => setSt((x) => ({ ...x, drafts: { ...x.drafts, [k]: v } }));
  const sig = settings?.mailbox.signature?.trim();
  const { req, d } = st;
  const title = req.forward ? "Transfert" : req.inReplyTo ? "Réponse" : "Nouveau message";
  const line = "flex items-center gap-2 border-b px-4";
  const field = "h-10 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground";

  return (
    <>
      {open && (
        <div role="dialog" aria-label={title}
          className={cn("fixed z-50 flex flex-col overflow-hidden border bg-card shadow-2xl animate-in fade-in-0 slide-in-from-bottom-4",
            mode === "min" ? "bottom-0 right-4 w-72 rounded-t-xl"
              : mode === "max" ? "inset-4 rounded-xl sm:inset-x-[10%] sm:inset-y-8"
                : "inset-0 sm:inset-auto sm:bottom-0 sm:right-6 sm:h-[min(36rem,85vh)] sm:w-[34rem] sm:rounded-t-xl")}>
          {/* barre de titre : réduire, agrandir, fermer */}
          <div className="flex h-11 shrink-0 cursor-default items-center gap-2 bg-primary px-4 text-primary-foreground"
            onClick={() => mode === "min" && setMode("normal")}>
            <span className="min-w-0 flex-1 truncate text-sm font-medium">{d.subject || title}</span>
            {status?.test_mode && <span className="inline-flex items-center gap-1 rounded-full bg-warning px-2 py-0.5 text-[11px] font-medium text-white"><FlaskConical className="size-3" />Test</span>}
            <button className="rounded p-1 hover:bg-white/15" aria-label={mode === "min" ? "Agrandir" : "Réduire"}
              onClick={(e) => { e.stopPropagation(); setMode(mode === "min" ? "normal" : "min"); }}>
              {mode === "min" ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
            </button>
            {mode !== "min" && (
              <button className="hidden rounded p-1 hover:bg-white/15 sm:block" aria-label="Plein écran" onClick={() => setMode(mode === "max" ? "normal" : "max")}>
                {mode === "max" ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
              </button>
            )}
            <button className="rounded p-1 hover:bg-white/15" aria-label="Fermer" onClick={(e) => { e.stopPropagation(); setOpen(false); }}><X className="size-4" /></button>
          </div>

          {mode !== "min" && (
            <form className={cn("relative flex min-h-0 flex-1 flex-col", dragging && "ring-2 ring-inset ring-primary")}
              onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setDragging(true); } }}
              onDragLeave={(e) => { if (e.currentTarget === e.target) setDragging(false); }}
              onDrop={(e) => { if (e.dataTransfer.files.length) { e.preventDefault(); setDragging(false); void addFiles(e.dataTransfer.files); } }}
              onSubmit={(e) => { e.preventDefault(); void send(st); }}
              onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); void send(st); } }}>
              <RecipientInput ref={toInput} label="À" placeholder="nom ou adresse (ex. yassine)"
                value={splitAddresses(d.to)} onChange={(v) => set({ to: joinAddresses(v) })}
                draft={st.drafts.to} onDraft={(v) => setDraft("to", v)} exclude={[...splitAddresses(d.cc), ...splitAddresses(d.bcc)]}
                trailing={<>
                  {!st.showCc && <button type="button" className="text-xs text-muted-foreground hover:text-foreground" onClick={() => setSt((x) => ({ ...x, showCc: true }))}>Cc</button>}
                  {!st.showBcc && <button type="button" className="text-xs text-muted-foreground hover:text-foreground" onClick={() => setSt((x) => ({ ...x, showBcc: true }))}>Cci</button>}
                </>} />
              {errors.to && <p className="px-4 pt-1 text-xs text-destructive">{errors.to}</p>}
              {st.showCc && (
                <RecipientInput label="Cc" value={splitAddresses(d.cc)} onChange={(v) => set({ cc: joinAddresses(v) })}
                  draft={st.drafts.cc} onDraft={(v) => setDraft("cc", v)} exclude={[...splitAddresses(d.to), ...splitAddresses(d.bcc)]} placeholder="en copie (plusieurs possibles)" />
              )}
              {st.showBcc && (
                <RecipientInput label="Cci" value={splitAddresses(d.bcc)} onChange={(v) => set({ bcc: joinAddresses(v) })}
                  draft={st.drafts.bcc} onDraft={(v) => setDraft("bcc", v)} exclude={[...splitAddresses(d.to), ...splitAddresses(d.cc)]}
                  placeholder="copie cachée : les autres destinataires ne la voient pas" />
              )}
              <div className={line}>
                <span className="w-12 text-sm text-muted-foreground">Objet</span>
                <input className={field} value={d.subject} onChange={(e) => set({ subject: e.target.value })} />
              </div>
              {errors.subject && <p className="px-4 pt-1 text-xs text-destructive">{errors.subject}</p>}
              <textarea ref={body} value={d.body} onChange={(e) => set({ body: e.target.value })} placeholder="Bonjour,"
                className="min-h-0 flex-1 resize-none bg-transparent px-4 py-3 text-sm leading-relaxed outline-none placeholder:text-muted-foreground" />
              {errors.body && <p className="px-4 pb-1 text-xs text-destructive">{errors.body}</p>}
              {(st.atts.length > 0 || uploading > 0) && (
                <div className="space-y-1 border-t px-4 py-2">
                  <AttachmentChips items={st.atts} onRemove={(id) => setSt((x) => ({ ...x, atts: x.atts.filter((a) => a.id !== id) }))} />
                  {uploading > 0 && <p className="flex items-center gap-1.5 text-xs text-muted-foreground"><Loader2 className="size-3 animate-spin" />Ajout de {uploading} fichier(s)…</p>}
                </div>
              )}
              {errors.attachments && <p className="px-4 pb-1 text-xs text-destructive">{errors.attachments}</p>}
              {dragging && <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-primary/5 text-sm font-medium text-primary">Déposez les fichiers pour les joindre</div>}
              {(sig || req.quote) && (
                <div className="space-y-1 border-t bg-muted/30 px-4 py-2 text-xs text-muted-foreground">
                  {sig && (
                    <label className="flex items-center gap-2" title={sig}>
                      <input type="checkbox" className="accent-[hsl(var(--primary))]" checked={st.signature} onChange={(e) => setSt((x) => ({ ...x, signature: e.target.checked }))} />
                      <span className="truncate">Signature : {sig.split("\n")[0]}…</span>
                    </label>
                  )}
                  {req.quote && (
                    <label className="flex items-center gap-2">
                      <input type="checkbox" className="accent-[hsl(var(--primary))]" checked={st.withQuote} onChange={(e) => setSt((x) => ({ ...x, withQuote: e.target.checked }))} />
                      <span className="truncate">Citer le message précédent ({req.quote.from})</span>
                    </label>
                  )}
                </div>
              )}
              <div className="flex shrink-0 items-center gap-2 border-t px-4 py-2.5">
                <Button type="submit" className="rounded-full px-5" disabled={uploading > 0} title="Envoyer (Ctrl + Entrée)"><Send /> Envoyer</Button>
                <Button type="button" variant="ghost" size="icon" className="size-9 rounded-full" title="Joindre un fichier (10 Mo au total)" aria-label="Joindre un fichier"
                  onClick={() => fileInput.current?.click()}><Paperclip /></Button>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button type="button" variant="ghost" size="sm" className="h-9 rounded-full" disabled={inserting} title="Insérer un email de vos séquences">
                      {inserting ? <Loader2 className="animate-spin" /> : <FileText />} Modèles
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start" side="top" className="max-h-80 w-72 overflow-y-auto">
                    {!seqs?.items.length && <p className="px-2 py-1.5 text-xs text-muted-foreground">Aucune séquence.</p>}
                    {(["prospection", "gestion", "souscription"] as const).map((cat, i) => {
                      const items = (seqs?.items ?? []).filter((x) => x.category === cat);
                      if (!items.length) return null;
                      return (
                        <div key={cat}>
                          {i > 0 && <DropdownMenuSeparator />}
                          <p className="px-2 pb-1 pt-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{{ prospection: "Prospection", gestion: "Gestion", souscription: "Souscription" }[cat]}</p>
                          {items.map((x) => <DropdownMenuItem key={x.id} onSelect={() => void insertTemplate(x.id)}>{x.name}</DropdownMenuItem>)}
                        </div>
                      );
                    })}
                  </DropdownMenuContent>
                </DropdownMenu>
                <input ref={fileInput} type="file" multiple className="hidden" onChange={(e) => { if (e.target.files) void addFiles(e.target.files); e.target.value = ""; }} />
                <span className="flex-1" />
                <span className="truncate text-xs text-muted-foreground">{status?.test_mode ? "Mode test : part vers votre adresse" : `Depuis ${settings?.mailbox.email ?? "votre boîte"}`}</span>
              </div>
            </form>
          )}
        </div>
      )}
      <ConfirmDialog open={!!confirm} onOpenChange={(o) => !o && setConfirm(null)} title="Destinataire exclu"
        description={confirm?.message ?? ""} confirmLabel="Envoyer quand même"
        onConfirm={() => { const c = confirm; setConfirm(null); if (c) void send(c.state, true, true); }} />
      <ConfirmDialog open={!!warn} onOpenChange={(o) => !o && setWarn(null)} title="Envoyer quand même ?"
        description={warn?.message ?? ""} confirmLabel="Envoyer quand même"
        onConfirm={() => { const w = warn; setWarn(null); if (w) void send(w.state, w.force, true); }} />
    </>
  );
}
