// Affichage des dates et des nombres. Tout est affiché en heure du Maroc, quel que soit
// le fuseau du PC : c'est l'heure qui compte pour les plages d'envoi.
const TZ = "Africa/Casablanca";

const dayTime = new Intl.DateTimeFormat("fr-FR", {
  timeZone: TZ, weekday: "long", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
});
const timeOnly = new Intl.DateTimeFormat("fr-FR", { timeZone: TZ, hour: "2-digit", minute: "2-digit" });
const dayKey = new Intl.DateTimeFormat("fr-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" });
const dayLabel = new Intl.DateTimeFormat("fr-FR", { timeZone: TZ, weekday: "long", day: "numeric", month: "long" });
const rel = new Intl.RelativeTimeFormat("fr", { numeric: "auto" });

export const formatDayTime = (iso: string) => dayTime.format(new Date(iso));
export const formatTime = (iso: string) => timeOnly.format(new Date(iso));
export const formatDayLabel = (iso: string) => {
  const s = dayLabel.format(new Date(iso));
  return s.charAt(0).toUpperCase() + s.slice(1);
};
/** Clé « 2026-11-04 » d'une date, en heure du Maroc (pour regrouper par jour). */
export const localDay = (iso: string) => dayKey.format(new Date(iso));

/** « il y a 2 minutes », « dans 3 heures »… */
export function relativeTime(iso: string | null, now: Date = new Date()): string {
  if (!iso) return "jamais";
  const diff = (new Date(iso).getTime() - now.getTime()) / 1000;
  const abs = Math.abs(diff);
  if (abs < 45) return diff < 0 ? "à l'instant" : "dans un instant";
  if (abs < 3600) return rel.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return rel.format(Math.round(diff / 3600), "hour");
  return rel.format(Math.round(diff / 86400), "day");
}

export const pct = (v: number | null) => (v === null ? "—" : `${Math.round(v * 100)} %`);

export const fullName = (c: { first_name: string | null; last_name: string | null; email: string }) =>
  [c.first_name, c.last_name].filter(Boolean).join(" ") || c.email;

/** « Vague 2 » (fichier d'origine) s'affiche « Lot 2 » : même valeur, mot plus parlant (V2.7). */
export const lot = (v: string | null | undefined) => (v ? v.replace(/^vague\b/i, "Lot") : v ?? null);
