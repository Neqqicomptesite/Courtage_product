// Fiche contact en mode saisie : sert à créer un contact et à modifier une fiche existante.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Building2, Landmark, Loader2, Target, UserRound } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { Field, fieldError, toastError } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { lot } from "@/lib/format";
import { ApiError, api, type ContactDetail, type ContactInput, type Kind, type Vocab } from "@/lib/api";
import { KindPicker } from "@/pages/companies";

type Values = Required<Omit<ContactInput, "custom" | "kind">>;
const EMPTY: Values = {
  first_name: "", last_name: "", email: "", job_title: "", company: "", phone: "", website: "", linkedin_url: "",
  sector: "", target_segment: "", sector_family: "", size_bucket: "", wave: "", email_reliability: "", notes: "",
  department: "", seniority: "",
};

function Section({ icon: Icon, title, children }: { icon: typeof UserRound; title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h3 className="flex items-center gap-2 text-sm font-medium"><Icon className="size-4 text-muted-foreground" />{title}</h3>
      <div className="grid gap-3 sm:grid-cols-2">{children}</div>
    </section>
  );
}

/** Liste déroulante qui garde une valeur hors liste (ex. ancienne fiabilité « Bonne (Findymail) »). */
function Choice({ value, options, onChange, placeholder }: { value: string; options: { value: string; label: string }[]; onChange: (v: string) => void; placeholder: string }) {
  const all = value && !options.some((o) => o.value === value) ? [{ value, label: value }, ...options] : options;
  return (
    <NativeSelect value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{placeholder}</option>
      {all.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </NativeSelect>
  );
}

export function ContactForm({ contact, vocab, companies, companyKinds = {}, onDone, onCancel, onExisting, initial }: {
  contact?: ContactDetail;
  initial?: Partial<Record<"company" | "email" | "first_name" | "last_name" | "department" | "seniority", string>>;
  companyKinds?: Record<string, Kind>;
  vocab: Vocab;
  companies: string[];
  onDone: (id: number) => void;
  onCancel: () => void;
  onExisting?: (id: number) => void;
}) {
  const qc = useQueryClient();
  const [v, setV] = useState<Values>(() => {
    if (!contact) return { ...EMPTY, ...Object.fromEntries(Object.entries(initial ?? {}).filter(([, x]) => x)) };
    const out = { ...EMPTY };
    (Object.keys(EMPTY) as (keyof Values)[]).forEach((k) => {
      const val = k === "email_reliability" ? contact.email_reliability_detail : (contact as unknown as Record<string, string | null>)[k];
      out[k] = val ?? "";
    });
    return out;
  });
  // Type : sans choix explicite, un nouveau contact prend celui de son entreprise (ou Prospect).
  const [kind, setKind] = useState<Kind | null>(contact ? contact.kind : null);
  const inherited = useMemo(() => {
    const name = v.company.trim().toLowerCase();
    const hit = Object.entries(companyKinds).find(([n]) => n.toLowerCase() === name);
    return hit ? hit[1] : null;
  }, [v.company, companyKinds]);
  const [custom, setCustom] = useState<Record<string, string>>(() => Object.fromEntries((contact?.custom ?? []).map((c) => [c.key, c.value])));
  const set = (k: keyof Values) => (val: string) => setV((x) => ({ ...x, [k]: val }));
  const input = (k: keyof Values, props: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
    <Input value={v[k]} onChange={(e) => set(k)(e.target.value)} {...props} />
  );

  // Le code séquence se lit en direct, comme dans le modèle Excel : FIN + BTP -> FIN-BTP.
  const code = useMemo(() => {
    const t = vocab.targets.find((o) => o.value === v.target_segment)?.code;
    const s = vocab.sectors.find((o) => o.value === v.sector_family)?.code;
    return t && s ? `${t}-${s}` : contact?.sequence_code ?? null;
  }, [v.target_segment, v.sector_family, vocab, contact]);

  const save = useMutation({
    mutationFn: async () => {
      const { notes, ...fields } = v;
      const k = kind ? { kind } : {};
      if (contact) {
        await api.contactUpdate(contact.id, { ...fields, ...k, custom });
        return { id: contact.id, warnings: [] as string[] };
      }
      return api.contactCreate({ ...fields, ...k, notes });
    },
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["contacts"] });
      qc.invalidateQueries({ queryKey: ["contact", r.id] });
      qc.invalidateQueries({ queryKey: ["companies"] });
      qc.invalidateQueries({ queryKey: ["company"] });
      toast.success(contact ? "Fiche enregistrée" : "Contact ajouté", { description: r.warnings.join(" ") || undefined });
      onDone(r.id);
    },
    onError: (e) => {
      if (e instanceof ApiError && e.existingId && onExisting) {
        toast.error("Ce contact existe déjà", { action: { label: "Ouvrir sa fiche", onClick: () => onExisting(e.existingId!) } });
      } else if (!(e instanceof ApiError && Object.keys(e.fields).length)) toastError(e, "Enregistrement impossible");
    },
  });
  const err = (f: string) => fieldError(save.error, f);
  const asOptions = (l: string[]) => l.map((x) => ({ value: x, label: x }));

  return (
    <form className="space-y-6" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <Section icon={UserRound} title="Personne">
        <Field label="Prénom">{input("first_name", { autoFocus: !contact })}</Field>
        <Field label="Nom">{input("last_name")}</Field>
        <Field label="Email" error={err("email")} className="sm:col-span-2"
          hint={contact ? "Modifiable tant qu'aucun email n'a été échangé." : "Seul champ obligatoire."}>
          {input("email", { type: "email", required: true })}
        </Field>
        <Field label="Poste">{input("job_title", { placeholder: "ex. Directeur administratif et financier" })}</Field>
        <Field label="Téléphone">{input("phone", { type: "tel" })}</Field>
        <Field label="Profil LinkedIn" className="sm:col-span-2">{input("linkedin_url", { placeholder: "https://www.linkedin.com/in/…" })}</Field>
      </Section>

      <KindPicker value={kind ?? inherited ?? "prospect"} onChange={setKind}
        hint={!contact && !kind ? (inherited ? `Type de ${v.company.trim()}, entreprise déjà connue.` : "Sans autre choix : Prospect, ou le type de son entreprise si elle est déjà connue.") : undefined} />
      {contact && kind !== contact.kind && kind !== "prospect" && (
        <p className="-mt-4 text-xs text-warning">Ses séquences de prospection en cours seront arrêtées à l'enregistrement.</p>
      )}

      {((kind ?? inherited) === "insurer" || v.department || v.seniority) && (
        <Section icon={Landmark} title="Chez l'assureur">
          <Field label="Service" hint="Range la personne dans l'onglet du service, sur la fiche de la compagnie.">
            <Choice value={v.department} onChange={set("department")} options={vocab.departments ?? []} placeholder="—" />
          </Field>
          <Field label="Niveau"><Choice value={v.seniority} onChange={set("seniority")} options={vocab.seniorities ?? []} placeholder="—" /></Field>
        </Section>
      )}

      <Section icon={Building2} title="Entreprise">
        <Field label="Nom de l'entreprise">
          <Input value={v.company} onChange={(e) => set("company")(e.target.value)} list="oddo-companies" />
        </Field>
        <datalist id="oddo-companies">{companies.map((c) => <option key={c} value={c} />)}</datalist>
        <Field label="Site web">{input("website", { placeholder: "entreprise.ma" })}</Field>
        <Field label="Activité">{input("sector", { placeholder: "ex. Logistique frigorifique" })}</Field>
        <Field label="Taille"><Choice value={v.size_bucket} onChange={set("size_bucket")} options={asOptions(vocab.sizes)} placeholder="—" /></Field>
      </Section>

      <Section icon={Target} title="Ciblage (choisit les textes envoyés)">
        <Field label="Fonction"><Choice value={v.target_segment} onChange={set("target_segment")} options={vocab.targets} placeholder="Choisir…" /></Field>
        <Field label="Secteur"><Choice value={v.sector_family} onChange={set("sector_family")} options={vocab.sectors} placeholder="Choisir…" /></Field>
        <div className="flex items-center gap-2 rounded-lg bg-muted/50 px-3 py-2 text-sm sm:col-span-2">
          <span className="text-muted-foreground">Profil</span>
          {code ? <code className="rounded bg-accent px-1.5 py-0.5 font-semibold text-accent-foreground">{code}</code>
            : <span className="text-xs text-muted-foreground">choisissez la fonction et le secteur</span>}
          <span className="ml-auto hidden text-xs text-muted-foreground sm:inline">choisit les textes de ses emails</span>
        </div>
        <Field label="Lot d'envoi"><Choice value={v.wave} onChange={set("wave")} options={vocab.waves.map((w) => ({ value: w, label: lot(w) ?? w }))} placeholder="—" /></Field>
        <Field label="Qualité de l'email"><Choice value={v.email_reliability} onChange={set("email_reliability")} options={asOptions(vocab.reliability)} placeholder="—" /></Field>
      </Section>

      {contact && Object.keys(custom).length > 0 && (
        <section className="space-y-3">
          <h3 className="text-sm font-medium">Champs personnalisés</h3>
          {contact.custom.map((f) => (
            <Field key={f.key} label={<>{f.label} <code className="ml-1 text-xs font-normal text-muted-foreground">{`{{ custom.${f.key} }}`}</code></>}>
              <Textarea rows={2} value={custom[f.key] ?? ""} onChange={(e) => setCustom((c) => ({ ...c, [f.key]: e.target.value }))} />
            </Field>
          ))}
        </section>
      )}

      {!contact && (
        <Field label="Notes"><Textarea rows={3} value={v.notes} onChange={(e) => set("notes")(e.target.value)} placeholder="Échéance du contrat, assureur actuel…" /></Field>
      )}

      <div className="sticky bottom-0 -mx-6 -mb-6 flex justify-end gap-2 border-t bg-card/95 px-6 py-3 backdrop-blur">
        <Button type="button" variant="outline" onClick={onCancel}>Annuler</Button>
        <Button type="submit" disabled={save.isPending}>{save.isPending && <Loader2 className="animate-spin" />}{contact ? "Enregistrer" : "Ajouter le contact"}</Button>
      </div>
    </form>
  );
}
