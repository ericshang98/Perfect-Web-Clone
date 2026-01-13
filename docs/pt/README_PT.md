# Nexting

<div align="center">

**Ferramenta de Clonagem Web Potencializada por IA — Construída com Claude Agent SDK**

*Claude Code para clonagem web. Um agente de IA vertical com mais de 40 ferramentas especializadas.*

[English](../../README.md) | [中文](../cn/README_CN.md) | [日本語](../ja/README_JA.md) | [한국어](../ko/README_KO.md) | [Español](../es/README_ES.md) | Português | [Deutsch](../de/README_DE.md) | [Français](../fr/README_FR.md) | [Tiếng Việt](../vi/README_VI.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Next.js](https://img.shields.io/badge/Next.js-15.x-black)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19.x-61dafb)](https://react.dev/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776ab)](https://python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)](https://fastapi.tiangolo.com/)
[![Playwright](https://img.shields.io/badge/Playwright-1.49+-2EAD33)](https://playwright.dev/)
[![Claude](https://img.shields.io/badge/Claude-Anthropic-cc785c)](https://anthropic.com/)

</div>

**Um verdadeiro agente de IA** — não apenas um wrapper em torno de um LLM. Colaboração multi-agente com ferramentas reais, loops de auto-correção e um ambiente sandbox completo para construir código pronto para produção do zero.

Outras ferramentas adivinham código de screenshots. Nós extraímos o **código real** — DOM, estilos, componentes, interações. **Clonagem pixel-perfect** que ferramentas baseadas em screenshots simplesmente não conseguem alcançar.

https://github.com/user-attachments/assets/248af639-20d9-45a8-ad0a-660a04a17b68

## Arquitetura Multi-Agente Open Source

**Todo o sistema multi-agente é open source.** Aprenda com ele, use-o, construa sobre ele.

### Por que Multi-Agente?

Abordagens tradicionais de IA com um único modelo encontram um limite em tarefas complexas. Um modelo tentando lidar com tudo leva a:
- Estouro de janela de contexto em páginas grandes
- Alucinações ao lidar com muitas responsabilidades
- Processamento sequencial lento

Nossa solução: **Agentes especializados trabalhando em paralelo**, cada um focado no que faz melhor.

### Por que não usar Cursor / Claude Code / Copilot?

<p align="center">
  <img src="https://img.shields.io/badge/Cursor-000000?style=for-the-badge&logo=cursor&logoColor=white" alt="Cursor" />
  <img src="https://img.shields.io/badge/Claude_Code-cc785c?style=for-the-badge&logo=anthropic&logoColor=white" alt="Claude Code" />
  <img src="https://img.shields.io/badge/GitHub_Copilot-000000?style=for-the-badge&logo=githubcopilot&logoColor=white" alt="GitHub Copilot" />
  <span style="margin: 0 10px;">vs</span>
  <img src="https://img.shields.io/badge/Nexting-8B5CF6?style=for-the-badge" alt="Nexting" />
</p>

Nós tentamos. Mesmo com o **JSON extraído completo** — árvore DOM completa, todas as regras CSS, cada URL de recurso — ferramentas de modelo único têm dificuldades:

| Desafio | <img src="https://img.shields.io/badge/-Cursor-000?style=flat-square&logo=cursor" /> <img src="https://img.shields.io/badge/-Claude_Code-cc785c?style=flat-square&logo=anthropic" /> <img src="https://img.shields.io/badge/-Copilot-000?style=flat-square&logo=githubcopilot" /> | <img src="https://img.shields.io/badge/-Nexting-8B5CF6?style=flat-square" /> Multi-Agente |
|---------|-------------------------------|---------------------|
| **Árvore DOM de 50.000+ linhas** | ❌ Estouro de contexto, trunca partes críticas | ✅ Agente DOM processa em chunks |
| **3.000+ regras CSS** | ❌ Perde especificidade, perde variáveis | ✅ Agente de Estilo lida com CSS separadamente |
| **Detecção de componentes** | ❌ Adivinha limites, cria monólitos | ✅ Agente dedicado identifica padrões |
| **Breakpoints responsivos** | ❌ Frequentemente hardcoda um único viewport | ✅ Extrai todas as media queries |
| **Estados hover/animação** | ❌ Não pode ver, não pode reproduzir | ✅ Automação do navegador captura tudo |
| **Qualidade da saída** | ❌ Aproximação "perto o suficiente" | ✅ Pixel-perfect, pronto para produção |

> **O problema central**: Um JSON extraído de 200KB excede os limites práticos de contexto. Mesmo se couber, o modelo não consegue manter coerência através de DOM→CSS→Componentes→Código. Cada etapa precisa de atenção focada.

### Padrão Agent + Tools + Sandbox

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
│  │                  Ferramentas                     │   │
│  │  • Operações de Arquivo  • Análise de Código   │   │
│  │  • Controle do Navegador • Chamadas API        │   │
│  └─────────────────────────────────────────────────┘   │
│                         │                               │
│                         ▼                               │
│  ┌─────────────────────────────────────────────────┐   │
│  │              Sandbox (BoxLite)                   │   │
│  │  Ambiente de execução isolado para geração     │   │
│  │  de código segura, testes e preview            │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

Este padrão — **Agent + Tools + Sandbox** — é reutilizável para qualquer produto de agente de IA:

| Componente | Propósito | No Nexting |
|------------|-----------|------------|
| **Agentes** | Workers de IA especializados com responsabilidades focadas | Agentes DOM, Estilo, Componente, Código |
| **Ferramentas** | Capacidades que os agentes podem invocar | I/O de arquivos, Automação do navegador, Chamadas API |
| **Sandbox** | Ambiente de execução seguro | [BoxLite](https://github.com/boxlite-ai/boxlite) - Runtime de micro-VM embarcado |

### Conecte-se Comigo

Construindo algo com esta arquitetura? Tem perguntas? Entre em contato:

[![Twitter](https://img.shields.io/badge/Twitter-@ericshang98-1DA1F2?style=flat&logo=twitter)](https://twitter.com/ericshang98)
[![GitHub](https://img.shields.io/badge/GitHub-ericshang98-181717?style=flat&logo=github)](https://github.com/ericshang98)
[![Discord](https://img.shields.io/badge/Discord-Entrar_Comunidade-5865F2?style=flat&logo=discord&logoColor=white)](https://discord.gg/HJURzJq3y5)

---

## Início Rápido

### Pré-requisitos

- Python 3.11+
- Node.js 18+
- Anthropic API Key

### Início Rápido

1. **Clonar o repositório**

```bash
git clone https://github.com/ericshang98/perfect-web-clone.git
cd perfect-web-clone
```

2. **Configuração do Backend**

```bash
cd backend

# Copiar arquivo de ambiente e adicionar sua API key
cp ../.env.example .env
# Edite .env e adicione seu ANTHROPIC_API_KEY

# Iniciar o servidor (auto-instala dependências)
sh start.sh
```

3. **Configuração do Frontend**

```bash
cd frontend

# Instalar dependências
npm install

# Configurar ambiente (opcional)
cp ../.env.example .env.local

# Iniciar servidor de desenvolvimento
npm run dev
```

4. **Abrir a Aplicação**

Navegue para [http://localhost:3000](http://localhost:3000) no seu navegador.

## Licença

Este projeto está licenciado sob a Licença MIT - veja o arquivo [LICENSE](../../LICENSE) para detalhes.

---

<div align="center">

**[Nexting](https://github.com/ericshang98/perfect-web-clone)** - Extraia o código real, não suposições.

Feito com ❤️ por [Eric Shang](https://github.com/ericshang98)

</div>
