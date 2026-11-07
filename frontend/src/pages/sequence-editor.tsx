import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle, ArrowLeft, Braces, CalendarClock, Check, CheckCircle2, ChevronLeft, ChevronRight, Clock, CornerDownRight, Loader2, Mail,
  Paperclip, Plus, Send, Split, Trash2,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { ConfirmDialog, toastError, useDebounced } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { AttachmentChips, fileSize, uploadFiles } from "@/components/composer";
import { api, type SequenceCategory, type SequenceFull, type StepData } from "@/lib/api";
import { BRANCHES, CATEGORIES } from "@/pages/sequences";
import { formatDayTime, fullName } from "@/lib/format";
import { cn } from "@/lib/utils";

type SaveState = "saved" | "dirty" | "saving" | "error";

// Variables proposées en un clic. « prenom » est inséré avec une valeur de repli :
// un contact sans prénom ne bloquera pas la campagne.
const VARS: { label: string; text: string; hint: string }[] = [
  { label: "Prénom", text: '{{ prenom | "Madame, Monsieur" }}', hint: "Prénom du contact, « Madame, Monsieur » s'il manque" },
  { label: "Nom", text: "{{ nom }}", hint: "Nom de famille" },
  { label: "Entreprise", text: "{{ entreprise }}", hint: "Nom de l'entreprise" },
  { label: "Poste", text: "{{ poste }}", hint: "Intitulé du poste" },
  { label: "Secteur", text: "{{ secteur }}", hint: "Secteur d'activité" },
  { label: "Texte fonction", text: "{{ bloc_cible }}", hint: "Votre texte personnalisé selon la fonction du contact (finance, RH, dirigeant) : Séquences → Textes personnalisés" },
  { label: "Texte secteur", text: "{{ bloc_secteur }}", hint: "Votre texte personnalisé selon le secteur du contact (industrie, BTP…) : Séquences → Textes personnalisés" },
];

export function SequenceEditorPage() {
  const id = Number(useParams().id);
  const { data, isError } = useQuery({ queryKey: ["sequence", id], queryFn: () => api.sequence(id), staleTime: Infinity });
  if (isError) return <p className="text-sm text-destructive">Séquence introuvable.</p>;
  if (!data) return <div className="space-y-4"><Skeleton className="h-10 w-80" /><Skeleton className="h-[600px] rounded-xl" /></div>;
  return <Editor key={id} initial={data} />;
}

function Editor({ initial }: { initial: SequenceFull }) {
  const qc = useQueryClient();
  const [name, setName] = useState(initial.name);
  const [category, setCategory] = useState<SequenceCategory>(initial.category ?? "prospection");
  const [branch, setBranch] = useState<string>(initial.branch ?? "");
  const [steps, setSteps] = useState<StepData[]>(initial.steps);
  const [selected, setSelected] = useState(initial.steps[0]?.id);
  const [state, setState] = useState<SaveState>("saved");
  const [version, setVersion] = useState(0); // incrémenté à chaque enregistrement : rafraîchit l'aperçu
  const [toDelete, setToDelete] = useState<StepData | null>(null);
  const latest = useRef({ name, steps, category, branch });
  latest.current = { name, steps, category, branch };
  const used = initial.campaigns > 0;

  // ---------------------------------------------------------------- enregistrement automatique
  const save = useMutation({
    mutationFn: () => api.sequenceSave(initial.id, latest.current.name, latest.current.steps, latest.current.category, latest.current.branch),
    onMutate: () => setState("saving"),
    onSuccess: () => {
      setState((s) => (s === "saving" ? "saved" : s));
      setVersion((v) => v + 1);
      qc.invalidateQueries({ queryKey: ["sequences"] });
    },
    onError: (e) => {
      setState("error");
      toastError(e, "Enregistrement impossible");
    },
  });
  const debouncedSave = useDebounced(() => save.mutate(), 700);
  const touch = () => {
    setState("dirty");
    debouncedSave();
  };
  // Prévenir avant de quitter la page si un enregistrement est en attente.
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (state === "dirty" || state === "saving") e.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [state]);

  const updateStep = (sid: number, patch: Partial<StepData>) => {
    setSteps((list) => list.map((s) => (s.id === sid ? { ...s, ...patch } : s)));
    touch();
  };

  const structural = (fn: () => Promise<{ steps: StepData[] }>, after?: (s: StepData[]) => void) => async () => {
    try {
      await api.sequenceSave(initial.id, latest.current.name, latest.current.steps, latest.current.category, latest.current.branch); // d'abord ce qui est en cours
      const res = await fn();
      setSteps(res.steps);
      setState("saved");
      setVersion((v) => v + 1);
      after?.(res.steps);
    } catch (e) {
      toastError(e);
    }
  };
  const addStep = structural(() => api.stepAdd(initial.id), (s) => setSelected(s[s.length - 1].id));
  const deleteStep = (st: StepData) =>
    structural(() => api.stepDelete(initial.id, st.id), (s) => {
      setToDelete(null);
      setSelected(s[Math.max(0, st.position - 2)]?.id);
    })();

  const current = steps.find((s) => s.id === selected) ?? steps[0];
  const cumul = useMemo(() => steps.reduce<number[]>((acc, s) => [...acc, (acc.at(-1) ?? 0) + (s.position === 1 ? 0 : s.delay_days)], []), [steps]);

  if (initial.editable === false) return <ReadOnlyNotice initial={initial}>{body()}</ReadOnlyNotice>;
  return body();

  function body() { return (
    <div className="space-y-5">
      {/* En-tête : nom modifiable directement, état d'enregistrement */}
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" size="icon" asChild><Link to="/sequences" aria-label="Retour"><ArrowLeft /></Link></Button>
        <input value={name} onChange={(e) => { setName(e.target.value); touch(); }} aria-label="Nom de la séquence"
          className="min-w-0 flex-1 rounded-md border border-transparent bg-transparent px-2 py-1 text-xl font-semibold tracking-tight outline-none transition-colors hover:border-border focus:border-ring" />
        <SaveIndicator state={state} />
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground">Type</span>
        <div className="inline-flex rounded-lg border bg-card p-0.5">
          {CATEGORIES.map((c) => (
            <button key={c.value} disabled={used && c.value !== category} title={used && c.value !== category ? "Déjà utilisée par une campagne : dupliquez-la pour changer de type." : c.hint}
              onClick={() => { if (c.value !== category) { setCategory(c.value); latest.current.category = c.value; touch(); } }}
              className={cn("rounded-md px-3 py-1 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-40",
                category === c.value ? "bg-primary font-medium text-primary-foreground" : "text-muted-foreground hover:bg-accent")}>{c.label}</button>
          ))}
        </div>
        <span className="text-xs text-muted-foreground">{CATEGORIES.find((c) => c.value === category)?.hint}</span>
        {category === "souscription" && (
          <label className="ml-auto flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">Branche</span>
            <select value={branch} aria-label="Branche" className="h-8 rounded-md border bg-background px-2 text-sm"
              onChange={(e) => { setBranch(e.target.value); latest.current.branch = e.target.value; touch(); }}>
              <option value="">Autre / aucune</option>
              {BRANCHES.map((b) => <option key={b} value={b}>{b}</option>)}
            </select>
          </label>
        )}
      </div>
      {used && (
        <p className="rounded-lg border border-warning/40 bg-warning/5 px-4 py-2.5 text-sm">
          Utilisée par {initial.campaigns} campagne{initial.campaigns > 1 ? "s" : ""} : les modifications s'appliquent aux prochains envois.
        </p>
      )}

      <div className="grid gap-5 xl:grid-cols-[280px_minmax(0,1fr)_minmax(0,1fr)] lg:grid-cols-[260px_minmax(0,1fr)]">
        {/* ------------------------------------------------------------ frise des étapes */}
        <div className="space-y-0">
          {steps.map((st, i) => (
            <div key={st.id}>
              {i > 0 ? <DelayPill step={st} cumul={cumul[i]} onChange={(p) => updateStep(st.id, p)} />
                : <DelayPill first step={st} cumul={0} onChange={(p) => updateStep(st.id, p)} />}
              <button onClick={() => setSelected(st.id)}
                className={cn("w-full rounded-xl border bg-card p-3.5 text-left shadow-sm transition-all",
                  st.id === current?.id ? "border-primary ring-2 ring-primary/15" : "hover:border-primary/40")}>
                <div className="flex items-center gap-2">
                  <span className={cn("flex size-6 items-center justify-center rounded-full text-[11px] font-semibold",
                    st.id === current?.id ? "bg-primary text-primary-foreground" : "bg-accent text-accent-foreground")}>{st.position}</span>
                  <span className="text-xs font-medium text-muted-foreground">{i === 0 ? "Premier email · J0" : `Relance · J+${cumul[i]}`}</span>
                  {st.position === 1 && st.subject_b && <Badge variant="info" className="ml-auto px-1.5"><Split className="size-3" />A/B</Badge>}
                </div>
                <p className="mt-2 truncate text-sm font-medium">
                  {st.position === 1 || !st.same_thread ? st.subject_a || <span className="italic text-muted-foreground">Sans objet</span>
                    : <span className="inline-flex items-center gap-1 text-muted-foreground"><CornerDownRight className="size-3.5" />Réponse dans le fil</span>}
                </p>
                <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{excerpt(st.body)}</p>
              </button>
            </div>
          ))}
          <button onClick={addStep} disabled={steps.length >= 8}
            className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl border border-dashed py-3 text-sm text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary disabled:opacity-50">
            <Plus className="size-4" /> Ajouter une relance
          </button>
        </div>

        {/* ------------------------------------------------------------ édition de l'étape */}
        {current && (
          <StepEditor key={current.id} step={current} customFields={initial.custom_fields} cumul={cumul[current.position - 1]}
            prospection={category === "prospection"}
            onChange={(p) => updateStep(current.id, p)}
            onDelete={current.position > 1 && !used ? () => setToDelete(current) : undefined} />
        )}

        {/* ------------------------------------------------------------ aperçu en direct */}
        {current && (
          <div className="lg:col-span-2 xl:col-span-1">
            <LivePreview sequenceId={initial.id} position={current.position} version={version} />
          </div>
        )}
      </div>

      <ConfirmDialog open={!!toDelete} onOpenChange={(o) => !o && setToDelete(null)} destructive
        title={`Supprimer l'étape ${toDelete?.position} ?`} description="Son texte sera perdu. Les étapes suivantes seront renumérotées."
        confirmLabel="Supprimer" onConfirm={() => toDelete && deleteStep(toDelete)} />
    </div>
  ); }
}

/** V3 : modèle commun à l'équipe, ouvert par un employé : lecture seule + « Dupliquer ». */
function ReadOnlyNotice({ initial, children }: { initial: SequenceFull; children: React.ReactNode }) {
  const navigate = useNavigate();
  const dup = useMutation({
    mutationFn: () => api.sequenceDuplicate(initial.id),
    onSuccess: (r) => { toast.success("Copie créée : c'est votre version, modifiable."); navigate(`/sequences/${r.id}`); },
    onError: (e) => toastError(e),
  });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-info/40 bg-accent/40 px-4 py-3 text-sm">
        <p className="min-w-0 flex-1">Modèle commun à l'équipe : seul l'administrateur peut le modifier. Vous pouvez l'utiliser tel quel, ou le dupliquer pour en faire votre version.</p>
        <Button size="sm" onClick={() => dup.mutate()} disabled={dup.isPending}>Dupliquer</Button>
      </div>
      <fieldset disabled className="min-w-0">{children}</fieldset>
    </div>
  );
}

function excerpt(body: string) {
  return body.replace(/\{\{\s*([\w.]+)[^}]*\}\}/g, "[$1]").replace(/\s+/g, " ").trim().slice(0, 140) || "Texte à rédiger";
}

function SaveIndicator({ state }: { state: SaveState }) {
  const map = {
    saved: [<Check key="i" className="size-3.5 text-success" />, "Enregistré"],
    dirty: [<span key="i" className="size-1.5 rounded-full bg-warning" />, "Modifications en cours"],
    saving: [<Loader2 key="i" className="size-3.5 animate-spin" />, "Enregistrement…"],
    error: [<AlertCircle key="i" className="size-3.5 text-destructive" />, "Non enregistré"],
  } as const;
  const [icon, label] = map[state];
  return <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">{icon}{label}</span>;
}

/* ----------------------------------------------------------------- délai entre étapes */

const DAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven"];
const DAYS_LONG = ["lundi", "mardi", "mercredi", "jeudi", "vendredi"];
const TIMES = ["09:00", "10:00", "11:00", "14:30", "15:00", "16:00"];

/** « +3 j ouvrés · mardi 10:00 » : le délai, puis le jour et l'heure précis s'il y en a (V2.5). */
export function timingLabel(step: StepData, first = false) {
  const when = [step.weekday !== null ? DAYS_LONG[step.weekday] : null, step.send_time?.replace(":", "h")].filter(Boolean).join(" ");
  if (first) return when ? `Envoi : ${when}` : "Envoi dès le lancement";
  const delay = `+${step.delay_days} jour${step.delay_days > 1 ? "s" : ""}${step.business_days ? " ouvrés" : ""}`;
  return when ? `${delay} · puis ${when}` : delay;
}

function DelayPill({ step, cumul, onChange, first }: { step: StepData; cumul: number; onChange: (p: Partial<StepData>) => void; first?: boolean }) {
  const chip = (active: boolean) => cn("rounded-md border px-2 py-1 text-xs transition-colors", active ? "border-primary bg-accent font-medium text-accent-foreground" : "hover:bg-accent");
  return (
    <div className={cn("relative flex justify-center", first ? "pb-2" : "py-2")}>
      {!first && <span className="absolute inset-y-0 left-1/2 w-px bg-border" />}
      <Popover>
        <PopoverTrigger asChild>
          <button className={cn("relative inline-flex items-center gap-1.5 rounded-full border bg-background px-3 py-1 text-xs font-medium shadow-sm transition-colors hover:border-primary/50 hover:text-primary",
            (step.weekday !== null || step.send_time) && "border-primary/40 text-primary")}>
            {first ? <CalendarClock className="size-3.5" /> : <Clock className="size-3.5" />}
            {timingLabel(step, first)}
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-80 space-y-4">
          {!first && <>
            <div>
              <p className="text-sm font-medium">Délai avant cette relance</p>
              <p className="text-xs text-muted-foreground">Compté depuis l'envoi précédent. Soit J+{cumul} après le premier email.</p>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="icon" className="size-8" onClick={() => onChange({ delay_days: Math.max(1, step.delay_days - 1) })}><ChevronLeft /></Button>
              <Input type="number" min={1} max={90} value={step.delay_days} className="h-8 w-16 text-center tabular"
                onChange={(e) => onChange({ delay_days: Math.min(90, Math.max(0, Number(e.target.value) || 0)) })} />
              <Button variant="outline" size="icon" className="size-8" onClick={() => onChange({ delay_days: Math.min(90, step.delay_days + 1) })}><ChevronRight /></Button>
              <span className="text-sm text-muted-foreground">jours</span>
            </div>
            <div className="flex gap-1.5">
              {[2, 3, 4, 7].map((d) => <button key={d} onClick={() => onChange({ delay_days: d })} className={chip(step.delay_days === d)}>{d} j</button>)}
            </div>
            <label className="flex items-center justify-between gap-3 text-sm">
              <span>Jours ouvrés uniquement<span className="block text-xs text-muted-foreground">Sans week-ends ni jours fériés</span></span>
              <Switch checked={step.business_days} onCheckedChange={(v) => onChange({ business_days: v })} />
            </label>
          </>}
          {first && <div>
            <p className="text-sm font-medium">Quand envoyer le premier email ?</p>
            <p className="text-xs text-muted-foreground">À partir du lancement de la campagne (ou de sa date de démarrage).</p>
          </div>}
          <div className="space-y-1.5 border-t pt-3">
            <p className="text-sm font-medium">{first ? "Jour" : "Puis attendre un jour précis"}</p>
            <div className="flex flex-wrap gap-1.5">
              <button onClick={() => onChange({ weekday: null })} className={chip(step.weekday === null)}>{first ? "Dès que possible" : "Non"}</button>
              {DAYS.map((d, i) => <button key={d} onClick={() => onChange({ weekday: i })} className={chip(step.weekday === i)}>{d}</button>)}
            </div>
          </div>
          <div className="space-y-1.5">
            <p className="text-sm font-medium">Heure</p>
            <div className="flex flex-wrap items-center gap-1.5">
              <button onClick={() => onChange({ send_time: null })} className={chip(!step.send_time)}>Ouverture</button>
              {TIMES.map((t) => <button key={t} onClick={() => onChange({ send_time: t })} className={chip(step.send_time === t)}>{t.replace(":", "h")}</button>)}
              <Input type="time" value={step.send_time ?? ""} className="h-7 w-24 text-xs" onChange={(e) => onChange({ send_time: e.target.value || null })} />
            </div>
            <p className="text-xs text-muted-foreground">
              {step.send_time ? "À partir de cette heure : un email à la fois, selon vos plafonds. Hors plages d'envoi, l'heure est ramenée à la plage suivante."
                : "Dès l'ouverture de la plage d'envoi (09h00 par défaut)."}
              {step.weekday !== null && " Si ce jour est férié, l'envoi passe à la prochaine ouverture."}
            </p>
          </div>
          {!first && (
            <label className="flex items-center justify-between gap-3 border-t pt-3 text-sm">
              <span>Répondre dans le même fil<span className="block text-xs text-muted-foreground">Objet « Re: … » sous le 1er email</span></span>
              <Switch checked={step.same_thread} onCheckedChange={(v) => onChange({ same_thread: v })} />
            </label>
          )}
        </PopoverContent>
      </Popover>
    </div>
  );
}

/* ---------------------------------------------------------------------- éditeur */

function StepEditor({ step, customFields, cumul, onChange, onDelete, prospection }: {
  step: StepData; customFields: string[]; cumul: number; onChange: (p: Partial<StepData>) => void; onDelete?: () => void; prospection: boolean;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const total = step.attachments.reduce((n, a) => n + a.size, 0);
  const addFiles = async (files: FileList) => {
    setUploading(true);
    try {
      const done = await uploadFiles(files);
      if (done.length) onChange({ attachments: [...step.attachments, ...done] });
    } finally { setUploading(false); }
  };
  // Dernier champ utilisé : c'est là que les variables s'insèrent, à l'endroit du curseur.
  const target = useRef<{ el: HTMLInputElement | HTMLTextAreaElement; field: "body" | "subject_a" | "subject_b" } | null>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const [abOpen, setAbOpen] = useState(!!step.subject_b);
  const showSubject = step.position === 1 || !step.same_thread;

  const insert = (text: string) => {
    const t = target.current ?? (bodyRef.current ? { el: bodyRef.current, field: "body" as const } : null);
    if (!t) return;
    const { el, field } = t;
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? el.value.length;
    const value = el.value.slice(0, start) + text + el.value.slice(end);
    onChange({ [field]: value } as Partial<StepData>);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(start + text.length, start + text.length);
    });
  };
  const track = (field: "body" | "subject_a" | "subject_b") => (e: React.FocusEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    target.current = { el: e.currentTarget, field };
  };

  return (
    <Card className="flex min-w-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b px-5 py-3">
        <div className="flex items-center gap-2">
          <Mail className="size-4 text-primary" />
          <span className="text-sm font-semibold">Étape {step.position}</span>
          <span className="text-xs text-muted-foreground">{step.position === 1 ? `· ${timingLabel(step, true).toLowerCase()}` : `· J+${cumul}${step.weekday !== null || step.send_time ? ` · ${timingLabel(step).split(" · puis ")[1] ?? ""}` : ""}`}</span>
        </div>
        {onDelete && (
          <Tooltip>
            <TooltipTrigger asChild><Button variant="ghost" size="icon" className="size-8 text-muted-foreground hover:text-destructive" onClick={onDelete}><Trash2 /></Button></TooltipTrigger>
            <TooltipContent>Supprimer l'étape</TooltipContent>
          </Tooltip>
        )}
      </div>
      <div className="space-y-4 p-4">
        {showSubject ? (
          <div className="space-y-2">
            <Label htmlFor="subject-a">{abOpen ? "Objet A" : "Objet"}</Label>
            <Input id="subject-a" value={step.subject_a} onFocus={track("subject_a")} onChange={(e) => onChange({ subject_a: e.target.value })}
              placeholder="ex. {{ entreprise }} : vos contrats d'assurance" />
            {step.position === 1 && (abOpen ? (
              <div className="space-y-2 pt-1">
                <div className="flex items-center justify-between">
                  <Label htmlFor="subject-b">Objet B</Label>
                  <button className="text-xs text-muted-foreground hover:text-destructive" onClick={() => { onChange({ subject_b: "" }); setAbOpen(false); }}>Retirer le test A/B</button>
                </div>
                <Input id="subject-b" value={step.subject_b} onFocus={track("subject_b")} onChange={(e) => onChange({ subject_b: e.target.value })}
                  placeholder="Un second objet, envoyé à la moitié des contacts" />
              </div>
            ) : (
              <button className="inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:underline" onClick={() => setAbOpen(true)}>
                <Split className="size-3.5" /> Tester un second objet (A/B)
              </button>
            ))}
          </div>
        ) : (
          <div className="flex items-center gap-2 rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">
            <CornerDownRight className="size-4" /> Objet « Re: … » repris du premier email : la relance s'affiche dans la même conversation.
          </div>
        )}

        <div className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Label htmlFor="body">Message</Label>
            <span className="text-xs text-muted-foreground">{prospection ? "Signature ajoutée automatiquement (et ligne STOP si activée dans Réglages)" : "Signature ajoutée automatiquement"}</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {VARS.map((v) => (
              <Tooltip key={v.label}>
                <TooltipTrigger asChild>
                  <button onMouseDown={(e) => e.preventDefault()} onClick={() => insert(v.text)}
                    className="inline-flex items-center gap-1 rounded-md border bg-card px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary">
                    <Braces className="size-3" />{v.label}
                  </button>
                </TooltipTrigger>
                <TooltipContent>{v.hint}</TooltipContent>
              </Tooltip>
            ))}
            {customFields.length > 0 && (
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button onMouseDown={(e) => e.preventDefault()} className="inline-flex items-center gap-1 rounded-md border border-dashed px-2 py-1 text-xs text-muted-foreground hover:text-primary">
                    <Plus className="size-3" />Colonne importée
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent onCloseAutoFocus={(e) => e.preventDefault()}>
                  {customFields.map((f) => (
                    <DropdownMenuItem key={f} onSelect={() => insert(`{{ custom.${f} }}`)}>{f.replace(/_/g, " ")}</DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
          <Textarea id="body" ref={bodyRef} value={step.body} onFocus={track("body")} onChange={(e) => onChange({ body: e.target.value })}
            className="min-h-[340px] font-[450]" placeholder="Rédigez votre message…" />
        </div>

        <div className="space-y-2 rounded-lg border border-dashed p-3">
          <div className="flex flex-wrap items-center gap-2">
            <Paperclip className="size-4 text-muted-foreground" />
            <span className="text-sm font-medium">Pièces jointes</span>
            <span className="text-xs text-muted-foreground">{step.attachments.length ? `${fileSize(total)} sur 10 Mo` : "plaquette, présentation… (10 Mo au total)"}</span>
            <Button type="button" variant="outline" size="sm" className="ml-auto h-7" disabled={uploading} onClick={() => fileInput.current?.click()}>
              {uploading ? <Loader2 className="animate-spin" /> : <Plus />} Joindre
            </Button>
            <input ref={fileInput} type="file" multiple className="hidden" onChange={(e) => { if (e.target.files) void addFiles(e.target.files); e.target.value = ""; }} />
          </div>
          {step.attachments.length > 0 && <AttachmentChips items={step.attachments} onRemove={(id) => onChange({ attachments: step.attachments.filter((a) => a.id !== id) })} />}
          {step.attachments.length > 0 && step.position === 1 && prospection && (
            <p className="text-xs text-muted-foreground">Envoyée à chaque contact avec le premier email. Une pièce jointe dans un premier email peut le faire classer en indésirables chez certains destinataires : gardez-la légère (un PDF).</p>
          )}
        </div>
      </div>
    </Card>
  );
}

/* ----------------------------------------------------------------- aperçu en direct */

function LivePreview({ sequenceId, position, version }: { sequenceId: number; position: number; version: number }) {
  const [contactIndex, setContactIndex] = useState(0);
  const [variant, setVariant] = useState<string>("");
  const { data: contacts } = useQuery({ queryKey: ["picker", ""], queryFn: () => api.picker("") });
  const contact = contacts?.[contactIndex];
  const { data, isFetching } = useQuery({
    queryKey: ["preview", sequenceId, contact?.id, variant, version],
    queryFn: () => api.preview(sequenceId, contact?.id, variant || undefined),
    enabled: !!contacts,
    placeholderData: (prev) => prev,
  });
  const send = useMutation({
    mutationFn: () => api.previewSend(sequenceId, data!.contact!.id, data!.variant ?? ""),
    onSuccess: (r) => toast.success(`${r.sent} emails d'aperçu envoyés`, { description: `À ${r.to}, jamais au contact.` }),
    onError: (e) => toastError(e, "Envoi de l'aperçu impossible"),
  });
  const step = data?.steps.find((s) => s.position === position);
  const allProblems = data?.steps.flatMap((s) => s.problems.map((p) => `Étape ${s.position} : ${p}`)) ?? [];

  return (
    <Card className="sticky top-20 overflow-hidden">
      <div className="flex items-center gap-2 border-b px-4 py-2.5">
        <span className="text-sm font-semibold">Aperçu</span>
        {isFetching && <Loader2 className="size-3.5 animate-spin text-muted-foreground" />}
        <div className="ml-auto flex items-center gap-1">
          <Button variant="ghost" size="icon" className="size-7" disabled={!contacts || contactIndex === 0} onClick={() => setContactIndex((i) => i - 1)} aria-label="Contact précédent"><ChevronLeft /></Button>
          <span className="max-w-[11rem] truncate text-xs text-muted-foreground" title={contact ? fullName(contact) : ""}>
            {contact ? `${fullName(contact)} · ${contact.sequence_code ?? "sans code"}` : "Aucun contact"}
          </span>
          <Button variant="ghost" size="icon" className="size-7" disabled={!contacts || contactIndex >= (contacts?.length ?? 1) - 1} onClick={() => setContactIndex((i) => i + 1)} aria-label="Contact suivant"><ChevronRight /></Button>
        </div>
      </div>
      {!data ? (
        <div className="p-4"><Skeleton className="h-64" /></div>
      ) : !data.contact ? (
        <p className="p-6 text-sm text-muted-foreground">Importez des contacts pour voir l'aperçu de vos emails.</p>
      ) : (
        <div className="space-y-3 p-4">
          {data.labels.length > 1 && (
            <div className="inline-flex rounded-lg bg-muted p-0.5 text-xs">
              {data.labels.map((l) => (
                <button key={l} onClick={() => setVariant(l)}
                  className={cn("rounded-md px-2.5 py-1 font-medium", data.variant === l ? "bg-card shadow-sm" : "text-muted-foreground")}>Objet {l}</button>
              ))}
            </div>
          )}
          {step && (
            <div className="rounded-lg border">
              <div className="space-y-1 border-b bg-muted/40 px-4 py-3 text-xs">
                <p><span className="text-muted-foreground">À </span>{data.contact.email}</p>
                <p className="text-sm font-semibold">{step.subject || <span className="font-normal italic text-muted-foreground">(sans objet)</span>}</p>
                {step.planned_at && <p className="text-muted-foreground">Prévu {formatDayTime(step.planned_at)}</p>}
              </div>
              <pre className="max-h-[420px] overflow-y-auto whitespace-pre-wrap px-4 py-3 font-sans text-sm leading-relaxed">{step.body}</pre>
            </div>
          )}
          {allProblems.length > 0 ? (
            <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs">
              <p className="mb-1 flex items-center gap-1.5 font-medium text-destructive"><AlertCircle className="size-3.5" />{allProblems.length} problème{allProblems.length > 1 ? "s" : ""} pour ce contact</p>
              <ul className="space-y-0.5 text-muted-foreground">{allProblems.slice(0, 6).map((p) => <li key={p}>• {p}</li>)}</ul>
            </div>
          ) : (
            <p className="flex items-center gap-1.5 text-xs text-success"><CheckCircle2 className="size-3.5" />Toutes les variables sont résolues pour ce contact</p>
          )}
          {step?.warnings.map((w) => <p key={w} className="text-xs text-warning">{w}</p>)}
          <Button variant="outline" size="sm" className="w-full" disabled={send.isPending} onClick={() => send.mutate()}>
            <Send /> M'envoyer les {data.steps.length} emails
          </Button>
        </div>
      )}
    </Card>
  );
}
