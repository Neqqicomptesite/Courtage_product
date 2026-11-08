# ODDO Séquences – guide d'utilisation

> **Version 2.25.1** – http://127.0.0.1:8765 (même adresse que la V1 : les deux ne peuvent pas tourner en même temps).
> - Le mode test n'est plus verrouillé : il reste **activé** jusqu'à ce que vous le désactiviez dans Réglages → Mode test.
> - La V1 (dossier `oddo-sequences`) reste une solution de repli : ne la lancez qu'après avoir fermé celle-ci.
> - Nouveautés de la V2 : nouvelle interface, entreprises et types de contacts, boîte mail complète et écriture
>   d'emails, relance à un jour précis, démarrage planifié, modèle Excel. Détail dans DECISIONS.md (n° 106 à 161).

Application installée sur votre PC pour envoyer des campagnes de prospection depuis
votre boîte mail professionnelle : un premier email, puis des relances automatiques qui s'arrêtent dès
que la personne répond. Rien n'est hébergé sur Internet : tout reste sur votre ordinateur.

> **À retenir :** l'application n'envoie rien quand elle est fermée ou quand le PC est éteint ou en veille.
> Au redémarrage, elle rattrape le retard tranquillement, un email à la fois.

---

## 1. Installation (une seule fois)

1. **Installer Python 3.12** depuis https://www.python.org/downloads/ (bouton « Download Python 3.12… »).
   Dans la première fenêtre de l'installateur, **cochez « Add python.exe to PATH »**, puis « Install Now ».
2. **Décompresser** le dossier de l'application où vous voulez (par exemple `C:\ODDO\oddo-sequences`).
   Évitez de le laisser dans Téléchargements, où il risque d'être supprimé lors d'un nettoyage.

## 2. Lancer l'application

Double-cliquez sur **`start.bat`**.

- La première fois, l'installation des composants prend quelques minutes (connexion internet nécessaire).
- Votre navigateur s'ouvre sur **http://127.0.0.1:8765** : c'est l'application.
- Une **fenêtre noire** reste ouverte : c'est le moteur. **La fermer arrête l'application et les envois.**
  Vous pouvez la réduire dans la barre des tâches.
- Si l'application tourne déjà, relancer `start.bat` ouvre simplement le navigateur.

**Pour fermer l'application :** fermez la fenêtre noire. Si vous ne la trouvez pas : Gestionnaire des tâches
(Ctrl+Maj+Échap) → ligne **Python** → clic droit → **Fin de tâche**.

## 3. Configurer la boîte mail (Réglages)

Les réglages se trouvent dans votre **cPanel Heberjahiz** :
**E-mail → Comptes de messagerie → ligne de votre adresse → « Connecter des appareils »**,
tableau « Paramètres manuels », colonne **« SSL/TLS sécurisés (recommandé) »**.

| Dans cPanel | Dans l'application |
|---|---|
| Serveur **sortant** | Envoi – serveur sortant (SMTP), port **465**, SSL |
| Serveur **entrant** (ligne IMAP) | Lecture – serveur entrant (IMAP), port **993** |
| Nom d'utilisateur | Identifiant (en général l'adresse complète) |

Utilisez le nom de serveur **exactement** comme cPanel l'affiche. Si le test signale un problème de
« certificat », c'est presque toujours que le nom de serveur n'est pas le bon.

Puis : **Tester la connexion** (un email de test arrive dans votre boîte, la liste des dossiers s'affiche),
vérifiez le dossier « Envoyés » et les dossiers surveillés (boîte de réception + spam), et **Enregistrez**.

Le mot de passe est rangé dans le **Gestionnaire d'identification Windows** (entrée « ODDO-Sequences »),
jamais dans les fichiers de l'application. Si vous changez le mot de passe de la boîte chez Heberjahiz,
ressaisissez-le dans Réglages.

**À demander une fois à Heberjahiz :** leur limite d'envoi par heure, et la confirmation que SPF, DKIM et DMARC
sont actifs pour oddo.ma (voir la page « Aide délivrabilité » de l'application).

## 4. Le mode test (activé au départ)

Tant que le **mode test** est activé (bandeau orange en haut), **tous les emails partent vers votre propre
adresse**, avec un objet du type `[TEST → contact@entreprise.ma] …`. Aucun prospect ne reçoit rien.
Faites toujours un premier essai complet ainsi. Pour passer aux envois réels : Réglages → « Désactiver le mode
test » (le bandeau devient rouge).

## 5. Préparer une campagne

1. **Contacts → Importer un fichier** : votre fichier Excel (ou CSV). Les colonnes sont reconnues
   automatiquement ; vérifiez puis validez l'aperçu. Ré-importer le même fichier met à jour sans doublon.
2. **Séquences → Blocs de contenu** : rédigez les 3 trames (FIN, RH, DIR) et les 7 paragraphes de secteur.
   L'email d'un contact `FIN-IND` = trame FIN + paragraphe IND. Remplacez tout le texte « À RÉDIGER ».
3. **Séquences → votre séquence** : objets (A, et B si vous voulez comparer deux objets), textes des relances,
   délais en jours ouvrés (week-ends et jours fériés exclus).
4. **Aperçu par contact** : voyez exactement les emails d'un contact et leurs dates ; **M'envoyer cet aperçu**
   pour les relire dans votre messagerie. Les problèmes (texte manquant…) s'affichent en rouge.

Variables utilisables : `{{ prenom }}`, `{{ nom }}`, `{{ entreprise }}`, `{{ poste }}`, `{{ secteur }}`,
`{{ custom.accroche_suggeree }}` (toute colonne importée), avec une valeur de repli :
`{{ prenom | "Madame, Monsieur" }}`. La signature et la ligne « répondez STOP » sont ajoutées automatiquement.

## 6. Lancer une campagne

**Campagnes → Nouvelle campagne** : nom, séquence, contacts visés (ex. code FIN-IND, Vague 1).
Puis **Vérifier et activer…** : nombre de contacts, premier envoi, fin estimée. L'activation est **refusée**
tant qu'un email serait incomplet.

Le moteur envoie ensuite **un email à la fois**, du lundi au vendredi entre 09:00–12:30 et 14:30–17:30
(réglable), avec un plafond de 25 emails par jour et 10 par heure, et un délai aléatoire entre deux envois.

## 7. Réponses, absences, rebonds, STOP

L'application lit votre boîte environ toutes les 10 minutes, et toujours juste avant d'envoyer. Elle **ne
marque rien comme lu** et ne déplace ni ne supprime aucun email.

- **Réponse** : les relances de la personne s'arrêtent ; la réponse apparaît dans **Réponses** (chiffre rouge).
- **Absence** : la séquence continue ; la date de retour s'affiche.
- **Rebond définitif** (adresse inexistante) : contact marqué « Rebond ».
- **STOP** : contact désinscrit et ajouté **définitivement** à la liste d'exclusion.
- **Réponse d'un collègue** de la même entreprise : affichée au tableau de bord, à rattacher d'un clic.

Classez chaque réponse d'un clic (Intéressé, À rappeler plus tard avec une date, Pas intéressé, Absent,
Mauvais contact, Désinscription). Les rappels du jour apparaissent au tableau de bord.

**Sécurité volontaire :** si la boîte devient illisible (mot de passe changé, serveur en panne), **plus rien
ne part** jusqu'à ce qu'elle redevienne lisible. Un message rouge l'indique au tableau de bord.

## 8. Suivre les résultats

- **Tableau de bord** : état du moteur, résultats, tableau par segment, test A/B, rappels, file d'envoi.
- **Récapitulatif par email** chaque jour à 18:00 (Réglages), seulement s'il s'est passé quelque chose.
- **Exporter (Excel)** : depuis le tableau de bord (tout) ou depuis une campagne.
- **Journal** : l'historique de toutes les actions de l'application.

Si l'app ou le PC s'arrête pendant un envoi, l'inscription apparaît dans **« À vérifier »** au tableau de bord :
regardez dans vos Envoyés, puis cliquez « Il est dans mes Envoyés » ou « Il n'est pas parti : renvoyer ».
L'application ne renvoie jamais un email d'elle-même dans ce cas (pas de doublon chez le prospect).

## 9. Lancement automatique au démarrage du PC

1. Touche **Windows + R**, tapez `shell:startup`, Entrée : un dossier s'ouvre.
2. Dans un autre explorateur, faites un **clic droit sur `start.bat` → Afficher d'autres options →
   Créer un raccourci**, puis déplacez ce raccourci dans le dossier `shell:startup`.
3. Facultatif : clic droit sur le raccourci → Propriétés → **Exécuter : Réduite**, pour que la fenêtre noire
   démarre réduite.

## 10. Empêcher la mise en veille pendant les heures d'envoi

Un PC en veille n'envoie rien. **Paramètres Windows → Système → Alimentation (et batterie) → Écran et mise en
veille** : réglez « Mettre en veille mon appareil après » sur **Jamais** quand l'ordinateur est branché.
L'écran peut, lui, s'éteindre sans problème.

## 11. Sauvegardes et restauration

Une sauvegarde de la base est faite **à chaque démarrage** et **chaque soir à 23:00**, dans `data\backups`
(les 14 dernières sont gardées). Copiez de temps en temps le dossier `data` sur une clé ou un cloud.

**Restaurer une sauvegarde :**
1. Fermez l'application (fenêtre noire).
2. Double-cliquez sur **`restaurer_sauvegarde.bat`**, choisissez la sauvegarde dans la liste, tapez **OUI**.
3. Relancez `start.bat`.

L'état d'avant la restauration est lui-même sauvegardé (« avant_restauration ») : on peut donc revenir en arrière.

## 12. Mettre à jour l'application

1. Fermez l'application.
2. Copiez les nouveaux fichiers **par-dessus** l'ancien dossier en remplaçant les fichiers.
   Ne supprimez **jamais** le dossier `data` : il contient vos contacts, vos campagnes et vos réglages.
3. Relancez `start.bat` : la base est sauvegardée puis mise à jour automatiquement.

## 13. Dépannage

| Problème | Solution |
|---|---|
| `start.bat` dit que Python est introuvable | Réinstallez Python 3.12 en cochant « Add python.exe to PATH ». |
| Les pages affichent « Not Found » après une mise à jour | Une ancienne version tourne encore : fermez Python dans le Gestionnaire des tâches, relancez `start.bat`. |
| « Envois suspendus : mot de passe refusé » | Ressaisissez le mot de passe dans Réglages. |
| « Lecture de la boîte impossible » | Testez la connexion dans Réglages ; vérifiez internet. |
| Rien ne part | Vérifiez : mode test, jour et heure d'envoi, plafond atteint (tableau de bord), campagne active ou en pause. |
| Erreur inexpliquée | Ouvrez le **Journal**, ou le fichier `data\logs\app.log`. |

## 14. Où sont mes données ?

Tout est dans le dossier **`data`** : la base (`oddo.db`), les journaux (`logs`), les sauvegardes (`backups`).
Chaque contact garde sa **source** (fichier et date d'import). Le bouton « Supprimer définitivement les
données » d'une fiche contact applique le droit d'effacement : seule une empreinte de l'adresse est gardée,
pour ne jamais la recontacter. *Ce guide ne constitue pas un avis juridique : vérifiez vos obligations au
titre de la loi 09-08 (CNDP).*

---

## Pour les développeurs

**Interface V2 (dossier `frontend/`)** : React 18 + TypeScript + Tailwind + composants shadcn/ui, compilée par Vite
dans `app/static/v2/`. Les fichiers compilés sont livrés : **Node.js n'est nécessaire que pour modifier l'interface**.
- `cd frontend && npm install` puis `npm run dev` (interface sur http://localhost:5173, l'API Python doit tourner) ;
- `npm run build` pour régénérer `app/static/v2/` (vérifie aussi les types TypeScript).
- Les données viennent de l'API JSON `app/web/api.py`, qui n'appelle que les fonctions testées de la V1.

- Vérifier que tout fonctionne : double-clic sur **`lancer_tests.bat`** (aucun email réel : faux serveurs et base temporaire).
- En ligne de commande : `.venv\Scripts\python -m pip install -r requirements-dev.txt` puis `.venv\Scripts\python -m pytest`.
- Bac à sable avec de faux serveurs mail : voir l'en-tête de `scripts/dev_fake_mail.py`.
- Choix techniques et écarts au cahier des charges : **`DECISIONS.md`**.
- Architecture : FastAPI + Jinja2 + HTMX, SQLite (SQLAlchemy 2, migrations Alembic dans `migrations/`),
  APScheduler. Points d'entrée : `app/launcher.py` (démarrage), `app/engine.py` (envoi),
  `app/imap_sync.py` (lecture), `app/web/` (pages).
