"use client";

import {
  Header,
  HeroWithInput,
  Features,
  ShowcasesGallery,
  Footer,
  QuantumScene,
  DemoVideo,
  ComparisonTable,
  AgentToolkit,
} from "@/components/landing";
import { Header as HeaderType, Section } from "@/types/landing";

// Header configuration matching reference project
const headerConfig: HeaderType = {
  id: "header",
  brand: {
    title: "", // Empty since SVG contains the text
    logo: {
      src: "/logo.svg",
      alt: "Nexting",
      width: 180,
      height: 48,
    },
    url: "/",
  },
  nav: {
    items: [
      {
        title: "Product",
        icon: "Package",
        children: [
          {
            title: "Full Page Clone",
            description: "Clone entire homepage with all sections",
            url: "/extractor",
            icon: "LayoutTemplate",
          },
          {
            title: "Section Clone",
            description: "Coming Soon · ⭐ Star us on GitHub",
            url: "https://github.com/ericshang98/Perfect-Web-Clone",
            target: "_blank",
            icon: "LayoutList",
            badge: "Soon",
          },
        ],
      },
      {
        title: "Step",
        icon: "ListOrdered",
        children: [
          {
            title: "Step 1: Extractor",
            description: "Extract webpage structure and styles",
            url: "/extractor",
            icon: "Globe",
          },
          {
            title: "Step 2: Agent",
            description: "AI-powered code generation",
            url: "/agent",
            icon: "Bot",
          },
        ],
      },
      {
        title: "About",
        url: "/about",
        icon: "User",
      },
      {
        title: "Docs",
        url: "https://perfectwebclone.com/docs",
        target: "_blank",
        icon: "BookOpenText",
      },
      {
        title: "GitHub",
        url: "https://github.com/ericshang98/Perfect-Web-Clone",
        target: "_blank",
        icon: "Github",
      },
    ],
  },
  buttons: [],
  user_nav: {
    show_name: true,
    show_credits: false,
    show_sign_out: true,
    items: [
      {
        title: "Settings",
        url: "/settings/profile",
        icon: "Settings",
      },
    ],
  },
  show_sign: true,
  show_theme: true,
  show_locale: false,
};

// Hero section configuration
const heroConfig: Section = {
  id: "hero",
  block: "hero-with-input",
  title: "Multi-Agent for Web Cloning",
  highlight_text: "Multi-Agent",
  description:
    "Not just a wrapper around an LLM. Multi-agent collaboration with real tools, self-correction loops, and a complete sandbox environment to build production-ready code from scratch.",
  announcement: {
    title: "Built with Claude Agent SDK →",
    url: "#architecture",
  },
  buttons: [],
};

// Page content configuration
const pageConfig = {
  comparison: {
    id: "comparison",
    label: "The Difference",
    title: "Screenshot Tools vs Code Extraction",
    description:
      "Most tools look at your page like a picture and guess the code. We read the actual source — that's why our output is production-ready, not a rough approximation.",
    image: {
      src: "/features/comparison.png",
      alt: "Comparison",
    },
    items: [
      {
        title: "Screenshot Tools",
        description:
          "AI interprets pixels → guesses layout → outputs approximation. Breaks on resize, loses interactions.",
        icon: "ImageOff",
      },
      {
        title: "Perfect Web Clone",
        description:
          "Extracts real DOM → analyzes CSS → preserves structure. Responsive, interactive, maintainable.",
        icon: "CheckCircle",
      },
      {
        title: "Their Output",
        description:
          "Hardcoded pixels, dead interactions, tangled code that needs complete rewrite.",
        icon: "X",
      },
      {
        title: "Our Output",
        description:
          "Clean components, flexible units, preserved animations, code you can actually ship.",
        icon: "Sparkles",
      },
    ],
  },

  solution: {
    id: "solution",
    title: "Why Multi-Agent Architecture?",
    description:
      "Traditional single-model approaches fail on complex pages. Our multi-agent system breaks down the problem — each agent specializes in one layer, then they collaborate to reconstruct the complete page from a single URL.",
    items: [
      {
        title: "DOM Structure Agent",
        description:
          "Handles massive, deeply nested DOM trees that would overwhelm a single model. Extracts semantic structure, hierarchy, and component boundaries piece by piece.",
        icon: "Layers",
      },
      {
        title: "Style Analysis Agent",
        description:
          "Processes thousands of CSS rules in parallel. Captures computed styles, CSS variables, breakpoints, and theme tokens without context limits.",
        icon: "Palette",
      },
      {
        title: "Component Detection Agent",
        description:
          "Analyzes patterns across the entire codebase. Identifies reusable components and outputs modular code — impossible with a single pass.",
        icon: "Code2",
      },
      {
        title: "Code Generation Agent",
        description:
          "Synthesizes outputs from all agents into production-ready code. Handles complex file structures that single models can't manage.",
        icon: "Zap",
      },
    ],
  },

  features: {
    id: "features",
    title: "What You Get",
    description: "Everything screenshot tools promise but can't deliver.",
    items: [
      {
        title: "Pixel-Perfect Accuracy",
        description:
          "We extract exact measurements, not approximations. Your clone matches the original down to the last pixel.",
        icon: "Layers",
      },
      {
        title: "Responsive by Default",
        description:
          "Breakpoints and flexible units are preserved. Your clone works on every screen size automatically.",
        icon: "Smartphone",
      },
      {
        title: "Living Interactions",
        description:
          "Hover effects, transitions, animations — all captured and regenerated. Your clone feels alive.",
        icon: "Zap",
      },
      {
        title: "Clean, Modular Code",
        description:
          "Component-based output with proper naming. Easy to read, easy to maintain, easy to extend.",
        icon: "Code2",
      },
      {
        title: "Multiple Frameworks",
        description:
          "Export to React, Next.js, Vue, or plain HTML. Use your preferred stack.",
        icon: "Layers",
      },
      {
        title: "Theme-Aware",
        description:
          "Dark mode, CSS variables, design tokens — all extracted and applied correctly.",
        icon: "Palette",
      },
    ],
  },

  showcase: {
    id: "showcase",
    label: "Gallery",
    title: "Community Clones",
    description:
      "See what others have built with Perfect Web Clone. Click any card to explore.",
    items: [
      // Featured: Did Global Cinema - checkpoint demo (click to run)
      {
        title: "Did Global Cinema",
        description: "Film production company website - Click to run live demo",
        source_url: "https://www.dg-cinema.com/en",
        image: { src: "/showcases/did-global-cinema/website.png", alt: "Did Global Cinema Clone" },
        chatImage: { src: "/showcases/did-global-cinema/chat.png", alt: "Did Global Cinema Chat" },
        checkpoint: {
          project_id: "did-global-cinema-aaf71f95",
          checkpoint_id: "cp_005",
        },
      },
      // Featured: Cake Equity - checkpoint demo (click to run)
      {
        title: "Cake Equity",
        description: "Cap table & equity management - Click to run live demo",
        source_url: "https://www.cakeequity.com",
        image: { src: "/showcases/cake-equity/website.png", alt: "Cake Equity Clone" },
        chatImage: { src: "/showcases/cake-equity/chat.png", alt: "Cake Equity Chat" },
        checkpoint: {
          project_id: "cake-equity-|-cap-table-and-eq-c18b9b37",
          checkpoint_id: "cp_002",
        },
      },
      // Featured: Team&Tonic - checkpoint demo (click to run)
      {
        title: "Team&Tonic",
        description: "Brand agency website - Click to run live demo",
        source_url: "https://www.teamandtonic.com",
        image: { src: "/showcases/team-and-tonic/website.png", alt: "Team&Tonic Clone" },
        chatImage: { src: "/showcases/team-and-tonic/chat.png", alt: "Team&Tonic Chat" },
        checkpoint: {
          project_id: "team&tonic-82630039",
          checkpoint_id: "cp_003",
        },
      },
    ],
    buttons: [{ title: "View All Clones →", url: "/showcases", variant: "outline" as const }],
  },

  footer: {
    brand: {
      name: "Nexting",
      logo: "/logo.svg",
      description:
        "Open source AI-powered web cloning tool. Extract, analyze, and clone any webpage with AI assistance.",
    },
    nav: [
      {
        title: "Tools",
        children: [
          { title: "Web Extractor", url: "/extractor" },
          { title: "Clone Agent", url: "/agent" },
        ],
      },
      {
        title: "Resources",
        children: [
          { title: "Documentation", url: "https://perfectwebclone.com/docs" },
          { title: "About", url: "/about" },
        ],
      },
      {
        title: "Links",
        children: [
          { title: "GitHub", url: "https://github.com/ericshang98/Perfect-Web-Clone" },
          { title: "Playwright", url: "https://playwright.dev" },
        ],
      },
    ],
    social: [
      { icon: "Github", url: "https://github.com/ericshang98/Perfect-Web-Clone", title: "GitHub" },
    ],
  },
};

export default function HomePage() {
  return (
    <main className="min-h-screen grid-background">
      <Header header={headerConfig} />

      {/* Hero section with 3D background */}
      <div className="relative min-h-screen overflow-hidden">
        {/* 3D背景 */}
        <QuantumScene />

        {/* 文字内容 - 在3D背景上方 */}
        <div className="relative z-10">
          <HeroWithInput section={heroConfig} />
        </div>
      </div>

      <ShowcasesGallery {...pageConfig.showcase} />

      {/* Demo Video - placed after Gallery */}
      <DemoVideo
        id="demo"
        videoSrc="/demo.mp4"
        label="Demo"
        title="See It In Action"
        description="Watch how Nexting extracts real code from any webpage and generates production-ready components."
        className="bg-muted"
      />

      {/* Comparison Table - vs Cursor/Claude Code/Copilot */}
      <ComparisonTable id="comparison" />

      {/* Agent Toolkit - 40+ Tools */}
      <AgentToolkit id="toolkit" className="bg-muted" />

      <Features {...pageConfig.solution} />

      <Features {...pageConfig.features} className="bg-muted" />

      <Footer {...pageConfig.footer} />
    </main>
  );
}
