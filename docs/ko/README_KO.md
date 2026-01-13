# Nexting

<div align="center">

**AI 기반 웹 클로닝 도구 — Claude Agent SDK로 구축**

*웹 클로닝을 위한 Claude Code. 40개 이상의 전문 도구를 갖춘 수직 AI 에이전트.*

[English](../../README.md) | [中文](../cn/README_CN.md) | [日本語](../ja/README_JA.md) | 한국어 | [Español](../es/README_ES.md) | [Português](../pt/README_PT.md) | [Deutsch](../de/README_DE.md) | [Français](../fr/README_FR.md) | [Tiếng Việt](../vi/README_VI.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Next.js](https://img.shields.io/badge/Next.js-15.x-black)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19.x-61dafb)](https://react.dev/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776ab)](https://python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)](https://fastapi.tiangolo.com/)
[![Playwright](https://img.shields.io/badge/Playwright-1.49+-2EAD33)](https://playwright.dev/)
[![Claude](https://img.shields.io/badge/Claude-Anthropic-cc785c)](https://anthropic.com/)

</div>

**진정한 AI 에이전트** — LLM의 단순한 래퍼가 아닙니다. 실제 도구, 자기 수정 루프, 그리고 처음부터 프로덕션 수준의 코드를 구축하는 완전한 샌드박스 환경을 갖춘 멀티 에이전트 협업.

다른 도구들은 스크린샷에서 코드를 추측합니다. 우리는 **실제 코드**를 추출합니다 — DOM, 스타일, 컴포넌트, 상호작용. 스크린샷 기반 도구로는 절대 달성할 수 없는 **픽셀 퍼펙트 클로닝**.

https://github.com/user-attachments/assets/248af639-20d9-45a8-ad0a-660a04a17b68

## 오픈소스 멀티 에이전트 아키텍처

**전체 멀티 에이전트 시스템이 오픈소스입니다.** 학습하고, 사용하고, 그 위에 구축하세요.

### 왜 멀티 에이전트인가?

전통적인 단일 모델 AI 접근 방식은 복잡한 작업에서 한계에 부딪힙니다. 하나의 모델이 모든 것을 처리하려고 하면:
- 대형 페이지에서 컨텍스트 윈도우 오버플로우
- 너무 많은 책임을 처리할 때 환각 현상
- 느린 순차 처리

우리의 솔루션: **전문화된 에이전트들이 병렬로 작업**, 각자가 가장 잘하는 것에 집중합니다.

### 왜 Cursor / Claude Code / Copilot을 쓰지 않나요?

<p align="center">
  <img src="https://img.shields.io/badge/Cursor-000000?style=for-the-badge&logo=cursor&logoColor=white" alt="Cursor" />
  <img src="https://img.shields.io/badge/Claude_Code-cc785c?style=for-the-badge&logo=anthropic&logoColor=white" alt="Claude Code" />
  <img src="https://img.shields.io/badge/GitHub_Copilot-000000?style=for-the-badge&logo=githubcopilot&logoColor=white" alt="GitHub Copilot" />
  <span style="margin: 0 10px;">vs</span>
  <img src="https://img.shields.io/badge/Nexting-8B5CF6?style=for-the-badge" alt="Nexting" />
</p>

우리도 시도해봤습니다. **완전한 추출 JSON** — 전체 DOM 트리, 모든 CSS 규칙, 모든 에셋 URL을 제공해도 단일 모델 도구는 어려움을 겪습니다:

| 도전 과제 | <img src="https://img.shields.io/badge/-Cursor-000?style=flat-square&logo=cursor" /> <img src="https://img.shields.io/badge/-Claude_Code-cc785c?style=flat-square&logo=anthropic" /> <img src="https://img.shields.io/badge/-Copilot-000?style=flat-square&logo=githubcopilot" /> | <img src="https://img.shields.io/badge/-Nexting-8B5CF6?style=flat-square" /> 멀티 에이전트 |
|-----------|-------------------------------|---------------------|
| **50,000+ 라인 DOM 트리** | ❌ 컨텍스트 오버플로우, 중요한 부분 잘림 | ✅ DOM 에이전트가 청크로 처리 |
| **3,000+ CSS 규칙** | ❌ 우선순위 손실, 변수 누락 | ✅ 스타일 에이전트가 CSS 별도 처리 |
| **컴포넌트 감지** | ❌ 경계 추측, 모놀리식 생성 | ✅ 전용 에이전트가 패턴 식별 |
| **반응형 브레이크포인트** | ❌ 단일 뷰포트 하드코딩 | ✅ 모든 미디어 쿼리 추출 |
| **호버/애니메이션 상태** | ❌ 볼 수 없음, 재현 불가 | ✅ 브라우저 자동화가 모두 캡처 |
| **출력 품질** | ❌ "대충 비슷한" 근사치 | ✅ 픽셀 퍼펙트, 프로덕션 준비 완료 |

> **핵심 문제**: 200KB 추출 JSON은 실질적인 컨텍스트 한계를 초과합니다. 들어간다 해도, 모델은 DOM→CSS→컴포넌트→코드 전체에서 일관성을 유지할 수 없습니다. 각 단계에 집중된 주의가 필요합니다.

### Agent + Tools + Sandbox 패턴

```
┌─────────────────────────────────────────────────────────┐
│                    멀티 에이전트 시스템                   │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │ DOM 에이전트│  │스타일 에이전트│  │코드 에이전트│     │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘     │
│         │                │                │             │
│         ▼                ▼                ▼             │
│  ┌─────────────────────────────────────────────────┐   │
│  │                    도구 레이어                   │   │
│  │  • 파일 작업  • 코드 분석                       │   │
│  │  • 브라우저 제어  • API 호출                    │   │
│  └─────────────────────────────────────────────────┘   │
│                         │                               │
│                         ▼                               │
│  ┌─────────────────────────────────────────────────┐   │
│  │              샌드박스 (BoxLite)                  │   │
│  │  안전한 코드 생성, 테스트 및 미리보기를 위한     │   │
│  │  격리된 실행 환경                               │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

이 패턴 — **Agent + Tools + Sandbox** — 은 모든 AI 에이전트 제품에 재사용 가능합니다:

| 컴포넌트 | 목적 | Nexting에서 |
|---------|------|------------|
| **에이전트** | 집중된 책임을 가진 전문 AI 워커 | DOM, 스타일, 컴포넌트, 코드 에이전트 |
| **도구** | 에이전트가 호출할 수 있는 기능 | 파일 I/O, 브라우저 자동화, API 호출 |
| **샌드박스** | 안전한 실행 환경 | [BoxLite](https://github.com/boxlite-ai/boxlite) - 임베디드 마이크로 VM 런타임 |

### 연락하기

이 아키텍처로 무언가를 구축하고 계신가요? 질문이 있으신가요? 연락해주세요:

[![Twitter](https://img.shields.io/badge/Twitter-@ericshang98-1DA1F2?style=flat&logo=twitter)](https://twitter.com/ericshang98)
[![GitHub](https://img.shields.io/badge/GitHub-ericshang98-181717?style=flat&logo=github)](https://github.com/ericshang98)
[![Discord](https://img.shields.io/badge/Discord-커뮤니티_참여-5865F2?style=flat&logo=discord&logoColor=white)](https://discord.gg/HJURzJq3y5)

---

## 빠른 시작

### 필수 조건

- Python 3.11+
- Node.js 18+
- Anthropic API Key

### 빠른 시작

1. **저장소 클론**

```bash
git clone https://github.com/ericshang98/perfect-web-clone.git
cd perfect-web-clone
```

2. **백엔드 설정**

```bash
cd backend

# 환경 파일 복사 및 API 키 추가
cp ../.env.example .env
# .env를 편집하고 ANTHROPIC_API_KEY 추가

# 서버 시작 (자동으로 의존성 설치)
sh start.sh
```

3. **프론트엔드 설정**

```bash
cd frontend

# 의존성 설치
npm install

# 환경 설정 (선택사항)
cp ../.env.example .env.local

# 개발 서버 시작
npm run dev
```

4. **애플리케이션 열기**

브라우저에서 [http://localhost:3000](http://localhost:3000)으로 이동합니다.

## 라이선스

이 프로젝트는 MIT 라이선스에 따라 라이선스가 부여됩니다 - 자세한 내용은 [LICENSE](../../LICENSE) 파일을 참조하세요.

---

<div align="center">

**[Nexting](https://github.com/ericshang98/perfect-web-clone)** - 추측이 아닌 실제 코드를 추출합니다.

[Eric Shang](https://github.com/ericshang98)이 ❤️로 만들었습니다

</div>
