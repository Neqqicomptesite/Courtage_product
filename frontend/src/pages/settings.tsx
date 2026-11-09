import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock, DatabaseBackup, Download, FlaskConical, Percent, Loader2, Lock, Mail, Plus, Send, Trash2, XCircle } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { UpdateSection } from "@/components/update-section";
import { BackupSection } from "@/components/backup-section";
import { ConfirmDialog, Field, PageHeader, fieldError, toastError } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { api, type ConnectionReport, type MailboxSettings, type SendingSettings, type Settings } from "@/lib/api";
import { cn } from "@/lib/utils";
import { BranchSettingsSection } from "@/pages/contracts";

const SECTIONS = [
  { key: "mailbox", label: "Boîte mail", icon: Mail },
  { key: "sending", label: "Rythme d'envoi", icon: Clock },
  { key: "test", label: "Mode test", icon: FlaskConical },
  { key: "branches", label: "Taxes et commissions", icon: Percent },
  { key: "backup", label: "Sauvegardes", icon: DatabaseBackup },
  { key: "update", label: "Mise à jour", icon: Download },
] as const;

export function SettingsPage() {
  const [params, setParams] = useSearchParams();
  const section = params.get("s") ?? "mailbox";
  const { data } = useQuery({ queryKey: ["settings"], queryFn: api.settings, staleTime: Infinity });

  return (
    <>
      <PageHeader title="Réglages" />
      <div className="grid gap-6 lg:grid-cols-[13rem_minmax(0,1fr)]">
        <nav className="flex gap-1 overflow-x-auto lg:flex-col">
          {SECTIONS.map((s) => (
            <button key={s.key} onClick={() => setParams({ s: s.key }, { replace: true })}
              className={cn("flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors",
                section === s.key ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-accent/50 hover:text-foreground")}>
              <s.icon className="size-4" />{s.label}
            </button>
          ))}
        </nav>
        <div className="min-w-0">
          {!data ? <Skeleton className="h-[480px] rounded-xl" /> :
            section === "sending" ? <SendingForm key="s" s={data} /> :
            section === "test" ? <TestMode s={data} /> :
            section === "update" ? <UpdateSection /> :
            section === "branches" ? <BranchSettingsSection /> :
            section === "backup" ? <BackupSection /> : <MailboxForm key="m" s={data} />}
        </div>
      </div>
    </>
  );
}

function SaveBar({ dirty, pending, onSave, children }: { dirty: boolean; pending: boolean; onSave: () => void; children?: ReactNode }) {
  return (
    <div className="sticky bottom-0 -mx-6 -mb-6 mt-6 flex flex-wrap items-center justify-end gap-2 rounded-b-xl border-t bg-card/95 px-6 py-3 backdrop-blur">
      {dirty && <span className="mr-auto text-xs text-muted-foreground">Modifications non enregistrées</span>}
      {children}
      <Button onClick={onSave} disabled={!dirty || pending}>{pending && <Loader2 className="animate-spin" />}Enregistrer</Button>
    </div>
  );
}

/* ----------------------------------------------------------------- boîte mail */

function MailboxForm({ s }: { s: Settings }) {
  const qc = useQueryClient();
  const [v, setV] = useState<MailboxSettings>(s.mailbox);
  const [password, setPassword] = useState("");
  const [dirty, setDirty] = useState(false);
  const [sendTest, setSendTest] = useState(true);
  const [report, setReport] = useState<ConnectionReport | null>(null);
  const [folders, setFolders] = useState(s.folders);
  const set = <K extends keyof MailboxSettings>(k: K, val: MailboxSettings[K]) => { setV((x) => ({ ...x, [k]: val })); setDirty(true); };
  const body = () => ({ ...v, ...(password ? { password } : {}) });

  const save = useMutation({
    mutationFn: () => api.saveMailbox(body()),
    onSuccess: () => { toast.success("Boîte mail enregistrée"); setDirty(false); setPassword(""); qc.invalidateQueries(); },
    onError: (e) => toastError(e, "Enregistrement impossible"),
  });
  const test = useMutation({
    mutationFn: () => api.testConnection({ ...body(), send_test_email: sendTest }),
    onSuccess: (r) => {
      setReport(r);
      if (r.folders.length) setFolders(r.folders);
      if (r.sent_folder && !v.sent_folder) set("sent_folder", r.sent_folder);
      if (r.junk_folder && !v.watched_folders.includes(r.junk_folder)) set("watched_folders", [...v.watched_folders, r.junk_folder]);
      r.ok ? toast.success("Connexion réussie") : toast.error("La connexion a échoué", { description: "Voir le détail ci-dessous." });
    },
    onError: (e) => toastError(e),
  });
  const err = (f: string) => fieldError(save.error ?? test.error, f);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Boîte mail d'envoi</CardTitle>
        <CardDescription>Les réglages de votre hébergeur (cPanel → Comptes email → Configurer le client mail). Le mot de passe est rangé dans le coffre-fort de Windows, jamais dans un fichier.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Nom affiché" error={err("display_name")} hint="Ce que voit le destinataire."><Input value={v.display_name} onChange={(e) => set("display_name", e.target.value)} placeholder="Prénom Nom – Cabinet" /></Field>
          <Field label="Adresse email" error={err("email")}><Input type="email" value={v.email} onChange={(e) => set("email", e.target.value)} /></Field>
          <Field label="Identifiant" error={err("username")} hint="Souvent l'adresse complète."><Input value={v.username} onChange={(e) => set("username", e.target.value)} /></Field>
          <Field label="Mot de passe" error={err("password")} hint={s.has_password ? "Laissez vide pour garder celui enregistré." : undefined}>
            <Input type="password" value={password} onChange={(e) => { setPassword(e.target.value); setDirty(true); }} placeholder={s.has_password ? "••••••••  (enregistré)" : ""} autoComplete="new-password" />
          </Field>
        </div>

        <div className="grid gap-4 rounded-xl border p-4 sm:grid-cols-2">
          <p className="text-sm font-medium sm:col-span-2">Envoi (SMTP)</p>
          <Field label="Serveur" error={err("smtp_host")}><Input value={v.smtp_host} onChange={(e) => set("smtp_host", e.target.value)} placeholder="mail.cabinet.ma" /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Port" error={err("smtp_port")}><Input type="number" value={v.smtp_port} onChange={(e) => set("smtp_port", Number(e.target.value))} /></Field>
            <Field label="Sécurité">
              <NativeSelect value={v.smtp_security} onChange={(e) => {
                const sec = e.target.value as "ssl" | "starttls";
                setV((x) => ({ ...x, smtp_security: sec, smtp_port: sec === "ssl" ? 465 : 587 })); setDirty(true);
              }}>
                <option value="ssl">SSL (465)</option><option value="starttls">STARTTLS (587)</option>
              </NativeSelect>
            </Field>
          </div>
          <p className="text-sm font-medium sm:col-span-2">Lecture (IMAP)</p>
          <Field label="Serveur" error={err("imap_host")}><Input value={v.imap_host} onChange={(e) => set("imap_host", e.target.value)} placeholder="mail.cabinet.ma" /></Field>
          <Field label="Port" error={err("imap_port")}><Input type="number" value={v.imap_port} onChange={(e) => set("imap_port", Number(e.target.value))} /></Field>
        </div>

        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="outline" onClick={() => test.mutate()} disabled={test.isPending}>
              {test.isPending ? <Loader2 className="animate-spin" /> : <Send />}Tester la connexion
            </Button>
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <Checkbox checked={sendTest} onCheckedChange={(c) => setSendTest(c === true)} />M'envoyer un email de test
            </label>
          </div>
          {report && (
            <div className="space-y-1.5 rounded-xl border p-4 text-sm">
              {report.steps.map((st) => (
                <p key={st.label} className="flex items-start gap-2">
                  {st.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" /> : <XCircle className="mt-0.5 size-4 shrink-0 text-destructive" />}
                  <span><span className="font-medium">{st.label}</span> <span className="text-muted-foreground">{st.detail}</span></span>
                </p>
              ))}
            </div>
          )}
        </div>

        {folders.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Dossier des envoyés" hint="Une copie de chaque email y est rangée.">
              <NativeSelect value={v.sent_folder ?? ""} onChange={(e) => set("sent_folder", e.target.value || null)}>
                <option value="">Ne pas ranger de copie</option>
                {folders.map((f) => <option key={f.raw} value={f.raw}>{f.display}</option>)}
              </NativeSelect>
            </Field>
            <div className="space-y-1.5">
              <span className="text-sm font-medium">Dossiers à surveiller</span>
              <div className="max-h-40 space-y-1.5 overflow-y-auto rounded-lg border p-3">
                {folders.map((f) => (
                  <label key={f.raw} className="flex items-center gap-2 text-sm">
                    <Checkbox checked={v.watched_folders.includes(f.raw)} onCheckedChange={(c) =>
                      set("watched_folders", c ? [...v.watched_folders, f.raw] : v.watched_folders.filter((x) => x !== f.raw))} />
                    {f.display}
                  </label>
                ))}
              </div>
              <span className="block text-xs text-muted-foreground">Boîte de réception et spam : une réponse peut y atterrir.</span>
            </div>
          </div>
        )}

        <Field label="Signature" hint="Ajoutée à la fin de chaque email, texte simple.">
          <Textarea rows={5} value={v.signature} onChange={(e) => set("signature", e.target.value)} />
        </Field>
        <SaveBar dirty={dirty} pending={save.isPending} onSave={() => save.mutate()} />
      </CardContent>
    </Card>
  );
}

/* ------------------------------------------------------------ rythme d'envoi */

const DAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];

function SendingForm({ s }: { s: Settings }) {
  const qc = useQueryClient();
  const [v, setV] = useState<SendingSettings>(s.sending);
  const [dirty, setDirty] = useState(false);
  const [newHoliday, setNewHoliday] = useState({ date: "", label: "" });
  const set = <K extends keyof SendingSettings>(k: K, val: SendingSettings[K]) => { setV((x) => ({ ...x, [k]: val })); setDirty(true); };
  const save = useMutation({
    mutationFn: () => api.saveSending(v),
    onSuccess: () => { toast.success("Rythme d'envoi enregistré"); setDirty(false); qc.invalidateQueries(); },
    onError: (e) => toastError(e, "Enregistrement impossible"),
  });
  const err = (f: string) => fieldError(save.error, f);
  const win = (i: number, j: 0 | 1, val: string) => {
    const w = v.send_windows.map((x) => [...x] as [string, string]);
    w[i][j] = val;
    set("send_windows", w);
  };
  const perDay = Math.min(v.daily_cap, v.rampup_enabled ? v.rampup_per_day : v.daily_cap);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Rythme d'envoi</CardTitle>
        <CardDescription>Un email à la fois, aux heures de bureau, pour ressembler à un envoi fait à la main et protéger la réputation du domaine du cabinet.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {fieldError(save.error, "mailbox") && <p className="text-sm text-destructive">{fieldError(save.error, "mailbox")}</p>}
        <div className="space-y-2">
          <span className="text-sm font-medium">Jours d'envoi</span>
          <div className="flex flex-wrap gap-1.5">
            {DAYS.map((d, i) => {
              const on = v.send_days.includes(i);
              return (
                <button key={d} onClick={() => set("send_days", on ? v.send_days.filter((x) => x !== i) : [...v.send_days, i].sort())}
                  className={cn("h-9 w-12 rounded-lg border text-sm transition-colors", on ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent")}>{d}</button>
              );
            })}
          </div>
          {err("send_days") && <p className="text-xs text-destructive">{err("send_days")}</p>}
        </div>

        <div className="space-y-2">
          <span className="text-sm font-medium">Plages horaires (heure du Maroc)</span>
          {v.send_windows.map((w, i) => (
            <div key={i} className="flex items-center gap-2">
              <Input type="time" className="w-32" value={w[0]} onChange={(e) => win(i, 0, e.target.value)} />
              <span className="text-muted-foreground">→</span>
              <Input type="time" className="w-32" value={w[1]} onChange={(e) => win(i, 1, e.target.value)} />
              {i === 1 && <Button variant="ghost" size="icon" className="size-8" aria-label="Retirer la plage" onClick={() => set("send_windows", [v.send_windows[0]])}><Trash2 /></Button>}
            </div>
          ))}
          {v.send_windows.length < 2 && <Button variant="ghost" size="sm" onClick={() => set("send_windows", [...v.send_windows, ["14:30", "17:30"]])}><Plus /> Ajouter une plage</Button>}
          {err("windows") && <p className="text-xs text-destructive">{err("windows")}</p>}
        </div>

        <div className="grid gap-4 rounded-xl border p-4 sm:grid-cols-2">
          <Field label="Maximum par jour" error={err("daily_cap")} hint={v.daily_cap > s.cap_warning ? `Au-delà de ${s.cap_warning}, le risque d'être classé en spam augmente.` : undefined}>
            <Input type="number" value={v.daily_cap} onChange={(e) => set("daily_cap", Number(e.target.value))} />
          </Field>
          <Field label="Maximum par heure" error={err("hourly_cap")}><Input type="number" value={v.hourly_cap} onChange={(e) => set("hourly_cap", Number(e.target.value))} /></Field>
          <Field label="Pause entre deux emails (secondes)" error={err("min_gap_s") ?? err("max_gap_s")} hint="Tirée au hasard entre ces deux valeurs." className="sm:col-span-2">
            <div className="flex items-center gap-2">
              <Input type="number" className="w-28" value={v.min_gap_s} onChange={(e) => set("min_gap_s", Number(e.target.value))} />
              <span className="text-muted-foreground">à</span>
              <Input type="number" className="w-28" value={v.max_gap_s} onChange={(e) => set("max_gap_s", Number(e.target.value))} />
            </div>
          </Field>
          <label className="flex items-center justify-between gap-3 text-sm sm:col-span-2">
            <span>Démarrage progressif<span className="block text-xs text-muted-foreground">Limite les premiers jours, le temps que la boîte se fasse une réputation.</span></span>
            <Switch checked={v.rampup_enabled} onCheckedChange={(c) => set("rampup_enabled", c)} />
          </label>
          {v.rampup_enabled && <Field label="Emails par jour au démarrage" error={err("rampup_per_day")}><Input type="number" value={v.rampup_per_day} onChange={(e) => set("rampup_per_day", Number(e.target.value))} /></Field>}
          <p className="text-xs text-muted-foreground sm:col-span-2">Soit au plus <b>{perDay}</b> emails par jour d'envoi.</p>
        </div>

        <div className="space-y-2">
          <span className="text-sm font-medium">Jours fériés (aucun envoi)</span>
          <div className="max-h-56 divide-y overflow-y-auto rounded-xl border">
            {v.holidays.map((h, i) => (
              <div key={h.date + i} className="flex items-center gap-3 px-3 py-2 text-sm">
                <span className="w-24 shrink-0 tabular text-muted-foreground">{new Date(h.date + "T12:00:00").toLocaleDateString("fr-FR")}</span>
                <span className="min-w-0 flex-1 truncate">{h.label}</span>
                <Button variant="ghost" size="icon" className="size-7" aria-label="Retirer" onClick={() => set("holidays", v.holidays.filter((_, j) => j !== i))}><Trash2 /></Button>
              </div>
            ))}
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input type="date" className="sm:w-44" value={newHoliday.date} onChange={(e) => setNewHoliday((x) => ({ ...x, date: e.target.value }))} />
            <Input placeholder="Nom (ex. Aïd al-Fitr)" value={newHoliday.label} onChange={(e) => setNewHoliday((x) => ({ ...x, label: e.target.value }))} />
            <Button variant="outline" disabled={!newHoliday.date} onClick={() => {
              set("holidays", [...v.holidays, newHoliday].sort((a, b) => a.date.localeCompare(b.date)));
              setNewHoliday({ date: "", label: "" });
            }}><Plus /> Ajouter</Button>
          </div>
          <p className="text-xs text-muted-foreground">Les fêtes religieuses dépendent de l'observation de la lune : vérifiez les dates annoncées chaque année.</p>
          {err("holidays") && <p className="text-xs text-destructive">{err("holidays")}</p>}
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="flex items-center justify-between gap-3 text-sm sm:col-span-2">
            <span>Ajouter une ligne de désinscription (STOP)<span className="block text-xs text-muted-foreground">Sous la signature des emails de prospection uniquement. Désactivée par défaut.</span></span>
            <Switch checked={v.unsubscribe_enabled} onCheckedChange={(c) => set("unsubscribe_enabled", c)} />
          </label>
          {v.unsubscribe_enabled && (
            <Field label="Texte de la ligne" error={err("unsubscribe_line")} className="sm:col-span-2">
              <Input value={v.unsubscribe_line} onChange={(e) => set("unsubscribe_line", e.target.value)} />
            </Field>
          )}
          <Field label="Email sans réponse au bout de" error={err("followup_days")} className="sm:col-span-2"
            hint="Délai en jours ouvrés après lequel un email envoyé apparaît dans « Envoyés sans réponse » (tableau de bord et boîte mail).">
            <div className="flex items-center gap-2">
              <Input type="number" min={1} max={30} className="w-24" value={v.followup_days} onChange={(e) => set("followup_days", Number(e.target.value))} />
              <span className="text-sm text-muted-foreground">jours ouvrés</span>
            </div>
          </Field>
          <Field label="Heure du résumé quotidien" error={err("digest_time")}><Input type="time" value={v.digest_time} onChange={(e) => set("digest_time", e.target.value)} /></Field>
          <Field label="Envoyer le résumé à" error={err("digest_recipient")} hint="Vide : votre boîte d'envoi."><Input type="email" value={v.digest_recipient} onChange={(e) => set("digest_recipient", e.target.value)} /></Field>
          <label className="flex items-center justify-between gap-3 text-sm sm:col-span-2">
            <span>Continuer la séquence après une réponse automatique<span className="block text-xs text-muted-foreground">Absence, congés : la relance suivante est décalée après la date de retour si elle est connue.</span></span>
            <Switch checked={v.auto_reply_continues} onCheckedChange={(c) => set("auto_reply_continues", c)} />
          </label>
        </div>
        <SaveBar dirty={dirty} pending={save.isPending} onSave={() => save.mutate()} />
      </CardContent>
    </Card>
  );
}

/* --------------------------------------------------------------- mode test */

function TestMode({ s }: { s: Settings }) {
  const qc = useQueryClient();
  const [on, setOn] = useState(s.test_mode);
  const [confirmOff, setConfirmOff] = useState(false);
  useEffect(() => setOn(s.test_mode), [s.test_mode]);
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => api.setTestMode(enabled),
    onSuccess: (r) => { setOn(r.test_mode); toast.success(r.test_mode ? "Mode test activé" : "Mode test désactivé : envois réels"); qc.invalidateQueries(); },
    onError: (e) => toastError(e),
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">Mode test {s.test_mode_locked && <Lock className="size-4 text-muted-foreground" />}</CardTitle>
        <CardDescription>En mode test, chaque email part vers votre propre adresse, avec l'objet préfixé [TEST → contact]. Les séquences se déroulent normalement : vous voyez exactement ce que recevraient vos prospects.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <label className={cn("flex items-center justify-between gap-3 rounded-xl border p-4", on ? "border-warning/40 bg-warning/5" : "border-destructive/40 bg-destructive/5")}>
          <span className="text-sm font-medium">{on ? "Mode test activé" : "Envois réels aux contacts"}</span>
          <Switch checked={on} disabled={s.test_mode_locked || toggle.isPending} onCheckedChange={(c) => (c ? toggle.mutate(true) : setConfirmOff(true))} />
        </label>
        {on && !s.test_mode_locked && (
          <div className="space-y-1.5 rounded-xl bg-muted/40 p-4 text-sm">
            <p className="font-medium">Avant de passer en envois réels</p>
            <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
              <li>Une campagne de test est allée jusqu'au bout, et les emails reçus dans votre boîte vous conviennent.</li>
              <li>Les blocs de contenu sont rédigés (plus aucun « À RÉDIGER »).</li>
              <li>Une seule copie de l'application tourne sur ce PC avec cette boîte (pas l'ancienne version en même temps).</li>
            </ul>
          </div>
        )}
        <ConfirmDialog open={confirmOff} onOpenChange={setConfirmOff} destructive typed="REEL" pending={toggle.isPending}
          title="Passer en envois réels ?"
          description="Les prochains emails des campagnes en cours partiront réellement à vos contacts, depuis votre boîte. Vous pourrez réactiver le mode test à tout moment."
          confirmLabel="Activer les envois réels" onConfirm={() => { toggle.mutate(false); setConfirmOff(false); }} />
        {s.test_mode_locked && (
          <p className="text-sm text-muted-foreground">Verrouillé dans cette version de développement (V2), pour qu'elle n'envoie jamais de vrais emails en même temps que la V1. Le verrou sera retiré au moment de la bascule.</p>
        )}
      </CardContent>
    </Card>
  );
}
