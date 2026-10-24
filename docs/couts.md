# Coûts d'une veille : avant / après PJ15

Mesuré le 2026-10-24 11:36 sur 3 marques, en rejouant les données de la dernière veille (outils rejoués, appels LLM réels). Une seule mesure par réglage : à lire comme un ordre de grandeur, pas comme une moyenne.

| | avant | apres |
|---|---:|---:|
| Marques traitées | 3/3 | 3/3 |
| Appels LLM (échecs) | 16 (15) | 16 (23) |
| Tokens d'entrée | 23714 | 25083 |
| dont lus en cache | 512 (2%) | 1024 (4%) |
| Tokens de sortie | 4684 | 4017 |
| dont raisonnement | 2692 | 1058 |
| Temps passé dans le LLM | 13.9 s | 14.4 s |
| Coût Groq par marque | 0.0011 $ | 0.0010 $ |
| Coût Claude par marque (sans cache) | 0.0016 $ | 0.0015 $ |
| Coût Claude par marque (avec cache) | 0.0017 $ | 0.0017 $ |
| Coût Groq par marque si rien n'a changé (rapport repris) | 0.0007 $ | 0.0006 $ |
| Pubs Meta retrouvées | 11/11 | 12/11 |
| Constats rédigés | 51 | 78 |
| Chiffres retirés à l'ancrage | 0 | 0 |

Tarifs au 2026-10-23 (dollars par million de tokens) :
- Groq : prix publics des modèles gpt-oss ; jetons lus en cache facturés -50 % (console.groq.com/docs/prompt-caching)
- Anthropic : platform.claude.com/docs/en/about-claude/pricing (Haiku 5.5 en dessous de 100k tokens de prompt)
- Claude = mêmes nombres de tokens facturés par l'équivalent (gpt-oss-20b → Haiku 5.5, gpt-oss-120b → Sonnet 5.5). « Avec cache » : ce que Groq a lu en cache serait lu en cache, le reste écrit en cache.

## Détail par réglage

#### avant

### Exécution couts-avant-2026-10-24T11-30 — 148.4 s

| Agent | Appels | Échecs | Entrée | dont cache | Sortie | dont raisonnement | Durée LLM | Groq | Claude | Claude + cache |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| collecteur | 13 | 13 | 17500 | 512 (3%) | 2300 | 1908 | 9.8 s | 0.0020 $ | 0.0029 $ | 0.0033 $ |
| redacteur | 3 | 2 | 6214 | 0 (0%) | 2384 | 784 | 4.1 s | 0.0012 $ | 0.0018 $ | 0.0020 $ |
| **total** | 16 | 15 | 23714 | 512 (2%) | 4684 | 2692 | 13.9 s | 0.0032 $ | 0.0047 $ | 0.0052 $ |

| Outil | Appels | Erreurs | Durée | Caractères renvoyés | Apify |
|---|---:|---:|---:|---:|---:|
| chercher_pubs_meta | 3 | 0 | 0.0 s | 6616 | 0.0000 $ |
| lire_page_web | 7 | 6 | 0.0 s | 2640 | 0.0000 $ |

#### apres

### Exécution couts-apres-2026-10-24T11-32 — 210.1 s

| Agent | Appels | Échecs | Entrée | dont cache | Sortie | dont raisonnement | Durée LLM | Groq | Claude | Claude + cache |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| collecteur | 13 | 19 | 18567 | 1024 (6%) | 1558 | 315 | 9.9 s | 0.0018 $ | 0.0026 $ | 0.0030 $ |
| redacteur | 3 | 4 | 6516 | 0 (0%) | 2459 | 743 | 4.5 s | 0.0012 $ | 0.0019 $ | 0.0020 $ |
| **total** | 16 | 23 | 25083 | 1024 (4%) | 4017 | 1058 | 14.4 s | 0.0030 $ | 0.0045 $ | 0.0050 $ |

| Outil | Appels | Erreurs | Durée | Caractères renvoyés | Apify |
|---|---:|---:|---:|---:|---:|
| chercher_pubs_meta | 4 | 0 | 0.0 s | 7632 | 0.0000 $ |
| lire_page_web | 5 | 4 | 0.0 s | 2458 | 0.0000 $ |
