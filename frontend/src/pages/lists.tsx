// V3.6 : listes de contacts. Une liste est personnelle et peut être partagée avec l'équipe.
// Elle se remplit à l'import, depuis Contacts (« Ajouter à une liste ») ou depuis une campagne
// (les sans-réponse), et sert à lancer une campagne sur ces contacts.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ListPlus, ListChecks, MoreHorizontal, Pencil, Rocket, Share2, Lock, Trash2, Upload, UserRoundCheck, Users } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { ConfirmDialog, EmptyState, PageHeader, toastError, BackButton } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type ContactListItem } from "@/lib/api";
import { useMe } from "@/pages/login";

const SOURCE: Record<ContactListItem["source"], string> = { manual: "À la main", import: "Import", campaign: "Campagne" };

/** Demande un nom (nouvelle liste ou renommage). */
export function ListNameDialog({ open, onOpenChange, title, initial = "", confirm, pending, onSubmit, description }: {
  open: boolean; onOpenChange: (v: boolean) => void; title: string; initial?: string; confirm: string; pending?: boolean;
  onSubmit: (name: string) => void; description?: string;
}) {
  const [name, setName] = useState(initial);
  return (
    <Dialog open={open} onOpenChange={(v) => { if (v) setName(initial); onOpenChange(v); }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        <form id="list-name" onSubmit={(e) => { e.preventDefault(); if (name.trim()) onSubmit(name.trim()); }}>
          <Input autoFocus value={name} onChange={(e) => setName(e.target.value)} maxLength={120} placeholder="ex. Salon BTP 2026" aria-label="Nom de la liste" />
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Annuler</Button>
          <Button form="list-name" disabled={!name.trim() || pending}>{confirm}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** « Ajouter à une liste » pour une sélection de contacts (barre d'actions de Contacts). */
export function AddToListMenu({ ids, onDone }: { ids: number[]; onDone?: () => void }) {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["lists"], queryFn: api.lists });
  const [naming, setNaming] = useState(false);
  const done = (msg: string) => { toast.success(msg); qc.invalidateQueries({ queryKey: ["lists"] }); qc.invalidateQueries({ queryKey: ["contacts"] }); onDone?.(); };
  const add = useMutation({
    mutationFn: (l: ContactListItem) => api.listAdd(l.id, ids),
    onSuccess: (r) => done(r.added ? `${r.added} ajouté${r.added > 1 ? "s" : ""} à « ${r.name} »` : `Déjà tous dans « ${r.name} »`),
    onError: (e) => toastError(e),
  });
  const create = useMutation({
    mutationFn: (name: string) => api.listCreate(name, ids),
    onSuccess: (r) => { setNaming(false); done(`Liste « ${r.name} » créée avec ${r.count} contact${r.count > 1 ? "s" : ""}`); },
    onError: (e) => toastError(e),
  });
  const editable = (data?.items ?? []).filter((l) => l.editable);
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild><Button size="sm" variant="outline"><ListPlus /> Ajouter à une liste</Button></DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="max-h-80 w-64 overflow-y-auto">
          <DropdownMenuItem onSelect={() => setNaming(true)}><ListPlus /> Nouvelle liste…</DropdownMenuItem>
          {editable.length > 0 && <DropdownMenuSeparator />}
          {editable.map((l) => (
            <DropdownMenuItem key={l.id} onSelect={() => add.mutate(l)}>
              <span className="min-w-0 flex-1 truncate">{l.name}</span><span className="text-xs text-muted-foreground tabular">{l.count}</span>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      <ListNameDialog open={naming} onOpenChange={setNaming} title="Nouvelle liste" confirm={`Créer avec ${ids.length} contact${ids.length > 1 ? "s" : ""}`}
        pending={create.isPending} onSubmit={(n) => create.mutate(n)} description="Elle est à vous ; vous pourrez la partager avec l'équipe." />
    </>
  );
}

/** V3.8 : confier une liste à un collègue. Il en devient le propriétaire (sa campagne partira de SA
 *  boîte), il est prévenu dans sa cloche et, si vous le laissez coché, par cet email relu ici. */
export function AssignListDialog({ list, open, onOpenChange, onDone }: {
  list: Pick<ContactListItem, "id" | "name" | "count"> | null; open: boolean; onOpenChange: (v: boolean) => void; onDone?: () => void;
}) {
  const me = useMe();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["list-colleagues"], queryFn: api.listColleagues, enabled: open });
  const [uid, setUid] = useState<number | null>(null);
  const [byEmail, setByEmail] = useState(true);
  const [text, setText] = useState("");
  const people = data?.items ?? [];
  const who = people.find((p) => p.id === uid) ?? null;
  const myName = me && me.server_mode ? (me.full_name || me.email).split(" ")[0] : "";
  const draft = (p: typeof who) => list && p ? [
    `Bonjour ${p.name.split(" ")[0]},`, "",
    `Je te confie la liste « ${list.name} » : ${list.count} contact${list.count > 1 ? "s" : ""}, prêts pour une campagne dans Cotalis.`,
    "", "Pour la lancer depuis ta boîte : Contacts → Listes → « Lancer une campagne », ou directement ici :",
    `${window.location.origin}/v2/campaigns/new?list_id=${list.id}`, "", "Merci,", myName,
  ].join("\n") : "";
  const assign = useMutation({
    mutationFn: () => api.listAssign(list!.id, { user_id: uid!, note: text, email: byEmail,
      subject: `${myName ? `${myName} te confie` : "Je te confie"} ${list!.count} contact${list!.count > 1 ? "s" : ""} : « ${list!.name} »` }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["lists"] }); qc.invalidateQueries({ queryKey: ["prospecting"] });
      onOpenChange(false); onDone?.();
      if (r.email_error) toast.warning(`Liste confiée à ${r.assigned_to}, mais l'email n'est pas parti`, { description: r.email_error });
      else toast.success(`Liste confiée à ${r.assigned_to}`, { description: r.email_sent ? "Prévenu(e) par email et dans sa cloche." : "Prévenu(e) dans sa cloche." });
    },
    onError: (e) => toastError(e),
  });
  return (
    <Dialog open={open} onOpenChange={(v) => { if (v) { setUid(null); setText(""); setByEmail(true); } onOpenChange(v); }}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Confier « {list?.name} »</DialogTitle>
          <DialogDescription>
            Le collègue en devient responsable : il la retrouve dans ses Listes et lance la campagne depuis sa propre boîte. Vous la gardez en vue.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="assign-to">À qui ?</Label>
            <NativeSelect id="assign-to" value={uid ?? ""} onChange={(e) => {
              const v = Number(e.target.value) || null; setUid(v);
              const p = people.find((x) => x.id === v) ?? null; setText(draft(p));
            }}>
              <option value="">Choisir un collègue…</option>
              {people.map((p) => <option key={p.id} value={p.id}>{p.name}{p.has_mailbox ? "" : " (boîte mail pas encore branchée)"}</option>)}
            </NativeSelect>
          </div>
          {who && (
            <>
              <label className="flex items-center gap-2 text-sm">
                <Checkbox checked={byEmail} onCheckedChange={(v) => setByEmail(!!v)} />
                Le prévenir aussi par email (envoyé depuis votre boîte, à {who.email})
              </label>
              <div className="space-y-1.5">
                <Label htmlFor="assign-note">{byEmail ? "Votre email (modifiable)" : "Un mot pour lui (affiché dans sa cloche)"}</Label>
                <Textarea id="assign-note" rows={9} value={text} onChange={(e) => setText(e.target.value)} />
              </div>
            </>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Annuler</Button>
          <Button disabled={!uid || assign.isPending || (byEmail && !text.trim())} onClick={() => assign.mutate()}>
            <UserRoundCheck /> Confier{who ? ` à ${who.name.split(" ")[0]}` : ""}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ListsPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data } = useQuery({ queryKey: ["lists"], queryFn: api.lists });
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState<ContactListItem | null>(null);
  const [deleting, setDeleting] = useState<ContactListItem | null>(null);
  const [assigning, setAssigning] = useState<ContactListItem | null>(null);
  const me = useMe();
  const team = !!me?.server_mode;
  const refresh = () => qc.invalidateQueries({ queryKey: ["lists"] });
  const create = useMutation({ mutationFn: (n: string) => api.listCreate(n), onSuccess: () => { setCreating(false); refresh(); toast.success("Liste créée : ajoutez-y des contacts depuis Contacts"); }, onError: (e) => toastError(e) });
  const rename = useMutation({ mutationFn: ({ id, name }: { id: number; name: string }) => api.listRename(id, name), onSuccess: () => { setRenaming(null); refresh(); }, onError: (e) => toastError(e) });
  const share = useMutation({
    mutationFn: (l: ContactListItem) => api.listShare(l.id, !l.shared),
    onSuccess: (l) => { refresh(); toast.success(l.shared ? "Liste partagée : toute l'équipe peut s'en servir" : "Liste repassée en perso"); },
    onError: (e) => toastError(e),
  });
  const remove = useMutation({ mutationFn: (id: number) => api.listDelete(id), onSuccess: () => { setDeleting(null); refresh(); toast.success("Liste supprimée (les contacts restent)"); }, onError: (e) => toastError(e) });

  return (
    <>
      <PageHeader title="Listes" back={<BackButton to="/contacts" label="Contacts" />}
        description="Des groupes de contacts à votre nom (un fichier importé, un salon, une sélection…), pour lancer une campagne sur eux."
        actions={<Button onClick={() => setCreating(true)}><ListPlus /> Nouvelle liste</Button>} />
      {!data ? <Skeleton className="h-64 rounded-xl" /> : data.items.length === 0 ? (
        <EmptyState icon={ListChecks} title="Aucune liste pour l'instant"
          text={<>Une liste se crée toute seule à chaque import. Vous pouvez aussi sélectionner des contacts puis « Ajouter à une liste ».</>}
          action={<div className="flex flex-wrap justify-center gap-2">
            <Button asChild><Link to="/contacts/import"><Upload /> Importer un fichier</Link></Button>
            <Button variant="outline" asChild><Link to="/contacts"><Users /> Choisir des contacts</Link></Button>
          </div>} />
      ) : (
        <Card className="divide-y">
          {data.items.map((l) => (
            <div key={l.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-3.5">
              <Link to={`/contacts?list_id=${l.id}`} className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate font-medium hover:underline">{l.name}</span>
                  {l.shared ? <Badge variant="secondary" className="gap-1"><Share2 className="size-3" /> Équipe</Badge>
                    : <Badge variant="outline" className="gap-1"><Lock className="size-3" /> Perso</Badge>}
                  {l.mine && l.assigned_by && <Badge variant="info" className="gap-1"><UserRoundCheck className="size-3" /> Confiée par {l.assigned_by}</Badge>}
                  {l.assigned_by_me && l.owner && <Badge variant="outline" className="gap-1"><UserRoundCheck className="size-3" /> Confiée à {l.owner}</Badge>}
                </div>
                <div className="mt-0.5 text-xs text-muted-foreground">
                  {l.count} contact{l.count > 1 ? "s" : ""} · {SOURCE[l.source]}{!l.mine && l.owner ? ` · de ${l.owner}` : ""}
                  {l.updated_at && ` · mise à jour le ${new Date(l.updated_at).toLocaleDateString("fr-FR")}`}
                </div>
              </Link>
              <Button size="sm" variant="outline" disabled={!l.count} onClick={() => navigate(`/campaigns/new?list_id=${l.id}`)}><Rocket /> Lancer une campagne</Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild><Button size="icon" variant="ghost" aria-label={`Actions pour ${l.name}`}><MoreHorizontal /></Button></DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem asChild><Link to={`/contacts?list_id=${l.id}`}><Users /> Voir les contacts</Link></DropdownMenuItem>
                  {l.editable && <>
                    {team && <DropdownMenuItem onSelect={() => setAssigning(l)}><UserRoundCheck /> Confier à un collègue…</DropdownMenuItem>}
                    <DropdownMenuItem onSelect={() => setRenaming(l)}><Pencil /> Renommer</DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => share.mutate(l)}>{l.shared ? <><Lock /> Repasser en perso</> : <><Share2 /> Partager avec l'équipe</>}</DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem className="text-destructive" onSelect={() => setDeleting(l)}><Trash2 /> Supprimer la liste</DropdownMenuItem>
                  </>}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          ))}
        </Card>
      )}
      <ListNameDialog open={creating} onOpenChange={setCreating} title="Nouvelle liste" confirm="Créer" pending={create.isPending} onSubmit={(n) => create.mutate(n)} />
      <ListNameDialog open={!!renaming} onOpenChange={(v) => !v && setRenaming(null)} title="Renommer la liste" initial={renaming?.name ?? ""}
        confirm="Enregistrer" pending={rename.isPending} onSubmit={(n) => renaming && rename.mutate({ id: renaming.id, name: n })} />
      <AssignListDialog list={assigning} open={!!assigning} onOpenChange={(v) => !v && setAssigning(null)} />
      <ConfirmDialog open={!!deleting} onOpenChange={(v) => !v && setDeleting(null)} destructive title={`Supprimer « ${deleting?.name ?? ""} » ?`}
        description="Seule la liste disparaît : les contacts restent dans l'application." confirmLabel="Supprimer" pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting.id)} />
    </>
  );
}
