import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AtSign, Fingerprint, Globe, Plus, ShieldOff, Trash2 } from "lucide-react";
import { useState } from "react";

import { toast } from "sonner";

import { EmptyState, PageHeader, toastError, BackButton } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { formatDayTime } from "@/lib/format";

const ICON = { email: AtSign, domain: Globe, hash: Fingerprint };

export function ExclusionsPage() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["exclusions"], queryFn: api.exclusions });
  const [entry, setEntry] = useState("");
  const [note, setNote] = useState("");
  const add = useMutation({
    mutationFn: () => api.exclusionAdd(entry, note),
    onSuccess: (r) => {
      toast.success(r.added ? `${r.entry} ajouté à la liste` : `${r.entry} était déjà exclu`,
        { description: r.affected ? `${r.affected} contact${r.affected > 1 ? "s" : ""} passé${r.affected > 1 ? "s" : ""} en « Ne plus contacter ».` : undefined });
      setEntry(""); setNote("");
      qc.invalidateQueries();
    },
    onError: (e) => toastError(e),
  });
  const remove = useMutation({
    mutationFn: api.exclusionDelete,
    onSuccess: () => { toast.success("Retiré de la liste"); qc.invalidateQueries({ queryKey: ["exclusions"] }); },
    onError: (e) => toastError(e),
  });

  return (
    <>
      <PageHeader back={<BackButton to="/contacts" label="Contacts" />}
        title="Liste d'exclusion" description="Ces adresses et domaines ne recevront jamais d'email, même s'ils sont réimportés." />
      <Card className="mb-5 p-4">
        <form className="flex flex-col gap-2 sm:flex-row" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
          <Input value={entry} onChange={(e) => setEntry(e.target.value)} placeholder="nom@entreprise.ma ou entreprise.ma" className="sm:flex-[2]" />
          <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Raison (facultatif) : client existant, concurrent…" className="sm:flex-[3]" />
          <Button type="submit" disabled={!entry.trim() || add.isPending}><Plus /> Exclure</Button>
        </form>
      </Card>
      {!data ? <Skeleton className="h-64 rounded-xl" /> : data.length === 0 ? (
        <EmptyState icon={ShieldOff} title="Liste vide" text="Les demandes STOP et les effacements s'y ajoutent automatiquement. Ajoutez vos clients existants pour ne jamais les prospecter." />
      ) : (
        <Card className="divide-y">
          {data.map((x) => {
            const Icon = ICON[x.kind];
            return (
              <div key={x.id} className="flex items-center gap-3 px-4 py-3 text-sm">
                <Icon className="size-4 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{x.kind === "hash" ? "Contact effacé (empreinte)" : x.value}</p>
                  <p className="truncate text-xs text-muted-foreground">{x.reason} · {formatDayTime(x.created_at)}</p>
                </div>
                {x.removable && <Button variant="ghost" size="icon" className="size-8" aria-label="Retirer" onClick={() => remove.mutate(x.id)}><Trash2 /></Button>}
              </div>
            );
          })}
        </Card>
      )}
    </>
  );
}
