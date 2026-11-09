import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Copy, FileText, ListOrdered, Lock, MoreHorizontal, Pencil, Plus, Send, Trash2, Users } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { ConfirmDialog, EmptyState, PageHeader, toastError } from "@/components/common";
import { openSendSequence } from "@/components/send-sequence";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type SequenceCategory } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useMe } from "@/pages/login";

export const CATEGORIES: { value: SequenceCategory; label: string; hint: string }[] = [
  { value: "prospection", label: "Prospection", hint: "Pour les prospects uniquement : clients, assureurs et partenaires ne la reçoivent jamais." },
  { value: "gestion", label: "Gestion", hint: "Pour vos clients, assureurs et partenaires (renouvellements, pièces à fournir…)." },
  { value: "souscription", label: "Souscription", hint: "Pour vos échanges de souscription avec clients et assureurs." },
];

/** V3 : branches des demandes de cotation (sous-onglets de Souscription), dans cet ordre. */
export const BRANCHES = ["Flotte", "Accidents du travail", "Prévoyance", "Retraite", "RC professionnelle", "RC exploitation",
  "Multirisque", "Multirisque habitation", "Transport", "Tous risques chantier"];

export function SequencesPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data } = useQuery({ queryKey: ["sequences"], queryFn: api.sequences });
  const [params, setParams] = useSearchParams();
  const type = (params.get("type") as SequenceCategory | null) ?? "prospection";
  const setType = (t: SequenceCategory) => setParams((p) => { const n = new URLSearchParams(p); n.set("type", t); return n; }, { replace: true });
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [newType, setNewType] = useState<SequenceCategory>("prospection");
  const [single, setSingle] = useState(false);  // V2.23 : un seul email = un modèle réutilisable
  const branch = params.get("branche");
  const setBranch = (b: string | null) => setParams((p) => { const n = new URLSearchParams(p); if (b) n.set("branche", b); else n.delete("branche"); return n; }, { replace: true });
  const ofType = (data?.items ?? []).filter((q) => (q.category ?? "prospection") === type);
  const branchesHere = [...BRANCHES.filter((b) => ofType.some((q) => q.branch === b)),
    ...[...new Set(ofType.map((q) => q.branch).filter((b): b is string => !!b && !BRANCHES.includes(b)))].sort()];
  const hasOther = ofType.some((q) => !q.branch);
  const items = type !== "souscription" || !branch ? ofType : ofType.filter((q) => (branch === "autres" ? !q.branch : q.branch === branch));
  const count = (t: SequenceCategory) => (data?.items ?? []).filter((q) => (q.category ?? "prospection") === t).length;
  const startCreate = () => { setNewType(type); setName(""); setSingle(false); setCreating(true); };
  const [toDelete, setToDelete] = useState<{ id: number; name: string } | null>(null);

  const create = useMutation({
    mutationFn: () => api.sequenceCreate(name.trim() || "Nouvelle séquence", newType, single ? 1 : 3),
    onSuccess: ({ id }) => navigate(`/sequences/${id}`),
    onError: (e) => toastError(e),
  });
  // V3 : une séquence créée par un employé n'est visible que par lui ; l'administrateur peut
  // rendre commune une des siennes.
  const me = useMe();
  const team = !!me?.server_mode;
  const [toShare, setToShare] = useState<number | null>(null);
  const share = useMutation({
    mutationFn: api.sequenceShare,
    onSuccess: () => { toast.success("Séquence partagée : toute l'équipe la voit maintenant"); qc.invalidateQueries({ queryKey: ["sequences"] }); },
    onError: (e) => toastError(e),
  });
  const duplicate = useMutation({
    mutationFn: api.sequenceDuplicate,
    onSuccess: ({ id }) => {
      toast.success("Séquence dupliquée");
      navigate(`/sequences/${id}`);
    },
    onError: (e) => toastError(e),
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.sequenceDelete(id),
    onSuccess: () => {
      setToDelete(null);
      qc.invalidateQueries({ queryKey: ["sequences"] });
      toast.success("Séquence supprimée");
    },
    onError: (e) => toastError(e),
  });

  return (
    <>
      <PageHeader
        title="Séquences"
        description="Un premier email puis des relances, rédigés une fois pour toutes les fonctions et tous les secteurs."
        actions={
          <>
            <Button variant="outline" asChild><Link to="/sequences/blocks"><FileText /> Textes personnalisés</Link></Button>
            <Button onClick={startCreate}><Plus /> Nouvelle séquence</Button>
          </>
        }
      />

      {data && data.todo_blocks.length > 0 && (
        <Link to="/sequences/blocks" className="mb-5 flex items-center gap-3 rounded-xl border border-warning/40 bg-warning/5 p-4 text-sm transition-colors hover:bg-warning/10">
          <AlertTriangle className="size-4 shrink-0 text-warning" />
          <span className="flex-1">
            <span className="font-medium">{data.todo_blocks.length} texte{data.todo_blocks.length > 1 ? "s" : ""} personnalisé{data.todo_blocks.length > 1 ? "s" : ""} encore à rédiger</span>
            <span className="text-muted-foreground"> ({data.todo_blocks.join(", ")}). Une campagne qui les utilise ne pourra pas démarrer.</span>
          </span>
          <ArrowRight className="size-4 text-muted-foreground" />
        </Link>
      )}

      <div className="mb-5 flex gap-1 overflow-x-auto rounded-xl border bg-card p-1">
        {CATEGORIES.map((c) => (
          <button key={c.value} onClick={() => setType(c.value)}
            className={cn("flex-1 shrink-0 rounded-lg px-4 py-2 text-sm transition-colors", type === c.value ? "bg-primary font-medium text-primary-foreground shadow-sm" : "text-muted-foreground hover:bg-accent")}>
            {c.label} <span className="ml-1 text-xs tabular opacity-80">{count(c.value)}</span>
          </button>
        ))}
      </div>
      <p className="-mt-2 mb-5 text-sm text-muted-foreground">{CATEGORIES.find((c) => c.value === type)?.hint}</p>
      {type === "souscription" && branchesHere.length > 0 && (
        <div className="-mt-2 mb-5 flex flex-wrap gap-1.5" role="tablist" aria-label="Branches">
          {[{ key: null as string | null, label: "Toutes" }, ...branchesHere.map((b) => ({ key: b, label: b })), ...(hasOther ? [{ key: "autres", label: "Autres" }] : [])].map((b) => (
            <button key={b.key ?? "all"} role="tab" aria-selected={branch === b.key} onClick={() => setBranch(b.key)}
              className={cn("rounded-full border px-3 py-1 text-xs transition-colors", branch === b.key ? "border-primary bg-primary/10 font-medium text-primary" : "text-muted-foreground hover:bg-accent")}>
              {b.label}
            </button>
          ))}
        </div>
      )}

      {!data ? (
        <div className="grid gap-4 md:grid-cols-2">{[0, 1].map((i) => <Skeleton key={i} className="h-36 rounded-xl" />)}</div>
      ) : items.length === 0 ? (
        <EmptyState icon={ListOrdered} title={`Aucune séquence de ${CATEGORIES.find((c) => c.value === type)?.label.toLowerCase()}`} text="Créez-en une : 3 étapes sont préparées pour vous."
          action={<Button onClick={startCreate}><Plus /> Nouvelle séquence</Button>} />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {items.map((q) => (
            <Card key={q.id} className="flex flex-col p-4 transition-all hover:border-primary/40 hover:shadow-md">
              <div className="flex items-start justify-between gap-2">
                <Link to={`/sequences/${q.id}`} className="font-medium leading-snug hover:text-primary">{q.name}</Link>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon" className="-mr-2 -mt-1 size-8" aria-label="Actions"><MoreHorizontal /></Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onSelect={() => duplicate.mutate(q.id)}><Copy /> Dupliquer</DropdownMenuItem>
                    {team && me?.role === "admin" && q.shared === false && q.editable && (
                      <DropdownMenuItem onSelect={() => setToShare(q.id)}><Users /> Partager avec l'équipe</DropdownMenuItem>
                    )}
                    <DropdownMenuSeparator />
                    <DropdownMenuItem destructive disabled={q.campaigns > 0 || q.editable === false} onSelect={() => setToDelete(q)}><Trash2 /> Supprimer</DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
              {/* Mini-frise : un point par étape */}
              <div className="my-5 flex items-center">
                {Array.from({ length: q.steps }).map((_, i) => (
                  <div key={i} className="flex flex-1 items-center last:flex-none">
                    <span className="flex size-6 items-center justify-center rounded-full border-2 border-primary/30 bg-accent text-[11px] font-semibold text-accent-foreground">{i + 1}</span>
                    {i < q.steps - 1 && <span className="h-0.5 flex-1 bg-gradient-to-r from-primary/30 to-primary/10" />}
                  </div>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                {team && (q.shared
                  ? <Badge variant="outline" className="font-normal" title="Modèle commun à toute l'équipe"><Users className="size-3" /> Équipe</Badge>
                  : <Badge variant="info" className="font-normal" title="Vos collègues ne la voient pas"><Lock className="size-3" /> Perso</Badge>)}
                <Badge variant="secondary">{q.steps} email{q.steps > 1 ? "s" : ""}</Badge>
                <Badge variant="secondary">{q.total_days} jours</Badge>
                {q.campaigns > 0 ? <Badge variant="info">{q.campaigns} campagne{q.campaigns > 1 ? "s" : ""}</Badge> : <span>Pas encore utilisée</span>}
              </div>
              <div className="mt-auto grid grid-cols-2 gap-2 pt-4">
                <Button variant="outline" size="sm" asChild><Link to={`/sequences/${q.id}`}><Pencil /> Modifier</Link></Button>
                <Button size="sm" onClick={() => openSendSequence({ sequenceId: q.id })}><Send /> Envoyer</Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent>
          <DialogHeader><DialogTitle>Nouvelle séquence</DialogTitle></DialogHeader>
          <form onSubmit={(e) => { e.preventDefault(); create.mutate(); }} className="space-y-4">
            <Input autoFocus value={name} onChange={(e) => setName(e.target.value)}
              placeholder={newType === "prospection" ? "ex. Prospection DAF – industrie" : newType === "gestion" ? "ex. Renouvellement des contrats flotte" : "ex. Suivi des demandes de cotation"} />
            <div className="space-y-1.5">
              <span className="text-sm font-medium">Type</span>
              <div className="grid grid-cols-3 gap-1.5">
                {CATEGORIES.map((c) => (
                  <button type="button" key={c.value} onClick={() => setNewType(c.value)}
                    className={cn("rounded-lg border px-3 py-2 text-sm transition-colors", newType === c.value ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent")}>{c.label}</button>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">{CATEGORIES.find((c) => c.value === newType)?.hint}</p>
            </div>
            <div className="space-y-1.5">
              <span className="text-sm font-medium">Forme</span>
              <div className="grid grid-cols-2 gap-1.5">
                {[{ v: false, l: "Avec relances", h: "3 emails : J0, puis relances à J+3 et J+7 jours ouvrés si pas de réponse." },
                  { v: true, l: "Un seul email", h: "Un modèle à réutiliser : Boîte mail → Nouveau message → Modèles." }].map((o) => (
                  <button type="button" key={o.l} onClick={() => setSingle(o.v)}
                    className={cn("rounded-lg border px-3 py-2 text-sm transition-colors", single === o.v ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent")}>{o.l}</button>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">{single
                ? "Un modèle à réutiliser : Boîte mail → Nouveau message → Modèles. Des relances peuvent s'ajouter plus tard."
                : "3 emails : J0, puis relances à J+3 et J+7 jours ouvrés si pas de réponse. Tout se modifie ensuite."}</p>
            </div>
            {team && <p className="flex items-center gap-1.5 text-xs text-muted-foreground"><Lock className="size-3.5" /> Visible par vous seul : vos collègues ne la verront pas.</p>}
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setCreating(false)}>Annuler</Button>
              <Button type="submit" disabled={create.isPending}>Créer et rédiger</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <ConfirmDialog open={toShare !== null} onOpenChange={(o) => !o && setToShare(null)}
        title="Partager avec l'équipe ?" confirmLabel="Partager"
        description="Toute l'équipe verra cette séquence et pourra l'utiliser. Vous seul (administrateur) pourrez encore la modifier. Ce partage ne se retire pas : pour une version perso, dupliquez-la."
        onConfirm={() => { if (toShare !== null) share.mutate(toShare); setToShare(null); }} />

      <ConfirmDialog open={!!toDelete} onOpenChange={(o) => !o && setToDelete(null)} destructive
        title={`Supprimer « ${toDelete?.name} » ?`} description="La séquence et ses étapes seront supprimées définitivement."
        confirmLabel="Supprimer" pending={remove.isPending} onConfirm={() => toDelete && remove.mutate(toDelete.id)} />
    </>
  );
}
