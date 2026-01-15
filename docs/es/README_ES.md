# Nexting

<div align="center">

**Sistema Open Source de Agent Co-work**

*Claude Code para clonación web. Un agente de IA vertical con más de 40 herramientas especializadas.*

[English](../../README.md) | [中文](../cn/README_CN.md) | [日本語](../ja/README_JA.md) | [한국어](../ko/README_KO.md) | Español | [Português](../pt/README_PT.md) | [Deutsch](../de/README_DE.md) | [Français](../fr/README_FR.md) | [Tiếng Việt](../vi/README_VI.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Next.js](https://img.shields.io/badge/Next.js-15.x-black)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19.x-61dafb)](https://react.dev/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776ab)](https://python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)](https://fastapi.tiangolo.com/)
[![Playwright](https://img.shields.io/badge/Playwright-1.49+-2EAD33)](https://playwright.dev/)
[![Claude](https://img.shields.io/badge/Claude-Anthropic-cc785c)](https://anthropic.com/)

</div>

**Un verdadero agente de IA** — no solo un wrapper alrededor de un LLM. Colaboración multi-agente con herramientas reales, bucles de auto-corrección y un entorno sandbox completo para construir código listo para producción desde cero.

Otras herramientas adivinan el código desde capturas de pantalla. Nosotros extraemos el **código real** — DOM, estilos, componentes, interacciones. **Clonación pixel-perfect** que las herramientas basadas en capturas simplemente no pueden lograr.

https://github.com/user-attachments/assets/248af639-20d9-45a8-ad0a-660a04a17b68

## Arquitectura Multi-Agente de Código Abierto

**Todo el sistema multi-agente es de código abierto.** Aprende de él, úsalo, construye sobre él.

### ¿Por qué Cowork?

Trabajar con una sola IA es como pedirle a un compañero de trabajo que maneje todo solo — se abruman. Los enfoques tradicionales de modelo único encuentran un límite:
- Desbordamiento de ventana de contexto en páginas grandes
- Alucinaciones al manejar demasiadas responsabilidades
- Procesamiento secuencial lento

Nuestra solución: **Un equipo de agentes especializados trabajando juntos**, como compañeros de trabajo enfocados en lo que cada uno hace mejor. Menos ida y vuelta, más trabajo hecho.

### ¿Por qué no usar Cursor / Claude Code / Copilot?

<p align="center">
  <img src="https://img.shields.io/badge/Cursor-000000?style=for-the-badge&logo=cursor&logoColor=white" alt="Cursor" />
  <img src="https://img.shields.io/badge/Claude_Code-cc785c?style=for-the-badge&logo=anthropic&logoColor=white" alt="Claude Code" />
  <img src="https://img.shields.io/badge/GitHub_Copilot-000000?style=for-the-badge&logo=githubcopilot&logoColor=white" alt="GitHub Copilot" />
  <span style="margin: 0 10px;">vs</span>
  <img src="https://img.shields.io/badge/Nexting-8B5CF6?style=for-the-badge" alt="Nexting" />
</p>

Lo intentamos. Incluso con el **JSON extraído completo** — árbol DOM completo, todas las reglas CSS, cada URL de recurso — las herramientas de un solo modelo tienen dificultades:

| Desafío | <img src="https://img.shields.io/badge/-Cursor-000?style=flat-square&logo=cursor" /> <img src="https://img.shields.io/badge/-Claude_Code-cc785c?style=flat-square&logo=anthropic" /> <img src="https://img.shields.io/badge/-Copilot-000?style=flat-square&logo=githubcopilot" /> | <img src="https://img.shields.io/badge/-Nexting-8B5CF6?style=flat-square" /> Multi-Agente |
|---------|-------------------------------|---------------------|
| **Árbol DOM de 50,000+ líneas** | ❌ Desbordamiento de contexto, trunca partes críticas | ✅ Agente DOM procesa en chunks |
| **3,000+ reglas CSS** | ❌ Pierde especificidad, omite variables | ✅ Agente de Estilo maneja CSS por separado |
| **Detección de componentes** | ❌ Adivina límites, crea monolitos | ✅ Agente dedicado identifica patrones |
| **Breakpoints responsivos** | ❌ A menudo hardcodea un solo viewport | ✅ Extrae todas las media queries |
| **Estados hover/animación** | ❌ No puede ver, no puede reproducir | ✅ Automatización del navegador captura todo |
| **Calidad de salida** | ❌ Aproximación "suficientemente cercana" | ✅ Pixel-perfect, listo para producción |

> **El problema central**: Un JSON extraído de 200KB excede los límites de contexto prácticos. Incluso si cabe, el modelo no puede mantener coherencia a través de DOM→CSS→Componentes→Código. Cada paso necesita atención enfocada.

### Patrón Agent + Tools + Sandbox

```
┌─────────────────────────────────────────────────────────┐
│                    Sistema Multi-Agente                  │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │ Agente DOM  │  │Agente Estilo│  │Agente Código│     │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘     │
│         │                │                │             │
│         ▼                ▼                ▼             │
│  ┌─────────────────────────────────────────────────┐   │
│  │                  Herramientas                    │   │
│  │  • Operaciones de Archivo  • Análisis de Código │   │
│  │  • Control del Navegador   • Llamadas API       │   │
│  └─────────────────────────────────────────────────┘   │
│                         │                               │
│                         ▼                               │
│  ┌─────────────────────────────────────────────────┐   │
│  │              Sandbox (BoxLite)                   │   │
│  │  Entorno de ejecución aislado para generación   │   │
│  │  de código segura, pruebas y vista previa       │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

Este patrón — **Agent + Tools + Sandbox** — es reutilizable para cualquier producto de agente de IA:

| Componente | Propósito | En Nexting |
|------------|-----------|------------|
| **Agentes** | Trabajadores de IA especializados con responsabilidades enfocadas | Agentes DOM, Estilo, Componente, Código |
| **Herramientas** | Capacidades que los agentes pueden invocar | I/O de archivos, Automatización del navegador, Llamadas API |
| **Sandbox** | Entorno de ejecución seguro | [BoxLite](https://github.com/boxlite-ai/boxlite) - Runtime de micro-VM embebido |

### Conéctate Conmigo

¿Construyendo algo con esta arquitectura? ¿Tienes preguntas? Contáctame:

[![Twitter](https://img.shields.io/badge/Twitter-@ericshang98-1DA1F2?style=flat&logo=twitter)](https://twitter.com/ericshang98)
[![GitHub](https://img.shields.io/badge/GitHub-ericshang98-181717?style=flat&logo=github)](https://github.com/ericshang98)
[![Discord](https://img.shields.io/badge/Discord-Unirse_Comunidad-5865F2?style=flat&logo=discord&logoColor=white)](https://discord.gg/HJURzJq3y5)

---

## Inicio Rápido

### Prerrequisitos

- Python 3.11+
- Node.js 18+
- Anthropic API Key

### Inicio Rápido

1. **Clonar el repositorio**

```bash
git clone https://github.com/ericshang98/perfect-web-clone.git
cd perfect-web-clone
```

2. **Configuración del Backend**

```bash
cd backend

# Copiar archivo de entorno y agregar tu API key
cp ../.env.example .env
# Edita .env y agrega tu ANTHROPIC_API_KEY

# Iniciar el servidor (auto-instala dependencias)
sh start.sh
```

3. **Configuración del Frontend**

```bash
cd frontend

# Instalar dependencias
npm install

# Configurar entorno (opcional)
cp ../.env.example .env.local

# Iniciar servidor de desarrollo
npm run dev
```

4. **Abrir la Aplicación**

Navega a [http://localhost:3000](http://localhost:3000) en tu navegador.

## Licencia

Este proyecto está licenciado bajo la Licencia MIT - ver el archivo [LICENSE](../../LICENSE) para más detalles.

---

<div align="center">

**[Nexting](https://github.com/ericshang98/perfect-web-clone)** - Extrae el código real, no adivinanzas.

Hecho con ❤️ por [Eric Shang](https://github.com/ericshang98)

</div>
