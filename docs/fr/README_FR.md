# Nexting

<div align="center">

**Système Open Source Agent Co-work**

*Claude Code pour le clonage web. Un agent IA vertical avec plus de 40 outils spécialisés.*

[English](../../README.md) | [中文](../cn/README_CN.md) | [日本語](../ja/README_JA.md) | [한국어](../ko/README_KO.md) | [Español](../es/README_ES.md) | [Português](../pt/README_PT.md) | [Deutsch](../de/README_DE.md) | Français | [Tiếng Việt](../vi/README_VI.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Next.js](https://img.shields.io/badge/Next.js-15.x-black)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19.x-61dafb)](https://react.dev/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776ab)](https://python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)](https://fastapi.tiangolo.com/)
[![Playwright](https://img.shields.io/badge/Playwright-1.49+-2EAD33)](https://playwright.dev/)
[![Claude](https://img.shields.io/badge/Claude-Anthropic-cc785c)](https://anthropic.com/)

</div>

**Un véritable agent IA** — pas simplement un wrapper autour d'un LLM. Collaboration multi-agent avec de vrais outils, des boucles d'auto-correction et un environnement sandbox complet pour construire du code prêt pour la production à partir de zéro.

Les autres outils devinent le code à partir de captures d'écran. Nous extrayons le **vrai code** — DOM, styles, composants, interactions. **Clonage pixel-perfect** que les outils basés sur les captures d'écran ne peuvent tout simplement pas atteindre.

https://github.com/user-attachments/assets/248af639-20d9-45a8-ad0a-660a04a17b68

## Architecture Multi-Agent Open Source

**L'ensemble du système multi-agent est open source.** Apprenez-en, utilisez-le, construisez dessus.

### Pourquoi Cowork ?

Travailler avec une seule IA, c'est comme demander à un collègue de tout gérer seul — ils sont débordés. Les approches traditionnelles à modèle unique atteignent leurs limites :
- Débordement de fenêtre de contexte sur les grandes pages
- Hallucinations lors de la gestion de trop de responsabilités
- Traitement séquentiel lent

Notre solution : **Une équipe d'agents spécialisés travaillant ensemble**, comme des collègues concentrés sur ce que chacun fait le mieux. Moins d'allers-retours, plus de travail accompli.

### Pourquoi ne pas simplement utiliser Cursor / Claude Code / Copilot ?

<p align="center">
  <img src="https://img.shields.io/badge/Cursor-000000?style=for-the-badge&logo=cursor&logoColor=white" alt="Cursor" />
  <img src="https://img.shields.io/badge/Claude_Code-cc785c?style=for-the-badge&logo=anthropic&logoColor=white" alt="Claude Code" />
  <img src="https://img.shields.io/badge/GitHub_Copilot-000000?style=for-the-badge&logo=githubcopilot&logoColor=white" alt="GitHub Copilot" />
  <span style="margin: 0 10px;">vs</span>
  <img src="https://img.shields.io/badge/Nexting-8B5CF6?style=for-the-badge" alt="Nexting" />
</p>

Nous avons essayé. Même avec le **JSON extrait complet** — arbre DOM complet, toutes les règles CSS, chaque URL de ressource — les outils à modèle unique ont des difficultés :

| Défi | <img src="https://img.shields.io/badge/-Cursor-000?style=flat-square&logo=cursor" /> <img src="https://img.shields.io/badge/-Claude_Code-cc785c?style=flat-square&logo=anthropic" /> <img src="https://img.shields.io/badge/-Copilot-000?style=flat-square&logo=githubcopilot" /> | <img src="https://img.shields.io/badge/-Nexting-8B5CF6?style=flat-square" /> Multi-Agent |
|------|-------------------------------|---------------------|
| **Arbre DOM de 50 000+ lignes** | ❌ Débordement de contexte, tronque les parties critiques | ✅ L'Agent DOM traite par morceaux |
| **3 000+ règles CSS** | ❌ Perd la spécificité, manque les variables | ✅ L'Agent Style gère le CSS séparément |
| **Détection de composants** | ❌ Devine les limites, crée des monolithes | ✅ Agent dédié identifie les patterns |
| **Breakpoints responsifs** | ❌ Souvent code en dur un seul viewport | ✅ Extrait toutes les media queries |
| **États hover/animation** | ❌ Ne peut pas voir, ne peut pas reproduire | ✅ L'automatisation du navigateur capture tout |
| **Qualité de sortie** | ❌ Approximation "assez proche" | ✅ Pixel-perfect, prêt pour la production |

> **Le problème central** : Un JSON extrait de 200Ko dépasse les limites de contexte pratiques. Même s'il rentre, le modèle ne peut pas maintenir la cohérence à travers DOM→CSS→Composants→Code. Chaque étape nécessite une attention focalisée.

### Pattern Agent + Tools + Sandbox

```
┌─────────────────────────────────────────────────────────┐
│                    Système Multi-Agent                   │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │ Agent DOM   │  │ Agent Style │  │ Agent Code  │     │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘     │
│         │                │                │             │
│         ▼                ▼                ▼             │
│  ┌─────────────────────────────────────────────────┐   │
│  │                     Outils                       │   │
│  │  • Opérations Fichiers  • Analyse de Code       │   │
│  │  • Contrôle Navigateur  • Appels API            │   │
│  └─────────────────────────────────────────────────┘   │
│                         │                               │
│                         ▼                               │
│  ┌─────────────────────────────────────────────────┐   │
│  │              Sandbox (BoxLite)                   │   │
│  │  Environnement d'exécution isolé pour la        │   │
│  │  génération de code sécurisée, tests et aperçu  │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

Ce pattern — **Agent + Tools + Sandbox** — est réutilisable pour tout produit d'agent IA :

| Composant | Objectif | Dans Nexting |
|-----------|----------|--------------|
| **Agents** | Workers IA spécialisés avec des responsabilités focalisées | Agents DOM, Style, Composant, Code |
| **Outils** | Capacités que les agents peuvent invoquer | I/O Fichiers, Automatisation navigateur, Appels API |
| **Sandbox** | Environnement d'exécution sécurisé | [BoxLite](https://github.com/boxlite-ai/boxlite) - Runtime micro-VM embarqué |

### Contactez-Moi

Vous construisez quelque chose avec cette architecture ? Vous avez des questions ? Contactez-moi :

[![Twitter](https://img.shields.io/badge/Twitter-@ericshang98-1DA1F2?style=flat&logo=twitter)](https://twitter.com/ericshang98)
[![GitHub](https://img.shields.io/badge/GitHub-ericshang98-181717?style=flat&logo=github)](https://github.com/ericshang98)
[![Discord](https://img.shields.io/badge/Discord-Rejoindre_Communauté-5865F2?style=flat&logo=discord&logoColor=white)](https://discord.gg/HJURzJq3y5)

---

## Démarrage Rapide

### Prérequis

- Python 3.11+
- Node.js 18+
- Clé API Anthropic

### Démarrage Rapide

1. **Cloner le dépôt**

```bash
git clone https://github.com/ericshang98/perfect-web-clone.git
cd perfect-web-clone
```

2. **Configuration Backend**

```bash
cd backend

# Copier le fichier d'environnement et ajouter votre clé API
cp ../.env.example .env
# Éditez .env et ajoutez votre ANTHROPIC_API_KEY

# Démarrer le serveur (installe automatiquement les dépendances)
sh start.sh
```

3. **Configuration Frontend**

```bash
cd frontend

# Installer les dépendances
npm install

# Configurer l'environnement (optionnel)
cp ../.env.example .env.local

# Démarrer le serveur de développement
npm run dev
```

4. **Ouvrir l'Application**

Naviguez vers [http://localhost:3000](http://localhost:3000) dans votre navigateur.

## Licence

Ce projet est sous licence MIT - voir le fichier [LICENSE](../../LICENSE) pour plus de détails.

---

<div align="center">

**[Nexting](https://github.com/ericshang98/perfect-web-clone)** - Extrayez le vrai code, pas des suppositions.

Fait avec ❤️ par [Eric Shang](https://github.com/ericshang98)

</div>
