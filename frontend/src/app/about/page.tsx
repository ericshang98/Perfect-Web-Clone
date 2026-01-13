"use client";

import Link from "next/link";
import { Github, MessageCircle, ArrowLeft, ExternalLink, Globe, Mail } from "lucide-react";
import { Header, Footer } from "@/components/landing";
import { Button } from "@/components/ui/button";

const headerConfig = {
  id: "header",
  brand: {
    title: "",
    logo: { src: "/logo.svg", alt: "Nexting", width: 180, height: 48 },
    url: "/",
  },
  nav: { items: [] },
  buttons: [],
  show_sign: false,
  show_theme: true,
  show_locale: false,
};

const footerConfig = {
  brand: {
    name: "Nexting",
    logo: "/logo.svg",
    description: "Open source AI-powered web cloning tool.",
  },
  nav: [
    {
      title: "Links",
      children: [
        { title: "GitHub", url: "https://github.com/ericshang98/Perfect-Web-Clone" },
        { title: "Documentation", url: "https://perfectwebclone.com/docs" },
      ],
    },
  ],
  social: [
    { icon: "Github", url: "https://github.com/ericshang98/Perfect-Web-Clone", title: "GitHub" },
  ],
};

export default function AboutPage() {
  return (
    <main className="min-h-screen bg-background">
      <Header header={headerConfig} />

      <div className="container max-w-4xl py-24 px-4">
        {/* Back link */}
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground mb-12 transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to Home
        </Link>

        {/* Page Title */}
        <h1 className="text-4xl font-bold text-foreground mb-4">About</h1>
        <p className="text-lg text-muted-foreground mb-16">
          The people and vision behind Nexting.
        </p>

        {/* Creator Section */}
        <section className="mb-20">
          <div className="flex items-center gap-2 text-muted-foreground/70 text-sm uppercase tracking-widest font-medium mb-6">
            <span className="inline-block w-5 h-px bg-foreground/30" />
            Creator
          </div>

          <div className="flex flex-col md:flex-row gap-8 items-start">
            {/* Avatar */}
            <img
              src="/eric-photo.png"
              alt="Eric Shang"
              className="w-24 h-24 rounded-full object-cover shrink-0"
            />

            <div className="flex-1">
              <h2 className="text-2xl font-semibold text-foreground mb-2">Eric Shang</h2>
              <p className="text-muted-foreground mb-4">
                Builder, developer, and creator of Nexting. Passionate about AI agents,
                developer tools, and helping indie hackers ship faster.
              </p>

              {/* Social Links */}
              <div className="flex flex-wrap gap-3">
                <Link
                  href="https://ericshang.com"
                  target="_blank"
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-muted/50 border border-border/50 text-sm hover:bg-muted hover:border-border transition-all"
                >
                  <Globe className="h-4 w-4" />
                  ericshang.com
                </Link>
                <Link
                  href="https://github.com/ericshang98"
                  target="_blank"
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-muted/50 border border-border/50 text-sm hover:bg-muted hover:border-border transition-all"
                >
                  <Github className="h-4 w-4" />
                  GitHub
                </Link>
                <Link
                  href="https://discord.gg/HJURzJq3y5"
                  target="_blank"
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-muted/50 border border-border/50 text-sm hover:bg-muted hover:border-border transition-all"
                >
                  <MessageCircle className="h-4 w-4" />
                  Discord
                </Link>
                <Link
                  href="https://www.xiaohongshu.com/user/profile/68818c5d000000001d00acf1"
                  target="_blank"
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-muted/50 border border-border/50 text-sm hover:bg-muted hover:border-border transition-all"
                >
                  <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm-1-13h2v6h-2zm0 8h2v2h-2z"/>
                  </svg>
                  小红书
                </Link>
                <Link
                  href="mailto:shangyiyong@outlook.com"
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-muted/50 border border-border/50 text-sm hover:bg-muted hover:border-border transition-all"
                >
                  <Mail className="h-4 w-4" />
                  Email
                </Link>
              </div>
            </div>
          </div>
        </section>

        {/* Vision Section */}
        <section className="mb-20">
          <div className="flex items-center gap-2 text-muted-foreground/70 text-sm uppercase tracking-widest font-medium mb-6">
            <span className="inline-block w-5 h-px bg-foreground/30" />
            Vision
          </div>

          <div className="space-y-6 text-muted-foreground leading-relaxed">
            <p>
              <strong className="text-foreground">Nexting exists for two reasons:</strong>
            </p>

            <div className="pl-6 border-l-2 border-border space-y-4">
              <p>
                <strong className="text-foreground">1. Help builders ship landing pages 100x faster.</strong><br />
                See a landing page you love? Clone it pixel-perfect in minutes, not days.
                Built for indie hackers and teams going global — your landing page shouldn&apos;t slow you down.
              </p>

              <p>
                <strong className="text-foreground">2. Provide a stable, open-source multi-agent foundation.</strong><br />
                40+ battle-tested tools. Isolated sandbox. Reproducible workflows.
                A foundation you can trust — no surprises, no breaking changes.
                Build your own AI agents on top of it.
              </p>
            </div>

            <p>
              Most AI cloning tools look at your page like a picture and guess the code.
              We extract the <strong className="text-foreground">real DOM, real CSS, real structure</strong>.
              That&apos;s why our output is production-ready, not a rough approximation.
            </p>
          </div>
        </section>

        {/* Open Source Section */}
        <section className="mb-20">
          <div className="flex items-center gap-2 text-muted-foreground/70 text-sm uppercase tracking-widest font-medium mb-6">
            <span className="inline-block w-5 h-px bg-foreground/30" />
            Open Source
          </div>

          <p className="text-muted-foreground mb-6">
            The entire multi-agent system is open source. Learn from it, use it, build upon it.
          </p>

          <div className="flex flex-wrap gap-4">
            <Button asChild variant="outline" size="lg">
              <Link
                href="https://github.com/ericshang98/Perfect-Web-Clone"
                target="_blank"
                className="gap-2"
              >
                <Github className="h-5 w-5" />
                View on GitHub
                <ExternalLink className="h-4 w-4 opacity-50" />
              </Link>
            </Button>
            <Button asChild variant="default" size="lg">
              <Link href="/" className="gap-2">
                Try Nexting
              </Link>
            </Button>
          </div>
        </section>

        {/* Contact */}
        <section>
          <div className="flex items-center gap-2 text-muted-foreground/70 text-sm uppercase tracking-widest font-medium mb-6">
            <span className="inline-block w-5 h-px bg-foreground/30" />
            Get in Touch
          </div>

          <p className="text-muted-foreground">
            Building something with this architecture? Have questions?{" "}
            <Link
              href="https://twitter.com/ericshang98"
              target="_blank"
              className="text-foreground hover:underline"
            >
              Reach out on Twitter
            </Link>{" "}
            or{" "}
            <Link
              href="https://discord.gg/HJURzJq3y5"
              target="_blank"
              className="text-foreground hover:underline"
            >
              join the Discord community
            </Link>
            .
          </p>
        </section>
      </div>

      <Footer {...footerConfig} />
    </main>
  );
}
