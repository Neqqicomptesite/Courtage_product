// V3 : l'équipe (administrateur seulement) : inviter un collègue, changer son rôle, le désactiver.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MailPlus, RotateCw, ShieldCheck, UserPlus, Users } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState, PageHeader, toastError } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { api, type TeamUser } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import { useMe } from "@/pages/login";

export function TeamPage() {
  const me = useMe();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["team"], queryFn: api.team, enabled: me?.role === "admin" });
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<"user" | "admin">("user");

  const invite = useMutation({
    mutationFn: () => api.teamInvite({ email: email.trim(), full_name: name.trim(), role }),
    onSuccess: (u) => {
      if (u.invite_error) toast.warning("Compte créé, mais l'email d'invitation n'est pas parti", { description: u.invite_error });
      else toast.success(`Invitation envoyée à ${u.email}`, { description: "Le lien reçu par email lui permet de choisir son mot de passe." });
      setEmail(""); setName(""); setRole("user");
      qc.invalidateQueries({ queryKey: ["team"] });
    },
    onError: (e) => toastError(e, "Invitation impossible"),
  });

  if (me?.role !== "admin") {
    return <EmptyState icon={ShieldCheck} title="Réservé à l'administrateur" text="Demandez à l'administrateur d'ODDO Séquences pour inviter un collègue." />;
  }

  return (
    <>
      <PageHeader title="Équipe" description="Chaque collègue a son compte, sa boîte mail et ses campagnes. Les compagnies d'assurance et les contacts sont communs ; un prospect est suivi par un seul employé." />
      <Card className="mb-5 p-4">
        <form className="grid gap-2 sm:grid-cols-[2fr_2fr_1fr_auto]" onSubmit={(e) => { e.preventDefault(); invite.mutate(); }}>
          <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="prenom.nom@oddo.ma" aria-label="Email" />
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Prénom Nom" aria-label="Nom" />
          <NativeSelect value={role} onChange={(e) => setRole(e.target.value as "user" | "admin")} aria-label="Rôle">
            <option value="user">Employé</option>
            <option value="admin">Administrateur</option>
          </NativeSelect>
          <Button type="submit" disabled={!email.trim() || invite.isPending}><UserPlus /> Inviter</Button>
        </form>
      </Card>
      {!data ? <Skeleton className="h-48 rounded-xl" /> : data.length === 0 ? (
        <EmptyState icon={Users} title="Personne pour l'instant" text="Invitez un premier collègue avec le formulaire ci-dessus." />
      ) : (
        <Card className="divide-y">
          {data.map((u) => <Row key={u.id} u={u} self={me.server_mode && u.id === me.id} />)}
        </Card>
      )}
    </>
  );
}

function Row({ u, self }: { u: TeamUser; self: boolean }) {
  const qc = useQueryClient();
  const patch = useMutation({
    mutationFn: (body: { role?: "admin" | "user"; active?: boolean }) => api.teamUpdate(u.id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["team"] }),
    onError: (e) => toastError(e),
  });
  const resend = useMutation({
    mutationFn: () => api.teamResend(u.id),
    onSuccess: (r) => r.invite_error ? toast.warning("Email non envoyé", { description: r.invite_error }) : toast.success(`Nouveau lien envoyé à ${u.email}`),
    onError: (e) => toastError(e),
  });
  return (
    <div className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-2 truncate font-medium">
          {u.full_name || u.email}
          {self && <Badge variant="secondary">Vous</Badge>}
          {!u.active && <Badge variant="destructive">Désactivé</Badge>}
          {u.active && !u.linked && <Badge variant="warning">Invitation en attente</Badge>}
        </p>
        <p className="truncate text-xs text-muted-foreground">
          {u.email} · {u.mailbox ? `boîte ${u.mailbox}` : "boîte mail pas encore réglée"} · {u.contacts} contact{u.contacts > 1 ? "s" : ""}
          {u.last_seen_at && ` · vu ${relativeTime(u.last_seen_at)}`}
        </p>
      </div>
      {!u.linked && u.active && (
        <Button variant="outline" size="sm" onClick={() => resend.mutate()} disabled={resend.isPending}>
          {resend.isPending ? <RotateCw className="animate-spin" /> : <MailPlus />} Renvoyer le lien
        </Button>
      )}
      <NativeSelect className="h-8 w-40" value={u.role} disabled={self || patch.isPending} aria-label={`Rôle de ${u.email}`}
        onChange={(e) => patch.mutate({ role: e.target.value as "user" | "admin" })}>
        <option value="user">Employé</option>
        <option value="admin">Administrateur</option>
      </NativeSelect>
      <label className="flex items-center gap-2 text-xs text-muted-foreground">
        <Switch checked={u.active} disabled={self || patch.isPending} onCheckedChange={(v) => patch.mutate({ active: v })} aria-label={`Compte actif : ${u.email}`} />
        Actif
      </label>
    </div>
  );
}
