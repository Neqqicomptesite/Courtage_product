import { useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import { openComposer } from "@/components/composer";
import { Building2, CalendarDays, FileText, Inbox, PenSquare, LayoutDashboard, ListOrdered, RefreshCw, Rocket, Settings, Upload, User, UserPlus, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { fullName } from "@/lib/format";

const PAGES = [
  { to: "/", label: "Tableau de bord", icon: LayoutDashboard },
  { to: "/inbox", label: "Boîte mail", icon: Inbox },
  { to: "/inbox/followups", label: "Emails sans réponse", icon: Inbox },
  { to: "/replies", label: "Réponses aux campagnes", icon: Inbox },
  { to: "/agenda", label: "Agenda", icon: CalendarDays },
  { to: "/sequences", label: "Séquences", icon: ListOrdered },
  { to: "/campaigns", label: "Campagnes", icon: Rocket },
  { to: "/companies", label: "Entreprises", icon: Building2 },
  { to: "/contacts", label: "Contacts", icon: Users },
  { to: "/settings", label: "Réglages", icon: Settings },
];
const ACTIONS = [
  { to: "/campaigns/new", label: "Nouvelle campagne", icon: Rocket },
  { to: "/contacts?new=1", label: "Nouveau contact", icon: UserPlus },
  { to: "/contacts/import", label: "Importer des contacts", icon: Upload },
  { to: "/agenda?new=1", label: "Ajouter un rappel", icon: CalendarDays },
  { to: "/sequences/blocks", label: "Rédiger les textes personnalisés", icon: FileText },
];

/** Palette de commandes (Ctrl+K) : aller n'importe où ou trouver un contact au clavier. */
export function CommandPalette({ onSync }: { onSync: () => void }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const navigate = useNavigate();
  const { data: contacts } = useQuery({ queryKey: ["picker", q], queryFn: () => api.picker(q), enabled: open && q.length >= 2 });
  const { data: companies } = useQuery({ queryKey: ["companies", q, "palette"], queryFn: () => api.companies({ q }), enabled: open && q.length >= 2 });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("open-command", () => setOpen(true));
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const go = (to: string) => {
    setOpen(false);
    setQ("");
    navigate(to);
  };
  const item = "flex cursor-default items-center gap-2.5 rounded-md px-2.5 py-2 text-sm aria-selected:bg-accent aria-selected:text-accent-foreground [&_svg]:size-4 [&_svg]:text-muted-foreground";

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-xl gap-0 overflow-hidden p-0">
        <DialogTitle className="sr-only">Rechercher</DialogTitle>
        <Command label="Palette de commandes" shouldFilter className="flex flex-col">
          <Command.Input value={q} onValueChange={setQ} autoFocus placeholder="Une page, une action, un contact ou une entreprise : « gestionnaire sanlam »…"
            className="h-12 border-b bg-transparent px-4 text-sm outline-none placeholder:text-muted-foreground" />
          <Command.List className="max-h-80 overflow-y-auto p-2">
            <Command.Empty className="py-6 text-center text-sm text-muted-foreground">Aucun résultat.</Command.Empty>
            <Command.Group heading="Actions" className="text-xs text-muted-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
              {ACTIONS.map((a) => (
                <Command.Item key={a.to} className={item} onSelect={() => go(a.to)}><a.icon />{a.label}</Command.Item>
              ))}
              <Command.Item className={item} onSelect={() => { setOpen(false); openComposer(); }}><PenSquare />Écrire un email</Command.Item>
              <Command.Item className={item} onSelect={() => { setOpen(false); onSync(); }}><RefreshCw />Lire la boîte de réception maintenant</Command.Item>
            </Command.Group>
            <Command.Group heading="Pages" className="text-xs text-muted-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
              {PAGES.map((p) => (
                <Command.Item key={p.to} className={item} onSelect={() => go(p.to)}><p.icon />{p.label}</Command.Item>
              ))}
            </Command.Group>
            {companies && companies.items.length > 0 && (
              <Command.Group heading="Entreprises" className="text-xs text-muted-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
                {companies.items.slice(0, 5).map((c) => (
                  <Command.Item key={c.id} value={`entreprise ${c.id} ${c.name}`} keywords={[q]} className={item} onSelect={() => go(`/companies/${c.id}`)}>
                    <Building2 />
                    <span className="flex-1 truncate">{c.name}</span>
                    <span className="text-xs text-muted-foreground">{c.people} pers.</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
            {contacts && contacts.length > 0 && (
              <Command.Group heading="Contacts" className="text-xs text-muted-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
                {contacts.slice(0, 8).map((c) => (
                  <Command.Item key={c.id} value={`contact ${c.id} ${fullName(c)} ${c.company ?? ""} ${c.email}`} keywords={[q]} className={item}
                    onSelect={() => go(`/contacts?open=${c.id}`)}>
                    <User />
                    <span className="flex-1 truncate">{fullName(c)}</span>
                    <span className="truncate text-xs text-muted-foreground">{[c.job_title, c.company].filter(Boolean).join(" · ")}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
          </Command.List>
          <div className="flex items-center justify-between border-t px-4 py-2 text-[11px] text-muted-foreground">
            <span>↑↓ pour naviguer · Entrée pour ouvrir</span>
            <kbd className="rounded border bg-muted px-1.5 font-sans">Ctrl K</kbd>
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
