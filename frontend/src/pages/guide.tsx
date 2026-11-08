// V2.16 : guide de démarrage ; V2.23 : morceaux réutilisés par les sous-pages (guide-pages.tsx).
// « Bien démarrer » (5 étapes, cochées d'elles-mêmes quand
// l'application peut le constater), puis un tour des écrans avec de vraies captures prises sur
// une base de démonstration (personnes et entreprises fictives), les bons réflexes et une FAQ.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Building2,
  CalendarDays,
  CheckCircle2,
  Clock,
  FlaskConical,
  FolderLock,
  Inbox,
  LayoutDashboard,
  ListOrdered,
  MessageSquareReply,
  MonitorCheck,
  Rocket,
  Send,
  Users,
  type LucideIcon,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { toastError } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { api, type GuideKey } from "@/lib/api";
import { SERVER_MODE } from "@/lib/auth";
import { cn } from "@/lib/utils";

const IMG = "/static/v2/guide/";

type Step = { key: GuideKey; title: string; text: ReactNode; href: string; cta: string; manual?: boolean };

const STEPS: Step[] = [
  {
    key: "mailbox", title: "Connecter votre boîte mail", href: "/settings", cta: "Réglages",
    get text() {
      return SERVER_MODE
        ? "Réglages → Boîte mail d'envoi : votre adresse, les serveurs indiqués dans le cPanel (envoi : port 587, sécurité STARTTLS), votre mot de passe, puis « Tester la connexion ». Le mot de passe est rangé chiffré sur le serveur."
        : "Réglages → Boîte mail d'envoi : votre adresse, les serveurs indiqués dans le cPanel, votre mot de passe, puis « Tester la connexion ». Le mot de passe reste dans le coffre-fort de Windows.";
    },
  },
  {
    key: "signature", title: "Mettre votre signature", href: "/settings", cta: "Réglages",
    text: "Même écran : nom, fonction, téléphone. Elle s'ajoute toute seule en bas de chaque email.",
  },
  {
    key: "test", title: "Faire un essai en mode test", href: "/sequences", cta: "Séquences", manual: true,
    text: <>Ajoutez-vous comme contact (Contacts → votre propre adresse), puis envoyez-vous une séquence de gestion, par exemple G6. En mode test, chaque email arrive chez vous avec l'objet [TEST → destinataire] : relisez-le comme si vous étiez le client. <b>Jamais d'essai sur un vrai contact</b> : ses relances encore prévues partiraient pour de vrai après le passage en mode réel.</>,
  },
  {
    key: "contacts", title: "Ajouter vos prospects", href: "/contacts/import", cta: "Importer", manual: true,
    text: "Contacts → Importer : téléchargez le modèle Excel, remplissez-le, importez-le. Les assureurs partenaires sont déjà là.",
  },
  {
    key: "real", title: "Passer en mode réel", href: "/settings", cta: "Réglages",
    text: "Une fois l'essai relu : Réglages → Mode test → désactiver, en tapant REEL pour confirmer. Les emails partent alors vraiment.",
  },
];

type Chapter = { id: string; icon: LucideIcon; title: string; img: string; lead: string; points: ReactNode[] };

const CHAPTERS: Chapter[] = [
  {
    id: "tableau", icon: LayoutDashboard, title: "Tableau de bord", img: "tableau-de-bord.png",
    lead: "Votre journée en un coup d'œil.",
    points: [
      <>Emails envoyés aujourd'hui et plafond du jour, prochain envoi, état du moteur.</>,
      <><b>Ils n'ont pas répondu</b> : vos emails restés sans réponse depuis 3 jours ouvrés.</>,
      <><b>À répondre</b> : les emails reçus auxquels vous n'avez pas encore répondu.</>,
      <><b>Aujourd'hui</b> : vos rappels du jour. Chaque carte s'ouvre d'un clic.</>,
    ],
  },
  {
    id: "boite", icon: Inbox, title: "Boîte mail", img: "boite-mail.png",
    lead: "Votre vraie boîte, lue par l'application : rien n'y est déplacé ni supprimé.",
    points: [
      <>Cliquez un email : <b>Répondre</b>, <b>Envoyer une séquence</b> à l'expéditeur, ou ajouter un <b>rappel</b>.</>,
      <><b>À répondre</b> : ce qui attend votre réponse. « Marquer comme répondu » retire ce qui est déjà traité.</>,
      <><b>Envoyés sans réponse</b> : les personnes à relancer.</>,
      <>Au clavier : ↑ ↓ pour changer d'email, R pour répondre, S pour envoyer une séquence.</>,
    ],
  },
  {
    id: "sequences", icon: ListOrdered, title: "Séquences", img: "sequences.png",
    lead: "Un premier email et ses relances, prêts à partir. 11 modèles sont déjà rédigés.",
    points: [
      <><b>Prospection</b> (P1 à P3) : pour les prospects uniquement.</>,
      <><b>Gestion</b> (avenant, délégation bancaire, sinistre, attestation…) et <b>Souscription</b> (cotation, proposition) : pour tout le monde, assureurs et clients compris.</>,
      <><b>Modifier</b> : objets, textes, délais entre les emails. <b>Textes personnalisés</b> : les paragraphes par fonction et par secteur insérés dans P1.</>,
      <>Les relances partent toutes seules dans la même conversation, et <b>s'arrêtent dès que la personne répond</b>.</>,
    ],
  },
  {
    id: "envoyer", icon: Send, title: "Envoyer une séquence", img: "envoyer-sequence.png",
    lead: "Depuis la page Séquences, un email reçu ou une fiche contact : quelques clics.",
    points: [
      <>Choisissez la séquence, puis la ou les personnes.</>,
      <><b>Personnaliser d'abord</b> : complétez les champs entre crochets, comme [N° de police] ou [Banque]. Tant qu'il en reste un, l'email ne part pas.</>,
      <>« Joindre un fichier pour cette personne » : carte grise, constat, demande de la banque…</>,
      <>Les dates prévues de chaque email s'affichent avant l'envoi.</>,
    ],
  },
  {
    id: "campagnes", icon: Rocket, title: "Campagnes", img: "campagnes.png",
    lead: "Pour écrire à tout un groupe d'un coup.",
    points: [
      <>1. <b>Quoi</b> : la séquence. 2. <b>Qui</b> : un groupe (fonction, secteur…) ou des personnes choisies. 3. <b>Vérifier et lancer</b>.</>,
      <>L'application vérifie chaque email avant le lancement et signale ce qui manque.</>,
      <>Suivi en direct : envoyés, réponses, prochains envois. « Mettre en pause » à tout moment.</>,
    ],
  },
  {
    id: "agenda", icon: CalendarDays, title: "Agenda", img: "agenda.png",
    lead: "Vos rappels : rappeler quelqu'un, relancer un dossier.",
    points: [
      <>Le petit « + » à côté d'une date ajoute un rappel ce jour-là.</>,
      <>Un rappel peut viser une personne : sa fiche s'ouvre d'un clic.</>,
      <>Les rappels du jour apparaissent sur le tableau de bord et dans la cloche en haut.</>,
    ],
  },
  {
    id: "contacts", icon: Building2, title: "Entreprises et contacts", img: "entreprises.png",
    lead: "Les compagnies partenaires sont déjà là, avec leur logo et leurs interlocuteurs par service.",
    points: [
      <>Sur la fiche d'une compagnie : « Séquence au service… » écrit d'un coup à tout le service Souscription ou Gestion.</>,
      <>Chaque contact a un type : prospect, client, assureur ou partenaire. Seuls les prospects reçoivent de la prospection.</>,
      <>La fiche d'une personne montre vos derniers emails échangés avec elle.</>,
    ],
  },
];

type Rule = { icon: LucideIcon; title: string; text: string };
const SERVER_RULES: Record<string, Rule> = {
  "La fenêtre noire reste ouverte": { icon: MonitorCheck, title: "L'appli tourne en ligne", text: "Elle envoie et lit votre boîte 24 h/24, même PC éteint. Ouvrez-la depuis votre navigateur, avec votre compte." },
  "Se répartir les prospects": { icon: Users, title: "Un prospect, un responsable", text: "Le premier qui écrit à un prospect le suit ; l'appli refuse qu'un collègue lui écrive aussi. Les compagnies d'assurance sont communes." },
  "Ne jamais supprimer le dossier « data »": { icon: FolderLock, title: "Modèles communs : on duplique", text: "Les modèles de l'équipe ne se modifient pas (sauf l'administrateur) : « Dupliquer » crée votre version, que vous seul voyez." },
};
const RULES_PC: Rule[] = [
  { icon: FlaskConical, title: "Toujours commencer en mode test", text: "Badge orange en haut : chaque email part vers vous. On passe en réel seulement après avoir relu un essai." },
  { icon: MonitorCheck, title: "La fenêtre noire reste ouverte", text: "C'est le moteur d'envoi : réduisez-la, ne la fermez pas. PC éteint ou en veille : rien ne part, l'envoi reprend au redémarrage." },
  { icon: Clock, title: "Un rythme raisonnable", text: "Envois les jours ouvrés, aux heures de bureau, 25 par jour au plus. Toute l'équipe partage le domaine email du cabinet : trop d'envois ou de rebonds pénalisent tout le monde." },
  { icon: Users, title: "Se répartir les prospects", text: "Chacun a sa propre application : elle ne voit pas les envois des collègues. Deux personnes ne doivent pas prospecter la même entreprise." },
  { icon: MessageSquareReply, title: "Une réponse arrête les relances", text: "Dès qu'une personne répond, les relances de cette conversation s'arrêtent d'elles-mêmes. Pensez à lui répondre vous-même !" },
  { icon: FolderLock, title: "Ne jamais supprimer le dossier « data »", text: "Il contient vos contacts et votre historique. Une sauvegarde est faite à chaque démarrage." },
];
const rules = () => RULES_PC.map((r) => (SERVER_MODE && SERVER_RULES[r.title]) || r);

const FAQ: { q: string; a: ReactNode }[] = [
  { q: "Mon email ne part pas, pourquoi ?", a: <>Il reste peut-être un champ entre crochets à compléter, ou l'on est hors des heures d'envoi : il partira au prochain créneau. Vérifiez aussi le point vert « Boîte lue » en haut de l'écran : en rouge, rien ne part tant que la boîte est illisible.</> },
  { q: "Où retrouver les emails envoyés ?", a: <>Dans le dossier « Envoyés » de votre boîte, comme d'habitude : l'application envoie depuis votre vraie adresse.</> },
  { q: "Comment arrêter les relances pour une personne ?", a: <>Elles s'arrêtent d'elles-mêmes si elle répond. Sinon : Campagnes → la campagne → menu de la personne → « Retirer de la campagne ». Pour tout arrêter : « Mettre en pause ».</> },
  { q: "Puis-je modifier un modèle ?", a: <>Oui : Séquences → Modifier. Pour un seul envoi, utilisez plutôt « Personnaliser d'abord » : le modèle reste intact.</> },
  { q: "Mes collègues voient-ils mes contacts ?", get a() {
    return SERVER_MODE
      ? <>Les contacts et les compagnies sont communs à l'équipe : chacun voit qui suit quel prospect. Mais vos emails, vos campagnes, vos réponses, votre agenda et vos modèles personnels ne sont visibles que par vous.</>
      : <>Non. Tout reste sur votre PC : contacts, emails, agenda.</>;
  } },
];

export function useGuide() {
  return useQuery({ queryKey: ["guide"], queryFn: api.guide, refetchInterval: 30_000 });
}

/** Bandeau du tableau de bord tant que « Bien démarrer » n'est pas terminé. */
export function GuideBanner() {
  const { data } = useGuide();
  if (!data || data.done >= data.total) return null;
  return (
    <Card className="border-primary/30 bg-primary/5">
      <CardContent className="flex flex-wrap items-center gap-4 p-4">
        <div className="min-w-0 flex-1">
          <p className="font-medium">Bien démarrer : {data.done} étape{data.done > 1 ? "s" : ""} sur {data.total}</p>
          <div className="mt-2 h-1.5 max-w-sm overflow-hidden rounded-full bg-primary/15">
            <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${(100 * data.done) / data.total}%` }} />
          </div>
        </div>
        <Button asChild><Link to="/guide/bien-demarrer">Continuer <ArrowRight /></Link></Button>
      </CardContent>
    </Card>
  );
}

/** Image cliquable qui s'agrandit (captures du guide). */
export function ZoomImage({ src, alt, className, frameClassName }: { src: string; alt: string; className?: string; frameClassName?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} title="Agrandir" className={cn("group block w-full", frameClassName)}>
        <img src={src} alt={alt} loading="lazy" className={cn("w-full rounded-md border shadow-sm transition-transform group-hover:scale-[1.005]", className)} />
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-[min(1400px,95vw)] p-2 sm:p-3">
          <DialogTitle className="sr-only">{alt}</DialogTitle>
          <img src={src} alt={alt} className="w-full rounded-md" />
        </DialogContent>
      </Dialog>
    </>
  );
}

/** « Bien démarrer » : 5 étapes, cochées d'elles-mêmes quand l'application peut le constater. */
export function StartChecklist({ compact = false }: { compact?: boolean }) {
  const { data } = useGuide();
  const qc = useQueryClient();
  const check = useMutation({
    mutationFn: ({ key, done }: { key: GuideKey; done: boolean }) => api.guideCheck(key, done),
    onSuccess: (r) => qc.setQueryData(["guide"], r),
    onError: (e) => toastError(e),
  });
  const done = data?.done ?? 0;
  const total = data?.total ?? STEPS.length;
  if (compact && data && done >= total) {
    return (
      <Card className="border-success/30 bg-success/5">
        <CardContent className="flex items-center gap-3 p-4 text-sm"><CheckCircle2 className="size-5 text-success" />Bien démarrer : les 5 étapes sont faites. Vous êtes prêt.</CardContent>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <CardTitle className="text-base">Bien démarrer</CardTitle>
            <CardDescription>Cinq étapes, à faire une seule fois.</CardDescription>
          </div>
          <p className="text-sm text-muted-foreground tabular">{done} / {total}</p>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-accent">
          <div className="h-full rounded-full bg-success transition-all" style={{ width: `${(100 * done) / total}%` }} />
        </div>
      </CardHeader>
      <CardContent className="divide-y p-0">
        {STEPS.map((s, i) => {
          const ok = data?.steps[s.key] ?? false;
          return (
            <div key={s.key} className="flex flex-col gap-3 px-5 py-3.5 sm:flex-row sm:items-start">
              <div className={cn("flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
                ok ? "bg-success text-success-foreground" : "bg-accent text-accent-foreground")}>
                {ok ? <CheckCircle2 className="size-4" /> : i + 1}
              </div>
              <div className="min-w-0 flex-1">
                <p className={cn("font-medium", ok && "text-muted-foreground line-through decoration-1")}>{s.title}</p>
                {!(compact && ok) && <p className="mt-0.5 text-sm text-muted-foreground">{s.text}</p>}
              </div>
              <div className="flex shrink-0 gap-2">
                {s.manual && (
                  <Button size="sm" variant="ghost" disabled={check.isPending}
                    onClick={() => check.mutate({ key: s.key, done: !ok })}>
                    {ok ? "Décocher" : "C'est fait"}
                  </Button>
                )}
                <Button size="sm" variant={ok ? "outline" : "default"} asChild><Link to={s.href}>{s.cta}</Link></Button>
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

/** Le tour des écrans (captures + points à retenir). */
export function ScreensTour() {
  return (
    <section className="space-y-5">
      <nav className="flex flex-wrap gap-1.5">
        {CHAPTERS.map((c) => (
          <a key={c.id} href={`#${c.id}`}
            className="inline-flex items-center gap-1.5 rounded-full border bg-card px-3 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground">
            <c.icon className="size-3.5" />{c.title}
          </a>
        ))}
      </nav>
      {CHAPTERS.map((c, i) => (
        <Card key={c.id} id={c.id} className="scroll-mt-20 overflow-hidden">
          <div className={cn("grid items-center gap-0 lg:grid-cols-5", i % 2 === 1 && "lg:[&>*:first-child]:order-2")}>
            <div className="border-b bg-accent/40 p-4 lg:col-span-3 lg:border-b-0 lg:border-r">
              <ZoomImage src={IMG + c.img} alt={`Écran ${c.title}`} />
            </div>
            <div className="space-y-3 p-5 lg:col-span-2">
              <div className="flex items-center gap-2">
                <span className="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary"><c.icon className="size-4" /></span>
                <h3 className="font-semibold">{c.title}</h3>
              </div>
              <p className="text-sm">{c.lead}</p>
              <ul className="space-y-2 text-sm text-muted-foreground">
                {c.points.map((p, k) => (
                  <li key={k} className="flex gap-2"><span className="mt-2 size-1 shrink-0 rounded-full bg-primary" /><span>{p}</span></li>
                ))}
              </ul>
            </div>
          </div>
        </Card>
      ))}
    </section>
  );
}

export function RulesGrid() {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {rules().map((r) => (
        <Card key={r.title}>
          <CardContent className="space-y-2 p-4">
            <r.icon className="size-5 text-primary" />
            <p className="font-medium">{r.title}</p>
            <p className="text-sm text-muted-foreground">{r.text}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export function FaqList() {
  return (
    <Card className="divide-y">
      {FAQ.map((f) => (
        <details key={f.q} className="group px-5 py-3.5 [&_summary::-webkit-details-marker]:hidden">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 font-medium">
            {f.q}
            <ArrowRight className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-90" />
          </summary>
          <p className="mt-2 text-sm text-muted-foreground">{f.a}</p>
        </details>
      ))}
    </Card>
  );
}
