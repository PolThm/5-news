# Intent produit — 5 News

_Source : session de brainstorming du 2026-08-10. Décisions arrêtées, prêtes pour un product brief._

## Problème

Surcharge informationnelle et anxiété liée à l'actualité. Les flux existants sont infinis, mêlent l'important au fait divers, et l'utilisateur en sort ni informé ni apaisé. Certains ont désinstallé les réseaux d'info et culpabilisent de ne plus rien suivre. Le besoin n'est pas « plus de news » mais **la tranquillité d'être à jour** — de la clarté, pas de l'information.

## Insight central (non négociable)

**Le produit est le FILTRE, pas le résumé.**
Test décisif de la session : la curation seule a de la valeur (5 titres bruts + liens sont déjà utiles) ; le résumé seul n'en a pas. Conséquence directe : le cœur technique est le **clustering d'événements + le classement des clusters**, pas le prompt de résumé. L'IA n'intervient qu'à la fin, sur 5 clusters déjà sélectionnés.

Corollaire de mesure d'importance : l'importance se mesure par **consensus de couverture** (volume et diversité géographique des sources couvrant l'événement), pas par jugement éditorial de l'IA — moins attaquable, plus défendable.

## Forme du MVP retenue — « Mad-libs + valeur immédiate »

À l'arrivée, le **top 5 monde / jour s'affiche immédiatement**. Aucun travail demandé avant de montrer la valeur.

Le titre de la page est une phrase à trous dont les mots sont les sélecteurs eux-mêmes (mad-libs) :
> « Les 5 actualités les plus importantes **[du jour]** **[dans le monde]** »

Cliquer sur un mot le change (période : jour / semaine / mois ; zone : pays / continent / monde) et rafraîchit le résultat. La phrase remplace titre, labels et bouton d'action.

Corrige explicitement l'anti-pattern identifié en session : ne jamais faire travailler l'utilisateur avant de lui montrer la valeur.

## Les trois différenciateurs (tous portés par le MVP)

1. **La rareté assumée** — l'avantage que les géants ne copieront pas : ils peuvent copier un résumé, pas se permettre d'en montrer moins.
   - Écran de fin explicite : « C'est tout. Revenez demain. » Pas de flux infini.
   - Nombre **variable de 2 à 5**, pas 5 forcés : « aujourd'hui, seulement 3 choses comptent » est un signal d'honnêteté.
   - Manifeste public « ce que nous ne ferons jamais » (pas de flux infini, pas de notifications multiples, pas de faits divers).

2. **Briser la bulle linguistique** — lire la presse étrangère dans sa propre langue. Un francophone ne lit jamais la presse japonaise ; ici c'est un clic et c'est en français. Multiplicateur d'audience quasi gratuit et différenciateur qu'aucun acteur ne couvre.

3. **Transparence du critère** — répond frontalement à « qui décide de ce qui est important ? ».
   - Montrer POURQUOI chaque news est dans le top : « couverte par 34 sources dans 12 pays ».
   - Montrer le volume écarté : « 1 247 articles lus, 5 gardés ». Le ratio EST le produit ; le travail invisible rendu visible crée la valeur perçue.

## Contrainte d'architecture découverte

**Génération par batch pré-calculée via cron, jamais d'IA à la demande.**
Un appel IA au clic coûte ~8 secondes d'attente qui tuent le rituel. Le top N est généré en amont pour chaque combinaison zone × période et servi depuis le cache. Cette seule décision résout trois tensions simultanément : **latence nulle, coût prévisible, scalabilité** (l'IA tourne quelques dizaines de fois par jour, pas une fois par utilisateur).

Pipeline en 3 étapes : (1) collecter les titres sur la fenêtre, (2) clusteriser les articles traitant du même événement, (3) classer les clusters par taille et diversité de sources, garder le top.

Sources envisagées : flux RSS des grands titres + API d'agrégation type NewsAPI / GDELT (GDELT mesurant déjà le volume de couverture mondiale, le signal de consensus est disponible sans le construire). Pas de scraping.

## Personas ayant structuré les décisions

- **Le Sceptique politique** — « qui décide de ce qui est important ? ». A produit le différenciateur transparence du critère et le choix du consensus de couverture comme mesure.
- **L'Anxieux** (a désinstallé les réseaux, culpabilise) — a produit l'écran de fin, l'anti-engagement assumé, le refus du flux infini.
- **Le Cadre pressé** (7 min de métro) — les 5 news tiennent dans un écran sans défilement ; lisible en une respiration.
- **L'Expatrié** (français à Singapour) — justifie le sélecteur de zone et révèle que le sélecteur mensuel sert à rattraper une absence, pas à suivre le quotidien.
- **L'Investisseur** — « pourquoi pas juste un prompt ChatGPT ? ». A forcé la réponse à la commoditisation : la valeur est la curation répétable et la confiance dans le critère.

## Hors périmètre (explicite)

Web uniquement pour le MVP. Écartés pour l'instant : **newsletter, notification push, briefing audio**. Également hors MVP : carte du monde cliquable, mode « depuis votre dernière visite » (fenêtre temporelle personnelle), badges de tonalité, mode « explique simplement », choix par l'utilisateur de sa définition d'« important », partage sous forme de carte image.

## Questions ouvertes pour le product brief

- **Périmètre géographique de lancement** : combien de pays au départ ? Le constat de session est qu'il vaut mieux 5-10 pays bien couverts que le monde entier mal couvert. Fallback gracieux vers le continent quand un pays manque de sources.
- **Règle anti-concentration** : plafonner à 2 news du même pays dans un top continental pour forcer la diversité — à confirmer comme règle produit.
- **Politique anti-hallucination** : appliquer la règle « le résumé ne dit rien qui ne soit dans au moins 2 sources concordantes » ? Et ancrer chaque affirmation à sa source.
- **Attribution et lien sortant** : le résumé doit donner envie de lire l'original, pas le remplacer (bande-annonce, pas substitut). Quelle forme d'attribution visible ?
- **Défaut de période** : jour ou semaine ? L'usage rituel du dimanche soir suggère que « semaine » pourrait être le défaut ; le MVP part sur « jour ».
- **Mémorisation du dernier choix** zone/période entre visites.
- **Archives et SEO** : chaque briefing quotidien archivé devient une page indexable, actif d'acquisition organique composée. Dans le MVP ou après ?
- **Modèle économique** : gratuit + sponsor unique quotidien / freemium (monde-jour gratuit, zones + archives payants) / B2B briefing zone pour entreprises internationales. Anti-modèle explicitement exclu : publicité programmatique et optimisation de l'engagement.
- **Nom et domaine** : Five / FIVE.news / Cinq / The Brief / Signal — vérifier la disponibilité tôt.
- **Métrique de succès contre-intuitive** à valider : temps passé **décroissant** par visite + retour quotidien.
- **Validation préalable au code** : publier 2 semaines de briefings manuels et mesurer les réouvertures.
