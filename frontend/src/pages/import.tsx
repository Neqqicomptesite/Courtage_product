import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, ArrowRight, CheckCircle2, Download, FileSpreadsheet, Loader2, RefreshCw, Rocket, ShieldOff, Upload, UserPlus } from "lucide-react";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { PageHeader, toastError, BackButton } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/select";
import { api, type ImportColumns, type ImportDone, type ImportPreview, type ImportRow } from "@/lib/api";
import { cn } from "@/lib/utils";

export function ImportPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [cols, setCols] = useState<ImportColumns | null>(null);
  const [mapping, setMapping] = useState<string[]>([]);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [done, setDone] = useState<ImportDone | null>(null);

  const load = (c: ImportColumns) => { setCols(c); setMapping(c.columns.map((x) => x.mapping)); setPreview(null); };
  const upload = useMutation({ mutationFn: api.importUpload, onSuccess: load, onError: (e) => toastError(e, "Import impossible") });
  const sheet = useMutation({ mutationFn: (s: string) => api.importColumns(cols!.token, s), onSuccess: load, onError: (e) => toastError(e) });
  const check = useMutation({ mutationFn: () => api.importPreview(cols!.token, cols!.sheet, mapping), onSuccess: setPreview, onError: (e) => toastError(e, "Correspondance à revoir") });
  const commit = useMutation({
    mutationFn: () => api.importCommit(cols!.token, cols!.sheet, mapping),
    onSuccess: (r) => { setDone(r); qc.invalidateQueries(); },
    onError: (e) => toastError(e, "Import impossible"),
  });
  const reset = () => { if (cols) api.importCancel(cols.token).catch(() => undefined); setCols(null); setPreview(null); setDone(null); };
  const pick = (f?: File | null) => f && upload.mutate(f);
  const stage = done ? 3 : preview ? 2 : cols ? 1 : 0;

  return (
    <>
      <PageHeader back={<BackButton to="/contacts" label="Contacts" />}
        title="Importer des contacts" description="Un fichier Excel ou CSV. Rien n'est enregistré avant votre confirmation." />

      <ol className="mb-6 flex items-center gap-2 text-sm">
        {["Fichier", "Colonnes", "Vérification"].map((l, i) => (
          <li key={l} className="flex flex-1 items-center gap-2 last:flex-none">
            <span className={cn("flex size-6 items-center justify-center rounded-full border text-xs font-semibold",
              i < stage ? "border-primary bg-primary text-primary-foreground" : i === stage ? "border-primary text-primary" : "text-muted-foreground")}>
              {i < stage ? <CheckCircle2 className="size-3.5" /> : i + 1}
            </span>
            <span className={cn("hidden sm:inline", i === stage ? "font-medium" : "text-muted-foreground")}>{l}</span>
            {i < 2 && <span className={cn("h-px flex-1", i < stage ? "bg-primary/40" : "bg-border")} />}
          </li>
        ))}
      </ol>

      {stage === 0 && (
        <button
          onClick={() => input.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]); }}
          className={cn("flex w-full flex-col items-center gap-3 rounded-2xl border-2 border-dashed px-6 py-16 text-center transition-colors",
            drag ? "border-primary bg-accent/60" : "hover:border-primary/50 hover:bg-accent/30")}>
          {upload.isPending ? <Loader2 className="size-8 animate-spin text-primary" /> : <Upload className="size-8 text-primary" />}
          <span className="font-medium">Glissez votre fichier ici, ou cliquez pour le choisir</span>
          <span className="text-sm text-muted-foreground">.xlsx ou .csv, 10 Mo maximum. Les colonnes sont reconnues automatiquement.</span>
          <input ref={input} type="file" accept=".xlsx,.xlsm,.csv" className="hidden" onChange={(e) => pick(e.target.files?.[0])} />
        </button>
      )}
      {stage === 0 && (
        <a href="/api/contacts/template" download className="mt-4 flex items-center gap-3 rounded-xl border p-4 text-sm transition-colors hover:bg-accent/40">
          <FileSpreadsheet className="size-5 shrink-0 text-brand" />
          <span className="flex-1"><span className="font-medium">Pas encore de fichier ?</span> <span className="text-muted-foreground">Téléchargez le modèle Excel : listes déroulantes, profil (fonction × secteur) calculé tout seul, et il s'importe sans aucun réglage.</span></span>
          <Download className="size-4 text-muted-foreground" />
        </a>
      )}

      {stage === 1 && cols && (
        <Card>
          <CardHeader className="flex-row flex-wrap items-center justify-between gap-3 space-y-0">
            <CardTitle className="flex items-center gap-2"><FileSpreadsheet className="size-4 text-brand" />{cols.filename}
              <span className="text-sm font-normal text-muted-foreground">· {cols.rows} lignes</span></CardTitle>
            {cols.sheets.length > 1 && (
              <NativeSelect className="h-8 w-auto text-xs" value={cols.sheet ?? ""} onChange={(e) => sheet.mutate(e.target.value)}>
                {cols.sheets.map((s) => <option key={s}>{s}</option>)}
              </NativeSelect>
            )}
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">Vérifiez à quoi correspond chaque colonne. Une colonne inconnue devient un <b>champ personnalisé</b>, utilisable dans vos emails.</p>
            <div className="divide-y rounded-xl border">
              {cols.columns.map((c, i) => (
                <div key={c.index} className="grid items-center gap-2 p-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_15rem]">
                  <span className="truncate text-sm font-medium">{c.header || `Colonne ${i + 1}`}</span>
                  <span className="truncate text-xs text-muted-foreground">{c.samples.join(" · ") || "vide"}</span>
                  <NativeSelect className={cn("h-8 text-xs", mapping[i] === "ignore" && "text-muted-foreground")} value={mapping[i]}
                    onChange={(e) => setMapping((m) => m.map((x, j) => (j === i ? e.target.value : x)))}>
                    {cols.fields.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
                    <option value={c.custom}>Champ personnalisé</option>
                    <option value="ignore">Ignorer cette colonne</option>
                  </NativeSelect>
                </div>
              ))}
            </div>
            <div className="flex justify-between">
              <Button variant="outline" onClick={reset}>Changer de fichier</Button>
              <Button onClick={() => check.mutate()} disabled={check.isPending}>{check.isPending && <Loader2 className="animate-spin" />}Vérifier <ArrowRight /></Button>
            </div>
          </CardContent>
        </Card>
      )}

      {stage === 2 && preview && (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <Stat icon={UserPlus} label="Nouveaux contacts" value={preview.new} tone="text-brand" />
            <Stat icon={RefreshCw} label="Mis à jour" value={preview.update} tone="text-primary" />
            <Stat icon={ShieldOff} label="Ignorés" value={preview.ignored.length + preview.suppressed.length} tone="text-muted-foreground" />
          </div>
          <RowList title="Lignes ignorées" rows={preview.ignored} />
          <RowList title="Adresses bloquées (STOP, effacement, exclusion)" rows={preview.suppressed} />
          <RowList title="Avertissements (importées quand même)" rows={preview.warnings} warn />
          <div className="flex justify-between">
            <Button variant="outline" onClick={() => setPreview(null)}><ArrowLeft /> Colonnes</Button>
            <Button variant="brand" disabled={commit.isPending || preview.new + preview.update === 0} onClick={() => commit.mutate()}>
              {commit.isPending && <Loader2 className="animate-spin" />}Importer {preview.new + preview.update} contacts
            </Button>
          </div>
        </div>
      )}

      {stage === 3 && done && (
        <Card className="flex flex-col items-center gap-3 p-10 text-center">
          <CheckCircle2 className="size-10 text-success" />
          <p className="text-lg font-semibold">Import terminé</p>
          <p className="text-sm text-muted-foreground">{done.new} ajoutés · {done.update} mis à jour · {done.ignore} ignorés</p>
          {/* V3.6 : les contacts du fichier sont dans une liste : on propose d'enchaîner sur une campagne */}
          {done.list && done.list.prospects > 0 && (
            <div className="mt-3 w-full max-w-lg rounded-xl border bg-accent/40 p-4 text-left">
              <p className="font-medium">Lancer une séquence pour ces {done.list.prospects} prospect{done.list.prospects > 1 ? "s" : ""} ?</p>
              <p className="mt-1 text-sm text-muted-foreground">Ils sont rangés dans la liste « {done.list.name} »{done.list.lot ? <>, <b className="text-foreground">lot {done.list.lot}</b>{done.list.lot >= 2 ? ` (ils recevront les variantes ${done.list.lot} de vos textes, ex. FIN${done.list.lot})` : " (textes d'origine)"}</> : null}. Vous choisirez la séquence, puis vous vérifierez les emails avant le départ.</p>
              <Button variant="brand" className="mt-3" onClick={() => navigate(`/campaigns/new?list_id=${done.list!.id}`)}><Rocket /> Créer une campagne pour eux</Button>
            </div>
          )}
          <div className="mt-2 flex flex-wrap justify-center gap-2">
            <Button variant="outline" onClick={reset}>Importer un autre fichier</Button>
            {done.list && <Button variant="outline" onClick={() => navigate(`/contacts?list_id=${done.list!.id}`)}>Voir la liste</Button>}
            <Button variant={done.list?.prospects ? "outline" : "default"} onClick={() => navigate("/contacts")}>Voir les contacts</Button>
          </div>
        </Card>
      )}
    </>
  );
}

function Stat({ icon: Icon, label, value, tone }: { icon: typeof UserPlus; label: string; value: number; tone: string }) {
  return (
    <Card className="flex items-center gap-3 p-4">
      <Icon className={cn("size-5", tone)} />
      <div><p className="text-xl font-semibold tabular">{value}</p><p className="text-xs text-muted-foreground">{label}</p></div>
    </Card>
  );
}

function RowList({ title, rows, warn }: { title: string; rows: ImportRow[]; warn?: boolean }) {
  if (!rows.length) return null;
  return (
    <details className="rounded-xl border bg-card p-4 text-sm" open={rows.length <= 5}>
      <summary className="flex cursor-pointer items-center gap-2 font-medium">
        {warn && <AlertTriangle className="size-4 text-warning" />}{title} <Badge variant="secondary">{rows.length}</Badge>
      </summary>
      <ul className="mt-3 max-h-60 space-y-1 overflow-y-auto text-xs text-muted-foreground">
        {rows.map((r) => <li key={r.row + (r.email ?? "")}>Ligne {r.row} · {r.email ?? "sans email"} : {r.reason || r.warnings.join(", ")}</li>)}
      </ul>
    </details>
  );
}
