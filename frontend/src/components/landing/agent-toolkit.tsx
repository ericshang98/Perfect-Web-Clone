"use client";

import { motion } from "framer-motion";
import {
  FileCode,
  Search,
  ListTodo,
  Terminal,
  Globe,
  MonitorPlay,
  Eye,
  Stethoscope,
  RefreshCw,
  Database,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface AgentToolkitProps {
  id?: string;
  className?: string;
}

const toolCategories = [
  {
    category: "File Operations",
    icon: FileCode,
    color: "text-blue-500",
    bgColor: "bg-blue-500/10",
    tools: ["read_file", "write_file", "edit_file", "delete_file", "rename_file", "create_directory"],
    purpose: "CRUD operations on project files",
  },
  {
    category: "Search & Discovery",
    icon: Search,
    color: "text-green-500",
    bgColor: "bg-green-500/10",
    tools: ["glob", "grep", "ls", "search_in_file", "search_in_project"],
    purpose: "Find files and content (ripgrep-powered)",
  },
  {
    category: "Task Management",
    icon: ListTodo,
    color: "text-yellow-500",
    bgColor: "bg-yellow-500/10",
    tools: ["todo_read", "todo_write", "task", "get_subagent_status"],
    purpose: "Track progress, spawn sub-agents",
  },
  {
    category: "System Execution",
    icon: Terminal,
    color: "text-orange-500",
    bgColor: "bg-orange-500/10",
    tools: ["bash", "run_command", "shell"],
    purpose: "Run any command in sandbox",
  },
  {
    category: "Network",
    icon: Globe,
    color: "text-cyan-500",
    bgColor: "bg-cyan-500/10",
    tools: ["web_fetch", "web_search"],
    purpose: "Fetch URLs, search the web",
  },
  {
    category: "Terminal",
    icon: MonitorPlay,
    color: "text-pink-500",
    bgColor: "bg-pink-500/10",
    tools: ["create_terminal", "send_terminal_input", "get_terminal_output", "install_dependencies", "start_dev_server"],
    purpose: "Manage multiple terminal sessions",
  },
  {
    category: "Preview",
    icon: Eye,
    color: "text-indigo-500",
    bgColor: "bg-indigo-500/10",
    tools: ["take_screenshot", "get_console_messages", "get_preview_dom", "get_preview_status"],
    purpose: "Inspect live preview state",
  },
  {
    category: "Diagnostics",
    icon: Stethoscope,
    color: "text-red-500",
    bgColor: "bg-red-500/10",
    tools: ["verify_changes", "diagnose_preview_state", "analyze_build_error", "get_comprehensive_error_snapshot"],
    purpose: "Debug and validate",
  },
  {
    category: "Self-Healing",
    icon: RefreshCw,
    color: "text-emerald-500",
    bgColor: "bg-emerald-500/10",
    tools: ["start_healing_loop", "verify_healing_progress", "stop_healing_loop"],
    purpose: "Auto-fix build errors",
  },
  {
    category: "Source Query",
    icon: Database,
    color: "text-violet-500",
    bgColor: "bg-violet-500/10",
    tools: ["list_saved_sources", "get_source_overview", "query_source_json"],
    purpose: "Query extracted website data",
  },
];

export function AgentToolkit({ id, className }: AgentToolkitProps) {
  const totalTools = toolCategories.reduce((acc, cat) => acc + cat.tools.length, 0);

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
            Built on Claude Agent SDK
          </span>
          <h2 className="text-foreground mb-4 text-3xl font-bold lg:text-4xl">
            Agent Toolkit
          </h2>
          <p className="text-muted-foreground mx-auto max-w-2xl text-lg">
            <strong>{totalTools}+ Tools</strong> across {toolCategories.length} categories.
            This isn&apos;t a chatbot with API calls; it&apos;s a <strong>real agent</strong> that
            thinks, plans, executes, and self-corrects in an isolated sandbox.
          </p>
        </motion.div>

        {/* Tool Categories Grid */}
        <div className="mx-auto max-w-6xl grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {toolCategories.map((category, index) => (
            <motion.div
              key={category.category}
              className="group rounded-xl border bg-card p-4 shadow-sm hover:shadow-md hover:border-primary/50 transition-all"
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.3, delay: index * 0.05 }}
            >
              <div className={cn("inline-flex rounded-lg p-2 mb-3", category.bgColor)}>
                <category.icon className={cn("h-5 w-5", category.color)} />
              </div>
              <h3 className="mb-1 font-semibold text-foreground text-sm">
                {category.category}
              </h3>
              <p className="mb-3 text-xs text-muted-foreground">
                {category.purpose}
              </p>
              <div className="flex flex-wrap gap-1">
                {category.tools.slice(0, 3).map((tool) => (
                  <span
                    key={tool}
                    className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground"
                  >
                    {tool}
                  </span>
                ))}
                {category.tools.length > 3 && (
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                    +{category.tools.length - 3}
                  </span>
                )}
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
