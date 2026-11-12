import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpen,
  Building2,
  CalendarDays,
  FileCheck2,
  FileStack,
  Inbox,
  LayoutDashboard, ListChecks,
  LogOut,
  ListOrdered,
  Menu,
  Moon,
  RefreshCw,
  Rocket,
  Search,
  Settings,
  Sun,
  UserCog,
  Users,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, ScrollRestoration } from "react-router-dom";
import { toast } from "sonner";

import { CommandPalette } from "@/components/command-palette";
import { Composer } from "@/components/composer";
import { NotificationBell } from "@/components/notifications";
import { ReminderDialog } from "@/pages/agenda";
import { SendSequenceDialog } from "@/components/send-sequence";
import { NewQuoteHost } from "@/pages/quotes";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { api, type Status } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import { signOut } from "@/lib/auth";
import { useTheme } from "@/lib/theme";
import { useMe } from "@/pages/login";
import { cn } from "@/lib/utils";
import { Brand } from "@/components/brand";

const NAV = [
  { to: "/", label: "Tableau de bord", icon: LayoutDashboard, end: true },
  { to: "/inbox", label: "Boîte mail", icon: Inbox, unread: true, also: ["/replies"] },
  { to: "/quotes", label: "Dossiers", icon: FileStack },
  { to: "/contracts", label: "Contrats", icon: FileCheck2 },
  { to: "/agenda", label: "Agenda", icon: CalendarDays },
  { to: "/sequences", label: "Séquences", icon: ListOrdered },
  { to: "/campaigns", label: "Campagnes", icon: Rocket },
  { to: "/companies", label: "Entreprises", icon: Building2 },
  { to: "/contacts", label: "Contacts", icon: Users },
  { to: "/contacts/lists", label: "Listes", icon: ListChecks, sub: true },  // V4 : les listes mises en avant
  { to: "/settings", label: "Réglages", icon: Settings },
];

export function useStatus() {
  // Interrogé toutes les 15 s : l'indicateur « boîte lue il y a … » reste à jour sans recharger.
  return useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 15_000 });
}

/** Re-render chaque 30 s pour que « il y a 2 minutes » avance tout seul. */
function useNow(intervalMs = 30_000) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

const SYNC_LABELS: Record<string, string> = {
  reply: "réponse(s)",
  auto_reply: "absence(s)",
  bounce_hard: "rebond(s)",
  bounce_soft: "rebond(s) temporaire(s)",
  unsubscribe: "désinscription(s)",
  unmatched: "réponse(s) à rattacher",
};

export function useSyncNow() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.sync,
    onSuccess: (r) => {
      qc.invalidateQueries();
      if (!r.ok) return toast.error("Lecture de la boîte impossible", { description: r.error ?? undefined });
      const parts = Object.entries(r.counts).map(([k, v]) => `${v} ${SYNC_LABELS[k] ?? k}`);
      toast.success("Boîte de réception lue", {
        description: parts.length ? parts.join(", ") : "Aucun nouveau message lié à vos campagnes.",
      });
    },
    onError: () => toast.error("L'application ne répond pas", { description: "Vérifiez que la fenêtre noire est ouverte." }),
  });
}

function SyncIndicator({ status, sync }: { status: Status | undefined; sync: ReturnType<typeof useSyncNow> }) {
  const now = useNow();
  const error = status?.sync.error;
  const last = status?.sync.last_ok ?? null;
  // Vert si la boîte a été lue récemment, orange si c'est ancien, rouge en cas d'erreur.
  const ageMin = last ? (now.getTime() - new Date(last).getTime()) / 60_000 : Infinity;
  const tone = error ? "bg-destructive" : ageMin <= (status?.sync.interval_minutes ?? 10) + 5 ? "bg-success" : "bg-warning";

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          onClick={() => sync.mutate()}
          disabled={sync.isPending}
          className="group inline-flex h-8 items-center gap-2 rounded-full border bg-card px-3 text-xs text-muted-foreground shadow-sm transition-colors hover:text-foreground"
        >
          <span className="relative flex size-2">
            {!error && ageMin < 2 && (
              <span className={cn("absolute inline-flex size-full animate-ping rounded-full opacity-60", tone)} />
            )}
            <span className={cn("relative inline-flex size-2 rounded-full", tone)} />
          </span>
          <span className="hidden sm:inline">
            {error ? "Boîte illisible" : last ? `Boîte lue ${relativeTime(last, new Date(Math.max(now.getTime(), Date.now(), new Date(last).getTime())))}` : "Boîte pas encore lue"}
          </span>
          <RefreshCw className={cn("size-3.5 transition-transform group-hover:rotate-90", sync.isPending && "animate-spin")} />
        </button>
      </TooltipTrigger>
      <TooltipContent>
        {error
          ? `Erreur : ${error}. Aucun email ne part tant que la boîte est illisible.`
          : `Lecture automatique toutes les ${status?.sync.interval_minutes ?? 10} min et avant chaque envoi. Cliquez pour lire maintenant.`}
      </TooltipContent>
    </Tooltip>
  );
}

/** V3.7.1 : emails non lus de la boîte de réception, comme le chiffre d'une messagerie (aussi dans l'onglet). */
export function useUnread() {
  const { data } = useQuery({ queryKey: ["mail-unread"], queryFn: api.mailUnread, refetchInterval: 60_000, retry: false, staleTime: 30_000 });
  const n = data?.unread ?? 0;
  useEffect(() => {
    const base = document.title.replace(/^\(\d+\) /, "");
    document.title = n > 0 ? `(${n}) ${base}` : base;
  }, [n]);
  return n;
}

function Sidebar({ status, onNavigate }: { status: Status | undefined; onNavigate?: () => void }) {
  const location = useLocation();
  const me = useMe();
  const unread = useUnread();
  const nav = me?.server_mode && me.role === "admin"
    ? [...NAV.slice(0, -1), { to: "/equipe", label: "Équipe", icon: UserCog }, NAV[NAV.length - 1]]
    : NAV;
  return (
    <div className="flex h-full flex-col">
      <div className="px-5 pb-6 pt-6">
        <Brand />
      </div>
      <nav className="flex-1 space-y-0.5 px-3">
        {nav.map((n) => {
          const count = "unread" in n && n.unread ? unread : 0;
          const alsoActive = "also" in n && n.also?.some((p) => location.pathname.startsWith(p));
          // une liste ouverte (Contacts filtré sur une liste) allume « Listes », pas « Contacts »
          const inList = location.pathname.startsWith("/contacts/lists") || (location.pathname === "/contacts" && new URLSearchParams(location.search).has("list_id"));
          const forced = n.to === "/contacts/lists" ? inList : n.to === "/contacts" && inList ? false : null;
          return (
            <NavLink key={n.to} to={n.to} end={n.end} onClick={onNavigate}
              className={({ isActive: active }) => { const isActive = forced ?? (active || alsoActive); return cn("flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors", "sub" in n && n.sub && "ml-4 py-1.5",
                isActive ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"); }}>
              <n.icon className="size-4 shrink-0" />
              <span className="flex-1">{n.label}</span>
              {count > 0 && <span className="rounded-full bg-destructive px-1.5 text-[11px] font-semibold text-destructive-foreground tabular">{count}</span>}
            </NavLink>
          );
        })}
      </nav>
      <div className="space-y-1 p-3 text-xs text-muted-foreground">
        <NavLink to="/guide" onClick={onNavigate}
          className={({ isActive }) => cn("mb-2 flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
            isActive ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground")}>
          <BookOpen className="size-4 shrink-0" /> Guide
        </NavLink>
        <p className="px-3">Version {status?.version ?? "2"}</p>
      </div>
    </div>
  );
}

/** V3 : l'employé connecté et la déconnexion (rien sur le poste unique). */
function UserMenu() {
  const me = useMe();
  if (!me?.server_mode) return null;
  const label = me.full_name || me.email;
  const initials = label.split(/[\s.@]+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("");
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="flex size-8 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground" aria-label={`Compte : ${label}`}>
          {initials}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <div className="px-2 py-1.5">
          <p className="truncate text-sm font-medium">{label}</p>
          <p className="truncate text-xs text-muted-foreground">{me.email} · {me.role === "admin" ? "Administrateur" : "Employé"}</p>
        </div>
        <DropdownMenuSeparator />
        {me.role === "admin" && <DropdownMenuItem asChild><NavLink to="/equipe"><UserCog /> Équipe</NavLink></DropdownMenuItem>}
        <DropdownMenuItem onSelect={() => void signOut()}><LogOut /> Se déconnecter</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function Layout() {
  const { data: status } = useStatus();
  const sync = useSyncNow();
  const [theme, toggleTheme] = useTheme();
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="min-h-screen">
      {/* Menu latéral fixe sur grand écran */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 border-r bg-sidebar text-sidebar-foreground lg:block">
        <Sidebar status={status} />
      </aside>

      {/* Menu en tiroir sur téléphone et petite fenêtre */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 border-r bg-sidebar shadow-xl animate-in slide-in-from-left">
            <Button variant="ghost" size="icon" className="absolute right-2 top-2" onClick={() => setMobileOpen(false)} aria-label="Fermer le menu">
              <X />
            </Button>
            <Sidebar status={status} onNavigate={() => setMobileOpen(false)} />
          </aside>
        </div>
      )}

      <div className="lg:pl-60">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur sm:px-6">
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Ouvrir le menu">
            <Menu />
          </Button>
          <div className="lg:hidden"><Brand tagline={false} /></div>
          <button onClick={() => window.dispatchEvent(new Event("open-command"))}
            className="hidden h-8 w-64 items-center gap-2 rounded-md border bg-card px-3 text-sm text-muted-foreground shadow-sm transition-colors hover:text-foreground md:flex">
            <Search className="size-3.5" />
            <span className="flex-1 text-left">Rechercher…</span>
            <kbd className="rounded border bg-muted px-1.5 text-[10px] font-medium">Ctrl K</kbd>
          </button>
          <div className="ml-auto flex items-center gap-2">
            {status?.test_mode ? (
              <Tooltip>
                <TooltipTrigger asChild>
                  <Badge variant="warning" className="h-7 whitespace-nowrap px-2.5">
                    Mode test<span className="hidden sm:inline">{status.test_mode_locked ? " · verrouillé" : ""}</span>
                  </Badge>
                </TooltipTrigger>
                <TooltipContent>
                  Tous les emails partent vers {status.mailbox.email ?? "votre adresse"}, avec l'objet préfixé [TEST → contact].
                  {status.test_mode_locked && " Verrouillé pendant le développement de la V2."}
                </TooltipContent>
              </Tooltip>
            ) : status ? (
              <Badge variant="destructive" className="h-7 px-2.5">Envois réels</Badge>
            ) : null}
            <SyncIndicator status={status} sync={sync} />
            <NotificationBell />
            <Button variant="ghost" size="icon" onClick={toggleTheme} aria-label="Changer de thème">
              {theme === "dark" ? <Sun /> : <Moon />}
            </Button>
            <UserMenu />
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:py-7">
          <Outlet />
          <ScrollRestoration />  {/* V4 : en revenant, on retrouve la page là où on l'avait laissée */}
        </main>
        <CommandPalette onSync={() => sync.mutate()} />
        <Composer />
        <ReminderDialog />
        <SendSequenceDialog />
        <NewQuoteHost />
      </div>
    </div>
  );
}
