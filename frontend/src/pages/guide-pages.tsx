// V2.23 : le guide en sous-pages. Un menu à gauche (Bien démarrer tant qu'il n'est pas fini,
// rubriques, cas d'usage, avec recherche), une page d'accueil, des rubriques et des « recettes »
// pas à pas avec des captures annotées (base de démonstration : personnes et entreprises fictives).
import {
  ArrowLeft, ArrowRight, BookOpen, Braces, Building2, CalendarDays, CheckCircle2, Clock, Compass, FilePlus2, FileSignature,
  HelpCircle, Inbox, Landmark, Lightbulb, ListOrdered, Rocket, Search, Settings2, ShieldAlert, Sparkles,
  Sun, Target, Users, Zap, type LucideIcon,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useParams } from "react-router-dom";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { SERVER_MODE } from "@/lib/auth";
import { cn } from "@/lib/utils";
import { FaqList, RulesGrid, ScreensTour, StartChecklist, useGuide, ZoomImage } from "@/pages/guide";

const CAS = "/static/v2/guide/cas/";

const B = ({ children }: { children: ReactNode }) => <b className="font-medium text-foreground">{children}</b>;
const P = ({ children }: { children: ReactNode }) => <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">{children}</p>;
const H2 = ({ children, id }: { children: ReactNode; id?: string }) => <h2 id={id} className="scroll-mt-24 pt-2 text-base font-semibold">{children}</h2>;
const CaseLink = ({ to, children }: { to: string; children: ReactNode }) => <Link to={`/guide/cas/${to}`} className="text-primary hover:underline">{children}</Link>;

function Shot({ img, alt, caption }: { img: string; alt: string; caption?: ReactNode }) {
  return (
    <figure className="max-w-2xl space-y-1.5">
      <div className="rounded-lg border bg-accent/30 p-2"><ZoomImage src={CAS + img} alt={alt} className="border-0 shadow-none" /></div>
      {caption && <figcaption className="text-xs text-muted-foreground">{caption}</figcaption>}
    </figure>
  );
}

/** V2.24 : vidéos du guide (servies par l'appli, rien à télécharger). */
const VID = "/static/v2/guide/videos/";
function Video({ file, title, caption }: { file: string; title: string; caption?: ReactNode }) {
  return (
    <figure className="max-w-3xl space-y-1.5">
      <video controls preload="none" poster={`${VID}${file}.jpg`} className="w-full rounded-lg border bg-black" aria-label={title}>
        <source src={`${VID}${file}.mp4`} type="video/mp4" />
      </video>
      {caption && <figcaption className="text-xs text-muted-foreground">{caption}</figcaption>}
    </figure>
  );
}

function Points({ items }: { items: ReactNode[] }) {
  return (
    <ul className="max-w-3xl space-y-1.5 text-sm text-muted-foreground">
      {items.map((t, i) => <li key={i} className="flex gap-2"><span className="mt-2 size-1 shrink-0 rounded-full bg-primary" /><span>{t}</span></li>)}
    </ul>
  );
}

function Table({ rows, head }: { rows: ReactNode[][]; head: string[] }) {
  return (
    <div className="max-w-3xl overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead className="bg-accent/50 text-left text-xs text-muted-foreground"><tr>{head.map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr></thead>
        <tbody className="divide-y">{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className={cn("px-3 py-2 align-top", j ? "text-muted-foreground" : "font-medium")}>{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

/* ------------------------------------------------------------------ rubriques */

type Section = { slug: string; title: string; icon: LucideIcon; lead: string; keywords: string; body: () => ReactNode;
  /** V3 : rubrique propre à l'appli en ligne (comptes, équipe). */
  serverOnly?: boolean };

const SECTIONS: Section[] = [
  { slug: "prise-en-main", title: "Prise en main", icon: Compass, keywords: "démarrer fenêtre noire mode test réel plage envoi réflexes",
    lead: "Comment l'appli travaille, et les bons réflexes.",
    body: () => <>
      <H2>Comment l'appli travaille</H2>
      <Points items={[
        SERVER_MODE
          ? <>L'appli tourne <B>en ligne, 24 h/24</B> : les emails partent et votre boîte est lue même quand votre PC est éteint. Vous l'ouvrez depuis votre navigateur, avec votre email et votre mot de passe.</>
          : <>La <B>fenêtre noire</B> est le moteur : tant qu'elle est ouverte (réduite, pas fermée) et le PC allumé, les emails partent et la boîte est lue. PC éteint ou en veille : rien ne part, tout reprend au redémarrage, rien n'est perdu.</>,
        <>Les emails partent <B>un par un</B>, les jours ouvrés, aux heures de bureau (par défaut 9 h – 12 h 30 et 14 h 30 – 17 h 30), 25 par jour au plus : comme des emails écrits à la main.</>,
        <>Votre boîte est lue <B>toutes les 5 minutes</B> : les réponses arrêtent les relances, les emails reçus apparaissent dans la Boîte mail. Le point vert « Boîte lue » en haut le confirme.</>,
        <>Le <B>mode test</B> (badge orange en haut) envoie chaque email vers votre propre adresse, avec l'objet [TEST → destinataire]. On passe en réel dans Réglages → Mode test, en tapant REEL.</>,
        SERVER_MODE
          ? <>Vos <B>emails, campagnes, réponses, agenda et modèles personnels</B> ne sont visibles que par vous. Les contacts et les compagnies sont communs à l'équipe : <Link to="/guide/equipe" className="text-primary hover:underline">Travailler en équipe</Link>.</>
          : <>Tout reste <B>sur votre PC</B> : vos collègues ne voient ni vos contacts ni vos envois. Une sauvegarde est faite à chaque démarrage et chaque jour.</>,
        <>Tant que vous débutez : <B>relisez chaque email avant l'envoi</B> (Personnaliser d'abord) et comprenez les balises {"{{ … }}"} et [ … ] : <Link to="/guide/balises" className="text-primary hover:underline">Balises et relecture</Link>.</>,
      ]} />
      <H2>Les bons réflexes</H2>
      <RulesGrid />
    </> },
  { slug: "balises", title: "Balises et relecture", icon: Braces, keywords: "balise variable accolades crochets champs prénom relire vérifier personnaliser aperçu tel quel",
    lead: "Les {{ variables }} remplies par l'appli, les [champs] remplis par vous, et comment relire avant d'envoyer.",
    body: () => <>
      <P>Un modèle est un texte à trous. Il y a deux sortes de trous, les <B>balises</B> : celles que l'appli remplit toute seule, et celles que vous devez remplir.</P>
      <Table head={["Balise", "Qui la remplit", "Exemple"]} rows={[
        [<code className="text-xs">{"{{ prenom }}"}</code>, <>L'appli, depuis la fiche du contact (prénom, nom, entreprise, poste, secteur). Les boutons <B>Prénom</B>, <B>Entreprise</B>… de l'éditeur les insèrent.</>, <>« Bonjour {"{{ prenom }}"} » devient « Bonjour Karima »</>],
        [<code className="text-xs">{'{{ prenom | "Madame, Monsieur" }}'}</code>, <>Pareil, avec une <B>valeur de repli</B> après la barre | si l'information manque sur la fiche.</>, <>Sans prénom : « Bonjour Madame, Monsieur »</>],
        [<code className="text-xs">{"{{ bloc_cible }}"}</code>, <>L'appli : un paragraphe entier choisi selon la fonction ou le secteur (Séquences → Textes personnalisés).</>, "Prospection seulement"],
        [<code className="text-xs">[N° de police]</code>, <><B>Vous</B>, à chaque envoi : ce qui est propre au dossier, que l'appli ne peut pas deviner.</>, <>« police n° [N° de police] » → « police n° 40.123.456 »</>],
      ]} />
      <H2>Ce qui bloque un envoi (et c'est voulu)</H2>
      <Points items={[
        <>Un <B>[champ]</B> pas remplacé : l'email ne part pas (séquence) ou l'appli demande confirmation (Nouveau message).</>,
        <>Une variable sans valeur et sans repli (ex. {"{{ entreprise }}"} pour un contact sans entreprise) : l'email ne part pas, l'appli dit lequel et pourquoi.</>,
        <>Une accolade abîmée ({"{{ prenom }"}, {"{ prenom }}"}) : « Variable mal écrite ». Ne tapez pas les accolades à la main : utilisez les boutons.</>,
      ]} />
      <H2>Relire avant d'envoyer : la règle tant qu'on débute</H2>
      <Shot img="avenant-4.png" alt="Personnaliser d'abord : l'email tel qu'il partira, et l'encadré des champs à compléter"
        caption={<>« Personnaliser d'abord » : l'email écrit pour cette personne, variables remplies. L'encadré orange (2) liste ce qui reste à compléter.</>} />
      <Points items={[
        <>Choisissez toujours <B>Personnaliser d'abord</B> : vous voyez l'email exact, variables remplies, et chaque relance dans son onglet. Corrigez librement : seul l'email de cette personne change, pas le modèle.</>,
        <><B>Envoyer tel quel</B> : pour plus tard, quand vous connaissez bien le modèle et qu'il n'a pas de [champs].</>,
        <>Dans tous les cas, un dernier écran <B>Vérifier avant d'envoyer</B> montre chaque email exact (objet, texte, signature, pièces jointes, date prévue), personne par personne. Rien ne part avant <B>Confirmer l'envoi</B>. Il signale aussi un « ci-joint » sans fichier joint.</>,
        <>Pour tester sans risque : le <B>mode test</B> envoie tout chez vous, avec l'objet [TEST → destinataire]. Lisez-le comme si vous étiez le client.</>,
      ]} />
      <H2>Relire un modèle dans l'éditeur</H2>
      <Shot img="modele-2.png" alt="L'éditeur : boutons de variables, texte, aperçu pour un vrai contact"
        caption={<>Les boutons (1) insèrent les variables dans le texte (2). À droite, l'aperçu pour un vrai contact ; en dessous, ce qui bloquerait l'envoi.</>} />
      <Points items={[
        <>L'<B>Aperçu</B> montre l'email rendu pour un contact réel ; les flèches passent au contact suivant.</>,
        <>Sous l'aperçu, « problème pour ce contact » dit ce qui bloquerait l'envoi (un [champ], une variable vide).</>,
        <><B>M'envoyer les emails</B> vous envoie la séquence pour la relire dans votre boîte.</>,
      ]} />
    </> },
  { slug: "tour", title: "Le tour de l'appli", icon: Sparkles, keywords: "écrans tableau de bord boîte mail séquences campagnes agenda entreprises",
    lead: "La vidéo de présentation (4 min), puis chaque écran en une capture et quatre points à retenir.",
    body: () => <>
      <Video file="tour" title="Le tour de l'appli" caption="4 minutes, sous-titrée : tableau de bord, boîte mail, envoyer une séquence, agenda, séquences, campagnes, entreprises, contacts, réglages." />
      <ScreensTour />
    </> },
  { slug: "boite-mail", title: "Boîte mail au quotidien", icon: Inbox, keywords: "lire répondre transférer archiver à répondre raccourcis pièces jointes modèles nouveau message",
    lead: "Lire, répondre, transférer, archiver, ne rien laisser sans réponse.",
    body: () => <>
      <H2>Les quatre onglets</H2>
      <Table head={["Onglet", "Ce qu'on y trouve"]} rows={[
        ["Boîte de réception", "Tous les emails reçus (30 derniers jours par défaut ; le menu à côté change de dossier ou de période). « Mes contacts » ne garde que les emails de vos contacts."],
        ["À répondre", "Les emails reçus de n'importe qui (contacts ou pas ; newsletters et envois automatiques exclus) restés sans réponse de votre part depuis 3 jours ouvrés. Un email d'aujourd'hui n'y est donc pas encore : il est dans la Boîte de réception. « Marquer comme répondu » le retire quand c'est réglé autrement (téléphone…). Le délai se change dans Réglages → Rythme d'envoi."],
        ["Envoyés sans réponse", "Vos emails restés sans réponse depuis 3 jours ouvrés : une relance à faire ?"],
        ["Réponses aux campagnes", "Les réponses aux séquences, à classer (Intéressé, À rappeler plus tard…)."],
      ]} />
      <H2>Lire et traiter un email</H2>
      <Shot img="matinee-2.png" alt="Un email ouvert : Répondre, Archiver, Rappel, Envoyer une séquence"
        caption={<>Répondre (1), Archiver (2), Rappel (3), Envoyer une séquence (4). Transférer est à côté d'Archiver.</>} />
      <Points items={[
        <>Les emails s'affichent comme dans Outlook, images comprises. Les images venant d'Internet restent bloquées jusqu'à votre clic : c'est une protection contre le suivi d'ouverture.</>,
        <>Les <B>pièces jointes</B> s'ouvrent d'un clic (PDF, images) ou se téléchargent (Word, Excel).</>,
        <><B>Transférer</B> renvoie l'email avec ses pièces jointes. <B>Archiver</B> le range dans le dossier Archives de votre boîte, rien n'est effacé ; « Annuler » juste après le remet.</>,
        <>Lire un email dans l'appli ne le marque pas comme lu sur le serveur.</>,
        <>Raccourcis : ↑ ↓ pour passer d'un email à l'autre, R répondre, F transférer, E archiver, S envoyer une séquence.</>,
        <>L'expéditeur n'est pas dans vos contacts ? <B>Créer le contact</B> l'ajoute en un clic.</>,
      ]} />
      <H2>Écrire un email : Nouveau message et Modèles</H2>
      <Shot img="avenant-rapide-1.png" alt="Nouveau message avec le menu Modèles ouvert" caption={<>Le destinataire (1), le bouton Modèles (2), puis le modèle voulu (3).</>} />
      <Points items={[
        <><B>Modèles</B> insère le 1er email d'une séquence, déjà écrit au nom du destinataire, avec ses pièces jointes. Pratique pour une demande ponctuelle, sans relances.</>,
        <>S'il reste des [champs] entre crochets, ou si l'objet est vide, l'appli demande confirmation avant d'envoyer.</>,
        <>En mode test, l'email part vers vous. La signature s'ajoute toute seule (case à décocher en bas).</>,
      ]} />
    </> },
  { slug: "sequences", title: "Séquences et modèles", icon: ListOrdered, keywords: "modifier texte champs crochets personnaliser modèles relances variables a/b textes personnalisés",
    lead: "Les 11 modèles, les [champs] à compléter, Personnaliser d'abord, modifier un modèle.",
    body: () => <>
      <P>Une séquence, c'est un premier email puis des relances, envoyées seulement si la personne ne répond pas. Dès qu'elle répond, la suite s'arrête.</P>
      <H2>Les 11 modèles fournis</H2>
      <Table head={["Modèle", "Pour qui, pour quoi", "Emails"]} rows={[
        ["P1 · Prospection entreprise", "Premier contact avec un prospect (texte adapté à sa fonction et à son secteur)", "3 sur 7 jours"],
        ["P2 · Suite à un rendez-vous", <>Le prospect rencontré : merci, et les documents à nous transmettre (<CaseLink to="rendez-vous">recette</CaseLink>)</>, "3 sur 9 jours"],
        ["P3 · Avant l'échéance des contrats", <>Un prospect avant le renouvellement de ses contrats (<CaseLink to="renouvellement">recette</CaseLink>)</>, "2 sur 5 jours"],
        ["G1 · Demande d'avenant", <>Gestionnaire de la compagnie (<CaseLink to="avenant">recette</CaseLink>)</>, "3 sur 7 jours"],
        ["G2 · Délégation bancaire", <>Gestionnaire, avec la demande de la banque (<CaseLink to="delegation">recette</CaseLink>)</>, "3 sur 7 jours"],
        ["G3 · Déclaration de sinistre", <>Gestionnaire sinistres (<CaseLink to="sinistre">recette</CaseLink>)</>, "3 sur 7 jours"],
        ["G4 · Suivi de sinistre", "Gestionnaire sinistres, avec la référence du dossier", "3 sur 10 jours"],
        ["G5 · Demande d'attestation", "Gestionnaire : un document pour un client (attestation…)", "3 sur 5 jours"],
        ["G6 · Documents à fournir (client)", "Votre client : les pièces qui manquent à son dossier", "3 sur 9 jours"],
        ["S1 · Demande de cotation", <>Souscripteurs des compagnies (<CaseLink to="cotation">recette</CaseLink>)</>, "3 sur 7 jours"],
        ["S2 · Envoi de proposition", "Votre client : la proposition retenue, en pièce jointe", "3 sur 10 jours"],
      ]} />
      <P>Les jours comptent en jours ouvrés. Prospection : prospects seulement. Gestion et souscription : clients, assureurs et partenaires (et prospects).</P>
      <H2>Les [champs] entre crochets</H2>
      <Points items={[
        <>[N° de police], [Nom de l'assuré]… sont propres à chaque dossier : l'appli ne peut pas les deviner. <B>Tant qu'il en reste un, l'email ne part pas.</B></>,
        <>Pour une personne : <B>Personnaliser d'abord</B>, puis remplacez chaque crochet dans le texte. Le modèle lui-même ne change pas.</>,
        <>Pour plusieurs personnes (3 compagnies pour une cotation) : un formulaire demande chaque [champ] <B>une seule fois</B> ; chacun reçoit son propre email, à son nom (<CaseLink to="cotation">voir la recette</CaseLink>).</>,
        <>Les relances reprennent ce que vous avez écrit dans le 1er email.</>,
        <>Pas besoin de relances ? Au moment d'envoyer, « Que faut-il envoyer ? » : <B>1er email seulement</B> (ou 1er email + 1 relance). Les emails retirés ne partent pas et leurs [champs] ne sont pas demandés.</>,
        <>Tout sur les balises et la relecture : <Link to="/guide/balises" className="text-primary hover:underline">Balises et relecture</Link>.</>,
      ]} />
      <H2>Vos propres modèles</H2>
      <P>Une demande que vous écrivez souvent (cotation AT, attestation de salaire…) ? Créez-la une fois : Séquences → <B>Nouvelle séquence</B> → « Un seul email ». Elle apparaît ensuite dans <B>Modèles</B> de chaque Nouveau message. Pas à pas : <CaseLink to="modele-perso">Créer mon propre modèle d'email</CaseLink>.</P>
      <H2>Modifier un modèle</H2>
      <Shot img="rubrique-editeur.png" alt="L'éditeur d'une séquence : étapes, texte, aperçu" />
      <Points items={[
        <>Séquences → <B>Modifier</B>. À gauche les étapes et leurs délais (« +3 jours ouvrés »), au centre le texte, à droite l'aperçu tel que le destinataire le recevra. Enregistrement automatique.</>,
        <>Les boutons <B>Prénom</B>, <B>Entreprise</B>… insèrent une variable remplie pour chaque personne ; « Madame, Monsieur » si le prénom manque.</>,
        <>« Réponse dans le fil » : la relance arrive dans la même conversation (objet « Re: … »).</>,
        <>« Tester un second objet (A/B) » : deux objets répartis au hasard, comparés dans le suivi des campagnes.</>,
        <>Une modification vaut pour les prochains envois. Pour un seul envoi, préférez <B>Personnaliser d'abord</B>.</>,
      ]} />
      <H2>Textes personnalisés (prospection)</H2>
      <Shot img="rubrique-textes.png" alt="Textes personnalisés : un texte par fonction et un par secteur, l'email assemblé à droite" />
      <P>Séquences → <B>Textes personnalisés</B>. Chaque email de prospection contient un paragraphe selon la <B>fonction</B> du contact et un selon son <B>secteur</B> (le « code séquence », ex. FIN-IND). Choisissez un profil : vous voyez l'email assemblé à droite.</P>
    </> },
  { slug: "campagnes", title: "Campagnes", icon: Rocket, keywords: "groupe prospection lancer pause retirer suivi exporter à l'unité",
    lead: "Écrire à un groupe, suivre, mettre en pause.",
    body: () => <>
      <P>Une campagne envoie une séquence à un groupe de contacts, un email à la fois. Pour une seule personne, pas besoin de campagne : <B>Envoyer une séquence</B> depuis sa fiche ou un email.</P>
      <H2>Lancer : 3 étapes</H2>
      <Table head={["Étape", "Ce que vous choisissez"]} rows={[
        ["Quoi", "La séquence, un nom, le démarrage (dès le lancement ou à une date), « Arrêter si un collègue répond »."],
        ["Qui", "Un groupe (fonction, secteur, profil, lot d'envoi, qualité de l'email) ou des personnes cochées une à une. Le compteur dit combien la recevront."],
        ["Vérifier et lancer", "Le nombre d'inscrits, le premier envoi, la fin estimée ; Lancer la campagne ou Garder en brouillon."],
      ]} />
      <Shot img="prospecter-5.png" alt="Étape Qui : filtre par lot d'envoi et compteur" caption={<>Le pas à pas complet, avec un import Excel : <CaseLink to="prospecter">Prospecter une liste de directeurs financiers</CaseLink>.</>} />
      <H2>Suivre</H2>
      <Shot img="prospecter-7.png" alt="Page d'une campagne : Mettre en pause, Réponses" />
      <Points items={[
        <>Les chiffres : contacts, en cours, emails envoyés, <B>réponses</B>, intéressés, rebonds et STOP. Plus bas : les emails par étape, les taux de réponse par profil et par objet (A/B).</>,
        <><B>Mettre en pause</B> arrête tout envoi de la campagne ; <B>Reprendre</B> continue là où on s'était arrêté.</>,
        <>Pour une seule personne : menu « … » sur sa ligne → <B>Retirer de la campagne</B>.</>,
        <>L'onglet <B>À vérifier</B> liste les envois en erreur ou à revoir : un coup d'œil de temps en temps.</>,
        <><B>Exporter</B> sort la liste et les résultats dans un fichier.</>,
        <>Les envois « à l'unité » (depuis une fiche ou un email) sont regroupés par séquence, dans une campagne « À l'unité – G1 » par exemple : c'est là qu'on les suit ou les met en pause.</>,
      ]} />
    </> },
  { slug: "assureurs", title: "Assureurs et contacts", icon: Building2, keywords: "compagnie service souscription gestion import excel type contact client partenaire",
    lead: "Fiches compagnie par service, types de contact, import Excel.",
    body: () => <>
      <H2>Quatre types de contact</H2>
      <Table head={["Type", "Ce qui est permis"]} rows={[
        ["Prospect", "Reçoit la prospection (P1 à P3), et les autres séquences si besoin."],
        ["Client", "Jamais de prospection. Séquences de gestion et de souscription (G6, S2…)."],
        ["Assureur", "Jamais de prospection. G1 à G5, S1 : les demandes aux compagnies."],
        ["Partenaire", "Jamais de prospection. Gestion et souscription."],
      ]} />
      <P>Le type se règle sur la fiche de l'entreprise (« Relation ») et s'applique à toutes ses personnes.</P>
      <H2>La fiche d'une compagnie</H2>
      <Shot img="cotation-1.png" alt="Fiche compagnie : onglets par service et bouton Séquence au service" caption={<>Le bouton « Séquence au service… » (1) écrit à toutes les personnes de l'onglet choisi (2).</>} />
      <Points items={[
        <>Les personnes sont rangées par <B>service</B> (Souscription, Gestion, Production, Maritime / transport) et par niveau (directeur, senior, junior).</>,
        <><B>Ajouter une personne</B> (ou « Ajouter en Souscription » depuis un onglet) : vous revenez sur la fiche ensuite.</>,
        <>Sur chaque ligne : écrire un email, ajouter un rappel, modifier.</>,
        <>Les derniers échanges avec la compagnie, ses rappels et vos notes sont sur la même page.</>,
      ]} />
      <H2>Importer une liste</H2>
      <P>Contacts → <B>Importer</B> : un fichier Excel ou CSV. Le modèle Excel à télécharger a des listes déroulantes (type de contact, service, niveau, cible, secteur…). Rien n'est enregistré avant votre confirmation ; un email déjà connu met à jour la fiche au lieu de créer un doublon. Le pas à pas : <CaseLink to="prospecter">Prospecter une liste</CaseLink>.</P>
    </> },
  { slug: "agenda", title: "Agenda et rappels", icon: CalendarDays, keywords: "rappel aujourd'hui notification cloche renouvellement rendez-vous",
    lead: "Ne rien oublier : rappels, Aujourd'hui, notifications.",
    body: () => <>
      <Shot img="rubrique-agenda.png" alt="L'agenda : le mois, Aujourd'hui, Dans les 2 semaines" />
      <Points items={[
        <><B>Ajouter un rappel</B> : depuis l'Agenda, la fiche d'un contact ou d'une entreprise, ou un email ouvert (bouton Rappel).</>,
        <>Six types : Appeler, Envoyer un email, Relancer un devis, Rendez-vous, Renouvellement, Autre. Le titre se propose tout seul (« Renouvellement du contrat de… »).</>,
        <>Le jour venu, le rappel apparaît dans <B>Aujourd'hui</B> (tableau de bord), dans la <B>cloche</B> et dans l'agenda. Cochez-le une fois fait.</>,
        <>Une réponse classée « À rappeler plus tard » revient elle aussi sur le tableau de bord et dans la cloche à la date choisie.</>,
      ]} />
      <Shot img="echeance-1.png" alt="Ajouter un rappel : type, personne, date, note" caption={<>Exemple : <CaseLink to="renouvellement">un prospect avant son échéance</CaseLink>.</>} />
    </> },
  { slug: "equipe", title: "Travailler en équipe", icon: Users, serverOnly: true,
    keywords: "compte connexion mot de passe oublié invitation équipe collègue responsable prospect modèle commun dupliquer administrateur",
    lead: "Votre compte, ce que voient vos collègues, les règles communes.",
    body: () => <>
      <H2>Votre compte</H2>
      <Points items={[
        <>Vous recevez une <B>invitation par email</B> de l'administrateur : le lien vous fait choisir votre mot de passe (10 caractères minimum).</>,
        <>Ensuite, vous vous connectez avec votre <B>email professionnel</B> et ce mot de passe. Oublié ? « Mot de passe oublié ? » sur l'écran de connexion.</>,
        <>Première chose à faire : <B>Réglages → Boîte mail</B> (port d'envoi 587, sécurité STARTTLS), puis « Tester la connexion ». Votre mode test est activé par défaut.</>,
        <>Votre compte est personnel : ne le partagez pas. Menu rond en haut à droite → <B>Se déconnecter</B> sur un ordinateur partagé.</>,
      ]} />
      <H2>Qui voit quoi</H2>
      <Table head={["", "Visible par"]} rows={[
        ["Vos emails, campagnes, réponses, rappels, journal", "Vous seul"],
        ["Vos modèles personnels (créés ou dupliqués par vous)", "Vous seul"],
        ["Contacts, compagnies, liste d'exclusion", "Toute l'équipe"],
        ["Modèles communs (S1, P1, G1…) et textes communs", "Toute l'équipe ; modifiables par l'administrateur seulement"],
      ]} />
      <H2>Les règles communes</H2>
      <Points items={[
        <><B>Un prospect, un responsable</B> : le premier qui lui écrit le suit. Si un collègue le suit déjà, l'appli refuse l'envoi et indique qui contacter.</>,
        <>Les <B>compagnies d'assurance</B> (gestionnaires, souscripteurs) sont communes : plusieurs collègues peuvent leur écrire.</>,
        <>Un modèle commun ne vous convient pas ? <B>Dupliquez-le</B> : la copie est à vous, modifiable, invisible des autres.</>,
        <>Effacer un contact suivi par un collègue, supprimer une compagnie ou retirer une exclusion : réservé à l'administrateur.</>,
        <>Le domaine email du cabinet est partagé par toute l'équipe : respectez les plafonds d'envoi et le mode test tant que vous débutez.</>,
      ]} />
      <H2>Administrateur</H2>
      <P>Menu <B>Équipe</B> : inviter un collègue, renvoyer son lien, changer son rôle, désactiver un compte (ses campagnes s'arrêtent, ses données restent).</P>
    </> },
  { slug: "reglages", title: "Réglages et sécurité", icon: Settings2, keywords: "mode test réel plafonds rythme sauvegardes mise à jour mot de passe signature",
    lead: "Boîte mail, rythme d'envoi, mode test, sauvegardes, mises à jour.",
    body: () => SERVER_MODE ? <>
      <Table head={["Réglage", "À savoir"]} rows={[
        ["Boîte mail", "Les serveurs indiqués dans le cPanel (envoi : port 587, sécurité STARTTLS), votre mot de passe (rangé chiffré sur le serveur), « Tester la connexion », votre signature."],
        ["Rythme d'envoi", "Jours et heures d'envoi (heure du Maroc), maximum par jour et par heure, pause entre deux emails, jours fériés (aucun envoi). Le domaine email du cabinet est partagé par toute l'équipe : restez raisonnable."],
        ["Mode test", "Propre à chacun. Activé, tout part vers vous. Le désactiver demande de taper REEL. On peut le réactiver à tout moment."],
        ["Sauvegardes", "Automatiques, chaque nuit et avant chaque mise à jour, gardées 30 jours, avec une copie chiffrée hors du serveur. Rien à faire de votre côté."],
        ["Mises à jour", "Automatiques, la nuit (entre 20 h et 7 h), pour ne jamais couper un envoi. Vos données ne bougent pas."],
      ]} />
    </> : <>
      <Table head={["Réglage", "À savoir"]} rows={[
        ["Boîte mail", "Les serveurs indiqués dans le cPanel, votre mot de passe (rangé dans le coffre-fort de Windows, jamais dans un fichier), « Tester la connexion », votre signature."],
        ["Rythme d'envoi", "Jours et heures d'envoi (heure du Maroc), maximum par jour et par heure, pause entre deux emails, jours fériés (aucun envoi). Le domaine email du cabinet est partagé par toute l'équipe : restez raisonnable."],
        ["Mode test", "Activé, tout part vers vous. Le désactiver demande de taper REEL. On peut le réactiver à tout moment."],
        ["Sauvegardes", "À chaque démarrage et chaque jour : les 10 dernières et une par jour sur 30 jours. Conseillé : un second dossier synchronisé (Google Drive, OneDrive) pour ne rien perdre si le PC tombe en panne."],
        ["Mise à jour", "L'appli vérifie deux fois par jour ; « Vérifier maintenant » pour le faire tout de suite. Vos données ne bougent jamais."],
      ]} />
      <Shot img="rubrique-sauvegardes.png" alt="Réglages : sauvegardes" />
      <P>Revenir à une sauvegarde : fermez la fenêtre noire, puis lancez <B>restaurer_sauvegarde.bat</B> dans le dossier de l'appli.</P>
    </> },
  { slug: "questions", title: "Questions et dépannage", icon: HelpCircle, keywords: "problème email ne part pas boîte illisible faq",
    lead: "Les réponses aux questions les plus fréquentes.", body: () => <FaqList /> },
];

/* ------------------------------------------------------------------ cas d'usage */

type Tag = "Quotidien" | "Prospection" | "Gestion" | "Souscription";
const TAG_STYLE: Record<Tag, string> = {
  Quotidien: "bg-sky-500/10 text-sky-700 dark:text-sky-300",
  Prospection: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  Gestion: "bg-primary/10 text-primary",
  Souscription: "bg-amber-500/10 text-amber-700 dark:text-amber-300",
};

type UseStep = { title: string; text: ReactNode; img?: string; alt?: string };
type UseCase = {
  slug: string; title: string; summary: string; tag: Tag; icon: LucideIcon; minutes: number; keywords: string;
  sequence?: string; who?: string; need?: string[];
  /** V2.23 : deux façons de faire (avec relances / email simple avec le modèle). */
  ways?: { main: ReactNode; quick: ReactNode };
  steps: UseStep[];
  quick?: { title: string; intro: ReactNode; steps: UseStep[] };
  after?: { title: string; text: ReactNode; img?: string; alt?: string }[];
  tips?: ReactNode[]; related?: string[];
};

const PICK = <>Menu <B>Séquences</B> → onglet <B>Gestion</B> → <B>Envoyer</B> sur la séquence, cherchez la personne, cochez-la, <B>Continuer</B>, puis <B>Personnaliser d'abord</B> (détail en images : <CaseLink to="avenant">Demander un avenant</CaseLink>, étapes 1 à 3).</>;

const USE_CASES: UseCase[] = [
  {
    slug: "matinee", title: "Ma matinée", tag: "Quotidien", icon: Sun, minutes: 10, keywords: "à répondre archiver transférer rappels cloche tableau de bord",
    summary: "Le tour du matin : ce qui attend une réponse, les réponses aux campagnes, les rappels du jour.",
    steps: [
      { title: "Commencez par le tableau de bord", img: "matinee-1.png", alt: "Cartes du tableau de bord",
        text: <>Quatre cartes disent ce qui vous attend : <B>Réponses à classer</B> (1), <B>À répondre</B>, les emails reçus restés sans réponse de votre part depuis 3 jours ouvrés, contacts ou pas (2), <B>Ils n'ont pas répondu</B>, vos emails restés sans réponse (3), et <B>Aujourd'hui</B>, vos rappels du jour (4). Chaque carte ouvre la liste.</> },
      { title: "Traitez « À répondre »", img: "matinee-2.png", alt: "Un email ouvert : Répondre, Archiver, Rappel, Envoyer une séquence",
        text: <>Boîte mail → <B>Boîte de réception</B> pour les nouveaux emails, puis l'onglet <B>À répondre</B> pour ceux qui attendent depuis 3 jours ouvrés ou plus. Pour chaque email : <B>Répondre</B> (1), puis <B>Archiver</B> (2) une fois traité. Pas le temps aujourd'hui ? <B>Rappel</B> (3) pour y revenir à une date. La demande appelle un suivi (un client veut un avenant) ? <B>Envoyer une séquence</B> (4).</> },
      { title: "Classez les réponses aux campagnes", img: "reponse-1.png", alt: "Une réponse et les boutons de classement",
        text: <>Onglet <B>Réponses aux campagnes</B> : répondez (1), puis classez d'un clic ou d'une touche de 1 à 6 (2). <B>Marquer comme lu</B> enlève la notification sans classer. Les relances de la personne sont déjà arrêtées (<CaseLink to="reponse">détail</CaseLink>).</> },
      { title: "Videz la cloche", img: "matinee-4.png", alt: "La cloche des notifications",
        text: <>La cloche, en haut à droite, rassemble ce qui est à faire : rappels du jour, réponses à trier, personnes sans réponse depuis 3 jours ouvrés. Une ligne ouvre le bon écran ; « Tout marquer comme vu » vide la pastille.</> },
    ],
    after: [
      { title: "Envoyés sans réponse", text: <>L'onglet <B>Envoyés sans réponse</B> de la Boîte mail liste les personnes restées sans réponse 3 jours ouvrés (réglable) après votre dernier email, séquences comprises. Si une relance automatique est encore prévue, sa date s'affiche sur la ligne (« Relance 1 prévue jeudi 12/11 ») : rien à faire, sauf si vous préférez appeler avant. Elles apparaissent aussi dans la cloche (« Sans réponse ») et sur le tableau de bord. Une relance d'un clic sur Répondre.</> },
    ],
    tips: [
      <>Raccourcis de la Boîte mail : ↑ ↓ pour passer d'un email à l'autre, R répondre, F transférer, E archiver, S envoyer une séquence.</>,
      <>Archiver n'efface rien : l'email va dans le dossier Archives de votre boîte, et « Annuler » juste après le remet.</>,
      <>Réglé par téléphone ? <B>Marquer comme répondu</B> le retire de la liste « À répondre ».</>,
      <>La boîte est lue toutes les 5 minutes ; <B>Actualiser</B> force la lecture.</>,
    ],
    related: ["reponse", "avenant"],
  },
  {
    slug: "modele-perso", title: "Créer mon propre modèle d'email", tag: "Quotidien", icon: FilePlus2, minutes: 5,
    keywords: "modèle template personnel réutiliser cotation at nouveau message modèles balises",
    summary: "Écrire une fois un email que vous envoyez souvent (ex. « Cotation AT »), puis le rappeler en deux clics depuis la Boîte mail.",
    sequence: "Votre modèle", who: "Qui vous voulez",
    steps: [
      { title: "Créez le modèle", img: "modele-1.png", alt: "Nouvelle séquence : nom, type, Un seul email",
        text: <>Séquences → <B>Nouvelle séquence</B>. Un nom clair (1), le type (2), qui le range dans le menu Modèles, la forme <B>Un seul email</B> (3), puis <B>Créer et rédiger</B> (4).</> },
      { title: "Rédigez-le avec des balises", img: "modele-2.png", alt: "Éditeur : boutons de variables, texte, aperçu",
        text: <>L'objet, puis le texte. Les boutons (1) insèrent les <B>variables</B> remplies toutes seules : <code className="text-xs">{'{{ prenom | "Madame, Monsieur" }}'}</code> deviendra « Youssef ». Ce qui change à chaque dossier, écrivez-le entre crochets (2) : [Nom du client], [Effectif]… L'aperçu à droite montre le résultat pour un vrai contact. Un document toujours joint ? « Pièces jointes » → Joindre. Tout s'enregistre seul. <Link to="/guide/balises" className="text-primary hover:underline">Tout sur les balises</Link>.</> },
      { title: "Rappelez-le depuis la Boîte mail", img: "modele-3.png", alt: "Nouveau message : Modèles, le modèle Cotation AT",
        text: <>Boîte mail → <B>Nouveau message</B> → le destinataire → <B>Modèles</B> → votre modèle (1), dans sa rubrique (ici Souscription).</> },
      { title: "Complétez, relisez, envoyez", img: "modele-4.png", alt: "L'email inséré : prénom rempli, champs entre crochets à compléter",
        text: <>Le prénom est déjà rempli (1) ; remplacez chaque [champ], relisez, joignez au besoin, puis <B>Envoyer</B>. S'il reste un crochet, l'appli vous le signale avant l'envoi.</> },
    ],
    tips: [
      <>Partir d'un modèle existant : menu « … » sur sa carte → <B>Dupliquer</B>, puis modifiez la copie.</>,
      <>Besoin de relances automatiques un jour ? Dans l'éditeur, <B>Ajouter une relance</B> : votre modèle devient une vraie séquence, à envoyer avec « Envoyer une séquence ».</>,
      <>Destinataire pas dans vos contacts : l'email commence par « Madame, Monsieur » (la valeur de repli).</>,
    ],
    related: ["avenant", "matinee"],
  },
  {
    slug: "prospecter", title: "Prospecter une liste de directeurs financiers", tag: "Prospection", icon: Target, minutes: 10,
    keywords: "import excel campagne p1 daf industrie groupe lot",
    summary: "Importer un fichier Excel, lancer P1 sur un groupe, suivre les réponses.",
    sequence: "P1 · Prospection entreprise", who: "Des prospects (jamais des clients, assureurs ou partenaires)",
    need: ["Votre liste dans le modèle Excel", "Une cible : fonction × secteur (ex. FIN-IND)", "Un lot d'envoi pour ce groupe (ex. Lot 2)", "Le mode test pour le premier essai"],
    steps: [
      { title: "Téléchargez le modèle Excel", img: "prospecter-1.png", alt: "Importer : modèle Excel et zone de dépôt",
        text: <>Contacts → <B>Importer</B>. Téléchargez le modèle (1) : listes déroulantes, et le code séquence (fonction × secteur) se calcule tout seul. Une ligne par personne ; seule la colonne Email est obligatoire. Glissez ensuite le fichier rempli dans le cadre (2).</> },
      { title: "Vérifiez les colonnes", img: "prospecter-2b.png", alt: "Colonnes reconnues, code séquence, bouton Vérifier",
        text: <>Avec le modèle, tout est reconnu. Le <B>code séquence</B> (1) choisit les textes adaptés à la fonction et au secteur de chacun. Une colonne inconnue devient un champ personnalisé. Puis <B>Vérifier</B> (2).</> },
      { title: "Importez", img: "prospecter-3.png", alt: "Bilan de l'import et bouton Importer",
        text: <>Le bilan (1) : nouveaux contacts, mis à jour (email déjà connu), ignorés. Rien n'est enregistré avant <B>Importer</B> (2).</> },
      { title: "Nouvelle campagne : la séquence", img: "prospecter-4.png", alt: "Choix de P1, nom de la campagne, À qui ?",
        text: <>Campagnes → <B>Nouvelle campagne</B>. Choisissez P1 (1), donnez un nom parlant (2), puis <B>À qui ?</B> (3).</> },
      { title: "Le groupe", img: "prospecter-5.png", alt: "Filtre Lot d'envoi et compteur de prospects",
        text: <>Filtrez, ici par lot d'envoi (1). Le compteur (2) dit combien de prospects la recevront. Ceux qui ont répondu, rebondi ou se sont désinscrits sont écartés d'office, comme les clients et les assureurs.</> },
      { title: "Vérifiez et lancez", img: "prospecter-6.png", alt: "Bandeau mode test, premier envoi, Lancer la campagne",
        text: <>En mode test, le bandeau le rappelle (1) : tout arrive chez vous. Le premier envoi (2) et la fin estimée donnent le calendrier. <B>Lancer la campagne</B> (3).</> },
      { title: "Suivez", img: "prospecter-7.png", alt: "Page de la campagne : Réponses, Mettre en pause",
        text: <>Les réponses (1), les intéressés, les rebonds. <B>Mettre en pause</B> (2) arrête les envois le temps qu'il faut.</> },
    ],
    after: [
      { title: "Les emails partent un par un", text: <>Un email à la fois, aux heures de bureau, 25 par jour au plus : une liste de 30 personnes à 3 emails prend donc plusieurs jours. C'est voulu : cela ressemble à des emails écrits à la main et protège la réputation du domaine du cabinet.</> },
      { title: "Un prospect répond", text: <>Ses relances s'arrêtent, il apparaît dans Réponses aux campagnes et dans la cloche. La suite : <CaseLink to="reponse">Un prospect répond</CaseLink>.</> },
    ],
    tips: [
      <>P1 a deux objets (A/B) : la campagne les répartit au hasard et compare les taux de réponse. Attendez une centaine de contacts par objet avant de conclure.</>,
      <>« Arrêter si un collègue répond » (étape Quoi) : si quelqu'un de la même entreprise répond, ses collègues ne reçoivent plus les relances. Jamais pour Gmail, Hotmail…</>,
      <>Répartissez-vous les entreprises avec vos collègues : chaque appli ne voit que ses propres envois.</>,
    ],
    related: ["reponse", "rendez-vous"],
  },
  {
    slug: "rendez-vous", title: "Relancer après un rendez-vous", tag: "Prospection", icon: Users, minutes: 2, keywords: "p2 rendez-vous documents conditions particulières",
    summary: "P2 depuis la fiche du contact : merci pour l'échange, et les documents à nous transmettre.",
    sequence: "P2 · Suite à un rendez-vous", who: "Le prospect rencontré",
    steps: [
      { title: "Ouvrez sa fiche", img: "rdv-1.png", alt: "Fiche contact, bouton Envoyer une séquence",
        text: <>Contacts → cherchez la personne : sa fiche s'ouvre à droite. Cliquez <B>Envoyer une séquence</B>. Elle a déjà répondu à P1 (« A répondu ») ? P2 reste possible : c'est un envoi à l'unité, voulu par vous.</> },
      { title: "Choisissez P2", img: "rdv-2.png", alt: "Choix de la séquence P2",
        text: <>Onglet Prospection → <B>P2 · Suite à un rendez-vous</B>.</> },
      { title: "Envoyez", img: "rdv-3.png", alt: "Dates prévues et Envoyer tel quel",
        text: <>Les dates prévues s'affichent (1). Choisissez <B>Personnaliser d'abord</B> (2) : vous lisez l'email et ses relances tels qu'ils partiront, vous ajoutez un mot sur votre échange, vous vérifiez la liste des documents demandés. <B>Envoyer tel quel</B>, seulement quand vous connaissez bien P2 (<Link to="/guide/balises" className="text-primary hover:underline">pourquoi relire</Link>).</> },
    ],
    after: [
      { title: "Ce que reçoit le prospect", text: <>Un merci pour l'échange et la liste des documents utiles : conditions particulières de ses contrats, relevé de sinistres des trois dernières années, dates d'échéance. Deux relances si rien ne vient (J+4, J+9), arrêtées dès qu'il répond.</> },
      { title: "Les documents arrivent", text: <>Ils sont dans la Boîte mail, pièces jointes ouvrables d'un clic. Ensuite : <CaseLink to="cotation">Mettre 3 compagnies en concurrence</CaseLink>.</> },
    ],
    tips: [
      <>Depuis l'email reçu du prospect, <B>Envoyer une séquence</B> mène au même endroit.</>,
      <>Un rappel pour l'appeler si rien ne vient : bouton <B>Rappel</B> sur sa fiche.</>,
    ],
    related: ["cotation", "reponse"],
  },
  {
    slug: "avenant", title: "Demander un avenant à une compagnie", tag: "Gestion", icon: FileSignature, minutes: 2,
    keywords: "g1 avenant police gestionnaire compagnie pièce jointe modèles nouveau message",
    summary: "Un client ajoute un véhicule, change d'adresse… : vous demandez l'avenant au gestionnaire.",
    sequence: "G1 · Demande d'avenant", who: "Le gestionnaire de la compagnie (service Gestion ou Production)",
    need: ["Le n° de police", "Le nom de l'assuré", "L'objet de l'avenant (ex. ajout d'un véhicule)", "La date d'effet souhaitée", "Le justificatif s'il y en a un (carte grise, bail…)"],
    ways: {
      main: <><B>Avec relances automatiques</B> : la séquence G1. Si le gestionnaire ne répond pas, deux relances partent seules. Le pas à pas est juste en dessous.</>,
      quick: <><B>Plus rapide, sans relances</B> : un email normal avec le modèle G1 (Nouveau message → Modèles), ou la séquence G1 avec « <B>1er email seulement</B> » (étape 2). Vous relancez vous-même si besoin. <a href="#rapide" className="text-primary hover:underline">Voir l'option rapide</a>.</>,
    },
    steps: [
      { title: "Ouvrez la séquence G1", img: "avenant-1.png", alt: "Séquences, onglet Gestion, bouton Envoyer de G1",
        text: <>Menu <B>Séquences</B> → onglet <B>Gestion</B> (1) → sur « G1 · Demande d'avenant », cliquez <B>Envoyer</B> (2).</> },
      { title: "Choisissez le gestionnaire", img: "avenant-2.png", alt: "Recherche du gestionnaire et bouton Continuer",
        text: <>Tapez son nom ou celui de la compagnie (1), cochez la bonne personne (2), puis <B>Continuer</B> (3). Les dates prévues du 1er email et des relances s'affichent juste au-dessus. Sous « Que faut-il envoyer ? », gardez <B>Toute la séquence</B> pour les relances automatiques, ou choisissez <B>1er email seulement</B>. La personne n'est pas dans la liste ? Ajoutez-la d'abord depuis la fiche de la compagnie (<B>Entreprises</B>).</> },
      { title: "Choisissez « Personnaliser d'abord »", img: "avenant-3.png", alt: "Choix Personnaliser d'abord",
        text: <>Ici c'est indispensable : l'email contient des informations propres à ce dossier. La séquence G1 elle-même ne change pas, seul l'email de cette personne est retouché.</> },
      { title: "Remplacez les champs entre crochets", img: "avenant-4.png", alt: "Objet et champs entre crochets à compléter",
        text: <>Dans l'objet (1) et dans le texte : [N° de police], [Nom de l'assuré], [Objet de l'avenant], [Date d'effet]. Tant qu'il en reste un, l'encadré orange (2) le signale et <B>l'email ne part pas</B>. Les relances reprennent toutes seules l'objet que vous avez écrit.</> },
      { title: "Joignez le justificatif", img: "avenant-5.png", alt: "Pièce jointe ajoutée et bouton Vérifier avant d'envoyer",
        text: <>« Joindre un fichier pour cette personne » : la pièce apparaît sous le texte (1). Cliquez <B>Vérifier avant d'envoyer</B> (2).</> },
      { title: "Vérifiez les emails exacts, puis confirmez", img: "avenant-5b.png", alt: "Vérifier avant d'envoyer : chaque email, son texte final et sa pièce jointe",
        text: <>Chaque email qui partira, avec sa date (1). Le texte exact (2) : objet, prénom, signature. La pièce jointe (3). Rien ne part tant que vous n'avez pas cliqué <B>Confirmer l'envoi</B> (4). Une erreur ? <B>Retour</B> pour corriger.</> },
      { title: "C'est parti", img: "avenant-6.png", alt: "Confirmation d'envoi",
        text: <>La confirmation indique l'heure du 1er email : il part dans la plage d'envoi (heures de bureau, jours ouvrés). <B>Voir</B> ouvre le suivi. En mode test, l'email arrive chez vous, avec l'objet [TEST → …].</> },
    ],
    quick: {
      title: "L'option rapide : un email normal avec le modèle",
      intro: <>Pour une demande simple, quand vous n'avez pas besoin de relances automatiques. L'email part tout de suite (dans la plage d'envoi en mode réel), comme un email écrit à la main.</>,
      steps: [
        { title: "Nouveau message, puis Modèles", img: "avenant-rapide-1.png", alt: "Nouveau message : destinataire, bouton Modèles, G1",
          text: <>Boîte mail → <B>Nouveau message</B>. Tapez l'adresse du gestionnaire (1), cliquez <B>Modèles</B> (2), puis <B>G1 · Demande d'avenant</B> (3).</> },
        { title: "Complétez et envoyez", img: "avenant-rapide-2.png", alt: "Objet et texte insérés, bouton Envoyer",
          text: <>L'objet (1) et le texte (2) s'insèrent, déjà écrits à son nom. Remplacez les [champs], joignez le justificatif (trombone), puis <B>Envoyer</B> (3). S'il reste un crochet, l'appli vous le signale avant l'envoi.</> },
      ],
    },
    after: [
      { title: "Sans réponse : les relances partent seules", text: <>Avec la séquence : relance 1 trois jours ouvrés plus tard, relance 2 quatre jours ouvrés après, dans la même conversation (« Re: … »).</> },
      { title: "Sa réponse arrête les relances", text: <>Dès que le gestionnaire répond, les relances de ce dossier s'arrêtent d'elles-mêmes, même si vous rangez sa réponse depuis votre téléphone. S'il écrit un email séparé, sans répondre au vôtre, l'appli ne sait pas de quel dossier il parle : par prudence, elle arrête les relances de tous ses dossiers en cours.</> },
      { title: "L'avenant arrive", img: "avenant-7.png", alt: "Email reçu avec pièce jointe, boutons Transférer et Archiver",
        text: <>Ouvrez la pièce jointe d'un clic (1), envoyez-la au client avec <B>Transférer</B> (2) : le PDF suit. Puis <B>Archiver</B> (3) range l'email (touche E).</> },
    ],
    tips: [
      <>Depuis la fiche d'une personne ou un email reçu, le bouton <B>Envoyer une séquence</B> mène au même parcours, la personne déjà choisie.</>,
      <>Plusieurs avenants pour le même gestionnaire ? Envoyez G1 une fois par dossier, chacun avec son n° de police dans l'objet : chaque dossier a ses propres relances, et une réponse sur l'un n'arrête pas les autres.</>,
    ],
    related: ["delegation", "sinistre"],
  },
  {
    slug: "delegation", title: "Délégation bancaire", tag: "Gestion", icon: Landmark, minutes: 2, keywords: "g2 banque délégation attestation crédit",
    summary: "La banque d'un client demande une délégation : G2 au gestionnaire, avec la demande de la banque en pièce jointe.",
    sequence: "G2 · Demande de délégation bancaire", who: "Le gestionnaire de la compagnie",
    need: ["Le n° de police", "Le nom de l'assuré", "Le nom de la banque", "La demande de la banque (PDF)"],
    steps: [
      { title: "Ouvrez G2 et choisissez le gestionnaire", text: PICK },
      { title: "Complétez, joignez, envoyez", img: "delegation-1.png", alt: "G2 personnalisée : objet, texte, pièce jointe",
        text: <>L'objet (1) et le texte (2) : [N° de police], [Nom de l'assuré], [Banque]. Joignez la demande de la banque (3) avec « Joindre un fichier pour cette personne », puis <B>Vérifier avant d'envoyer</B> et <B>Confirmer l'envoi</B>.</> },
    ],
    after: [
      { title: "L'attestation de délégation arrive", text: <>Ouvrez-la d'un clic, <B>Transférer</B> à la banque ou au client (la pièce jointe suit), puis <B>Archiver</B>. Les relances G2 se sont arrêtées dès la réponse.</> },
    ],
    tips: [
      <>Sans relances : Nouveau message → <B>Modèles</B> → G2, comme l'option rapide de <CaseLink to="avenant">Demander un avenant</CaseLink>.</>,
      <>Une autre attestation (assurance, carte verte…) : <B>G5 · Demande d'attestation</B>, même parcours.</>,
    ],
    related: ["avenant", "sinistre"],
  },
  {
    slug: "sinistre", title: "Déclarer puis suivre un sinistre", tag: "Gestion", icon: ShieldAlert, minutes: 3, keywords: "g3 g4 sinistre déclaration suivi expert constat photos",
    summary: "G3 pour déclarer avec le constat, G4 pour suivre le dossier jusqu'au règlement.",
    sequence: "G3 puis G4", who: "Le gestionnaire sinistres de la compagnie",
    need: ["Le n° de police et le nom de l'assuré", "La date du sinistre", "Les circonstances en une phrase", "Constat, photos, devis…"],
    steps: [
      { title: "Déclarez avec G3", img: "sinistre-1.png", alt: "G3 personnalisée : texte et constat joint",
        text: <>Séquences → Gestion → <B>G3 · Déclaration de sinistre</B> → Envoyer → le gestionnaire → Personnaliser d'abord. Complétez le texte (1) : police, date, circonstances. Joignez le constat et les photos (2), puis envoyez.</> },
      { title: "La compagnie répond", img: "sinistre-2.png", alt: "Réponse de la compagnie avec pièces jointes",
        text: <>Sa réponse (référence du dossier, expert désigné) arrête les relances G3. Les pièces jointes s'ouvrent d'un clic (2). Expéditeur pas encore dans vos contacts ? <B>Créer le contact</B>. Pour lancer le suivi : <B>Envoyer une séquence</B> (1).</> },
      { title: "Suivez avec G4", img: "sinistre-3.png", alt: "G4 personnalisée : référence du sinistre dans l'objet",
        text: <><B>G4 · Suivi de sinistre</B>, Personnaliser d'abord : la référence du dossier dans l'objet (1) et le texte. Deux relances (J+5, J+10) si rien ne vient.</> },
    ],
    after: [
      { title: "Le dossier traîne encore ?", text: <>Renvoyez G4 plus tard : une même séquence de gestion peut repartir à la même personne, une fois par dossier ou par relance de fond.</> },
      { title: "Le rapport d'expertise arrive", text: <><B>Transférer</B> au client avec la pièce jointe, puis <B>Archiver</B>.</> },
    ],
    tips: [<>Un rappel pour faire le point avec le client : bouton <B>Rappel</B> sur l'email ou sur sa fiche.</>],
    related: ["avenant", "delegation"],
  },
  {
    slug: "cotation", title: "Mettre 3 compagnies en concurrence", tag: "Souscription", icon: Building2, minutes: 5, keywords: "s1 s2 cotation souscription proposition plusieurs compagnies",
    summary: "S1 aux souscripteurs de plusieurs compagnies en une fois, puis S2 au client avec la proposition retenue.",
    sequence: "S1 puis S2", who: "Les souscripteurs des compagnies, puis votre client",
    need: ["Le nom du client et son activité", "Le risque à couvrir", "La date d'effet", "La fiche de renseignements ou de risque"],
    steps: [
      { title: "Toute une équipe Souscription", img: "cotation-1.png", alt: "Fiche compagnie : Séquence au service Souscription",
        text: <>Entreprises → la compagnie → onglet <B>Souscription</B> (2) → <B>Séquence au service Souscription</B> (1) : tous ses souscripteurs d'un coup.</> },
      { title: "Ou plusieurs compagnies à la fois", img: "cotation-2.png", alt: "Trois souscripteurs de trois compagnies choisis",
        text: <>Séquences → Souscription → <B>S1 · Demande de cotation</B> → Envoyer : cochez un souscripteur dans chaque compagnie (1), puis <B>Continuer</B> (2).</> },
      { title: "Remplissez une seule fois", img: "cotation-3.png", alt: "Les champs remplis une fois, pièce jointe, Envoyer à 3 personnes",
        text: <>Chaque [champ] une fois (1) : chacun reçoit son propre email, à son nom, avec ces informations. Joignez la fiche de risque (2), puis <B>Vérifier les emails</B> (3).</> },
      { title: "Vérifiez chaque email, puis envoyez", img: "cotation-3b.png", alt: "Vérifier avant d'envoyer : une ligne par compagnie, le texte exact de chaque email",
        text: <>Une ligne par compagnie (1). Ses emails, avec leur date (2). Le texte exact, à son nom (3) : relisez au moins le 1er email d'une compagnie. Puis <B>Envoyer à 3 personnes</B> (4).</> },
      { title: "Envoyez la proposition au client avec S2", img: "cotation-4.png", alt: "S2 personnalisée avec la proposition jointe",
        text: <>Les offres reçues et comparées : <B>S2 · Envoi de proposition</B> au client, Personnaliser d'abord, [Objet de la proposition] dans le texte (1), la proposition en pièce jointe (2).</> },
    ],
    after: [
      { title: "Chaque compagnie a ses relances", text: <>Une compagnie qui répond n'arrête pas les relances des autres : ce sont des personnes différentes.</> },
    ],
    tips: [
      <>« Séquence au service… » marche pour chaque onglet : Gestion, Production…</>,
      <>Les relances reprennent les informations remplies une fois.</>,
    ],
    related: ["rendez-vous", "avenant"],
  },
  {
    slug: "renouvellement", title: "Approcher un prospect avant son échéance", tag: "Prospection", icon: CalendarDays, minutes: 3,
    keywords: "p3 échéance rappel renouvellement agenda",
    summary: "Un rappel quelques semaines avant l'échéance de ses contrats, puis P3 le jour venu.",
    sequence: "P3 · Avant l'échéance des contrats", who: "Un prospect dont vous connaissez l'échéance",
    steps: [
      { title: "Notez la date dans l'agenda", img: "echeance-1.png", alt: "Ajouter un rappel : Renouvellement, personne, date, note",
        text: <>Agenda → <B>Ajouter un rappel</B> (ou Rappel sur sa fiche). Type <B>Renouvellement</B> (1), la personne (2), la date où agir, par exemple six semaines avant l'échéance (3), une note (4). Puis Ajouter.</> },
      { title: "Le jour venu", text: <>Le rappel apparaît dans <B>Aujourd'hui</B> sur le tableau de bord, dans la cloche et dans l'agenda.</> },
      { title: "Envoyez P3", text: <>Ouvrez sa fiche → <B>Envoyer une séquence</B> → Prospection → <B>P3 · Avant l'échéance des contrats</B> → <B>Personnaliser d'abord</B> pour relire et ajouter ce que vous savez de ses contrats. Deux emails sur 5 jours : une mise en concurrence avant l'échéance, sans engagement.</> },
      { title: "Cochez le rappel", text: <>Dans l'agenda ou sur le tableau de bord, pour qu'il disparaisse d'Aujourd'hui.</> },
    ],
    tips: [
      <>L'échéance d'un <B>client</B> n'est pas de la prospection : consultez les compagnies avec S1, puis présentez l'offre avec S2 (<CaseLink to="cotation">Mettre 3 compagnies en concurrence</CaseLink>).</>,
      <>Pour viser plusieurs prospects à la fois (même mois d'échéance), une campagne P3 sur un lot.</>,
    ],
    related: ["prospecter", "cotation"],
  },
  {
    slug: "reponse", title: "Un prospect répond", tag: "Quotidien", icon: CheckCircle2, minutes: 2, keywords: "réponse arrêt relances classer intéressé rappeler désinscription stop",
    summary: "Ce que fait l'appli toute seule, et ce qu'il vous reste à faire.",
    ways: {
      main: <><B>L'appli, toute seule</B> : elle arrête ses relances, le marque « A répondu » (plus de campagne de groupe pour lui), le signale dans la cloche et dans Réponses aux campagnes.</>,
      quick: <><B>Vous</B> : lui répondre, puis classer sa réponse. Deux minutes.</>,
    },
    steps: [
      { title: "Répondez-lui", img: "reponse-1.png", alt: "Une réponse : Répondre et les boutons de classement",
        text: <>Boîte mail → <B>Réponses aux campagnes</B> → sa réponse → <B>Répondre</B> (1). Ajoutez au besoin une note privée.</> },
      { title: "Classez sa réponse", text: <>Un clic ou une touche de 1 à 6 (2) : <B>Intéressé</B>, <B>À rappeler plus tard</B>, <B>Pas intéressé</B>, <B>Absent</B>, <B>Mauvais contact</B>, <B>Désinscription</B>. Le classement nourrit les statistiques des campagnes. Pas le temps de classer ? <B>Marquer comme lu</B> (touche L) enlève la notification ; la réponse attend sous <B>Lues, non classées</B>.</> },
      { title: "« À rappeler plus tard » : choisissez la date", img: "reponse-2.png", alt: "Rappeler quand : date et Programmer le rappel",
        text: <>Une date proposée ou la vôtre, puis <B>Programmer le rappel</B> : il apparaîtra sur le tableau de bord ce jour-là.</> },
      { title: "La suite", text: <>Un rendez-vous obtenu ? Après l'échange : <CaseLink to="rendez-vous">P2</CaseLink>. Il demande une proposition ? <CaseLink to="cotation">Consultez les compagnies</CaseLink>.</> },
    ],
    after: [
      { title: "Désinscription et Mauvais contact protègent pour l'avenir", text: <>Désinscription : l'adresse passe sur la liste d'exclusion, plus aucun email. Mauvais contact : la personne passe en « ne plus contacter ». En mode test, le classement ne bloque pas le vrai contact.</> },
      { title: "Les réponses automatiques", text: <>Un message d'absence n'arrête pas les relances : elles continuent comme prévu.</> },
    ],
    related: ["matinee", "rendez-vous"],
  },
];

const norm = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/* ------------------------------------------------------------------ mise en page */

export function GuideLayout() {
  const [q, setQ] = useState("");
  const { data: g } = useGuide();
  const started = !!g && g.done < g.total;  // V2.23 : « Bien démarrer » disparaît une fois fini
  const match = (s: string) => !q.trim() || norm(s).includes(norm(q.trim()));
  const sections = SECTIONS.filter((s) => (!s.serverOnly || SERVER_MODE) && match(`${s.title} ${s.lead} ${s.keywords}`));
  const cases = USE_CASES.filter((u) => match(`${u.title} ${u.summary} ${u.keywords} ${u.tag}`));
  const item = "flex items-center gap-2 rounded-md px-2.5 py-1.5 text-sm transition-colors";
  const cls = ({ isActive }: { isActive: boolean }) => cn(item, isActive ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground");
  return (
    <div className="grid gap-6 lg:grid-cols-[15rem_minmax(0,1fr)]">
      <aside className="space-y-4 lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:self-start lg:overflow-y-auto">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Chercher dans le guide" className="h-9 pl-8" aria-label="Chercher dans le guide" />
        </div>
        <nav className="space-y-0.5">
          <NavLink end to="/guide" className={cls}><BookOpen className="size-4" /> Accueil du guide</NavLink>
          {started && match("bien démarrer étapes départ") && (
            <NavLink to="/guide/bien-demarrer" className={({ isActive }) => cn(item, isActive ? "bg-primary text-primary-foreground" : "bg-primary/10 font-medium text-primary hover:bg-primary/15")}>
              <Zap className="size-4" /> Bien démarrer <span className="ml-auto text-xs tabular">{g!.done}/{g!.total}</span>
            </NavLink>
          )}
          <p className="px-2.5 pb-1 pt-3 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Rubriques</p>
          {sections.map((s) => (
            <NavLink key={s.slug} to={`/guide/${s.slug}`} className={cls}>
              <s.icon className="size-4 shrink-0" /><span className="truncate">{s.title}</span>
            </NavLink>
          ))}
          <p className="px-2.5 pb-1 pt-3 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Cas d'usage</p>
          {cases.map((u) => (
            <NavLink key={u.slug} to={`/guide/cas/${u.slug}`} className={cls}>
              <u.icon className="size-4 shrink-0 self-start mt-0.5" /><span className="leading-snug">{u.title}</span>
            </NavLink>
          ))}
          {!sections.length && !cases.length && <p className="px-2.5 py-2 text-sm text-muted-foreground">Rien trouvé pour « {q} ».</p>}
        </nav>
      </aside>
      <div className="min-w-0"><Outlet /></div>
    </div>
  );
}

function UseCaseCard({ u }: { u: UseCase }) {
  return (
    <Link to={`/guide/cas/${u.slug}`} className="block">
      <Card className="h-full transition-all hover:border-primary/40 hover:shadow-md">
        <CardContent className="flex h-full flex-col gap-2 p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="flex size-8 items-center justify-center rounded-lg bg-accent text-foreground"><u.icon className="size-4" /></span>
            <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", TAG_STYLE[u.tag])}>{u.tag}</span>
          </div>
          <p className="font-medium leading-snug">{u.title}</p>
          <p className="flex-1 text-sm text-muted-foreground">{u.summary}</p>
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground"><Clock className="size-3.5" />{u.minutes} min</p>
        </CardContent>
      </Card>
    </Link>
  );
}

/* ------------------------------------------------------------------ accueil */

export function GuideHome() {
  const { data: g } = useGuide();
  const started = !!g && g.done < g.total;
  const starts = [
    started
      ? { icon: Zap, title: "Je débute", text: `Bien démarrer : ${g!.done} étape${g!.done > 1 ? "s" : ""} sur ${g!.total}. Les réglages à faire une seule fois.`, to: "/guide/bien-demarrer" }
      : { icon: Compass, title: "Je découvre l'appli", text: "Comment elle travaille, les bons réflexes, le tour des écrans.", to: "/guide/prise-en-main" },
    { icon: FileSignature, title: "Je gère des dossiers", text: "Avenants, délégations, sinistres, cotations : les recettes pas à pas.", to: "/guide/cas/avenant" },
    { icon: Target, title: "Je prospecte", text: "Importer une liste, lancer une campagne, suivre les réponses.", to: "/guide/cas/prospecter" },
  ];
  return (
    <div className="space-y-7">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Guide</h1>
        <p className="mt-1 text-sm text-muted-foreground">Tout pour être autonome : chaque écran, et des recettes pas à pas pour les situations du cabinet.</p>
      </div>
      <section className="space-y-3">
        <h2 className="text-base font-semibold">La vidéo de présentation</h2>
        <Video file="tour" title="Le tour de l'appli" caption="4 minutes pour voir l'appli en entier. Sous-titrée : elle se regarde aussi sans le son." />
      </section>
      <section className="space-y-3">
        <h2 className="text-base font-semibold">Par où commencer ?</h2>
        <div className="grid gap-3 sm:grid-cols-3">
          {starts.map((s) => (
            <Link key={s.title} to={s.to} className="group block">
              <Card className="h-full transition-all group-hover:border-primary/40 group-hover:shadow-md">
                <CardContent className="space-y-2 p-4">
                  <s.icon className="size-5 text-primary" />
                  <p className="font-medium">{s.title}</p>
                  <p className="text-sm text-muted-foreground">{s.text}</p>
                  <p className="flex items-center gap-1 text-sm text-primary">Commencer <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" /></p>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      </section>
      <section className="space-y-3">
        <div className="flex items-end justify-between gap-3">
          <h2 className="text-base font-semibold">Cas d'usage</h2>
          <p className="text-xs text-muted-foreground">Des recettes pas à pas, avec les captures de l'écran</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {USE_CASES.map((u) => <UseCaseCard key={u.slug} u={u} />)}
        </div>
      </section>
      <section className="space-y-3 pb-8">
        <h2 className="text-base font-semibold">Toutes les rubriques</h2>
        <div className="grid gap-2 sm:grid-cols-2">
          {SECTIONS.filter((s) => !s.serverOnly || SERVER_MODE).map((s) => (
            <Link key={s.slug} to={`/guide/${s.slug}`}>
              <div className="flex items-start gap-3 rounded-lg border bg-card p-3 transition-colors hover:border-primary/40">
                <s.icon className="mt-0.5 size-4 shrink-0 text-primary" />
                <div className="min-w-0"><p className="text-sm font-medium">{s.title}</p><p className="text-xs text-muted-foreground">{s.lead}</p></div>
              </div>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}

/* ------------------------------------------------------------------ Bien démarrer */

export function StartPage() {
  const { data: g } = useGuide();
  const finished = !!g && g.done >= g.total;
  return (
    <div className="space-y-5 pb-8">
      <Back />
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight"><Zap className="size-5 text-primary" />Bien démarrer</h1>
        <p className="mt-1 text-sm text-muted-foreground">Les réglages à faire une seule fois. Cette page quitte le menu du guide quand tout est fait.</p>
      </div>
      {finished ? (
        <Card className="border-success/30 bg-success/5">
          <CardContent className="flex items-center gap-3 p-4 text-sm"><CheckCircle2 className="size-5 text-success" />Les 5 étapes sont faites : vous êtes prêt. La suite : <Link to="/guide/cas/matinee" className="text-primary hover:underline">Ma matinée</Link>.</CardContent>
        </Card>
      ) : <StartChecklist />}
    </div>
  );
}

/* ------------------------------------------------------------------ rubrique */

export function GuideSectionPage() {
  const { slug } = useParams();
  const s = SECTIONS.find((x) => x.slug === slug);
  if (!s) return <NotFound />;
  return (
    <div className="space-y-5 pb-8">
      <Back />
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight"><s.icon className="size-5 text-primary" />{s.title}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{s.lead}</p>
      </div>
      <div className="space-y-4">{s.body()}</div>
    </div>
  );
}

function Back() {
  return <Link to="/guide" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="size-4" /> Guide</Link>;
}

function NotFound() {
  return (
    <div className="space-y-4">
      <Back />
      <Card><CardContent className="p-6 text-sm text-muted-foreground">Page introuvable : revenez à l'accueil du guide.</CardContent></Card>
    </div>
  );
}

/* ------------------------------------------------------------------ cas d'usage */

function Figure({ img, alt }: { img?: string; alt?: string }) {
  if (!img) return null;
  return <div className="mt-3 max-w-2xl rounded-lg border bg-accent/30 p-2"><ZoomImage src={CAS + img} alt={alt ?? ""} className="border-0 shadow-none" /></div>;
}

function Steps({ steps }: { steps: UseStep[] }) {
  return (
    <ol className="relative space-y-6 border-l pl-6">
      {steps.map((st, i) => (
        <li key={st.title} className="relative">
          <span className="absolute -left-[37px] flex size-6 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground ring-4 ring-background">{i + 1}</span>
          <p className="font-medium">{st.title}</p>
          <div className="mt-1 max-w-2xl text-sm text-muted-foreground">{st.text}</div>
          <Figure img={st.img} alt={st.alt} />
        </li>
      ))}
    </ol>
  );
}

export function UseCasePage() {
  const { slug } = useParams();
  const u = USE_CASES.find((x) => x.slug === slug);
  const idx = useMemo(() => USE_CASES.findIndex((x) => x.slug === slug), [slug]);
  if (!u) return <NotFound />;
  const next = USE_CASES[idx + 1];
  return (
    <article className="space-y-6 pb-10">
      <Back />
      <header className="space-y-3">
        <span className={cn("inline-block rounded-full px-2 py-0.5 text-[11px] font-medium", TAG_STYLE[u.tag])}>Cas d'usage · {u.tag}</span>
        <h1 className="text-xl font-semibold tracking-tight">{u.title}</h1>
        <p className="max-w-2xl text-sm text-muted-foreground">{u.summary}</p>
        <div className="flex flex-wrap gap-2 text-xs">
          <Badge variant="secondary" className="gap-1 font-normal"><Clock className="size-3" />{u.minutes} min</Badge>
          {u.sequence && <Badge variant="secondary" className="gap-1 font-normal"><ListOrdered className="size-3" />{u.sequence}</Badge>}
          {u.who && <Badge variant="secondary" className="gap-1 font-normal"><Users className="size-3" />{u.who}</Badge>}
        </div>
      </header>

      {u.ways && (
        <div className="grid max-w-3xl gap-3 sm:grid-cols-2">
          <Card className="border-primary/30"><CardContent className="space-y-1 p-4 text-sm text-muted-foreground"><ListOrdered className="mb-1 size-4 text-primary" />{u.ways.main}</CardContent></Card>
          <Card className="border-amber-500/30"><CardContent className="space-y-1 p-4 text-sm text-muted-foreground"><Zap className="mb-1 size-4 text-amber-600" />{u.ways.quick}</CardContent></Card>
        </div>
      )}

      {u.need && (
        <Card className="border-primary/20 bg-primary/5">
          <CardContent className="p-4">
            <p className="mb-2 text-sm font-medium">Ayez sous la main</p>
            <ul className="grid gap-1 text-sm text-muted-foreground sm:grid-cols-2">
              {u.need.map((n) => <li key={n} className="flex gap-2"><CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-primary" />{n}</li>)}
            </ul>
          </CardContent>
        </Card>
      )}

      <section>
        <h2 className="mb-3 text-base font-semibold">Pas à pas</h2>
        <Steps steps={u.steps} />
      </section>

      {u.quick && (
        <section id="rapide" className="scroll-mt-24">
          <h2 className="mb-1 flex items-center gap-2 text-base font-semibold"><Zap className="size-4 text-amber-600" />{u.quick.title}</h2>
          <p className="mb-3 max-w-2xl text-sm text-muted-foreground">{u.quick.intro}</p>
          <Steps steps={u.quick.steps} />
        </section>
      )}

      {u.after && (
        <section>
          <h2 className="mb-3 text-base font-semibold">Et ensuite ?</h2>
          <div className="space-y-3">
            {u.after.map((a) => (
              <Card key={a.title}>
                <CardContent className="p-4">
                  <p className="font-medium">{a.title}</p>
                  <div className="mt-1 max-w-2xl text-sm text-muted-foreground">{a.text}</div>
                  <Figure img={a.img} alt={a.alt} />
                </CardContent>
              </Card>
            ))}
          </div>
        </section>
      )}

      {u.tips && (
        <Card className="border-amber-500/30 bg-amber-500/5">
          <CardContent className="space-y-2 p-4">
            <p className="flex items-center gap-2 text-sm font-medium"><Lightbulb className="size-4 text-amber-600" /> Astuces</p>
            <ul className="space-y-1.5 text-sm text-muted-foreground">
              {u.tips.map((t, i) => <li key={i} className="flex gap-2"><span className="mt-2 size-1 shrink-0 rounded-full bg-amber-600" /><span>{t}</span></li>)}
            </ul>
          </CardContent>
        </Card>
      )}

      {u.related && (
        <section className="space-y-2">
          <h2 className="text-base font-semibold">Voir aussi</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {u.related.map((r) => USE_CASES.find((x) => x.slug === r)).filter(Boolean).map((x) => <UseCaseCard key={x!.slug} u={x!} />)}
          </div>
        </section>
      )}

      {next && (
        <Link to={`/guide/cas/${next.slug}`} className="flex items-center justify-end gap-1.5 text-sm text-primary hover:underline">
          Cas suivant : {next.title} <ArrowRight className="size-4" />
        </Link>
      )}
    </article>
  );
}
