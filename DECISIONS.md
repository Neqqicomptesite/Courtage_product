# Décisions prises pendant le développement

Le cahier des charges demande de noter ici chaque point ambigu et l'option retenue
(la plus simple et la plus sûre).

## M1 – Squelette, base, Réglages, test de connexion

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 1 | ORM | SQLAlchemy 2 (style `Mapped[...]`) plutôt que SQLModel | Une seule source de vérité, documentation abondante, intégration Alembic sans contournement. |
| 2 | Dates en base | Type `UTCDateTime` : refuse toute date sans fuseau, relit en UTC | SQLite perd le fuseau ; une date « naïve » est la source n°1 de bugs d'horaires. |
| 3 | Colonne `references` | Renommée `references_header` | `REFERENCES` est un mot réservé SQL. |
| 4 | `message.sent_at/received_at` | Deux colonnes séparées | Plus clair qu'un champ à double sens. |
| 5 | Champs ajoutés à `enrollment` | `updated_at`, `attempts`, `last_error` | Nécessaires pour : détection des envois bloqués en `sending` (> 10 min), 3 nouvelles tentatives SMTP, affichage de l'erreur. |
| 6 | Champ ajouté à `message` | `body_full` (texte complet) et `step_position` | §6.7 demande de conserver le texte complet ; l'étape sert aux statistiques. |
| 7 | `kind` des messages envoyés | `NULL` (la liste du §5 ne concerne que les messages reçus) | Évite un faux type « out ». |
| 8 | Délais de la séquence d'exemple | « J+3, J+7 » = jours depuis l'étape 1 ; stocké en délai depuis l'étape précédente : 0, 3, **4** | Le §5 stocke le délai depuis l'étape précédente, le §7 parle en J+n cumulés. |
| 9 | Identifiant SMTP / IMAP | Un seul identifiant et un seul mot de passe pour les deux | Le §5 n'a qu'un champ `username` ; c'est le cas chez la plupart des hébergeurs. |
| 10 | Certificats TLS | Toujours vérifiés, **aucune option pour désactiver** la vérification | Option la plus sûre. Si le nom du serveur ne correspond pas au certificat, le message d'erreur explique quoi demander à Heberjahiz. |
| 11 | Absence de coffre de mots de passe | L'app refuse d'enregistrer (message clair) plutôt que d'écrire le mot de passe en clair | §3 : jamais en clair. |
| 12 | Protection CSRF / DNS rebinding | Vérification des en-têtes `Host` et `Origin` sur toutes les requêtes | Écouter sur 127.0.0.1 ne protège pas d'une page web malveillante ouverte dans le navigateur. C'est aussi le point d'extension pour l'authentification future (§10). |
| 13 | Jours fériés | Préremplis pour l'année en cours **et la suivante** ; dates lunaires 2027 marquées « (estimé) » | En novembre, une campagne déborde sur janvier. Sources : calendrier wafir.ma 2026-2027 et annonce de la Fête de l'Unité (31 octobre), consultés le 03/11/2026. À revérifier chaque année. |
| 14 | `tzdata` | Version minimale, **non figée** | La base horaire installée (2026.6) indique que Casablanca est passée à UTC+0 depuis l'automne 2026 : les règles changent, il faut la version la plus récente. |
| 15 | Fichier `requirements.txt` | Seuls les paquets utilisés directement sont épinglés | Un « pip freeze » fait sous Linux oublierait les dépendances propres à Windows (ex. `pywin32-ctypes` pour keyring). |
| 16 | Verrou d'instance | Verrou posé par le système (`msvcrt.locking` / `flock`) sur `data/app.lock` | Libéré automatiquement si l'app plante : pas de verrou fantôme. |
| 17 | Sauvegarde au démarrage | Faite dès M1, **avant** les migrations | Permet de revenir en arrière si une migration future pose problème. |
| 18 | Test de connexion | Teste les valeurs **saisies**, même non enregistrées ; mot de passe vide = celui déjà enregistré | Permet de corriger avant d'enregistrer. |
| 19 | Mot de passe avec accents | Message d'erreur explicite | Les protocoles SMTP/IMAP de la bibliothèque standard n'acceptent que l'ASCII pour l'authentification (limite connue). |
| 20 | Faux serveurs de test | `tests/fakes/` : SMTP (aiosmtpd) et IMAP maison, avec TLS et une autorité de test dont la clé a été détruite | Teste tout le chemin réel (TLS, authentification) sans jamais toucher la vraie boîte. |

## M2 – Import et contacts

Fichier réel analysé : 100 lignes, 100 emails uniques, 18 codes séquence.

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 21 | Fiabilité de l'email | Texte libre conservé tel quel ; filtres et règle des 30 % (§8) basés sur le **premier mot** : Bonne / Moyenne / À vérifier / Personnelle / Générique / Autre | Le fichier contient ~40 variantes (« Bonne (Limadata, via LinkedIn) »…). |
| 22 | Colonnes hors §6.1 | `#` ignorée ; `Accroche suggérée`, `Garanties à évoquer (pistes)` → champs personnalisés, avec leur libellé d'origine | Utilisables en variables (`{{ custom.accroche_suggeree }}`). |
| 23 | Ligne d'en-tête et feuille | Détectées automatiquement (première ligne contenant « Email », première feuille qui en contient une) | Le classeur d'Omar a 3 feuilles. |
| 24 | Ré-import d'un contact existant | Une cellule vide **n'efface pas** une valeur connue ; statut et notes jamais modifiés par un import | On ne perd jamais d'information en ré-important. |
| 25 | Champ `source` | Fixé au premier import (« fichier – importé le JJ/MM/AAAA HH:MM ») ; les mises à jour sont tracées dans le journal | Traçabilité de l'origine (loi 09-08). |
| 26 | Adresses de la liste d'exclusion | Importées mais **signalées** ; elles ne pourront jamais être inscrites dans une campagne | §6.1 demande de les signaler. |
| 27 | Contact effacé (droit d'effacement) | Ignoré à l'import (« Contact effacé à sa demande ») : ses données ne sont pas recréées | Ré-importer l'ancien fichier ne doit pas annuler un effacement. |
| 28 | Fichier importé | Supprimé de `data/imports/` après validation ou annulation | Minimisation des données. |
| 29 | Exclusion d'un domaine ou d'une adresse | Les contacts actifs concernés passent aussitôt en « Ne plus contacter » | Cohérence entre la liste et les statuts. |
| 30 | Retrait de la liste d'exclusion | Possible seulement pour les ajouts manuels ; un STOP ou un effacement est définitif | §9. |
| 31 | Réactivation | Refusée pour un contact désinscrit (STOP) ou présent dans la liste d'exclusion | §9 : désinscription définitive. |
| 32 | Données réelles et tests | Le vrai fichier n'est **pas** copié dans le projet ; un fichier synthétique reproduit ses pièges ; test d'acceptation optionnel via `ODDO_REAL_LEADS` | Ne pas disperser des données personnelles. |
| 33 | Libellés Réglages | « Envoi – serveur sortant (SMTP) » / « Lecture – serveur entrant (IMAP) » | Vocabulaire de cPanel. |

## M3 – Blocs, séquences, aperçu, A/B

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 34 | Moteur de modèles | Syntaxe maison minimale (`{{ var }}`, `{{ var \| "repli" }}`), pas Jinja | Pas de boucles ni de code dans un email ; rien ne s'exécute par accident. |
| 35 | Ce qui compte comme « problème » | Variable inconnue, valeur vide sans repli, variable mal écrite, bloc introuvable, code séquence absent, objet ou corps vide, texte « À RÉDIGER » restant (bloc, étape ou objet) | Une campagne avec un problème ne pourra pas être activée (M4). |
| 36 | Variables dans les blocs | Autorisées ; un bloc ne peut pas contenir `{{ bloc_cible }}` / `{{ bloc_secteur }}` | Évite les boucles infinies. |
| 37 | Signature | Ajoutée automatiquement sous le corps, sauf si le modèle contient `{{ signature }}` | Pas de double signature. |
| 38 | Ligne STOP | Toujours ajoutée en dernier, impossible à retirer d'un modèle | §9. |
| 39 | Lignes vides | Jamais plus d'une ligne vide d'affilée après rendu | Un bloc vide ne laisse pas de trou. |
| 40 | Objets des relances | Relance « dans le même fil » : `Re: <objet de l'étape 1>` ; relance hors fil : objet propre (variante A) | §6.4. |
| 41 | Étape 1 | Délai forcé à 0 et toujours un nouveau fil | Elle ouvre la conversation. |
| 42 | Répartition A/B | Mélange aléatoire puis alternance A, B, A, B… ; les ajouts ultérieurs vont dans le groupe le moins rempli | 50/50 exact (un tirage à pile ou face donnerait p. ex. 58/42 sur 100), stable, aléatoire. Le tirage réel a lieu à l'inscription (M4) ; l'aperçu montre une variante fixe par contact. |
| 43 | Jours ouvrés / jours d'envoi | Délais comptés en jours ouvrés (lun-ven hors fériés) ; envois uniquement les jours cochés hors fériés, dans les plages horaires | Deux notions distinctes du §4 et du §6.4. |
| 44 | Heure d'une relance | Première ouverture de la fenêtre le jour prévu (ex. 09:00) | Simple et prévisible ; le moteur (M4) étale ensuite selon les plafonds. |
| 45 | Dates de l'aperçu | Estimation « si la campagne démarrait maintenant », sans les plafonds | Les plafonds dépendent des autres contacts de la campagne. |
| 46 | « M'envoyer cet aperçu » | Toutes les étapes, chaînées dans un même fil, objet `[APERÇU → contact] [Étape n] …`, **uniquement** à l'adresse de la boîte ; ne compte pas dans les plafonds | Voir le rendu réel dans Outlook ou le webmail sans risque. |
| 47 | Suppression d'étape | Interdite pour l'étape 1, et pour toute étape d'une séquence déjà utilisée par une campagne | Décalerait les envois en cours. |
| 48 | Jours de la semaine | Affichés en français par l'app (« mardi 03/11/2026 à 14:30 ») | Indépendant de la langue de Windows. |

## M4 – Campagnes et moteur d'envoi

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 49 | Migration 0002 | `message.to_email` (destinataire réel) et `message.test_mode` | Prouver après coup qu'en mode test rien n'est parti chez un contact. |
| 50 | Un seul endroit choisit le destinataire | `engine._send` : en mode test, To = adresse de la boîte, objet `[TEST → contact]` | Impossible d'oublier le mode test ailleurs. |
| 51 | Ordre d'écriture | Message enregistré + statut `sending` validés en base **avant** SMTP ; en cas d'échec avant envoi, la trace est retirée | §6.6 étape 4 ; base de la protection anti-doublon. |
| 52 | Envoi bloqué en `sending` | Passe en « à vérifier » après 10 min, au démarrage **et** à chaque passage du moteur | Le §6.6 ne parle que du démarrage ; sans vérification périodique, un redémarrage dans les 10 min laisserait l'inscription bloquée. |
| 53 | Actions « à vérifier » | « Il est dans mes Envoyés » (valide et avance) ou « Il n'est pas parti : renvoyer » | Jamais de renvoi automatique. |
| 54 | Erreurs SMTP | 4xx / coupure réseau : nouvel essai à +5, +15, +60 min puis « erreur » ; 5xx sur le **destinataire** : rebond définitif (contact `bounced`) ; autre 5xx (ex. contenu refusé) : « erreur » sans rebond ; mot de passe refusé : rien n'est perdu, envois suspendus avec message au tableau de bord | §6.6. Un refus de contenu ne prouve pas que l'adresse est mauvaise. |
| 55 | Mode test et refus 5xx | En mode test, un refus ne passe jamais le contact en rebond | Le destinataire réel était l'adresse d'Omar. |
| 56 | Délai aléatoire | Tiré après chaque envoi réussi et mémorisé (`engine_next_allowed_at`) | Survit à un redémarrage de l'app. |
| 57 | Plafonds | Comptés sur les envois réussis de la boîte ; jour = journée calendaire au Maroc ; heure = 60 dernières minutes glissantes | Simple et prévisible. Les aperçus envoyés à soi-même ne comptent pas. |
| 58 | Montée en charge | Active pendant `rampup_days` (7) jours à partir du tout premier envoi de la boîte | §4. |
| 59 | Revérification avant envoi | Statut du contact, liste d'exclusion, réponse / STOP / rebond reçu depuis l'inscription | §6.6 étape 2. La synchro IMAP « si plus de 10 min » est appelée mais ne lit la boîte qu'à partir de M5. |
| 60 | Rendu à l'envoi | Mêmes fonctions que l'aperçu (`compose_step`) ; un email qui ne se compose plus (séquence modifiée entre-temps) passe en « erreur » au lieu de partir incomplet | Ce que montre l'aperçu est ce qui part. |
| 61 | Étape 1 sautée | La relance reprend l'objet qu'aurait eu l'étape 1 (`Re: …`), dans un nouveau fil | Pas de « Re: » vide. |
| 62 | Inscription | À l'activation uniquement ; les contacts importés plus tard ne sont pas ajoutés automatiquement | Option la plus prévisible. |
| 63 | Activation | Bloquée si un contact produit un email incomplet, pour **les deux** variantes A et B ; avertissements fiabilité > 30 % et > 1 lien ; contacts déjà dans une autre campagne active exclus sauf choix contraire | §6.5, §8. |
| 64 | Fin estimée | Simulation du moteur (plafonds, fenêtres, délai moyen, fériés) en supposant aucune réponse | C'est une borne haute, annoncée comme telle. |
| 65 | Reprise après pause | Les échéances dépassées sont reportées à la prochaine ouverture de la fenêtre ; le moteur les envoie ensuite une par une | §6.5. |
| 66 | « Envoyer maintenant » | Respecte le mode test et la revérification, mais pas la fenêtre ni le délai entre deux envois | C'est une action manuelle explicite. |
| 67 | Fin de campagne | « Terminée » quand plus aucune inscription n'est programmée, en attente, en erreur ou à vérifier | Une erreur non traitée garde la campagne ouverte. |
| 68 | Planificateur | APScheduler : moteur chaque minute (une exécution à la fois), sauvegarde quotidienne 23:00 heure du Maroc | §3, §10. |

## M5 – Synchronisation IMAP

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 69 | Lecture seule | Dossiers ouverts avec EXAMINE, contenu lu avec BODY.PEEK[] ; rien n'est déplacé, supprimé ni marqué comme lu | §6.7. Vérifié par le test (le faux serveur note tout marquage « lu »). |
| 70 | Premier passage sur un dossier | Seuls les messages reçus depuis le **premier envoi de l'app** sont lus (à défaut : depuis la veille) | Ne pas analyser des années de boîte de réception. |
| 71 | Doublons | UIDVALIDITY + dernier UID lu, **et** contrôle par Message-ID | Si le serveur renumérote un dossier, rien n'est traité deux fois. |
| 72 | Fréquence | Le moteur lance la synchro dès que la dernière date de plus de 10 min (donc ≈ toutes les 10 min, et toujours juste avant un envoi) ; bouton « Synchroniser maintenant » | §6.6 étape 2 et §6.7, sans deux tâches concurrentes. |
| 73 | Boîte illisible | **Aucun envoi** tant que la boîte ne peut pas être lue ; nouvel essai 10 min plus tard ; message rouge au tableau de bord | Option la plus sûre : on n'envoie pas de relance à quelqu'un qui a peut-être répondu. |
| 74 | Nos propres emails | Ignorés s'ils reviennent dans la boîte (cas du mode test : ils arrivent chez Omar) | Sinon chaque envoi test serait pris pour une réponse. |
| 75 | Email sans aucun lien avec un contact | Non enregistré | Minimisation des données ; la boîte reste la référence. |
| 76 | Rebond sans code lisible | Traité comme **temporaire** | On n'élimine pas un contact sur une supposition. |
| 77 | Rebond : retrouver le contact | Message-ID d'origine, sinon `Final-Recipient` | §6.7. |
| 78 | STOP | Message très court (≤ 12 mots) qui commence par « stop » ou contient une formule de désinscription, ou objet « STOP » | « Contient seulement » du §6.7 ; une vraie réponse contenant le mot « stop » n'est pas une désinscription. |
| 79 | Citations | Coupure aux lignes « > », à « Le … a écrit : » (1 ou 2 lignes, deux-points obligatoires), « On … wrote: », séparateurs Outlook, en-tête « De : / Envoyé : », `<blockquote>` HTML | « Le client a écrit hier » ne doit pas couper le message. |
| 80 | Date de retour d'absence | Affichée telle qu'écrite, jamais interprétée | Trop de formats pour une conversion fiable. |
| 81 | Réponse d'un collègue (même domaine) | « Non rattachée », avec suggestion ; rien n'est arrêté avant confirmation d'Omar ; jamais pour Gmail/Hotmail/Yahoo… | §6.7 étape 3. |
| 82 | Mode test | Une réponse à un email de test arrête la séquence concernée, mais ne change ni le statut du contact ni la liste d'exclusion | §4 « aucun statut de contact n'est modifié » ; arrêter la séquence permet de tester le comportement. Le mode test est celui de l'email d'origine, pas le réglage du moment. |
| 83 | Classement automatique | STOP → « Désinscription », absence → « Absent » ; les vraies réponses restent « non classées » pour Omar (M6) | Moins de tri manuel, sans deviner l'intention d'une vraie réponse. |
| 84 | Migration 0003 | `message.return_date`, `message.suggested_contact_id` | Affichage de l'absence et de la piste de rattachement. |
| 85 | Journal | APScheduler limité aux avertissements | Il écrivait 2 lignes par minute (constaté sur le PC d'Omar). |

## M6 – Tableau de bord, Réponses, récapitulatif, export

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 86 | Unité des indicateurs | L'**inscription** (un contact dans une campagne) | Un contact peut être dans plusieurs campagnes ; chaque campagne a ses propres chiffres. |
| 87 | « Réponse » | Vraie réponse uniquement (pas une absence, pas un STOP, qui sont comptés à part) ; taux = réponses ÷ contacts ayant reçu au moins 1 email | §6.8. |
| 88 | Segment | Code séquence (cible × secteur), touchés / réponses / taux, effectifs toujours affichés | §6.8. |
| 89 | A/B | Base : contacts ayant reçu l'étape 1 ; mention « échantillon trop petit » tant qu'une variante a moins de 100 contacts | §6.8. |
| 90 | Envois en mode test | Comptés dans les indicateurs de leur campagne (une campagne lancée en mode test est une campagne de test) ; signalés « mode test » dans Réponses et dans l'export | Simple et transparent. |
| 91 | Boîte « Réponses » | Réponses, STOP et absences ; filtre « Non classées » par défaut ; compteur dans le menu = réponses et STOP non classés ; classement en un clic sans recharger la page (HTMX), compteur mis à jour | §6.8. |
| 92 | Effets du classement | « Désinscription » = comme un STOP (liste d'exclusion, définitif) ; « Mauvais contact » = contact « Ne plus contacter » ; les autres classements n'ont pas d'effet sur les envois (les relances sont déjà arrêtées par la réponse) | Protéger l'avenir sans surprise. En mode test, aucun effet sur le contact. |
| 93 | Rappels | Classement « À rappeler plus tard » avec date obligatoire ; liste « Rappels du jour » au tableau de bord (avec le téléphone) ; bouton « Rappel effectué » | §6.8. |
| 94 | Migration 0004 | `message.note`, `message.callback_on` | Note et date de rappel par réponse. |
| 95 | Récapitulatif | Vérifié chaque minute ; part une fois par jour dès l'heure passée (si le PC était éteint à 18:00, il part à l'ouverture le même jour) ; rien s'il n'y a eu aucune activité ; pas de ligne STOP ; non compté dans les plafonds | §6.9. |
| 96 | « Prévus demain » | Échéances jusqu'à demain soir, plafonnées au plafond du jour ; annoncé comme estimation | Les plafonds peuvent en décaler. |
| 97 | Export | Feuilles Synthèse, Contacts, Réponses ; dates en heure du Maroc sans fuseau (Excel n'en gère pas) ; export global = une ligne par contact avec sa dernière campagne ; export d'une campagne = une ligne par inscription | §6.10. |
| 98 | File d'envoi | 7 prochains jours, 100 lignes au plus, actions « Envoyer maintenant », « Sauter l'étape », « Retirer » | §6.8. |

## M7 – Finitions

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 99 | Restauration | `restaurer_sauvegarde.bat` → `python -m app.restore` : liste numérotée, confirmation « OUI », refus si l'app est ouverte, contrôle d'intégrité, copie de sécurité « avant_restauration », écriture via l'API backup de SQLite | §11 demande de pouvoir restaurer ; une copie de fichier à la main risque de corrompre la base (fichiers -wal/-shm). |
| 100 | Ordre de la restauration | La sauvegarde choisie est chargée en mémoire avant la copie de sécurité | La copie de sécurité peut supprimer la plus ancienne des 14 sauvegardes, peut-être celle qu'on restaure. |
| 101 | Page Journal | 300 derniers événements, filtres catégorie / gravité / texte, liens vers contact ou campagne | §10. Le fichier `data/logs/app.log` garde le détail technique. |
| 102 | `lancer_tests.bat` | Installe les outils de test puis lance pytest ; aucun email réel (faux serveurs locaux, base temporaire) | Permettre de valider le critère M7 « tous les tests au vert » sur le PC Windows. |
| 103 | Fichiers .bat | ASCII pur, fins de ligne Windows (CRLF), vérifiés par un test | cmd.exe affiche mal les accents et exécute mal les fichiers aux fins de ligne Unix. |
| 105 | Tests sous Windows | Les tests se connectent aux faux serveurs par `127.0.0.1`, jamais par `localhost` | Constaté sur le PC d'Omar : sous Windows, `localhost` tente d'abord l'IPv6 `::1` (où rien n'écoute) et attend ~2 s à chaque connexion, soit des tests environ 30 fois plus lents. |
| 104 | Hors périmètre volontaire | Pas de graphiques Chart.js (optionnel au §3) : tableaux avec effectifs | Sur de petits volumes, un tableau avec les effectifs est plus honnête qu'un graphique. |

## Points à vérifier par Omar (non vérifiables par le développement)

- Réglages exacts Heberjahiz (fait : connexion SMTP/IMAP réussie le 03/11/2026, dossiers INBOX et INBOX.spam).
- Limite d'envoi horaire de l'offre Heberjahiz, et SPF / DKIM / DMARC actifs sur oddo.ma.
- Dates des fêtes religieuses 2027 (estimations à corriger dans Réglages dès l'annonce officielle).
- Obligations exactes de la loi 09-08 pour la prospection B2B (ce projet ne constitue pas un avis juridique).

# V2

## V2.0 – Socle et tableau de bord

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 106 | Séparation V1 / V2 | Dossier distinct, port 8766, base copiée de la V1, version 2.0.0-dev | Omar garde la V1 intacte comme solution de repli. |
| 107 | Mode test verrouillé | `ODDO_FORCE_TEST_MODE=1` dans `start.bat` : le réglage `test_mode` vaut toujours « activé » et le bouton de désactivation est refusé | Les deux versions partagent la même boîte : aucun envoi réel en double possible pendant le développement. À retirer à la bascule (V2.4). |
| 108 | Interface | React 18 + TypeScript + Tailwind 3 + composants shadcn/ui écrits dans `frontend/src/components/ui` (pas de CLI : l'environnement n'accède qu'aux registres de paquets), compilée par Vite dans `app/static/v2` | Choix d'Omar (vrai shadcn/ui). Aucun Node.js requis sur le PC d'Omar : fichiers compilés livrés. |
| 109 | API | `app/web/api.py` ne contient aucune règle métier ; elle appelle `stats`, `engine`, `imap_sync`, `replies_service` | Les règles restent testées à un seul endroit (tests V1 inchangés). |
| 110 | Cohabitation des interfaces | `/` = nouvelle interface ; les sections non migrées s'ouvrent dans les pages V1 (icône flèche dans le menu) ; ancien tableau de bord sur `/classique` | Migration section par section, sans rupture (terminée en V2.1). |
| 111 | Identité | Bleu `#244480` (couleur principale), vert `#009454` (succès, réponses), anthracite `#303030`, relevés sur le logo ; police Inter (variable, embarquée, sans connexion) ; logo recoloré pour le mode sombre | Logo fourni par Omar le 03/11/2026. |
| 112 | Temps réel | État interrogé toutes les 15 s, tableau de bord toutes les 30 s ; indicateur « Boîte lue il y a … » (vert / orange / rouge) ; lecture de la boîte d'un clic avec notification | Rendre visible la synchronisation automatique, qui existait déjà en V1. |
| 113 | Thème | Clair / sombre, mémorisé dans le navigateur | Confort ; perte sans conséquence. |

## V2.1 – Toutes les pages dans la nouvelle interface

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 114 | Application d'une seule page | Toutes les sections (séquences, blocs, campagnes, réponses, contacts, import, exclusions, journal, réglages) sous `/v2/…`, routeur React avec `basename="/v2"` ; le serveur renvoie `index.html` pour chaque adresse `/v2/…` | Navigation instantanée sans rechargement ; les pages classiques restent accessibles à leurs adresses d'origine (repli). |
| 115 | API JSON complète | `api_contacts`, `api_sequences`, `api_campaigns`, `api_misc` réutilisent les services et la validation V1 (`read_sending_form`, `_read_mailbox_form`, `importer`, `campaigns_service`…) | Une seule source de vérité pour les règles ; 12 tests d'API ajoutés. |
| 116 | Éditeur de séquence | Trois colonnes : frise des étapes (délai réglable dans une bulle), éditeur (variables insérées au curseur), aperçu réel pour un contact ; enregistrement automatique (0,7 s), alerte si on quitte avant | Moins de clics, inspiré des outils de prospection actuels. |
| 117 | Campagnes | Assistant en 3 étapes (Qui → Quoi → Vérifier et lancer) avec compteur de contacts en direct ; le contrôle complet de lancement (V1) est affiché avant le bouton | Rien ne part sans le contrôle « email incomplet » de la V1. |
| 118 | Réponses | Boîte de réception en deux volets, raccourcis J/K et 1–6, date de rappel en un clic (1 semaine, 2 semaines, 1 mois, 3 mois) | Classer vite, comme dans une messagerie. |
| 119 | Graphiques | Activité par jour (envois / réponses), emails par étape, issues des contacts (barre empilée), taux de réponse par segment et par objet A/B | Demande d'Omar. Les effectifs restent affichés à côté des pourcentages (cf. #104 : petits volumes). |
| 120 | Fiche contact | Panneau latéral ouvert par `?open=<id>` (lien partageable depuis le tableau de bord, les réponses, la recherche Ctrl+K) | Garder la liste visible derrière. |

## V2.2 – Retouches avant partage

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 121 | Sauvegarde V2.1 | Dossier `oddo-sequences-v2.1-sauvegarde` sur le PC (code + copie des données du 03/11 19:25, intégrité vérifiée) | Demande d'Omar : garder la V2.1 comme solution de repli. |
| 122 | Résultats du tableau de bord | 3 cartes : emails envoyés, réponses, « sans réponse depuis plus de 3 jours » ; les autres chiffres restent sur la page de chaque campagne ; les rebonds deviennent une alerte affichée seulement s'il y en a | Demande d'Omar ; les rebonds protègent la réputation du domaine, on ne les masque pas complètement. |
| 123 | « Sans réponse depuis 3 jours » | Contacts actifs dont le dernier email a au moins 3 jours OUVRÉS (week-ends et fériés des Réglages exclus) et qui n'ont jamais répondu, rebondi ni dit STOP ; une réponse d'absence ne compte pas comme une réponse ; liste triée du plus ancien, avec téléphone et prochaine relance automatique éventuelle | Choix d'Omar (jours ouvrés). Sert à relancer par téléphone. |
| 124 | Journal | Retiré du menu de la nouvelle interface ; les évènements restent enregistrés (historique des fiches contact) ; retiré aussi du menu de l'ancienne interface V2 (la page reste joignable par son adresse /journal) ; la V1 n'est pas modifiée | Demande d'Omar ; ces données servent ailleurs. |
| 125 | Modèle Excel | `GET /api/contacts/template` : en-têtes reconnus par l'import, listes déroulantes (feuille « Listes » masquée), code séquence par formule, onglet « Mode d'emploi » avec un exemple fictif hors de la feuille importée | Un fichier rempli s'importe sans réglage ; l'exemple ne peut pas être importé par erreur. |
| 126 | Code séquence déduit | À l'import comme à la saisie, si la cible et la famille de secteur sont reconnues, le code (FIN-BTP…) est calculé ; libellés du fichier d'Omar (« Finance & administration ») et des blocs (« Finance et administration ») acceptés | La formule Excel n'a pas de valeur tant qu'Excel n'a pas enregistré le fichier ; on ne dépend pas d'elle. |
| 127 | Saisie et modification à la main | Fiche latérale « Nouveau contact » et bouton « Modifier » ; email obligatoire, unique (lien vers la fiche existante), refus d'une personne effacée, avertissement si l'adresse est exclue ; l'email ne se modifie plus dès qu'un email a été échangé ; chaque création ou modification est notée dans l'historique | Les emails reçus sont rattachés par adresse : la changer après coup casserait l'historique. |

## V2.3 – Entreprises et types de contacts

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 128 | Table `company` | Une fiche par entreprise, reconnue par son nom « replié » (minuscules, sans accents ni formes juridiques, « groupe » ou « Maroc ») : « SANLAM Maroc S.A. » = « Sanlam » ; le nom reste recopié dans `contact.company` | Les variables des emails, les filtres et l'export utilisent déjà ce champ : rien ne casse. |
| 129 | Reprise des données | Migration 0005 : regroupement par nom replié uniquement, sans rapprochement approximatif ; domaine déduit des emails (sauf messageries gratuites) ; testée sur une copie de la base d'Omar : 100 contacts → 100 entreprises, aucun regroupement, 75 domaines | Un regroupement approximatif pourrait mélanger deux sociétés ; les doublons se fusionnent à la main (« Fusionner avec… »). |
| 130 | Recréation de la table contact | Vérifiée par un test : la migration ne supprime ni inscriptions ni messages (les clés étrangères ne sont pas actives pendant les migrations) | SQLite recrée la table pour ajouter une contrainte ; avec les suppressions en cascade actives, l'historique aurait été effacé. |
| 131 | Types de contacts | Prospect, Client, Assureur, Partenaire (choix d'Omar) ; seuls les prospects entrent dans une campagne (exclusion à l'activation, refus à l'ajout individuel, vérification par le moteur juste avant chaque envoi) | Un gestionnaire de Sanlam ou un client ne doit jamais recevoir de prospection, même par erreur. |
| 132 | Type d'entreprise | Le type se règle sur l'entreprise et s'applique à toutes ses personnes ; passer en non-prospect arrête aussitôt leurs séquences (confirmation demandée) ; un nouveau contact d'une entreprise connue en hérite | En B2B, la relation est avec l'entreprise. |
| 133 | Ajout d'un seul contact | « Ajouter à une campagne » depuis la fiche : campagne en cours ou en pause, mêmes contrôles qu'un lancement (statut, type, exclusion, email complet), confirmation si le contact est déjà dans une autre campagne | Demande d'Omar ; prépare l'action depuis la future page Boîte mail. |
| 134 | Recherche | Ctrl+K et la page Entreprises cherchent mot par mot dans l'entreprise ET ses personnes (nom, poste, email) : « gestionnaire sanlam » | Exemple d'Omar. |
| 135 | Test daté | `test_reply_received_stops_next_steps` dépendait de la date réelle (échec à partir du 04/11/2026 08:00) : corrigé en V2 ; le même test de la V1 échouera désormais sans que l'application soit en cause | La V1 reste intacte par choix ; seul le test est concerné. |

## V2.4 – Boîte mail

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 136 | Boîte mail complète | Page « Boîte mail » : n'importe quel dossier, 7/30/90 derniers jours (200 emails au plus), onglet « Réponses aux campagnes » à côté ; chaque email est relié au CRM (contact, entreprise, type) avec « Créer le contact » ou « Ajouter à une campagne » | Demande d'Omar : la boîte devient le point d'entrée. |
| 137 | Lecture seule | EXAMINE et BODY.PEEK uniquement : rien n'est marqué comme lu, déplacé ni supprimé (vérifié par test sur le faux serveur) | La boîte reste celle d'Omar ; l'application n'y change rien. |
| 138 | Rien sur le disque | La liste (expéditeur, objet, date) est gardée en mémoire 60 s ; le texte est relu sur le serveur à chaque ouverture ; les pièces jointes sont listées, pas téléchargées | Les emails contiennent des données de clients (choix d'Omar). |
| 139 | Écrire depuis l'application | Un seul éditeur (bouton « Nouveau message », « Répondre », fiche contact, fiche entreprise, Ctrl+K) ; fil de conversation conservé (In-Reply-To / References), signature au choix, citation du message d'origine au choix, copie dans « Envoyés » | Choix d'Omar : « écrire dans l'app ». |
| 140 | Mode test | Un email écrit à la main suit le mode test comme les séquences (part chez Omar, objet [TEST → destinataire]) ; la Cc est ignorée en mode test | Le verrou de la V2 vaut pour TOUT envoi, sans exception. |
| 141 | Hors statistiques | Un email écrit à la main est enregistré dans l'historique du contact et de l'entreprise, mais sans inscription : il ne compte ni dans les statistiques, ni dans le graphique d'activité, ni dans les plafonds d'envoi ; pas de ligne de désinscription ni d'en-tête List-Unsubscribe | Ce n'est pas de la prospection. |
| 142 | Liste d'exclusion | Écrire à une adresse exclue demande une confirmation explicite | Une personne qui a dit STOP peut encore vous écrire ; lui répondre reste votre décision. |
| 143 | Réponses à un email écrit à la main | La synchronisation ne les range pas dans « Réponses aux campagnes » (elles restent dans la boîte) ; un prospect inscrit qui répond voit quand même sa séquence s'arrêter | Ne pas mélanger la prospection et les échanges courants (assureurs, clients). |

## V2.5 – Relance à un jour précis, démarrage planifié

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 144 | Jour et heure d'une étape | Chaque étape peut ajouter au délai un jour de la semaine (lundi à vendredi) et/ou une heure : « au moins J+3, puis le mardi suivant, à 10:00 » ; l'étape 1 aussi (« envoi le mardi à 10:00 ») | Choix d'Omar (« relance à un jour précis ») ; le délai reste le minimum garanti entre deux emails. |
| 145 | Cas limites | Heure déjà passée ce jour-là : semaine suivante (jour précis) ou lendemain ; heure hors plages : ramenée à la plage suivante ; jour férié ou sans envoi : prochaine ouverture (pas d'attente d'une semaine) | Ne jamais envoyer hors plages ni un jour férié ; ne pas retarder inutilement. |
| 146 | « À partir de » | L'heure est un début : avec 20 contacts dus le mardi à 10:00, le moteur les envoie un par un, avec les pauses et plafonds habituels | Un envoi groupé à la même minute ressemblerait à du publipostage. |
| 147 | Démarrage planifié | La campagne peut être lancée tout de suite avec une date de démarrage : tous les 1ers emails sont dus à cette date (puis jour/heure de l'étape 1) ; l'estimation de fin en tient compte ; la date se change tant qu'aucun email n'est parti | Préparer une campagne le vendredi pour le lundi matin, sans y penser le lundi. |
| 148 | Migration 0006 | Trois colonnes ajoutées (step.weekday, step.send_time, campaign.start_at), sans recréation de table ; testée sur une copie de la base d'Omar | Aucune donnée recopiée, donc aucun risque pour l'historique. |
| 149 | Heure saisie | La date et l'heure de démarrage sont saisies à l'heure du PC (heure du Maroc chez Omar) et envoyées avec leur fuseau | Si un collègue est à l'étranger, c'est son heure locale qui s'applique : à garder en tête pour le kit de partage. |

## V2.6 – Bascule et kit de partage

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 150 | Bascule | La V2 devient l'outil de production : verrou du mode test retiré de `start.bat` (le mode test reste ACTIVÉ, Omar le désactive lui-même), adresse http://127.0.0.1:8765 (celle de la V1), version 2.6.0 | Même adresse = la V1 et la V2 ne peuvent pas tourner en même temps : jamais deux moteurs d'envoi sur la même boîte. Le lanceur de la V2 le détecte et refuse de démarrer avec un message clair ; la V1, inchangée, s'arrête sur une erreur de port. |
| 151 | Données de production | On garde la base de la V2 (déjà migrée, entreprises créées) : vérifié le 04/11, elle contient les mêmes 100 contacts que la V1 et aucun email n'était parti, ni d'un côté ni de l'autre | Aucune donnée à reprendre de la V1. |
| 152 | Envois réels | Désactiver le mode test demande de taper « REEL », avec une liste de vérifications | Le seul réglage qui fait partir de vrais emails : il ne doit jamais se faire d'un clic distrait. |
| 153 | Kit de partage | `ODDO-Sequences-kit.zip` : l'application compilée (sans données, sans tests, sans sources de l'interface), `start.bat`, un guide d'installation d'une page (`LISEZ-MOI-INSTALLATION.html`) ; boîte mail par défaut vide (plus l'adresse d'Omar) ; démarrage testé sur une base vierge | Chaque collègue a sa propre copie, sa boîte et ses données (choix d'Omar). |
| 154 | Domaine partagé | Le guide rappelle que tout le monde envoie depuis oddo.ma (plafonds, fiabilité « Bonne ») ; SPF, DKIM et DMARC restent à vérifier par Omar (non vérifiables depuis l'environnement de développement) | La réputation du domaine est commune à toute l'équipe. |

## V2.7 – Retouches d'usage

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 155 | Sauvegarde V2.6 | Dossier `oddo-sequences-v2.6-sauvegarde` (créé par Omar, base vérifiée : intègre, 100 contacts, schéma à jour) | Repli si la V2.7 pose problème. |
| 156 | Ordre du menu | Tableau de bord, Boîte mail, Séquences, Campagnes, Contacts, Entreprises, Réglages | La boîte mail est l'outil du quotidien. |
| 157 | « Envoyés sans réponse » | 3e onglet de la Boîte mail : chaque contact dont le dernier email date d'au moins N jours ouvrés, avec cet email, la prochaine relance automatique éventuelle, « Appeler » et « Relancer » (réponse dans le même fil) ; la carte du tableau de bord y mène ; N se règle dans Réglages → Rythme d'envoi (1 à 30, 3 par défaut) | Demande d'Omar : la carte doit mener aux emails eux-mêmes. |
| 158 | Noms de dossiers | « Boîte de réception », « Envoyés », « Archives », « Brouillons », « Indésirables », « Spam », « Corbeille » au lieu de INBOX.Sent… ; le nom exact reste utilisé pour parler au serveur | Lisible sans connaître IMAP. |
| 159 | Vocabulaire | Cible → Fonction ; Famille de secteur → Secteur ; Secteur précis → Activité ; Code séquence → Profil ; Vague → Lot (la valeur « Vague 2 » du fichier s'affiche « Lot 2 ») ; Fiabilité → Qualité de l'email ; Trames → Messages par fonction ; Étape → Email n° ; touchés → contactés | Les mots du métier plutôt que ceux du fichier de segmentation. Les valeurs enregistrées et le modèle Excel ne changent pas (compatibilité avec le fichier d'Omar). |
| 160 | Types en haut de page | Contacts et Entreprises : cartes cliquables Tous / Assureurs / Clients / Prospects / Partenaires (dans cet ordre), en dehors des filtres ; la liste des entreprises suit le même ordre | La distinction principale du CRM d'un courtier. |
| 161 | Écrire un email | Fenêtre ancrée en bas à droite (réduire, plein écran, fermer), champs compacts, Ctrl+Entrée ; l'envoi se fait en arrière-plan avec un bandeau de suivi ; en cas d'échec, le brouillon revient intact | L'ancien panneau prenait toute la hauteur et bloquait pendant l'envoi. |

## V2.8 – Pièces jointes, types de séquence, assureurs, agenda, notifications

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 162 | Sauvegarde V2.7 | Dossier `oddo-sequences-v2.7-sauvegarde` (code + copie de la base du 04/11, intègre, 100 contacts) | Repli si la V2.8 pose problème. |
| 163 | Pièces jointes | Dans un email écrit depuis l'application (trombone ou glisser-déposer) et dans n'importe quelle étape d'une séquence (en pratique la 1re) ; fichiers rangés dans `data/attachments`, jamais supprimés (l'historique y fait référence) ; 10 Mo au plus par email, toutes pièces confondues ; programmes (.exe, .bat, .js…) refusés | Demande d'Omar. 10 Mo : au-delà, des serveurs refusent l'email. Une pièce jointe dans un 1er email de prospection peut nuire à la délivrabilité : l'éditeur le signale, sans l'interdire. |
| 164 | Types de séquence | Prospection, Gestion, Souscription ; la page Séquences est rangée par type ; le type se choisit à la création et se change tant qu'aucune campagne n'utilise la séquence (sinon : dupliquer) | Demande d'Omar. Changer le type d'une séquence en cours changerait les règles d'envoi en cours de route. |
| 165 | Qui reçoit quoi | Prospection : prospects uniquement, ligne « STOP » et en-tête de désinscription. Gestion et souscription : tous les types de contacts (choix d'Omar : clients et assureurs aussi), sans ligne STOP ; filtre « Type de contact » dans l'assistant ; passer un contact en client/assureur n'arrête que ses séquences de prospection | Un client ou un assureur n'est pas prospecté, mais Omar lui écrit pour la gestion et la souscription. La liste d'exclusion (STOP, effacement) s'applique toujours, quel que soit le type. |
| 166 | Assureurs : services et niveaux | Chaque contact peut avoir un service (Souscription, Gestion, Production, Maritime / transport, Autre) et un niveau (Directeur de département, Senior, Junior). Fiche d'un assureur : un onglet par service, et dans chaque onglet les personnes rangées par niveau ; bouton « ranger » sur chaque personne ; colonnes « Service » et « Niveau » dans le modèle Excel et à l'import | Demande d'Omar. « Autre » couvre les services non listés sans créer de liste libre (qui donnerait « Souscription » et « souscription » en deux onglets). |
| 167 | Logos | Un logo par entreprise (PNG, JPG, WEBP ou SVG, 2 Mo max), rangé dans `data/logos`, ajouté en cliquant sur la vignette de la fiche ; affiché dans la liste et la fiche. Un SVG est servi avec une politique qui interdit tout script | Omar fournira les logos des assureurs. Les logos ne sont pas inclus d'office : l'application n'a pas d'accès Internet et ces logos appartiennent aux compagnies. |
| 168 | Agenda | Page « Agenda » : calendrier du mois, liste du jour, en retard, 2 semaines à venir. Types : Appeler, Envoyer un email, Relancer un devis, Rendez-vous, Renouvellement, Autre (libre) ; raccourcis « demain, 3 jours, 1 semaine, 2 semaines, 1 mois, 3 mois » ; lien facultatif vers un contact ou une entreprise ; bouton « Rappel » sur la fiche contact, la fiche entreprise, la boîte mail et « Envoyés sans réponse ». Les « À rappeler plus tard » posés depuis une réponse y figurent aussi | Demande d'Omar (« rappeler dans X jours, faire X dans Y jours »). Pas de synchronisation avec Outlook/Google : rien ne quitte le PC. |
| 169 | Notifications | Cloche en haut à droite : rappels du jour et en retard, personnes à rappeler, une ligne par personne sans réponse depuis N jours ouvrés (clic → son email dans « Envoyés sans réponse »), réponses à trier, envois bloqués, erreurs de boîte. La pastille compte ce qui n'a pas été vu ; un élément reste dans la liste tant que l'action n'est pas faite | Demande d'Omar. « Vu » ne veut pas dire « fait » : un rappel coché disparaît, un rappel seulement vu reste. |
| 170 | Ordre du menu | Tableau de bord, Boîte mail, Séquences, Campagnes, Agenda, Entreprises, Contacts, Réglages | Demande d'Omar : Entreprises avant Contacts. |
| 171 | Textes personnalisés | Les « blocs de contenu » deviennent « Textes personnalisés » : on choisit une fonction et un secteur, on rédige leurs deux textes, et l'email assemblé s'affiche en direct à côté (contact fictif, texte fonction et texte secteur surlignés) | Omar ne comprenait pas la page : voir le résultat explique le principe mieux qu'un texte. Les codes et le moteur de rendu ne changent pas. |
| 172 | Migration 0007 | Colonnes ajoutées (sequence.category, contact.department, contact.seniority, company.logo, message.attachments) et 3 tables créées (attachment, step_attachment, reminder), sans recréation de table ; testée sur une copie de la base d'Omar | Aucune donnée recopiée ; les séquences existantes deviennent « Prospection ». |

## V2.9 – Envoyer une séquence en quelques clics

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 173 | Sauvegarde V2.8 | Dossier `oddo-sequences-v2.8-sauvegarde` (créé à 11:32 ; base intègre, 100 contacts, au schéma d'avant la V2.8 : elle se met à jour toute seule si on la relance) | Repli si la V2.9 pose problème. |
| 174 | Modifier / Envoyer | Chaque carte de la page Séquences a deux boutons : « Modifier » (l'éditeur) et « Envoyer » | Demande d'Omar. |
| 175 | Envoyer une séquence | Une seule fenêtre, ouverte depuis la page Séquences, la boîte mail (bandeau de l'expéditeur) ou une fiche contact : choisir la séquence (rangée par type), puis les personnes (recherche et cases à cocher) ; « Un groupe entier » ouvre l'assistant de campagne avec la séquence déjà choisie (vérification complète) | Envoyer à quelqu'un sans passer par l'assistant de campagne, tout en gardant l'assistant pour les envois en nombre. |
| 176 | Campagne « à l'unité » | Les personnes ajoutées ainsi entrent dans une campagne « À l'unité – nom de la séquence », créée au premier envoi et déjà lancée ; elle ne se termine jamais d'elle-même. Mêmes contrôles qu'un ajout à une campagne (type, liste d'exclusion, email complet, autre campagne en cours) ; une personne ne reçoit pas deux fois la même séquence | Le moteur, les plafonds, les statistiques, la pause et l'arrêt sur réponse s'appliquent sans rien de nouveau. |
| 177 | Personnaliser d'abord | Pour une seule personne, choix « Personnaliser d'abord » ou « Envoyer tel quel ». Personnaliser montre chaque email déjà écrit pour elle (objet et texte, sans signature ni ligne STOP) ; ce qui est retouché est gardé pour elle seule ; la signature et la ligne STOP (prospection) restent ajoutées ; les relances gardent le fil (« Re: » de l'objet personnalisé) | Demande d'Omar (« d'abord un choix pour personnaliser »). Une personnalisation corrige aussi un texte encore « À RÉDIGER » pour cette personne. |
| 178 | Expéditeur inconnu | Dans la boîte mail, « Envoyer une séquence » sur un expéditeur inconnu crée d'abord sa fiche (nom tiré de l'email, type Prospect par défaut) | Quelques clics depuis un email reçu, comme demandé. |
| 179 | Fonctions et secteurs ajoutés | « Textes personnalisés » : « Ajouter une fonction » et « Ajouter un secteur » ; un nom suffit, le code est créé tout seul (Achats → ACH, Hôtellerie et tourisme → HOT) ; le nouveau choix apparaît aussitôt dans les fiches, l'import et le modèle Excel ; suppression possible seulement pour un ajout qu'aucun contact n'utilise. Les fonctions et secteurs de départ ne se suppriment pas | Demande d'Omar (nouvelles trames). Supprimer un profil utilisé rendrait les emails de ces contacts impossibles à composer. |
| 180 | Migration 0008 | 3 colonnes ajoutées (content_block.label, campaign.direct, enrollment.overrides), sans recréation de table ; testée sur une copie de la base d'Omar | Aucune donnée recopiée. |

## V2.10 – Retouches : assistant de campagne, boîte mail, agenda

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 181 | Sauvegarde V2.9 | Dossier `oddo-sequences-v2.9-sauvegarde` (code + base copiée à chaud avec son journal ; vérifiée : intègre, 100 contacts, schéma V2.9) | Repli si la V2.10 pose problème. |
| 182 | « Nouvelle campagne » | Le bouton du tableau de bord ouvre directement l'assistant | Demande d'Omar : une page de moins. |
| 183 | Assistant : Quoi puis Qui | 1. la séquence (rangée par type), le nom, le démarrage ; 2. les destinataires ; 3. vérifier et lancer. Le type ne se choisit plus dans « Qui » : il vient de la séquence, et une phrase dit qui peut la recevoir | Omar ne comprenait pas « gestion / prospection / souscription » au milieu du ciblage. Choisir l'email d'abord rend évident à qui il s'adresse. |
| 184 | Personnes choisies | « Qui » propose « Un groupe » (filtres, comme avant) ou « Des personnes choisies » (recherche, cases à cocher, tout cocher) ; la campagne garde la liste des personnes (`contact_ids`) et passe par la même vérification complète | Demande d'Omar : envoyer à des contacts précis, au-delà des segments. |
| 185 | Boîte mail plus haute | Phrase d'explication retirée, en-tête et onglets resserrés, zone de lecture plus haute | Demande d'Omar. |
| 186 | Menu | Tableau de bord, Boîte mail, Agenda, Séquences, Campagnes, Entreprises, Contacts, Réglages | Demande d'Omar. |
| 187 | Agenda | « + » à côté de chaque date (au survol sur ordinateur, toujours visible sur téléphone) pour ajouter un rappel ce jour-là ; un rappel coché reste affiché, barré, dans sa journée et dans la liste où on l'a coché | Demande d'Omar : voir ce qui a été fait. |

## V2.11 – Petites améliorations validées par Omar

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 188 | Sauvegarde V2.10 | Dossier `oddo-sequences-v2.10-sauvegarde` (code + base copiée à chaud avec son journal ; vérifiée : intègre, 101 contacts) | Repli si la V2.11 pose problème. |
| 189 | Liens dans les emails | Une adresse web dans un email affiché devient une étiquette courte « nom du site ↗ » (ou « image ») ; l'adresse complète apparaît au survol ; ouverture dans un nouvel onglet | Les reçus et newsletters affichaient des adresses de plusieurs lignes. Montrer le nom du site permet de voir où mène un lien avant de cliquer. |
| 190 | « Mes contacts » | Bouton dans la boîte mail : n'affiche que les emails des personnes présentes dans les contacts ; le choix est mémorisé sur ce PC | Masquer reçus, newsletters et notifications. |
| 191 | Raccourcis clavier | Boîte de réception : ↑/↓ (ou K/J) pour changer d'email, R pour répondre, S pour envoyer une séquence ; inactifs pendant la saisie et quand une fenêtre est ouverte ; rappelés en bas de la liste | Traiter la boîte sans souris. |
| 192 | Carte « Aujourd'hui » | 4e carte des résultats du tableau de bord : rappels du jour et en retard (dont « À rappeler » des réponses), avec les deux premiers titres ; clic → Agenda | Voir d'un coup d'œil ce qu'il y a à faire. |
| 193 | Modifier un rappel | Clic sur le titre d'un rappel (agenda, fiches) : même fenêtre qu'à la création, avec « Enregistrer » et « Supprimer » | Changer une date ou une note sans recréer le rappel. |
| 194 | Dates avant l'envoi | La fenêtre « Envoyer une séquence » affiche la date indicative de chaque email si l'on envoie maintenant (plages, jours ouvrés, jour/heure des étapes) | Savoir quand partiront les relances. Indicatif : le moteur espace les envois (plafonds, pauses) et une réponse arrête la suite. |
| 195 | Sélection multiple | Liste des contacts : cases à cocher (et « tout cocher ») ; barre d'actions « Envoyer une séquence » et « Ajouter un rappel » (un rappel par personne, à son nom) | Agir sur plusieurs personnes à la fois. |
| 196 | Séquence à un service | Fiche entreprise : « Séquence au service … » envoie à toutes les personnes actives de l'onglet affiché (ou de l'entreprise) | Écrire d'un clic à tout le service Souscription d'un assureur. |

## V2.12 – Assureurs de départ, « À répondre », ligne STOP facultative

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 197 | Sauvegarde V2.11 | Dossier `oddo-sequences-v2.11-sauvegarde` (code + base copiée à chaud ; vérifiée : intègre, 101 contacts) | Repli si la V2.12 pose problème. |
| 198 | Assureurs de départ | Les 5 compagnies (Sanlam Allianz, Wafa Assurance, AtlantaSanad, AXA Assurance Maroc, RMA Assurance), leurs logos et leurs 56 interlocuteurs (poste, service, niveau) sont livrés avec l'application (`app/starter/`) et chargés au démarrage, une seule fois par version de la liste. Rien n'est effacé ni remplacé : une fiche existante (même nom ou alias, ex. « Sanlam ») est complétée, un contact existant (même email) garde ses notes et son historique | Demande d'Omar : chaque collègue retrouve tout dès la première ouverture, et sa propre installation est complétée sans doublon. |
| 199 | Lecture du fichier d'Omar | Service : « Souscription » tel quel ; le bloc « Gestion / production » est réparti d'après le poste (« Production … » → Production, le reste → Gestion) ; « Directeur Maritime et transport » → Maritime / transport. Niveau : Junior / Senior / Directeur. Deux adresses corrigées : « ghizlane.makhloufi@axa.ma> » (chevron en trop) et « N.ElMimouni@rmaassurance.co » → « .com » comme les 10 autres adresses RMA | Hypothèses signalées à Omar, à vérifier. |
| 200 | Logos | Convertis en PNG carrés ou bandeaux légers (moins de 70 Ko) ; un logo déjà mis par l'utilisateur n'est jamais remplacé | Affichage net et rapide dans les listes. |
| 201 | « À répondre » | Nouvel onglet de la boîte mail et carte du tableau de bord : les emails reçus (30 derniers jours) auxquels vous n'avez pas répondu depuis N jours ouvrés (même réglage que « sans réponse »). Répondu = un email envoyé après lui, dans le même fil ou à son expéditeur, lu dans le dossier Envoyés (donc aussi les réponses écrites depuis Outlook ou le webmail). Exclus : newsletters et envois automatiques, adresses « noreply / notification… », réponses d'absence. Une ligne par expéditeur | Demande d'Omar : le pendant de « ils ne m'ont pas répondu ». Lecture seule, comme toute la boîte mail. |
| 202 | Ligne STOP facultative | Réglages → Envoi : « Ajouter une ligne de désinscription (STOP) », désactivée par défaut ; quand elle est activée, seulement en prospection. L'en-tête technique List-Unsubscribe (invisible dans le corps du message) reste en prospection | Demande d'Omar. L'en-tête permet à Gmail ou Outlook de proposer « se désabonner » sans ligne visible. Obligations légales au Maroc (loi 09-08, CNDP) pour la prospection B2B : non vérifiées, à confirmer. |

## V2.13 – Ranger « À répondre », fiche contact

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 203 | Sauvegarde V2.12 | Dossier `oddo-sequences-v2.12-sauvegarde` (code + base copiée à chaud ; vérifiée : intègre, 157 contacts dont 56 assureurs) | Repli si la V2.13 pose problème. |
| 204 | « Marquer comme répondu » | Dans « À répondre » : bouton sur l'email ouvert, cases à cocher et « Tout sélectionner » ; l'expéditeur sort de la liste jusqu'à son prochain email ; « Annuler » dans le message de confirmation | Vider la liste des emails auxquels on ne répond pas volontairement. Rien n'est modifié dans la boîte mail elle-même (lecture seule). |
| 205 | Fiche contact | Bouton de fermeture rond et décalé des actions « Modifier » et « … » ; ouverte depuis une entreprise, l'agenda ou la boîte mail, sa fermeture ramène à la page d'origine ; contenu qui ne déborde plus à droite | Demande d'Omar. |

## V2.14 – Fiche contact, filtres, champs à compléter

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 206 | Sauvegarde V2.13 | Dossier `oddo-sequences-v2.13-sauvegarde` | Repli. |
| 207 | Listes d'emails | Les listes de la boîte mail (réception, À répondre, sans réponse, réponses) défilent dans leur cadre | Les derniers emails étaient inaccessibles. |
| 208 | Fiche d'un assureur, client ou partenaire | Sans « Source » ni « Historique » ; à la place, « Derniers emails » : les 15 derniers échangés avec la personne (reçus et envoyés, 3 derniers mois), cliquables vers l'email dans la boîte mail. Les prospects gardent l'historique de campagne | Demande d'Omar. |
| 209 | Filtres des contacts | Statut, Fonction, Secteur, Campagne ; le menu affiche la valeur choisie seule (« Actif ») | Demande d'Omar : moins de filtres, plus lisibles. |
| 210 | Champs à compléter | Un texte entre crochets dans un modèle (« [N° de police] », « [Banque] ») doit être remplacé avant l'envoi : il est signalé dans « Personnaliser d'abord » et l'envoi est refusé tant qu'il en reste | Les demandes de gestion (avenant, délégation…) dépendent de chaque dossier. |
| 211 | Pièces jointes pour une personne | « Joindre un fichier pour cette personne » dans « Personnaliser d'abord », en plus des pièces fixes de la séquence ; 10 Mo au total | Carte grise, déclaration de sinistre… différentes à chaque dossier. |

## V2.15 – Séquences modèles et textes par fonction / secteur, prêts dès le premier lancement

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 212 | Séquences modèles | 11 séquences chargées au démarrage (`app/starter/sequences.json`, version 1) : P1 Prospection entreprise, P2 Suite à un rendez-vous, P3 Avant l'échéance ; G1 Avenant, G2 Délégation bancaire, G3 Déclaration de sinistre, G4 Suivi de sinistre, G5 Attestation, G6 Documents à fournir (client) ; S1 Demande de cotation, S2 Envoi de proposition. Relances dans le même fil, jours ouvrés | Demande d'Omar : l'application est configurée dès son installation, pour lui comme pour ses collègues. Les textes restent modifiables dans la page Séquences. |
| 213 | Textes fonction / secteur | Les 10 textes (FIN, RH, DIR ; IND, SRV, BTP, COM, TRA, AGRO, SANTE) validés par Omar le 04/11/2026 ; un texte n'est rempli que s'il est absent ou encore « À RÉDIGER » | Ne jamais écraser un texte réécrit à la main. |
| 214 | Règles de chargement | Une fois par version (réglage `starter_sequences_version`) ; une séquence n'est ajoutée que si aucune ne porte déjà son nom ; une erreur n'empêche pas l'application de démarrer | Même principe que les assureurs de départ (V2.12). |
| 215 | Séquences de test | « Prospection PME – 3 étapes », « PME » et « Délégation » supprimées (choix d'Omar), avec leurs campagnes si ce sont des brouillons vides ; gardées si une campagne lancée ou une inscription les utilise | Leur historique compterait ; chez Omar, seules 2 campagnes brouillon vides y étaient liées. |
| 216 | Champs à compléter | Gestion et souscription : numéro de police, assuré, banque, dates… entre crochets dans le 1er email, à remplir dans « Personnaliser d'abord » ; les relances n'en contiennent pas | Une relance part sans qu'on la retouche. |
| 217 | Pièce jointe G2 | G2 annonce « la demande de la banque ci-jointe » mais n'a pas de pièce fixe : Omar ajoutera son modèle dans l'éditeur, ou joindra le document de chaque dossier | Modèle pas encore fourni. |

## V2.16 – Guide de démarrage

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 218 | Page Guide | `/v2/guide`, lien « Guide » en bas du menu : « Bien démarrer » (5 étapes), un tour des 7 écrans avec de vraies captures, les bons réflexes, une FAQ | Demande d'Omar : chaque collègue s'approprie l'outil seul. |
| 219 | Captures | Prises sur une base de démonstration : personnes et entreprises de prospection fictives (Atlas Froid Industrie, Ahmed Sqalli…), boîte « Leila Démo » ; seuls apparaissent les assureurs de départ, que chacun a déjà. Images en 256 couleurs (≈ 50 Ko chacune) dans `frontend/public/guide` | Aucun vrai prospect dans un document diffusé. |
| 220 | Bien démarrer | Boîte connectée (lue sans erreur), signature, essai en mode test, prospects, mode réel : cochées d'elles-mêmes quand l'application peut le constater, sinon « C'est fait » (réglage `guide_checked`) ; bandeau sur le tableau de bord tant que ce n'est pas fini | Savoir où l'on en est sans rien deviner. |
| 221 | Essai sur soi-même | Le guide demande de s'ajouter comme contact et de s'envoyer une séquence de gestion, jamais d'essai sur un vrai contact | Passer en mode réel fait partir pour de vrai les relances encore prévues d'un essai. |

## V2.17 – Mises à jour automatiques, boîte relue toutes les 5 minutes

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 222 | Source des mises à jour | Un seul fichier : le kit, sur le Google Drive d'Omar, partagé « Tous les utilisateurs qui ont le lien ». Le même lien sert au premier téléchargement par un collègue et aux mises à jour. Nouvelle version = Drive → Gérer les versions → Importer une nouvelle version (le lien ne change pas) | Plus de clé USB ni de passage sur chaque PC. Le connecteur Drive ne permet pas de remplacer le contenu d'un fichier : c'est Omar qui dépose chaque version. |
| 223 | Vérification | 2 minutes après le démarrage puis toutes les 12 heures, et bouton « Vérifier maintenant » (Réglages → Mise à jour) ; le kit est téléchargé (≈ 1,5 Mo) et sa version lue dans `app/__init__.py` ; notification dans la cloche si elle est plus récente | Simple : pas de second fichier « version » à tenir à jour. |
| 224 | Installation | Un clic (« Installer et redémarrer ») : sauvegarde de la base, écriture des seuls fichiers de l'application (app/, migrations/, fichiers connus à la racine), jamais data/ ni .venv, aucun chemin hors du dossier ; les .bat sont remplacés après l'arrêt ; relance automatique de start.bat (Windows), la page se recharge quand la nouvelle version répond | Les données ne bougent jamais ; un .bat réécrit pendant qu'il tourne casserait la fenêtre. Si la relance échoue, relancer start.bat suffit. |
| 225 | Confiance | Le code installé vient du fichier Drive d'Omar : seul quelqu'un qui peut modifier ce fichier peut publier une version | Pas de signature des kits pour l'instant. |
| 226 | Lecture de la boîte | Toutes les 5 minutes (10 avant) | Demande d'Omar ; une lecture IMAP ne télécharge que les nouveaux messages. |
| 227 | Fiche contact | Ni « Source » ni « Historique », pour tous les contacts, prospects compris ; « Derniers emails » et « Campagnes » restent | Demande d'Omar. |

## V2.18 – Filtres selon le type de contact, lien des mises à jour intégré

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 228 | Filtres des contacts | Ils suivent la carte choisie : Tous (statut, campagne) ; Prospects (statut, fonction, secteur, campagne) ; Assureurs (compagnie, service, niveau, statut) ; Clients et Partenaires (entreprise, statut, campagne). Changer de carte retire les filtres qui n'y ont plus de sens | Demande d'Omar : « Dirigeant » sur les assureurs ne donnait rien. |
| 229 | Lien des mises à jour | Fichier « ODDO-Sequences-kit.zip » créé sur le Drive d'Omar (provisoire, à remplacer par le kit via « Gérer les versions »), lien intégré à l'application ; modifiable dans Réglages → Mise à jour | Un lien fixe, connu avant de construire le kit. |

## V2.19 – Emails reçus : mise en forme, photos et pièces jointes

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 230 | Mise en forme | Un email HTML s'affiche avec sa mise en forme, dans un cadre isolé (aucun script, formulaire ni redirection ; liens ouverts dans un nouvel onglet) ; « Afficher en texte seul » reste possible | Demande d'Omar : l'application doit remplacer Outlook. |
| 231 | Photos dans l'email | Les images intégrées (cid:) s'affichent ; les images venant d'Internet sont masquées jusqu'au clic « Afficher les images » | Comme Outlook : ces images servent souvent à savoir si l'email a été ouvert. |
| 232 | Pièces jointes | Cliquables : images, PDF et texte s'ouvrent dans un nouvel onglet ; les autres (Word, Excel…) se téléchargent et s'ouvrent avec le logiciel du PC ; aperçu des photos jointes ; jamais de HTML ni de SVG affiché tel quel (type forcé, nosniff, CSP « sandbox ») | Ouvrir une pièce jointe ne doit jamais pouvoir exécuter de code dans l'application. |
| 233 | Données | Rien n'est écrit sur le disque : l'email ouvert reste 2 minutes en mémoire (8 au plus) pour ses images et pièces jointes | Même règle que la V2.4 (les emails contiennent des données de clients). |

## V2.20 – Transférer, Archiver, fiabilité

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 234 | Transférer | Bouton « Transférer » (touche F) : objet « TR: … », en-tête du message d'origine, texte d'origine, pièces jointes ET photos du corps reprises en pièces jointes (10 Mo au total ; au-delà, signalé) | Demande d'Omar : comme dans Outlook. Le transfert part en texte (la mise en forme d'origine n'est pas reprise). |
| 235 | Archiver | Bouton « Archiver » (touche E) : l'email est DÉPLACÉ (jamais supprimé) dans le dossier d'archives du serveur (marqué \Archive, sinon « Archive(s) », sinon « INBOX.Archive » créé) ; « Annuler » le remet ; l'email suivant s'ouvre. Seule écriture de la boîte faite par l'application. UID MOVE, ou copie + suppression ciblée (UID EXPUNGE) ; refusé si le serveur ne permet ni l'un ni l'autre | Demande d'Omar. Visible aussi dans Outlook et le webmail. La boîte est relue juste avant, pour qu'une réponse de campagne archivée tout de suite arrête quand même les relances. |
| 236 | Sauvegardes | Les 10 dernières + une par jour sur 30 jours ; « quotidienne » vérifiée toutes les heures ; copie facultative dans un second dossier (Google Drive pour ordinateur, OneDrive…) ; écran Réglages → Sauvegardes | Constaté chez Omar : une journée de redémarrages avait effacé les jours précédents (14 dernières seulement), et la sauvegarde de 23:00 n'était jamais faite PC éteint. |
| 237 | Copie dans « Envoyés » | Si elle échoue (coupure), l'email est gardé dans data/envoyes_a_copier et recopié après la prochaine lecture réussie de la boîte (7 jours au plus) | Constaté au test de panne : un email parti n'apparaissait pas dans « Envoyés » d'Outlook. |
| 238 | Message « serveur introuvable » | « vérifiez la connexion internet » d'abord | Les 3 cas chez Omar étaient des coupures passagères, pas une faute de frappe. |
| 239 | Essai d'endurance | `tests/test_v220_soak.py` : 40 contacts × 3 étapes sur 6 semaines simulées, 15 % d'envois en échec, PC éteint 2 jours, 6 réponses : aucun doublon, rien après une réponse, séquences complètes, plafonds et heures respectés | Vérifier les promesses avant le déploiement au cabinet. |

## V2.21 – Avant le lancement interne

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 240 | Réponses rangées ailleurs | La synchronisation lit aussi les dossiers Archive et Corbeille (repérés par leur marque \Archive / \Trash, sinon par leur nom) ; un dossier illisible ne bloque jamais la lecture ; doublons évités par Message-ID | Une réponse archivée ou supprimée sur le téléphone avant que le PC soit allumé doit quand même arrêter les relances. |
| 241 | Modèles dans « Nouveau message » | Bouton « Modèles » : le 1er email d'une séquence, écrit pour le destinataire s'il est dans les contacts (sinon « Madame, Monsieur »), avec ses pièces jointes ; l'objet d'une réponse ou d'un transfert est gardé | Demande d'Omar. |
| 242 | Sans objet / [champs] | Envoi permis sans objet, après confirmation (comme Gmail) ; idem s'il reste des [champs] entre crochets | Demande d'Omar ; prévenir sans bloquer pour un email écrit à la main. |
| 243 | Ajouter une personne | Depuis la fiche d'une entreprise, on y revient après « Enregistrer » ou « Annuler » | Demande d'Omar. |
| 244 | Ancienne interface | Lien retiré du menu (la page /classique reste accessible par son adresse, en secours) | Demande d'Omar. |

## V2.22 – Finitions

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 245 | Bien démarrer | Une étape atteinte une fois reste cochée (`guide_done`) ; « mode réel » compte aussi si un email est déjà parti en réel ; la barre disparaît pour de bon une fois les 5 faites | Demande d'Omar : repasser en mode test faisait réapparaître la barre. |
| 246 | Échelle de l'interface | Titres de page 24 → 20 px, grands chiffres un cran plus petits, marges des cartes 20 → 16 px, espaces un peu resserrés | Demande d'Omar : « un brin plus sleek », sans changer la structure. |

## V2.23 – Guide en sous-pages, un envoi par dossier

| # | Sujet | Décision | Pourquoi |
|---|---|---|---|
| 247 | Guide | Accueil (Bien démarrer, « Par où commencer ? », cas d'usage, rubriques) + une page par rubrique + une page par cas d'usage, avec recherche ; captures sur des données fictives, zones numérotées. Un seul cas complet (« Demander un avenant ») pour valider le style avant les 8 autres | Demande d'Omar : faciliter l'adoption par les collègues. |
| 248 | Un envoi par dossier | Les séquences de gestion et de souscription envoyées « à l'unité » peuvent partir plusieurs fois à la même personne (un G1 par avenant), sans question « déjà en cours ailleurs ». La prospection et les envois à un groupe restent « une fois par personne » | Avant : un gestionnaire ne pouvait recevoir G1 qu'une seule fois dans toute la vie de l'appli. Découvert en écrivant le cas d'usage. |
| 249 | Contrainte en base | Migration 0009 : la table des inscriptions est recréée sans la contrainte (campagne, contact), comptes vérifiés avant/après ; s'arrête sans rien toucher si les clés étrangères sont actives. Testée sur une copie de la base d'Omar et sur une base de démonstration remplie | SQLite ne sait pas retirer une contrainte autrement. |
| 250 | « A répondu » | Ne s'applique qu'aux prospects. Un assureur, client ou partenaire qui répond reste joignable ; une personne « A répondu » peut recevoir des séquences de gestion/souscription, pas de prospection | Avant : toute réponse bloquait la personne pour toujours, y compris pour les dossiers de gestion. |
| 251 | Réponse et dossiers | Une réponse qui cite à coup sûr l'email d'un dossier de gestion/souscription (Message-ID) n'arrête que ce dossier ; un email écrit à part arrête, par prudence, tous les dossiers en cours de la personne | Avec plusieurs dossiers chez le même gestionnaire, une réponse sur l'un ne doit pas couper les relances des autres. |
| 252 | Pièce jointe « Personnaliser » | Corrigé : le fichier choisi était perdu (liste vidée avant lecture) ; il s'ajoute bien maintenant | Bug présent depuis la V2.14, trouvé en préparant les captures. |
| 253 | Fausses alertes sur les relances | Les onglets de relance ne signalent plus « à compléter » à cause de l'objet (les relances reprennent l'objet du 1er email) | Point orange trompeur vu en préparant les captures. |
| 254 | Bien démarrer | Devient un onglet du guide (« Bien démarrer 4/5 » en tête du menu) et quitte le menu quand les 5 étapes sont faites ; retiré de l'accueil et de Prise en main. Le bandeau du tableau de bord mène à cet onglet | Demande d'Omar (V2.23.1). |
| 255 | Avenant : deux façons | Le cas « Demander un avenant » présente aussi l'option rapide : Nouveau message → Modèles → G1, sans relances | Demande d'Omar : plus rapide pour une demande simple. |
| 256 | Guide complet | 9 cas d'usage et 9 rubriques rédigés, 40 captures annotées sur une base fictive (assureurs « Démo », jamais les vrais assureurs ni leurs employés) | Adoption par les collègues. |
| 257 | Réponse et dossiers (suite) | Au moment d'envoyer une relance de gestion/souscription, une réponse liée à un AUTRE dossier de la personne ne l'arrête plus (avant : le 2e dossier s'arrêtait quand même à l'envoi) | Bug trouvé en écrivant les tests de la V2.23. |
| 258 | « A répondu » et P2 | « A répondu » n'empêche que les campagnes de prospection de groupe. Envoyée à l'unité, une séquence reste possible (P2 après le rendez-vous obtenu grâce à P1) ; le bouton « Envoyer une séquence » reste sur la fiche | Avant : impossible d'envoyer P2 à un prospect qui avait répondu à P1, le cas le plus courant. |
| 259 | Plusieurs personnes, [champs] une fois | Une séquence avec des [champs] envoyée à plusieurs personnes (S1 à 3 compagnies, « Séquence au service Souscription ») : un formulaire demande chaque champ une fois, plus une pièce jointe commune ; chacun reçoit son email à son nom | Avant : tous les envois étaient refusés (email incomplet). |
| 260 | Sauvegarde | La sauvegarde qu'on vient de créer n'est jamais supprimée par le tri, même si l'horloge du PC a reculé | Trouvé par un test lancé après minuit. |
| 261 | Mes propres modèles | « Nouvelle séquence » propose « Un seul email » : un modèle à réutiliser depuis Nouveau message → Modèles (relances ajoutables plus tard). Cas d'usage « Créer mon propre modèle d'email » (exemple : Cotation AT) | Demande d'Omar. |
| 262 | Balises et relecture | Nouvelle rubrique : {{ variables }} remplies par l'appli (avec valeur de repli), [champs] remplis à la main, ce qui bloque un envoi, et la règle « Personnaliser d'abord tant qu'on débute ». Les recettes ne conseillent plus « Envoyer tel quel » | Demande d'Omar : relire avant d'envoyer le temps de maîtriser les balises. |
| 263 | « À répondre » expliqué juste | Le guide dit maintenant ce que fait la liste : emails reçus de n'importe qui (contacts ou pas, envois automatiques exclus), sans réponse depuis 3 jours ouvrés (réglable) | Question d'Omar ; l'ancien texte disait « vos contacts ». |
| 264 | Envoyer une partie de la séquence | À l'envoi à l'unité (boîte mail, fiche, page Séquences), « Que faut-il envoyer ? » : toute la séquence, 1er email + N relances, ou 1er email seulement. Seuls les N premiers emails partent (migration 0010 : `enrollment.max_steps`) ; les [champs] et problèmes des emails retirés ne bloquent pas ; « Email n°1 sur 1 » dans le suivi. Pas de retrait d'une relance au milieu : les relances s'enchaînent (« je reviens vers vous une dernière fois ») | Demande d'Omar : envoyer G1 sans relances depuis la boîte mail, ou un seul email d'une séquence à un prospect. |
| 265 | Vidéo de présentation | « Le tour de l'appli » (4 min, voix ElevenLabs, sous-titrée) servie par l'appli (12 Mo, guide/videos) : en tête de l'accueil du guide et de la rubrique « Le tour de l'appli » | Demande d'Omar. Locale : marche hors connexion, rien à partager sur Drive. |
| 266 | Vérifier avant d'envoyer | Tout envoi de séquence (une ou plusieurs personnes, tel quel ou personnalisé) passe par un dernier écran : pour chaque personne, chaque email exact qui partira (objet, texte rempli, signature, pièces jointes, date prévue), calculé par le serveur comme à l'envoi (inscription jouée « à blanc », rien n'est enregistré). Personnes refusées signalées avec la raison. « Confirmer l'envoi » / « Envoyer à N personnes » | Demande d'Omar : voir précisément ce qui part avant que ça parte. |
| 267 | « ci-joint » sans fichier | L'écran de vérification avertit quand le texte annonce une pièce jointe (« ci-joint », « en pièce jointe », « en annexe ») et qu'aucun fichier n'est joint | Le modèle S1 dit « ci-joint » : oubli fréquent. |
| 268 | Envoyés sans réponse | Une personne n'y apparaît qu'après la DERNIÈRE relance automatique restée sans réponse (N jours ouvrés, réglable) ; tant qu'une séquence doit encore la relancer, elle n'est pas listée. Une réponse à un échange plus ancien ne la masque plus | Question d'Omar. Avant : liste polluée pendant les séquences, et un assureur ayant répondu une fois n'y apparaissait plus jamais. |
| 269 | Date du 1er email | Le suivi affiche la vraie date du 1er email (prochaine ouverture des plages d'envoi) au lieu de l'heure du clic | « vendredi 15:51 » affiché pour un email parti lundi 09:00. |
| 270 | Captures du guide | Avenant et cotation : nouvelle étape « Vérifiez les emails exacts » ; captures refaites (avenant, rendez-vous, délégation, sinistre, cotation) | Suit 264 et 266. |
| 271 | Envoyés sans réponse (retour) | Retour au comportement d'avant pour les séquences : une personne apparaît N jours ouvrés après chaque email resté sans réponse, même si une relance automatique est encore prévue. On garde seulement la correction « une réponse à un échange plus ancien ne la masque plus » | Choix d'Omar (V2.25.1) : « c'était mieux avant ». Remplace la 1re partie de 268. |
| 272 | Relance prévue, visible | Dans « Envoyés sans réponse » : une pastille « Relance 1 prévue jeudi 12/11 09:00 » sur la ligne, et dans le lecteur un encadré (quelle relance, quand, quelle séquence, « Voir le suivi »). La cloche ajoute « relance auto prévue … » | Demande d'Omar (V2.25.1) : garder la personne dans la liste, mais voir qu'un email automatique arrive. |
