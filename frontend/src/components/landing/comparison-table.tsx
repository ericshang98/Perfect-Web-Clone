"use client";

import { motion } from "framer-motion";
import { Check, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface ComparisonTableProps {
  id?: string;
  className?: string;
}

const comparisonData = [
  {
    challenge: "50,000+ line DOM tree",
    others: "Context overflow, truncates critical parts",
    nexting: "DOM Agent processes in chunks",
    othersWorks: false,
    nextingWorks: true,
  },
  {
    challenge: "3,000+ CSS rules",
    others: "Loses specificity, misses variables",
    nexting: "Style Agent handles CSS separately",
    othersWorks: false,
    nextingWorks: true,
  },
  {
    challenge: "Component detection",
    others: "Guesses boundaries, creates monoliths",
    nexting: "Dedicated agent identifies patterns",
    othersWorks: false,
    nextingWorks: true,
  },
  {
    challenge: "Responsive breakpoints",
    others: "Often hardcodes single viewport",
    nexting: "Extracts all media queries",
    othersWorks: false,
    nextingWorks: true,
  },
  {
    challenge: "Hover/animation states",
    others: "Cannot see, cannot reproduce",
    nexting: "Browser automation captures all",
    othersWorks: false,
    nextingWorks: true,
  },
  {
    challenge: "Output quality",
    others: '"Close enough" approximation',
    nexting: "Pixel-perfect, production-ready",
    othersWorks: false,
    nextingWorks: true,
  },
];

const brandBadges = [
  { name: "Cursor", color: "bg-zinc-800" },
  { name: "Claude Code", color: "bg-[#cc785c]" },
  { name: "Copilot", color: "bg-zinc-800" },
];

export function ComparisonTable({ id, className }: ComparisonTableProps) {
  return (
    <section id={id} className={cn("py-16 md:py-24", className)}>
      <div className="container">
        <motion.div
          className="mb-10 text-center"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
        >
          <span className="text-primary mb-2 block text-sm font-medium uppercase tracking-wider">
            The Difference
          </span>
          <h2 className="text-foreground mb-4 text-3xl font-bold lg:text-4xl">
            Why Not Just Use Cursor / Claude Code / Copilot?
          </h2>
          <p className="text-muted-foreground mx-auto max-w-3xl text-lg">
            We tried. Even with the <strong>complete extracted JSON</strong> — full DOM tree,
            all CSS rules, every asset URL — single-model tools struggle.
          </p>

          {/* Brand badges */}
          <div className="mt-6 flex items-center justify-center gap-3 flex-wrap">
            {brandBadges.map((badge) => (
              <span
                key={badge.name}
                className={cn(
                  "px-3 py-1 rounded text-xs font-medium text-white",
                  badge.color
                )}
              >
                {badge.name}
              </span>
            ))}
            <span className="text-muted-foreground mx-2">vs</span>
            <span className="px-3 py-1 rounded text-xs font-medium text-white bg-purple-600">
              Nexting
            </span>
          </div>
        </motion.div>

        {/* Comparison Table */}
        <motion.div
          className="mx-auto max-w-5xl overflow-hidden rounded-xl border bg-card shadow-lg"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, delay: 0.2 }}
        >
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="px-6 py-4 text-left text-sm font-semibold text-foreground">
                    Challenge
                  </th>
                  <th className="px-6 py-4 text-left text-sm font-semibold text-foreground">
                    <div className="flex items-center gap-2">
                      <span className="text-zinc-500">Single-Model Tools</span>
                    </div>
                  </th>
                  <th className="px-6 py-4 text-left text-sm font-semibold text-foreground">
                    <div className="flex items-center gap-2">
                      <span className="text-purple-600">Nexting Multi-Agent</span>
                    </div>
                  </th>
                </tr>
              </thead>
              <tbody>
                {comparisonData.map((row, index) => (
                  <motion.tr
                    key={index}
                    className="border-b last:border-0 hover:bg-muted/30 transition-colors"
                    initial={{ opacity: 0, x: -20 }}
                    whileInView={{ opacity: 1, x: 0 }}
                    viewport={{ once: true }}
                    transition={{ duration: 0.3, delay: index * 0.05 }}
                  >
                    <td className="px-6 py-4 text-sm font-medium text-foreground">
                      {row.challenge}
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-start gap-2">
                        <X className="h-5 w-5 text-red-500 shrink-0 mt-0.5" />
                        <span className="text-sm text-muted-foreground">
                          {row.others}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-start gap-2">
                        <Check className="h-5 w-5 text-green-500 shrink-0 mt-0.5" />
                        <span className="text-sm text-foreground">
                          {row.nexting}
                        </span>
                      </div>
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        </motion.div>

        {/* Core problem callout */}
        <motion.div
          className="mx-auto mt-8 max-w-3xl rounded-lg border-l-4 border-primary bg-muted/50 p-4"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, delay: 0.4 }}
        >
          <p className="text-sm text-muted-foreground">
            <strong className="text-foreground">The core problem:</strong> A 200KB extracted JSON
            exceeds practical context limits. Even if it fits, the model can&apos;t maintain coherence
            across DOM→CSS→Components→Code. Each step needs focused attention.
          </p>
        </motion.div>
      </div>
    </section>
  );
}
