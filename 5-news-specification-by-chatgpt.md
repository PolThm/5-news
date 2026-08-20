# 5 News — Spécification MVP v2

**Destinataire :** Claude Code / équipe d’implémentation  
**Statut :** spécification de produit et d’architecture MVP  
**Principe directeur :** 5 News est un moteur de veille, de hiérarchisation et de synthèse d’actualité ; ce n’est pas un scraper de journaux.

## 1. Objectif

Créer une application web et mobile qui produit, pour une zone éditoriale et une langue données, une sélection Daily ou Weekly des actualités les plus importantes. Les zones initiales sont **Monde**, **Europe**, **France** et **Espagne** ; les langues sont **FR**, **EN** et **ES**.

La valeur du produit est de transformer de nombreux signaux éditoriaux et sources primaires en une liste courte d’**événements** distincts, corroborés, diversifiés et expliqués. Le résultat doit ressembler à une revue humaine fiable : pas à une succession de liens, ni à un simple résumé d’une seule page.

## 2. La méthode centrale : comment obtenir une bonne revue

La revue initiale appréciée par l’utilisateur provient conceptuellement de ce pipeline :

```text
Découverte multi-sources
        ↓
Collecte de métadonnées et de sources publiques
        ↓
Normalisation + déduplication d’articles
        ↓
Clustering : plusieurs articles → un événement
        ↓
Évaluation : importance, corroboration, fraîcheur, fiabilité, diversité
        ↓
Sélection Top 5 / Top 10
        ↓
Génération LLM structurée, ancrée dans les faits disponibles
        ↓
Revue éditoriale Daily ou Weekly avec sources
```

Il ne faut pas partir d’une seule page de journal puis la résumer. Il faut découvrir des signaux indépendants, recouper l’information et ne donner au modèle de langage que le dossier factuel de chaque événement.

### 2.1 Séparer découverte, lecture et rédaction

| Étape | But | Entrées MVP recommandées | Ne pas faire |
|---|---|---|---|
| Découverte | trouver les signaux | APIs, RSS, feeds éditeurs, sitemaps, communiqués, données publiques | faire reposer le MVP sur un crawler fragile face aux anti-bots et paywalls |
| Enrichissement | consolider les faits | métadonnées, extrait court, pages/API publiques, documents institutionnels | aspirer inutilement des pages entières |
| Événement | relier les articles sur le même fait | titres, descriptions, entités, date/lieu, embeddings, règles | assimiler des sujets voisins sans preuve |
| Rédaction | produire une revue utile | fiches d’événements validées | demander au LLM d’« inventer le contexte manquant » |

### 2.2 Simplicité pratique pour un projet personnel

- Un RSS est avant tout une excellente source de découverte. Stocker le minimum utile : URL, titre, date, média, catégorie, entités et empreinte ; renvoyer vers la page originale.
- Éviter de faire du texte intégral et des images le cœur de la base : ce n’est pas nécessaire pour produire une très bonne revue et cela alourdit fortement le MVP.
- Les faits sensibles ou chiffrés gagnent à être reliés à une source primaire : administrations, instituts statistiques, banque centrale, météo officielle, services d’urgence, textes législatifs, justice ou organismes internationaux.
- Conserver la provenance de chaque affirmation. C’est surtout un outil de qualité, de débogage et de correction rapide.

## 3. Ce que 5 News ne doit PAS faire

- Ne pas dépendre du scraping HTML de médias protégés par Cloudflare, anti-bot, authentification ou paywall : ce serait trop fragile pour le MVP.
- Ne pas perdre du temps à contourner CAPTCHA, protections d’accès ou abonnements ; privilégier les sources qui alimentent naturellement le pipeline.
- Ne pas faire du stockage de texte intégral, photos ou graphiques une dépendance du produit ; des métadonnées, courts extraits et liens suffisent au départ.
- Ne pas présenter une information non corroborée comme un fait établi.
- Ne pas confondre couverture médiatique abondante et importance réelle.
- Ne pas sélectionner cinq variantes du même sujet parce qu’il génère beaucoup de liens.
- Ne pas laisser le LLM compléter des chiffres, dates, causalités, citations ou consensus absents du dossier source.
- Ne pas réutiliser un exemple historique de revue comme une actualité du jour.

## 4. Sources et contrats d’ingestion

L’implémentation doit utiliser des adaptateurs indépendants du fournisseur. Chaque source déclare son type, sa fréquence, sa qualité estimée et les champs qu’elle fournit, afin que le pipeline reste simple à faire évoluer.

```json
{
  "id": "publisher-rss-example",
  "name": "Éditeur exemple",
  "type": "rss",
  "regions": ["ES"],
  "languages": ["es"],
  "access_mode": "feed_or_api",
  "fields_available": ["title", "url", "published_at", "snippet", "category"],
  "refresh_minutes": 30,
  "trust_tier": 3,
  "adapter": "rss"
}
```

Ordre de préférence pour le MVP :

1. APIs officielles et sources de données institutionnelles publiques.
2. API de fournisseur de news ou agrégateur.
3. Flux RSS et feeds éditeurs, employés au minimum pour la découverte et le lien sortant.
4. Communiqués, bulletins et pages publiques d’organismes reconnus.

Une liste de sources est configurable par région, langue, catégorie et niveau de confiance. Ne jamais figer de clé API dans le code : employer les secrets du déploiement et documenter seulement les variables attendues. Pour un projet personnel, commencer avec quelques sources robustes vaut mieux qu’une longue liste instable.

## 5. Modèle de données minimal

### 5.1 Article / signal

```json
{
  "id": "art_01J...",
  "source_id": "public-agency-es",
  "source_url": "https://example.org/bulletin/123",
  "canonical_url": "https://example.org/bulletin/123",
  "title": "Titre fourni par la source",
  "snippet": "Extrait court fourni par le feed ou l’API.",
  "published_at": "2026-08-19T08:30:00Z",
  "ingested_at": "2026-08-19T08:35:00Z",
  "language": "es",
  "regions": ["ES", "CE"],
  "categories": ["politics", "migration"],
  "entities": [{"type": "place", "value": "Ceuta"}],
  "content_hash": "sha256:...",
  "access_profile": "feed_or_api",
  "source_trust_tier": 4,
  "raw_payload_ref": "object://restricted/..."
}
```

### 5.2 Événement

```json
{
  "id": "evt_01J...",
  "headline_seed": "Débat sur la gestion migratoire à Ceuta",
  "region": "ES",
  "topic": "migration",
  "entities": ["Ceuta", "gouvernement espagnol"],
  "time_window": {"start": "2026-08-13", "end": "2026-08-19"},
  "article_ids": ["art_a", "art_b", "art_c"],
  "primary_source_ids": ["agency_a"],
  "facts": [
    {"claim": "Une mesure a été annoncée", "supporting_article_ids": ["art_a", "art_b"], "status": "corroborated"}
  ],
  "divergences": [
    {"question": "Calendrier d’application", "positions": [{"label": "annoncé", "article_ids": ["art_a"]}, {"label": "à confirmer", "article_ids": ["art_c"]}]}
  ],
  "status": "candidate"
}
```

### 5.3 Score explicable

```json
{
  "event_id": "evt_01J...",
  "window": "weekly",
  "score_total": 78.4,
  "components": {
    "impact": 24.0,
    "prominence": 15.0,
    "corroboration": 13.4,
    "freshness": 8.0,
    "geographic_relevance": 8.0,
    "source_reliability": 7.0,
    "novelty": 3.0,
    "duplication_penalty": 0.0,
    "diversity_adjustment": 0.0
  },
  "explanation": ["impact national", "4 sources indépendantes", "source primaire disponible"]
}
```

## 6. Pipeline détaillé

### 6.1 Ingestion et normalisation

À chaque exécution, l’adaptateur récupère les champs disponibles dans le feed ou l’API. Il normalise dates en UTC, langue, URL canonique, noms de sources, régions, catégories et entités. Les articles sans URL ou date raisonnable sont mis en quarantaine.

Déduplication en deux niveaux :

- **Exacte :** même URL canonique, GUID RSS ou empreinte normalisée du titre + média + temps.
- **Quasi-duplicate :** forte similarité de titre/description, mêmes entités et fenêtre temporelle courte ; conserver un article représentatif mais compter les sources indépendantes.

Les reprises d’agence publiées par dix titres ne constituent pas dix confirmations. Utiliser une `origin_id` lorsque le fournisseur le fournit, ou un regroupement probable de wire copy.

### 6.2 Clustering en événements

Un cluster est une hypothèse d’événement, formée à partir de similarité sémantique et de contraintes explicites : entités communes, lieu, période, catégorie et relation d’action. Un seuil unique d’embeddings est insuffisant.

Pseudo-code :

```text
for article in new_articles:
  candidates = search_recent_events(region=article.region, last_days=14)
  match = best_candidate(article, candidates,
    semantic_similarity,
    entity_overlap,
    time_proximity,
    place_compatibility,
    topic_compatibility)
  if match.score >= CLUSTER_THRESHOLD and no_hard_conflict(article, match):
      attach(article, match)
  else:
      create_event(article)

for event in changed_events:
  extract_atomic_claims(event.allowed_material)
  mark_claims_as(corroborated | single_source | disputed | unsupported)
  recompute_event_score(event)
```

`no_hard_conflict` doit empêcher de fusionner deux incendies, deux votes, ou deux décisions judiciaires distinctes ayant le même thème. Prévoir une revue humaine/admin pour scinder ou fusionner les clusters à enjeu élevé.

### 6.3 Corroboration et divergences

Pour chaque affirmation importante :

- Distinguer source primaire, reportage original, reprise d’agence et commentaire/opinion.
- Compter des origines indépendantes, pas seulement des URLs.
- Une affirmation unique reste libellée « selon X » ou est exclue du résumé factuel si elle est centrale.
- En cas de divergence, conserver le désaccord : « les sources divergent sur… », puis n’énoncer que le noyau commun confirmé.
- Les chiffres sont publiés avec unité, date de référence et provenance. Si deux chiffres incompatibles existent, ne pas les moyenner.

## 7. Ranking et diversité éditoriale

### 7.1 Facteurs de score

Chaque facteur est normalisé entre 0 et 1, puis pondéré par format et région.

```text
score brut =
  0.28 × impact
  + 0.16 × prominence_multi_source
  + 0.16 × corroboration_independence
  + 0.12 × freshness
  + 0.10 × geographic_relevance
  + 0.10 × source_reliability
  + 0.08 × novelty
  - penalties
```

- **Impact :** personnes/territoires affectés, gravité, effet économique, politique, juridique ou de sécurité ; idéalement données structurées et non nombre de clics.
- **Prominence multi-source :** couverture par des sources distinctes et pertinentes.
- **Corroboration :** confirmations réellement indépendantes et/ou source primaire.
- **Fraîcheur :** force de la mise à jour dans la fenêtre sélectionnée.
- **Pertinence géographique :** lien direct avec Monde/Europe/France/Espagne.
- **Fiabilité :** tier de source, traçabilité, correction connue, caractère primaire.
- **Nouveauté :** développement significatif, plutôt que répétition d’un sujet ancien.
- **Pénalités :** doute non résolu, réédition d’agence, faible traçabilité, événement déjà sélectionné très proche.

Les poids doivent être configurables et versionnés. L’interface interne affiche les composantes : une équipe doit pouvoir expliquer pourquoi un sujet est n°2.

### 7.2 Daily vs Weekly

| Dimension | Daily | Weekly |
|---|---|---|
| Fenêtre principale | dernières 24–36 h | 7 jours, avec contexte antérieur si nécessaire |
| Fraîcheur | très forte | modérée |
| Impact durable | important | très important |
| Évolution d’un sujet | nouvelle information substantielle requise | privilégier le bilan et le tournant de la semaine |
| Sélection | 5 événements | Top 5 affiché + Top 10 disponible / documenté |

Pour le Weekly, regrouper les mises à jour d’un même récit en une seule entrée, expliquer ce qui a changé pendant la semaine et éviter de remonter une vieille information sans nouveau développement.

### 7.3 Sélection Top 5 / Top 10

Trier d’abord par score brut puis appliquer un reranking de diversité (type MMR) :

```text
selected = []
while len(selected) < target:
  choose candidate maximizing(
    score_normalized(candidate)
    - λ × max_topic_similarity(candidate, selected)
    - same_topic_quota_penalty(candidate, selected)
    - same_source_dominance_penalty(candidate, selected)
  )
  selected.append(candidate)
```

Règles MVP : pas plus de deux sujets d’un même sous-thème dans le Top 5 sauf événement exceptionnel ; pas de dépendance à une seule source ; inclure au moins deux familles éditoriales parmi politique/société/économie/climat-science/international selon la disponibilité réelle. La diversité est un correctif, jamais un prétexte pour cacher un événement majeur.

## 8. Exemple représentatif : revue Espagne historique de démonstration

> **Avertissement impératif :** l’exemple ci-dessous est une reconstitution de style et d’architecture inspirée d’une revue couvrant le **13 → 19 août 2026**. Il ne constitue pas un état actuel des faits, n’est pas une base de publication et ne doit jamais être réutilisé sans une collecte fraîche, datée, licenciée et corroborée.

### Sortie Top 10 illustrée

**🇪🇸 La semaine en Espagne — 13 → 19 août 2026 (exemple)**

1. **🚨 Ceuta et la migration : un enjeu local devenu conflit national et européen**  
   Des articles et sources publiques hypothétiques décrivent une crise de gestion migratoire, avec débats sur les transferts, la protection des mineurs et les compétences respectives.  
   **Pourquoi c’est important :** conséquences humanitaires, juridiques et politiques à l’échelle espagnole et européenne.  
   **À retenir :** un événement local peut devenir un test national de politique migratoire.  
   **Sources :** liens vers les sources effectivement collectées.

2. **🔥 Incendies : l’été place la prévention et les moyens de secours au premier plan**  
   Plusieurs signaux hypothétiques font état d’incendies, d’évacuations et d’un débat sur les ressources de lutte et la prévention.  
   **Pourquoi c’est important :** sécurité des personnes, territoires affectés, climat et politiques publiques.  
   **À retenir :** ne retenir que les bilans et localisations corroborés à la date de publication.  
   **Sources :** services d’urgence, météo/autorités et médias recoupés.

3. **🌡️ Météo : chaleur, risques et effets sur les activités quotidiennes**  
   Une séquence météorologique notable est contextualisée depuis les bulletins officiels et des sources locales.  
   **Pourquoi c’est important :** santé, incendies, transports et agriculture.  
   **À retenir :** distinguer une alerte officielle d’un commentaire sur la météo.  
   **Sources :** agence météorologique, protection civile, articles liés.

4. **⛽ Carburant : pression sur le budget des ménages et entreprises**  
   Le classement peut couvrir l’évolution des prix et ses causes documentées.  
   **Pourquoi c’est important :** effet direct sur transport, inflation et pouvoir d’achat.  
   **À retenir :** dater les relevés et citer leur méthode.  
   **Sources :** observatoires de prix, données publiques, presse économique licenciée.

5. **📈 Inflation européenne : les décisions et données européennes se répercutent en Espagne**  
   Une publication statistique ou une décision européenne est reliée aux indicateurs espagnols, sans surinterpréter la causalité.  
   **Pourquoi c’est important :** salaires réels, coût de la vie et politique monétaire.  
   **À retenir :** séparer le chiffre observé de son explication économique.  
   **Sources :** Eurostat, banque centrale, institut statistique, analyses recoupées.

6. **🏠 Logement : disponibilité, loyers et réponses publiques**  
   Les signaux concernent tensions de marché, règles ou annonces locales/nationales.  
   **Pourquoi c’est important :** logement et accès des ménages sont structurels.  
   **À retenir :** rendre le périmètre géographique explicite.  
   **Sources :** administrations, données de marché licenciées, médias.

7. **💶 Dette publique : trajectoire budgétaire et crédibilité financière**  
   Le sujet s’appuie sur des données publiées et distingue stock, déficit et prévisions.  
   **Pourquoi c’est important :** marges de manœuvre de l’État et lien avec l’Europe.  
   **À retenir :** ne pas réduire un indicateur budgétaire à un jugement politique.  
   **Sources :** ministère, banque centrale, institutions européennes.

8. **⚡ Énergie : prix, réseau et choix de transition**  
   La revue rassemble les évolutions ayant un effet concret sur l’approvisionnement ou les prix.  
   **Pourquoi c’est important :** compétitivité, ménages, climat et souveraineté.  
   **À retenir :** une annonce énergétique n’est pas nécessairement une mise en œuvre.  
   **Sources :** régulateurs, opérateurs publics, données de marché.

9. **🌍 Moyen-Orient : répercussions possibles pour l’Espagne**  
   La sélection n’inclut ce sujet que si un lien espagnol direct est documenté : diplomatie, économie, transport, communauté concernée ou sécurité.  
   **Pourquoi c’est important :** les crises internationales peuvent avoir des effets domestiques.  
   **À retenir :** ne pas forcer un angle Espagne sans preuve.  
   **Sources :** diplomatie officielle, institutions internationales, médias diversifiés.

10. **🌘 Éclipse : science, sécurité et mobilisation du public**  
    Un phénomène astronomique peut figurer quand son intérêt public est exceptionnel, avec dates et conseils de sécurité vérifiés.  
    **Pourquoi c’est important :** événement collectif et éducation scientifique.  
    **À retenir :** citer les organismes scientifiques et les consignes officielles.  
    **Sources :** observatoires, organismes de sécurité civile, médias.

### 8.1 Exemple de regroupement hypothétique

Les données suivantes sont fictives : elles montrent la logique de regroupement, pas des articles réels.

| Signal | Indices | Décision |
|---|---|---|
| A : bulletin d’autorité sur un transfert à Ceuta | Ceuta, migration, date 15 août | `evt_ceuta_migration` |
| B : article de média 1 sur le débat parlementaire | Ceuta, mêmes acteurs, 16 août | `evt_ceuta_migration` |
| C : dépêche reprise par plusieurs médias | même fait, même origine | un seul signal d’origine dans le cluster |
| D : article sur une arrivée distincte à une autre date/lieu | migration mais autre lieu/action | nouveau cluster ou revue humaine |
| E : alerte d’incendie dans une province | incendie, localisation X, 14 août | `evt_fire_x` |
| F : article de bilan national des feux | incendies, portée nationale, 18 août | `evt_wildfire_national` ; ne pas fusionner automatiquement avec E |

Après classement, `evt_ceuta_migration` peut arriver n°1 grâce à l’impact, la portée nationale et les sources indépendantes ; `evt_fire_x` peut ne pas entrer dans le Top 5 si `evt_wildfire_national` couvre déjà le même angle et a une portée plus large. Cette décision reste visible et explicable.

## 9. Génération LLM structurée et anti-hallucination

Le LLM ne reçoit pas le web libre. Il reçoit un paquet d’événement contenant les métadonnées, extraits utiles et faits structurés, avec statut de vérification, liens et contradictions.

### 9.1 Contrat de sortie

```json
{
  "rank": 1,
  "title": "Titre factuel et concis",
  "summary": "2 à 4 phrases exclusivement fondées sur les faits corroborés.",
  "why_it_matters": "Conséquence explicitement justifiée.",
  "takeaway": "Une phrase de synthèse prudente.",
  "source_refs": ["art_a", "art_b"],
  "claims_used": ["claim_1", "claim_2"],
  "uncertainties": ["élément dont le calendrier est contesté"]
}
```

### 9.2 Prompt de rédaction

```text
Tu rédiges une entrée de revue d’actualité en {language}.
Tu peux utiliser exclusivement les FAITS CORROBORÉS et les sources incluses ci-dessous.
N’ajoute aucun chiffre, nom, date, cause, citation ou conséquence qui n’y figure pas.
Si un point est single_source ou disputed, attribue-le explicitement ou omets-le.
Ne présente pas une hypothèse comme un fait. Ne reproduis pas de longs extraits.

Format strict :
1. emoji + titre factuel
2. résumé (2–4 phrases)
3. « Pourquoi c’est important : »
4. « À retenir : »
5. « Sources : » avec noms et liens fournis

FAITS CORROBORÉS : {facts}
DIVERGENCES : {divergences}
SOURCES FOURNIES : {sources}
```

### 9.3 Prompt de contrôle

```text
Compare le brouillon avec le dossier source. Retourne du JSON uniquement.
Pour chaque phrase : supported, partially_supported ou unsupported ; donne les IDs de faits.
Signale : chiffre sans source, attribution absente, causalité non prouvée, ton excessif,
contradiction ignorée, ou lien ne menant pas à une source fournie.
Si un élément est unsupported, propose sa suppression plutôt qu’une invention de correction.
```

La publication est bloquée si le validateur relève une affirmation centrale non étayée. Une version d’abord en JSON, puis rendue côté application, évite que le modèle casse le format ou les liens.

## 10. Produit et UX

### 10.1 Navigation

- Sélecteur : Monde / Europe / France / Espagne.
- Sélecteur : Daily / Weekly.
- Sélecteur de langue : FR / EN / ES.
- Page revue : Top 5, date/fenêtre, méthode courte, cartes événement, liens sources et étiquette d’incertitude si nécessaire.
- Page « Voir les 10 » : classement étendu, sans surcharger l’accueil.
- Page événement : chronologie courte, sources, faits confirmés et limites ; elle ne réhéberge pas le contenu protégé.

La langue de lecture peut différer de celle de la source. Le résumé est traduit/rédigé par le LLM à partir du même dossier factuel ; le libellé indique la langue originale de la source si utile.

### 10.2 Web et mobile

MVP responsive (web mobile-first), puis application mobile partageant les mêmes API. Les priorités UX : lecture en moins de deux minutes, source accessible en un geste, date visible, distinction nette entre fait et analyse, et chargement rapide.

## 11. Backend, API et jobs

### 11.1 Services

```text
API / BFF
 ├─ catalogue des sources et de leurs capacités
 ├─ ingestion adapters (RSS, API, institutionnel)
 ├─ normalisation / déduplication
 ├─ clustering + dossier d’événement
 ├─ scoring + reranking diversité
 ├─ génération + validation LLM
 ├─ publication et cache
 └─ administration / corrections
```

### 11.2 Endpoints MVP (indicatifs)

```text
GET  /v1/digests?region=ES&period=weekly&language=fr
GET  /v1/digests/{digestId}
GET  /v1/events/{eventId}
GET  /v1/events/{eventId}/sources
POST /v1/admin/events/{eventId}/merge
POST /v1/admin/events/{eventId}/split
POST /v1/admin/digests/{digestId}/publish
```

Les endpoints publics exposent le digest, les résumés et les liens sources. Les endpoints d’administration exigent authentification, audit log et contrôle de rôle.

### 11.3 Planification des jobs

- Ingestion : toutes les 15 à 60 minutes selon la source et ses limites.
- Normalisation/déduplication : après chaque lot d’ingestion.
- Clustering/scoring : périodique et à l’arrivée de signaux à forte priorité.
- Daily : préparation continue, gel et génération à l’heure éditoriale configurée.
- Weekly : clôture à une heure/zone définie, génération, validation puis publication.
- Recalcul : déclenché par correction de source, fusion/scission d’événements ou changement de règle.

Tous les jobs doivent être idempotents, rejouables et accompagnés d’un `run_id`.

## 12. Observabilité, qualité et sûreté

Mesurer : fraîcheur par source, taux d’échec d’ingestion, taux de déduplication, taille des clusters, nombre d’origines indépendantes, distribution des scores, concentration de sources dans les Top 5, hallucinations détectées, délai jusqu’à publication et corrections après publication.

Conserver un audit trail : version de l’algorithme, version du prompt/modèle, IDs des faits, IDs de sources et décision de sélection pour chaque entrée publiée. Prévoir des alertes si une source domine anormalement, si une ingestion tombe à zéro, ou si la validation LLM échoue.

## 13. Tests et critères d’acceptation MVP

### Tests

- Unitaires : parseurs, normalisation, scores, quotas de diversité, format JSON LLM.
- Intégration : ingestion RSS/API simulée, idempotence, reprise après panne, cache et publication.
- Jeux de données annotés : articles dupliqués, reprises d’agence, événements voisins, informations contradictoires, sujets très couverts mais peu importants.
- Évaluation éditoriale : annotateurs comparent Top 5 attendu, exactitude des phrases et diversité.
- Tests de sécurité : secrets non exposés, autorisations admin, validation d’URL, protection contre contenu source malveillant dans les prompts.

### Critères d’acceptation

1. L’application peut produire une revue ES/FR/EN pour Espagne en Daily et Weekly à partir de plusieurs adaptateurs non liés à du scraping protégé.
2. Chaque entrée publiée contient au moins une source cliquable et une provenance interne ; les affirmations centrales ont une source primaire ou deux origines indépendantes, sauf attribution explicite.
3. Le MVP produit ses revues sans dépendre du texte intégral ni des images d’un site tiers.
4. Les reprises d’un même wire/service ne gonflent pas artificiellement le score de corroboration.
5. Le Top 5 ne répète pas un même événement et respecte la politique de diversité, avec exceptions journalisées.
6. Le validateur bloque les nombres, citations ou affirmations centrales non soutenus.
7. Un opérateur peut corriger, fusionner, scinder ou retirer un événement, puis régénérer la revue avec traçabilité.

## 14. Roadmap MVP → suites

### MVP

- Une région pilote : Espagne ; trois langues de sortie ; Daily et Weekly.
- Petit catalogue de sources publiques, RSS et APIs simples à intégrer.
- Pipeline d’événements, Top 5 + Top 10, LLM sous contraintes, validation automatique et revue admin.
- Web responsive, sources sortantes, métriques et audit trail.

### V1

- Monde, Europe et France ; profils de pondération par région.
- Plus de sources, alertes personnalisées et pages événement enrichies.
- Revue humaine assistée par file de contrôle des divergences.

### V2

- Personnalisation transparente, abonnements, notifications, édition collaborative et évaluation continue du ranking.
- Amélioration active des règles de clustering à partir de corrections annotées, avec tests de régression éditoriale.

## 15. Décision d’implémentation à retenir

Construire d’abord la qualité de la chaîne **source disponible → événement corroboré → score explicable → rédaction contrainte → liens vers les sources**. Le choix d’un fournisseur de news ou d’un modèle de langage doit rester interchangeable derrière des adaptateurs. La réussite de 5 News ne dépend pas de récupérer plus de HTML ; elle dépend de sélectionner, vérifier et expliquer mieux.
