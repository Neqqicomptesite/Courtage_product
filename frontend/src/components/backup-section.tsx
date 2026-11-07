// V2.20 : sauvegardes de la base, et copie dans un second dossier (Google Drive, OneDrive…)
// pour ne rien perdre si le PC tombe en panne.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, HardDrive, Loader2, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Field, toastError } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { formatDayTime } from "@/lib/format";

const LABELS: Record<string, string> = {
  demarrage: "au démarrage", quotidienne: "quotidienne", manuelle: "manuelle",
  "avant-mise-a-jour": "avant une mise à jour", avant_restauration: "avant une restauration",
};

export function BackupSection() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["backups"], queryFn: api.backups });
  const [dir, setDir] = useState("");
  useEffect(() => { if (data) setDir(data.copy_dir); }, [data?.copy_dir]); // eslint-disable-line react-hooks/exhaustive-deps
  const now = useMutation({
    mutationFn: api.backupNow,
    onSuccess: (r) => { qc.setQueryData(["backups"], r); toast.success("Sauvegarde faite"); },
    onError: (e) => toastError(e),
  });
  const save = useMutation({
    mutationFn: () => api.backupCopyDir(dir),
    onSuccess: (r) => { qc.setQueryData(["backups"], r); toast.success(r.copy_dir ? "Copie activée : première sauvegarde copiée" : "Copie désactivée"); },
    onError: (e) => toastError(e, "Dossier refusé"),
  });
  const items = data?.items ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Sauvegardes</CardTitle>
        <CardDescription>Votre base (contacts, campagnes, historique, réglages) est sauvegardée à chaque démarrage et chaque jour. On garde les 10 dernières et une par jour sur 30 jours.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" onClick={() => now.mutate()} disabled={now.isPending}>
            {now.isPending ? <Loader2 className="animate-spin" /> : <Save />} Sauvegarder maintenant
          </Button>
          {items[0] && <span className="text-xs text-muted-foreground">Dernière : {formatDayTime(items[0].date)} ({LABELS[items[0].label] ?? items[0].label}) · {items.length} sauvegardes sur ce PC</span>}
        </div>

        <Field label="Copier aussi chaque sauvegarde dans ce dossier"
          hint="Conseillé : un dossier synchronisé (Google Drive pour ordinateur, OneDrive…), pour ne rien perdre si ce PC tombe en panne. Collez le chemin complet, par exemple G:\Mon Drive\ODDO-sauvegardes. Laisser vide pour désactiver.">
          <div className="flex gap-2">
            <Input value={dir} onChange={(e) => setDir(e.target.value)} placeholder="G:\Mon Drive\ODDO-sauvegardes" />
            <Button variant="outline" onClick={() => save.mutate()} disabled={save.isPending || dir === (data?.copy_dir ?? "")}>Enregistrer</Button>
          </div>
        </Field>
        {data?.copy_dir && (data.copy_dir_ok
          ? <p className="flex items-center gap-2 text-sm text-success"><CheckCircle2 className="size-4" />{data.copies} sauvegarde(s) copiée(s) dans ce dossier.</p>
          : <p className="text-sm text-destructive">Ce dossier est introuvable sur ce PC : les sauvegardes n'y sont plus copiées.</p>)}

        <div className="space-y-1 border-t pt-4">
          <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground"><HardDrive className="size-3.5" />Sur ce PC (dossier data\backups)</p>
          <div className="max-h-56 overflow-y-auto text-sm">
            {items.slice(0, 40).map((b) => (
              <div key={b.name} className="flex justify-between gap-3 border-b py-1.5 last:border-0">
                <span>{formatDayTime(b.date)}</span>
                <span className="text-muted-foreground">{LABELS[b.label] ?? b.label} · {Math.round(b.size / 1024)} Ko</span>
              </div>
            ))}
          </div>
          <p className="pt-2 text-xs text-muted-foreground">Pour revenir à une sauvegarde : fermez la fenêtre noire puis lancez restaurer_sauvegarde.bat.</p>
        </div>
      </CardContent>
    </Card>
  );
}
