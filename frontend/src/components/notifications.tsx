// Centre de notifications (V2.8) : la cloche en haut à droite. Rappels du jour ou en retard,
// personnes à rappeler, emails restés sans réponse (un par personne, cliquable vers l'email),
// réponses à trier et envois bloqués. La pastille compte ce qui n'a pas encore été vu.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Bell, CalendarClock, CheckCheck, Clock, Download, MailQuestion, PhoneCall } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { api, type Notification } from "@/lib/api";
import { cn } from "@/lib/utils";

const ICON: Record<Notification["type"], typeof Bell> = {
  reminder: CalendarClock, callback: PhoneCall, followup: Clock, replies: MailQuestion, error: AlertTriangle, update: Download,
};
const TONE: Record<Notification["level"], string> = {
  info: "bg-primary/10 text-primary", warning: "bg-warning/15 text-warning", error: "bg-destructive/10 text-destructive",
};
const GROUPS: { title: string; types: Notification["type"][] }[] = [
  { title: "À faire", types: ["error", "update", "reminder", "callback", "replies"] },
  { title: "Sans réponse", types: ["followup"] },
];

export function useNotifications() {
  return useQuery({ queryKey: ["notifications"], queryFn: api.notifications, refetchInterval: 60_000 });
}

export function NotificationBell() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { data } = useNotifications();
  const [open, setOpen] = useState(false);
  const items = data?.items ?? [];
  const unseen = data?.unseen ?? 0;

  const markSeen = async (keys?: string[]) => {
    await api.notificationsSeen(keys);
    qc.invalidateQueries({ queryKey: ["notifications"] });
  };
  const go = (n: Notification) => {
    setOpen(false);
    if (!n.seen) void markSeen([n.key]);
    navigate(n.href);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" className="relative" aria-label={`Notifications${unseen ? ` (${unseen} nouvelles)` : ""}`}>
          <Bell />
          {unseen > 0 && (
            <span className="absolute right-0.5 top-0.5 min-w-4 rounded-full bg-destructive px-1 text-center text-[10px] font-semibold leading-4 text-destructive-foreground tabular">
              {unseen > 99 ? "99+" : unseen}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[min(24rem,calc(100vw-2rem))] p-0">
        <div className="flex items-center gap-2 border-b px-4 py-3">
          <span className="flex-1 text-sm font-semibold">Notifications</span>
          {unseen > 0 && (
            <button className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground" onClick={() => markSeen()}>
              <CheckCheck className="size-3.5" /> Tout marquer comme vu
            </button>
          )}
        </div>
        <div className="max-h-[min(30rem,70vh)] overflow-y-auto">
          {items.length === 0 ? (
            <div className="flex flex-col items-center gap-2 px-6 py-10 text-center text-sm text-muted-foreground">
              <Bell className="size-6" />
              Rien à signaler pour l'instant.
            </div>
          ) : GROUPS.map((g) => {
            const list = items.filter((n) => g.types.includes(n.type));
            if (!list.length) return null;
            return (
              <div key={g.title}>
                <p className="bg-muted/40 px-4 py-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  {g.title} · {list.length}
                </p>
                <ul className="divide-y">
                  {list.map((n) => {
                    const Icon = ICON[n.type];
                    return (
                      <li key={n.key}>
                        <button onClick={() => go(n)} className="flex w-full gap-3 px-4 py-3 text-left transition-colors hover:bg-accent/40">
                          <span className={cn("mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full", TONE[n.level])}>
                            <Icon className="size-3.5" />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className={cn("block truncate text-sm", !n.seen && "font-semibold")}>{n.title}</span>
                            <span className="line-clamp-2 text-xs text-muted-foreground">{n.detail}</span>
                          </span>
                          {!n.seen && <span className="mt-2 size-2 shrink-0 rounded-full bg-primary" aria-label="nouveau" />}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </div>
        <div className="border-t px-4 py-2 text-right">
          <button className="text-xs font-medium text-primary hover:underline" onClick={() => { setOpen(false); navigate("/agenda"); }}>
            Ouvrir l'agenda
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
