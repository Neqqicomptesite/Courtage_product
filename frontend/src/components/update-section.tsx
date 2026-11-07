// V2.17 : mise à jour de l'application depuis le lien du kit (Google Drive d'Omar).
// Vérifier → « Installer et redémarrer » : la base est sauvegardée, le dossier data n'est jamais
// touché, puis l'application se relance seule ; la page se recharge quand la nouvelle version répond.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, Loader2, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog, Field, toastError } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { formatDayTime } from "@/lib/format";

export function UpdateSection() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["update"], queryFn: api.update });
  const [url, setUrl] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [restarting, setRestarting] = useState<string | null>(null);
  useEffect(() => { if (data) setUrl(data.url); }, [data?.url]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: () => api.updateUrl(url),
    onSuccess: (r) => { qc.setQueryData(["update"], r); toast.success("Lien enregistré"); },
    onError: (e) => toastError(e),
  });
  const check = useMutation({
    mutationFn: api.updateCheck,
    onSuccess: (r) => {
      qc.setQueryData(["update"], r);
      qc.invalidateQueries({ queryKey: ["notifications"] });
      if (r.error) toast.error("Vérification impossible", { description: r.error });
      else if (r.newer) toast.success(`Version ${r.available} disponible`);
      else toast.success("Vous avez déjà la dernière version");
    },
    onError: (e) => toastError(e),
  });
  const install = useMutation({
    mutationFn: api.updateInstall,
    onSuccess: (r) => {
      setConfirm(false);
      if (r.restarting) setRestarting(r.version);
      else toast.success(`Version ${r.version} installée`, { description: "Fermez la fenêtre noire puis relancez start.bat." });
    },
    onError: (e) => { setConfirm(false); toastError(e, "Installation impossible"); },
  });

  // Après « Installer et redémarrer » : on attend que la nouvelle version réponde, puis on recharge.
  useEffect(() => {
    if (!restarting) return;
    const id = setInterval(async () => {
      try {
        const s = await api.status();
        if (s.version === restarting) window.location.reload();
      } catch { /* l'application redémarre : pas encore de réponse */ }
    }, 3000);
    return () => clearInterval(id);
  }, [restarting]);

  if (restarting) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 p-10 text-center">
          <Loader2 className="size-6 animate-spin text-primary" />
          <p className="font-medium">Redémarrage avec la version {restarting}…</p>
          <p className="max-w-md text-sm text-muted-foreground">Une nouvelle fenêtre noire s'ouvre : la page se rechargera d'elle-même. Si rien ne se passe au bout d'une minute, relancez start.bat.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Mise à jour</CardTitle>
        <CardDescription>Votre version : <b>{data?.current ?? "…"}</b>. L'application vérifie seule deux fois par jour ; vos données (contacts, emails, réglages) ne bougent jamais.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {data?.newer ? (
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-primary/30 bg-primary/5 p-4">
            <Download className="size-5 text-primary" />
            <p className="flex-1 text-sm"><b>Version {data.available} disponible.</b> Installation en quelques secondes, puis redémarrage automatique.</p>
            <Button onClick={() => setConfirm(true)}><Download /> Installer et redémarrer</Button>
          </div>
        ) : data?.available && !data.error ? (
          <p className="flex items-center gap-2 text-sm text-success"><CheckCircle2 className="size-4" />Vous avez la dernière version.</p>
        ) : null}
        {data?.error && <p className="text-sm text-destructive">{data.error}</p>}
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" onClick={() => check.mutate()} disabled={check.isPending || !data?.url}>
            {check.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />} Vérifier maintenant
          </Button>
          {data?.checked_at && <span className="text-xs text-muted-foreground">Dernière vérification : {formatDayTime(data.checked_at)}</span>}
        </div>
        <Field label="Lien des mises à jour" hint="Le lien de partage Google Drive du kit, déjà réglé : à changer seulement si on vous le demande.">
          <div className="flex gap-2">
            <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://drive.google.com/file/d/…" />
            <Button variant="outline" onClick={() => save.mutate()} disabled={save.isPending || url === (data?.url ?? "")}>Enregistrer</Button>
          </div>
        </Field>
      </CardContent>
      <ConfirmDialog open={confirm} onOpenChange={setConfirm} pending={install.isPending}
        title={`Installer la version ${data?.available ?? ""} ?`}
        description="Votre base est sauvegardée juste avant. L'application s'arrête quelques secondes puis se relance seule : les envois reprennent ensuite normalement."
        confirmLabel="Installer et redémarrer" onConfirm={() => install.mutate()} />
    </Card>
  );
}
