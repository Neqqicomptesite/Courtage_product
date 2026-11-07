// Textes personnalisés (anciennement « blocs de contenu », simplifié en V2.8).
// Un email de prospection contient deux emplacements : le texte selon la FONCTION du contact
// ({{ bloc_cible }}) et le texte selon son SECTEUR ({{ bloc_secteur }}). Ici, on choisit une
// fonction et un secteur, on rédige les deux textes et on voit l'email assemblé en direct.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowLeft, Briefcase, Check, Factory, Loader2, Mail, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { PageHeader, toastError } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { NativeSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { api, type Block } from "@/lib/api";
import { cn } from "@/lib/utils";

const TODO = "À RÉDIGER";
// Contact fictif de l'aperçu : le poste suit la fonction choisie.
const SAMPLE_JOB: Record<string, string> = { FIN: "Directrice administrative et financière", RH: "Directrice des ressources humaines", DIR: "Gérante" };
const SAMPLE = { prenom: "Salma", nom: "Bennani", entreprise: "Exemple SARL" };
const VAR_RE = /\{\{\s*([a-zA-Z_][\w.]*)\s*(?:\|\s*"([^"]*)")?\s*\}\}/g;

type Part = { text: string; tag?: "target" | "sector" | "var" | "todo" };

/** Remplace les variables simples par des valeurs d'exemple (approximation de l'aperçu réel). */
function fillVars(text: string, ctx: Record<string, string>, out: Part[], tag?: Part["tag"]) {
  let last = 0;
  for (const m of text.matchAll(VAR_RE)) {
    if (m.index! > last) out.push({ text: text.slice(last, m.index), tag });
    const key = m[1];
    const value = key.startsWith("custom.") ? `[${key.slice(7).replace(/_/g, " ")}]` : ctx[key] ?? m[2] ?? `{{ ${key} }}`;
    out.push({ text: value, tag: tag ?? "var" });
    last = m.index! + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last), tag });
}

function assemble(body: string, target: string, sector: string, ctx: Record<string, string>): Part[] {
  const out: Part[] = [];
  const re = /\{\{\s*(bloc_cible|bloc_secteur)\s*\}\}/g;
  let last = 0;
  for (const m of body.matchAll(re)) {
    if (m.index! > last) fillVars(body.slice(last, m.index), ctx, out);
    const text = m[1] === "bloc_cible" ? target : sector;
    if (text.includes(TODO) || !text.trim()) out.push({ text: text.trim() || TODO, tag: "todo" });
    else fillVars(text, ctx, out, m[1] === "bloc_cible" ? "target" : "sector");
    last = m.index! + m[0].length;
  }
  if (last < body.length) fillVars(body.slice(last), ctx, out);
  return out;
}

const TAG_CLASS: Record<NonNullable<Part["tag"]>, string> = {
  target: "rounded-sm bg-primary/10 text-foreground ring-1 ring-primary/20",
  sector: "rounded-sm bg-success/10 text-foreground ring-1 ring-success/25",
  var: "font-medium",
  todo: "rounded-sm bg-warning/15 text-warning ring-1 ring-warning/30",
};

export function BlocksPage() {
  const { data } = useQuery({ queryKey: ["blocks"], queryFn: api.blocks, staleTime: Infinity });
  if (!data) return <><Header /><Skeleton className="h-[560px] rounded-xl" /></>;
  return <><Header /><Workspace blocks={data} /></>;
}

function Header() {
  return (
    <PageHeader
      back={<Button variant="ghost" size="sm" className="-ml-2" asChild><Link to="/sequences"><ArrowLeft /> Séquences</Link></Button>}
      title="Textes personnalisés"
      description={<>Chaque email de prospection contient <b>un texte selon la fonction</b> du contact et <b>un texte selon son secteur</b>. Choisissez un profil : vous rédigez ses deux textes et voyez l'email tel qu'il le recevra. Enregistrement automatique.</>}
    />
  );
}

function Workspace({ blocks }: { blocks: Block[] }) {
  const targets = blocks.filter((b) => b.kind === "target");
  const sectors = blocks.filter((b) => b.kind === "sector");
  const [texts, setTexts] = useState<Record<number, string>>(() => Object.fromEntries(blocks.map((b) => [b.id, b.body])));
  // un texte ajouté (nouvelle fonction ou nouveau secteur) rejoint la liste
  useEffect(() => {
    setTexts((x) => { const n = { ...x }; blocks.forEach((b) => { if (!(b.id in n)) n[b.id] = b.body; }); return n; });
  }, [blocks]);
  const firstTodo = (l: Block[]) => (l.find((b) => b.todo) ?? l[0])?.id;
  const [tId, setTId] = useState<number | undefined>(() => firstTodo(targets));
  const [sId, setSId] = useState<number | undefined>(() => firstTodo(sectors));
  const t = targets.find((b) => b.id === tId);
  const s = sectors.find((b) => b.id === sId);
  const isTodo = (b: Block) => (texts[b.id] ?? "").includes(TODO) || !(texts[b.id] ?? "").trim();

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div className="space-y-5">
        <Picker icon={Briefcase} title="1. Fonction du contact" kind="target" items={targets} value={tId} onChange={setTId} isTodo={isTodo} tone="primary" />
        {t && <Editor key={t.id} block={t} onDeleted={() => setTId(targets.find((b) => b.id !== t.id)?.id)} title={`Texte pour la fonction « ${t.label} »`} tone="primary" value={texts[t.id] ?? ""} onChange={(v) => setTexts((x) => ({ ...x, [t.id]: v }))} />}
        <Picker icon={Factory} title="2. Secteur du contact" kind="sector" items={sectors} value={sId} onChange={setSId} isTodo={isTodo} tone="success" />
        {s && <Editor key={s.id} block={s} onDeleted={() => setSId(sectors.find((b) => b.id !== s.id)?.id)} title={`Texte pour le secteur « ${s.label} »`} tone="success" value={texts[s.id] ?? ""} onChange={(v) => setTexts((x) => ({ ...x, [s.id]: v }))} />}
        <p className="text-xs text-muted-foreground">
          Variables possibles dans ces textes : {"{{ prenom }}"}, {"{{ entreprise }}"}, {"{{ poste }}"}, {"{{ custom.accroche_suggeree }}"}…
          Tant qu'un texte contient « {TODO} », une campagne qui l'utilise ne peut pas démarrer.
        </p>
      </div>
      <div className="xl:sticky xl:top-20 xl:self-start">
        <AssembledPreview target={t} sector={s} targetText={t ? texts[t.id] ?? "" : ""} sectorText={s ? texts[s.id] ?? "" : ""} />
      </div>
    </div>
  );
}

function Picker({ icon: Icon, title, kind, items, value, onChange, isTodo, tone }: {
  icon: typeof Briefcase; title: string; kind: Block["kind"]; items: Block[]; value?: number; onChange: (id: number) => void; isTodo: (b: Block) => boolean; tone: "primary" | "success";
}) {
  const left = items.filter(isTodo).length;
  return (
    <section className="space-y-2">
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        <Icon className="size-4 text-muted-foreground" />{title}
        {left > 0 ? <Badge variant="warning" className="ml-auto">{left} à rédiger</Badge> : <span className="ml-auto inline-flex items-center gap-1 text-xs text-success"><Check className="size-3.5" />Tout est rédigé</span>}
      </h2>
      <div className="flex flex-wrap gap-1.5">
        {items.map((b) => (
          <button key={b.id} onClick={() => onChange(b.id)}
            className={cn("inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm transition-colors",
              value === b.id ? (tone === "primary" ? "border-primary bg-primary text-primary-foreground" : "border-success bg-success text-white") : "hover:bg-accent")}>
            {isTodo(b) ? <span className={cn("size-1.5 rounded-full", value === b.id ? "bg-white" : "bg-warning")} /> : <Check className="size-3.5" />}
            {b.label}
          </button>
        ))}
        <AddProfile kind={kind} onAdded={onChange} />
      </div>
    </section>
  );
}

function Editor({ block, title, tone, value, onChange, onDeleted }: { block: Block; title: string; tone: "primary" | "success"; value: string; onChange: (v: string) => void; onDeleted: () => void }) {
  const qc = useQueryClient();
  const [dirty, setDirty] = useState(false);
  const timer = useRef<number>();
  const pending = useRef<string | null>(null);
  const save = useMutation({
    mutationFn: (text: string) => api.blockSave(block.id, text),
    onSuccess: () => { setDirty(false); qc.invalidateQueries({ queryKey: ["sequences"] }); qc.setQueryData<Block[]>(["blocks"], (l) => l?.map((b) => (b.id === block.id ? { ...b, body: value, todo: value.includes(TODO) } : b))); },
    onError: (e) => toastError(e, "Enregistrement impossible"),
  });
  // En changeant de profil, ce qui est en attente est enregistré tout de suite (rien n'est perdu).
  useEffect(() => () => {
    window.clearTimeout(timer.current);
    if (pending.current !== null) {
      const text = pending.current;
      api.blockSave(block.id, text).then(() => qc.setQueryData<Block[]>(["blocks"], (l) => l?.map((b) => (b.id === block.id ? { ...b, body: text, todo: text.includes(TODO) } : b))))
        .catch((e) => toastError(e, "Enregistrement impossible"));
    }
  }, [block.id, qc]);
  const todo = value.includes(TODO) || !value.trim();
  return (
    <Card className={cn("border-l-4 p-4", tone === "primary" ? "border-l-primary" : "border-l-success")}>
      <div className="mb-2 flex items-center gap-2">
        <span className="text-sm font-medium">{title}</span>
        {block.custom && (
          <button title={block.used ? `${block.used} contact(s) ont ce profil : impossible de supprimer` : "Supprimer ce texte"} disabled={block.used > 0}
            className="rounded p-1 text-muted-foreground hover:text-destructive disabled:cursor-not-allowed disabled:opacity-40"
            onClick={async () => {
              try { await api.blockDelete(block.id); pending.current = null; qc.setQueryData<Block[]>(["blocks"], (l) => l?.filter((b) => b.id !== block.id)); qc.invalidateQueries({ queryKey: ["sequences"] }); onDeleted(); toast.success("Supprimé"); }
              catch (e) { toastError(e, "Suppression impossible"); }
            }}><Trash2 className="size-3.5" /></button>
        )}
        <span className="ml-auto text-xs text-muted-foreground">
          {save.isPending ? <Loader2 className="size-3.5 animate-spin" /> : dirty ? "…" : todo ? <Badge variant="warning">À rédiger</Badge>
            : <span className="inline-flex items-center gap-1 text-success"><Check className="size-3.5" />Enregistré</span>}
        </span>
      </div>
      <Textarea value={value} rows={block.kind === "target" ? 7 : 5}
        onChange={(e) => {
          const v = e.target.value;
          onChange(v); setDirty(true); pending.current = v;
          window.clearTimeout(timer.current);
          timer.current = window.setTimeout(() => { pending.current = null; save.mutate(v); }, 800);
        }} />
    </Card>
  );
}

function AssembledPreview({ target, sector, targetText, sectorText }: { target?: Block; sector?: Block; targetText: string; sectorText: string }) {
  const { data: seqs } = useQuery({ queryKey: ["sequences"], queryFn: api.sequences });
  const candidates = (seqs?.items ?? []).filter((q) => (q.category ?? "prospection") === "prospection");
  const [seqId, setSeqId] = useState<number | null>(null);
  const chosen = seqId ?? candidates[0]?.id ?? null;
  const { data: seq } = useQuery({ queryKey: ["sequence", chosen], queryFn: () => api.sequence(chosen!), enabled: chosen !== null });
  const step = seq?.steps.find((s) => s.position === 1);
  const ctx = useMemo(() => ({ ...SAMPLE, poste: SAMPLE_JOB[target?.key ?? "FIN"] ?? "Directeur", secteur: sector?.label ?? "", bloc_cible: "", bloc_secteur: "" }), [target, sector]);
  const parts = useMemo(() => (step ? assemble(step.body, targetText, sectorText, ctx) : []), [step, targetText, sectorText, ctx]);
  const subject = useMemo(() => {
    const out: Part[] = [];
    fillVars(step?.subject_a ?? "", ctx, out);
    return out.map((p) => p.text).join("");
  }, [step, ctx]);
  const uses = step ? { t: /\{\{\s*bloc_cible\s*\}\}/.test(step.body), s: /\{\{\s*bloc_secteur\s*\}\}/.test(step.body) } : null;

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b px-4 py-2.5">
        <Mail className="size-4 text-primary" />
        <span className="text-sm font-semibold">L'email assemblé</span>
        {candidates.length > 1 && (
          <NativeSelect className="ml-auto h-8 w-auto max-w-[14rem] text-xs" value={chosen ?? ""} onChange={(e) => setSeqId(Number(e.target.value))}>
            {candidates.map((q) => <option key={q.id} value={q.id}>{q.name}</option>)}
          </NativeSelect>
        )}
      </div>
      {!seqs ? <div className="p-4"><Skeleton className="h-72" /></div> : !step ? (
        <p className="p-6 text-sm text-muted-foreground">Créez une séquence de prospection pour voir l'email assemblé.</p>
      ) : (
        <div className="space-y-3 p-4">
          <div className="space-y-1 rounded-lg bg-muted/40 px-4 py-3 text-xs">
            <p><span className="text-muted-foreground">À </span>{SAMPLE.prenom} {SAMPLE.nom}, {ctx.poste} · {SAMPLE.entreprise}{sector ? ` (${sector.label})` : ""}</p>
            <p className="text-sm font-semibold">{subject || <span className="font-normal italic text-muted-foreground">(sans objet)</span>}</p>
          </div>
          <div className="max-h-[520px] overflow-y-auto whitespace-pre-wrap px-1 text-sm leading-relaxed">
            {parts.map((p, i) => <span key={i} className={p.tag ? TAG_CLASS[p.tag] : undefined}>{p.text}</span>)}
          </div>
          <div className="flex flex-wrap gap-3 border-t pt-3 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1.5"><span className="size-3 rounded-sm bg-primary/15 ring-1 ring-primary/30" />Texte fonction</span>
            <span className="inline-flex items-center gap-1.5"><span className="size-3 rounded-sm bg-success/15 ring-1 ring-success/30" />Texte secteur</span>
            <span className="inline-flex items-center gap-1.5"><span className="size-3 rounded-sm bg-warning/20 ring-1 ring-warning/30" />À rédiger</span>
          </div>
          {uses && (!uses.t || !uses.s) && (
            <p className="text-xs text-warning">
              Le premier email de « {seq?.name} » n'utilise pas {!uses.t && !uses.s ? "ces textes" : !uses.t ? "le texte fonction" : "le texte secteur"} :
              ajoutez-le depuis l'éditeur de la séquence (boutons « Texte fonction » et « Texte secteur »).
            </p>
          )}
          <p className="text-[11px] text-muted-foreground">Aperçu avec un contact fictif ; la signature est ajoutée à l'envoi.</p>
        </div>
      )}
    </Card>
  );
}

/** « + Ajouter une fonction / un secteur » : un nom suffit, le code (ex. ACH) est créé tout seul. */
function AddProfile({ kind, onAdded }: { kind: Block["kind"]; onAdded: (id: number) => void }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState("");
  const add = useMutation({
    mutationFn: () => api.blockCreate(kind, label),
    onSuccess: (b) => {
      qc.setQueryData<Block[]>(["blocks"], (l) => [...(l ?? []), b]);
      qc.invalidateQueries({ queryKey: ["contacts"] });  // listes « Fonction » et « Secteur » des fiches
      qc.invalidateQueries({ queryKey: ["sequences"] });  // bandeau « textes à rédiger »
      setOpen(false); setLabel("");
      onAdded(b.id);
      toast.success(`${kind === "target" ? "Fonction" : "Secteur"} « ${b.label} » ajouté`, { description: `Code ${b.key} : rédigez son texte ci-dessous.` });
    },
    onError: (e) => toastError(e, "Ajout impossible"),
  });
  const what = kind === "target" ? "une fonction" : "un secteur";
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button className="inline-flex items-center gap-1 rounded-full border border-dashed px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary">
          <Plus className="size-3.5" /> Ajouter {what}
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 space-y-3">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (label.trim()) add.mutate(); }}>
          <p className="text-sm font-medium">Ajouter {what}</p>
          <Input autoFocus value={label} onChange={(e) => setLabel(e.target.value)} placeholder={kind === "target" ? "ex. Achats, Direction commerciale" : "ex. Hôtellerie et tourisme"} />
          <p className="text-xs text-muted-foreground">
            Elle apparaîtra dans les fiches contacts, l'import et le modèle Excel. Chaque contact {kind === "target" ? "de cette fonction" : "de ce secteur"} recevra le texte que vous allez rédiger.
          </p>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => setOpen(false)}>Annuler</Button>
            <Button type="submit" size="sm" disabled={!label.trim() || add.isPending}>{add.isPending ? <Loader2 className="animate-spin" /> : <Plus />} Ajouter</Button>
          </div>
        </form>
      </PopoverContent>
    </Popover>
  );
}
