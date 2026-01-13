"use client";

import { motion } from "framer-motion";
import { Box, Code, FileCode, Layers, Search, Terminal, Eye, Wrench, Cpu, Database } from "lucide-react";
import { cn } from "@/lib/utils";

interface ArchitectureProps {
  id?: string;
  className?: string;
}

const agentLayers = [
  { name: "Planner", color: "bg-blue-500" },
  { name: "Coder", color: "bg-green-500" },
  { name: "Debugger", color: "bg-orange-500" },
  { name: "Verifier", color: "bg-purple-500" },
];

const components = [
  {
    title: "Agents",
    description: "Specialized AI workers with focused responsibilities",
    example: "DOM, Style, Component, Code agents",
    icon: Cpu,
    color: "text-blue-500",
  },
  {
    title: "Tools",
    description: "Capabilities agents can invoke",
    example: "File I/O, Browser automation, API calls",
    icon: Wrench,
    color: "text-green-500",
  },
  {
    title: "Sandbox",
    description: "Safe execution environment",
    example: "BoxLite - Embedded micro-VM runtime",
    icon: Box,
    color: "text-purple-500",
  },
];

export function Architecture({ id, className }: ArchitectureProps) {
  return (
    <section id={id} className={cn("py-16 md:py-24", className)}>
      <div className="container">
        <motion.div
          className="mb-12 text-center"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5 }}
        >
          <span className="text-primary mb-2 block text-sm font-medium uppercase tracking-wider">
            Open Source
          </span>
          <h2 className="text-foreground mb-4 text-3xl font-bold lg:text-4xl">
            Multi-Agent Architecture
          </h2>
          <p className="text-muted-foreground mx-auto max-w-2xl text-lg">
            <strong>This entire multi-agent system is open source.</strong> Learn from it, use it, build upon it.
          </p>
        </motion.div>

        {/* Architecture Diagram */}
        <motion.div
          className="mx-auto max-w-4xl"
          initial={{ opacity: 0, scale: 0.95 }}
          whileInView={{ opacity: 1, scale: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, delay: 0.2 }}
        >
          <div className="overflow-hidden rounded-xl border bg-card shadow-lg">
            {/* Header */}
            <div className="border-b bg-muted/50 px-6 py-4">
              <div className="flex items-center gap-2">
                <Code className="h-5 w-5 text-primary" />
                <span className="font-semibold text-foreground">Claude Agent SDK</span>
              </div>
            </div>

            <div className="p-6">
              {/* Nexting Agent Container */}
              <div className="rounded-lg border-2 border-dashed border-primary/30 bg-muted/30 p-6">
                <div className="mb-4 text-center text-sm font-medium text-muted-foreground">
                  Nexting Agent
                </div>

                {/* Agent Layer */}
                <div className="mb-6 flex flex-wrap justify-center gap-3">
                  {agentLayers.map((agent, index) => (
                    <motion.div
                      key={agent.name}
                      className={cn(
                        "rounded-lg px-4 py-2 text-sm font-medium text-white shadow-md",
                        agent.color
                      )}
                      initial={{ opacity: 0, y: -20 }}
                      whileInView={{ opacity: 1, y: 0 }}
                      viewport={{ once: true }}
                      transition={{ duration: 0.3, delay: 0.3 + index * 0.1 }}
                    >
                      {agent.name}
                    </motion.div>
                  ))}
                </div>

                {/* Arrow down */}
                <div className="my-4 flex justify-center">
                  <div className="h-8 w-0.5 bg-muted-foreground/30" />
                </div>

                {/* Tools Layer */}
                <motion.div
                  className="mb-6 rounded-lg border bg-background p-4"
                  initial={{ opacity: 0, y: 20 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.3, delay: 0.5 }}
                >
                  <div className="mb-3 text-center text-sm font-medium text-foreground">
                    40+ Specialized Tools
                  </div>
                  <div className="flex flex-wrap justify-center gap-2 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1 rounded bg-muted px-2 py-1">
                      <FileCode className="h-3 w-3" /> File Operations
                    </span>
                    <span className="flex items-center gap-1 rounded bg-muted px-2 py-1">
                      <Search className="h-3 w-3" /> Code Analysis
                    </span>
                    <span className="flex items-center gap-1 rounded bg-muted px-2 py-1">
                      <Terminal className="h-3 w-3" /> Browser Control
                    </span>
                    <span className="flex items-center gap-1 rounded bg-muted px-2 py-1">
                      <Database className="h-3 w-3" /> API Calls
                    </span>
                  </div>
                </motion.div>

                {/* Arrow down */}
                <div className="my-4 flex justify-center">
                  <div className="h-8 w-0.5 bg-muted-foreground/30" />
                </div>

                {/* Sandbox Layer */}
                <motion.div
                  className="rounded-lg border-2 border-purple-500/30 bg-purple-500/5 p-4"
                  initial={{ opacity: 0, y: 20 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.3, delay: 0.6 }}
                >
                  <div className="flex items-center justify-center gap-2">
                    <Box className="h-5 w-5 text-purple-500" />
                    <span className="font-medium text-foreground">BoxLite Sandbox (Micro-VM)</span>
                  </div>
                  <p className="mt-2 text-center text-xs text-muted-foreground">
                    Isolated environment for code execution & preview
                  </p>
                </motion.div>
              </div>
            </div>
          </div>
        </motion.div>

        {/* Component Grid */}
        <div className="mx-auto mt-12 grid max-w-4xl gap-6 md:grid-cols-3">
          {components.map((component, index) => (
            <motion.div
              key={component.title}
              className="rounded-xl border bg-card p-6 shadow-sm hover:shadow-md transition-shadow"
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.3, delay: 0.7 + index * 0.1 }}
            >
              <component.icon className={cn("h-8 w-8 mb-3", component.color)} />
              <h3 className="mb-2 font-semibold text-foreground">{component.title}</h3>
              <p className="mb-2 text-sm text-muted-foreground">{component.description}</p>
              <p className="text-xs text-primary">{component.example}</p>
            </motion.div>
          ))}
        </div>

        {/* What makes this different */}
        <motion.div
          className="mx-auto mt-12 max-w-3xl rounded-xl border bg-muted/50 p-6"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, delay: 0.9 }}
        >
          <h3 className="mb-4 text-center font-semibold text-foreground">
            What makes this different from ChatGPT/Claude chat?
          </h3>
          <div className="grid gap-3 text-sm sm:grid-cols-2">
            <div className="flex items-start gap-2">
              <Layers className="h-4 w-4 text-primary shrink-0 mt-0.5" />
              <span className="text-muted-foreground">
                <strong className="text-foreground">Persistent state:</strong> Agent remembers context across the entire session
              </span>
            </div>
            <div className="flex items-start gap-2">
              <Terminal className="h-4 w-4 text-primary shrink-0 mt-0.5" />
              <span className="text-muted-foreground">
                <strong className="text-foreground">Tool chaining:</strong> Can execute 10+ tools in sequence without human intervention
              </span>
            </div>
            <div className="flex items-start gap-2">
              <Wrench className="h-4 w-4 text-primary shrink-0 mt-0.5" />
              <span className="text-muted-foreground">
                <strong className="text-foreground">Self-correction:</strong> Detects errors, diagnoses root cause, fixes automatically
              </span>
            </div>
            <div className="flex items-start gap-2">
              <Eye className="h-4 w-4 text-primary shrink-0 mt-0.5" />
              <span className="text-muted-foreground">
                <strong className="text-foreground">Live preview:</strong> Sees actual rendered output, not just code
              </span>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
