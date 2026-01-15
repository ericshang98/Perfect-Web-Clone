# Nexting

<div align="center">

**Open Source Agent Co-work System**

*Claude Code für Web-Kloning. Ein vertikaler KI-Agent mit über 40 spezialisierten Werkzeugen.*

[English](../../README.md) | [中文](../cn/README_CN.md) | [日本語](../ja/README_JA.md) | [한국어](../ko/README_KO.md) | [Español](../es/README_ES.md) | [Português](../pt/README_PT.md) | Deutsch | [Français](../fr/README_FR.md) | [Tiếng Việt](../vi/README_VI.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Next.js](https://img.shields.io/badge/Next.js-15.x-black)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19.x-61dafb)](https://react.dev/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776ab)](https://python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)](https://fastapi.tiangolo.com/)
[![Playwright](https://img.shields.io/badge/Playwright-1.49+-2EAD33)](https://playwright.dev/)
[![Claude](https://img.shields.io/badge/Claude-Anthropic-cc785c)](https://anthropic.com/)

</div>

**Ein echter KI-Agent** — nicht nur ein Wrapper um ein LLM. Multi-Agent-Zusammenarbeit mit echten Werkzeugen, Selbstkorrektur-Schleifen und einer vollständigen Sandbox-Umgebung zum Erstellen von produktionsfertigem Code von Grund auf.

Andere Tools raten Code aus Screenshots. Wir extrahieren den **echten Code** — DOM, Stile, Komponenten, Interaktionen. **Pixel-perfektes Klonen**, das Screenshot-basierte Tools einfach nicht erreichen können.

https://github.com/user-attachments/assets/248af639-20d9-45a8-ad0a-660a04a17b68

## Open-Source Multi-Agent-Architektur

**Das gesamte Multi-Agent-System ist Open Source.** Lernen Sie davon, nutzen Sie es, bauen Sie darauf auf.

### Warum Cowork?

Mit einer einzelnen KI zu arbeiten ist wie einen Kollegen zu bitten, alles alleine zu erledigen — sie werden überfordert. Traditionelle Single-Model-Ansätze stoßen an Grenzen:
- Kontextfenster-Überlauf bei großen Seiten
- Halluzinationen bei zu vielen Verantwortlichkeiten
- Langsame sequenzielle Verarbeitung

Unsere Lösung: **Ein Team spezialisierter Agenten arbeitet zusammen**, wie Kollegen, die sich jeweils auf das konzentrieren, was sie am besten können. Weniger Hin und Her, mehr erledigt.

### Warum nicht einfach Cursor / Claude Code / Copilot verwenden?

<p align="center">
  <img src="https://img.shields.io/badge/Cursor-000000?style=for-the-badge&logo=cursor&logoColor=white" alt="Cursor" />
  <img src="https://img.shields.io/badge/Claude_Code-cc785c?style=for-the-badge&logo=anthropic&logoColor=white" alt="Claude Code" />
  <img src="https://img.shields.io/badge/GitHub_Copilot-000000?style=for-the-badge&logo=githubcopilot&logoColor=white" alt="GitHub Copilot" />
  <span style="margin: 0 10px;">vs</span>
  <img src="https://img.shields.io/badge/Nexting-8B5CF6?style=for-the-badge" alt="Nexting" />
</p>

Wir haben es versucht. Selbst mit dem **vollständigen extrahierten JSON** — vollständiger DOM-Baum, alle CSS-Regeln, jede Asset-URL — haben Single-Model-Tools Schwierigkeiten:

| Herausforderung | <img src="https://img.shields.io/badge/-Cursor-000?style=flat-square&logo=cursor" /> <img src="https://img.shields.io/badge/-Claude_Code-cc785c?style=flat-square&logo=anthropic" /> <img src="https://img.shields.io/badge/-Copilot-000?style=flat-square&logo=githubcopilot" /> | <img src="https://img.shields.io/badge/-Nexting-8B5CF6?style=flat-square" /> Multi-Agent |
|-----------------|-------------------------------|---------------------|
| **50.000+ Zeilen DOM-Baum** | ❌ Kontextüberlauf, schneidet kritische Teile ab | ✅ DOM-Agent verarbeitet in Chunks |
| **3.000+ CSS-Regeln** | ❌ Verliert Spezifität, übersieht Variablen | ✅ Style-Agent behandelt CSS separat |
| **Komponenten-Erkennung** | ❌ Rät Grenzen, erstellt Monolithen | ✅ Dedizierter Agent identifiziert Muster |
| **Responsive Breakpoints** | ❌ Oft hartcodierter einzelner Viewport | ✅ Extrahiert alle Media Queries |
| **Hover-/Animationszustände** | ❌ Kann nicht sehen, kann nicht reproduzieren | ✅ Browser-Automatisierung erfasst alles |
| **Ausgabequalität** | ❌ "Nah genug"-Annäherung | ✅ Pixel-perfekt, produktionsbereit |

> **Das Kernproblem**: Ein 200KB extrahiertes JSON überschreitet praktische Kontextgrenzen. Selbst wenn es passt, kann das Modell keine Kohärenz über DOM→CSS→Komponenten→Code aufrechterhalten. Jeder Schritt braucht fokussierte Aufmerksamkeit.

### Agent + Tools + Sandbox Muster

```
┌─────────────────────────────────────────────────────────┐
│                    Multi-Agent-System                    │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │ DOM-Agent   │  │ Style-Agent │  │ Code-Agent  │     │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘     │
│         │                │                │             │
│         ▼                ▼                ▼             │
│  ┌─────────────────────────────────────────────────┐   │
│  │                   Werkzeuge                      │   │
│  │  • Dateioperationen  • Code-Analyse             │   │
│  │  • Browser-Steuerung • API-Aufrufe              │   │
│  └─────────────────────────────────────────────────┘   │
│                         │                               │
│                         ▼                               │
│  ┌─────────────────────────────────────────────────┐   │
│  │              Sandbox (BoxLite)                   │   │
│  │  Isolierte Ausführungsumgebung für sichere      │   │
│  │  Code-Generierung, Tests und Vorschau           │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

Dieses Muster — **Agent + Tools + Sandbox** — ist wiederverwendbar für jedes KI-Agent-Produkt:

| Komponente | Zweck | In Nexting |
|------------|-------|------------|
| **Agenten** | Spezialisierte KI-Worker mit fokussierten Verantwortlichkeiten | DOM-, Style-, Komponenten-, Code-Agenten |
| **Werkzeuge** | Fähigkeiten, die Agenten aufrufen können | Datei-I/O, Browser-Automatisierung, API-Aufrufe |
| **Sandbox** | Sichere Ausführungsumgebung | [BoxLite](https://github.com/boxlite-ai/boxlite) - Eingebettete Micro-VM-Runtime |

### Kontaktieren Sie Mich

Bauen Sie etwas mit dieser Architektur? Haben Sie Fragen? Kontaktieren Sie mich:

[![Twitter](https://img.shields.io/badge/Twitter-@ericshang98-1DA1F2?style=flat&logo=twitter)](https://twitter.com/ericshang98)
[![GitHub](https://img.shields.io/badge/GitHub-ericshang98-181717?style=flat&logo=github)](https://github.com/ericshang98)
[![Discord](https://img.shields.io/badge/Discord-Community_Beitreten-5865F2?style=flat&logo=discord&logoColor=white)](https://discord.gg/HJURzJq3y5)

---

## Schnellstart

### Voraussetzungen

- Python 3.11+
- Node.js 18+
- Anthropic API Key

### Schnellstart

1. **Repository klonen**

```bash
git clone https://github.com/ericshang98/perfect-web-clone.git
cd perfect-web-clone
```

2. **Backend-Setup**

```bash
cd backend

# Umgebungsdatei kopieren und API-Schlüssel hinzufügen
cp ../.env.example .env
# Bearbeiten Sie .env und fügen Sie Ihren ANTHROPIC_API_KEY hinzu

# Server starten (installiert Abhängigkeiten automatisch)
sh start.sh
```

3. **Frontend-Setup**

```bash
cd frontend

# Abhängigkeiten installieren
npm install

# Umgebung konfigurieren (optional)
cp ../.env.example .env.local

# Entwicklungsserver starten
npm run dev
```

4. **Anwendung öffnen**

Navigieren Sie zu [http://localhost:3000](http://localhost:3000) in Ihrem Browser.

## Lizenz

Dieses Projekt ist unter der MIT-Lizenz lizenziert - siehe die [LICENSE](../../LICENSE) Datei für Details.

---

<div align="center">

**[Nexting](https://github.com/ericshang98/perfect-web-clone)** - Extrahieren Sie den echten Code, keine Vermutungen.

Mit ❤️ erstellt von [Eric Shang](https://github.com/ericshang98)

</div>
