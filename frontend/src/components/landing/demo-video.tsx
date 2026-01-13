"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

interface DemoVideoProps {
  id?: string;
  label?: string;
  title?: string;
  description?: string;
  videoSrc: string;
  className?: string;
}

export function DemoVideo({
  id,
  label = "Demo",
  title = "See It In Action",
  description = "Watch how Nexting extracts real code from any webpage and generates production-ready components.",
  videoSrc,
  className,
}: DemoVideoProps) {
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
          <h2 className="text-foreground mb-4 text-3xl font-bold lg:text-4xl">
            {title}
          </h2>
          <p className="text-muted-foreground text-lg">
            {description}
          </p>
        </motion.div>

        <motion.div
          className="mx-auto max-w-5xl"
          initial={{ opacity: 0, scale: 0.95 }}
          whileInView={{ opacity: 1, scale: 1 }}
          viewport={{ once: true }}
          transition={{ duration: 0.5, delay: 0.2 }}
        >
          <div className="relative overflow-hidden rounded-xl border bg-card shadow-2xl">
            {/* Browser-like header */}
            <div className="flex items-center gap-2 border-b bg-muted/50 px-4 py-3">
              <div className="flex gap-1.5">
                <div className="h-3 w-3 rounded-full bg-red-500/80" />
                <div className="h-3 w-3 rounded-full bg-yellow-500/80" />
                <div className="h-3 w-3 rounded-full bg-green-500/80" />
              </div>
              <div className="ml-4 flex-1">
                <div className="mx-auto max-w-md rounded-md bg-background/50 px-3 py-1 text-center text-xs text-muted-foreground">
                  nexting.dev
                </div>
              </div>
            </div>

            {/* Video */}
            <video
              src={videoSrc}
              autoPlay
              loop
              muted
              playsInline
              className="w-full"
            />
          </div>
        </motion.div>
      </div>
    </section>
  );
}
