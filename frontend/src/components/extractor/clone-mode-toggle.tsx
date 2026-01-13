/**
 * Clone Mode Toggle Component
 *
 * A toggle button for switching between Full Page and Section clone modes
 * Section mode is locked for future development
 */

"use client";

import React from "react";
import { Globe, LayoutPanelTop, Lock } from "lucide-react";
import { cn } from "@/lib/utils";

export type CloneMode = "full-page" | "section";

interface CloneModeToggleProps {
  /**
   * Current active clone mode
   */
  activeMode: CloneMode;

  /**
   * Callback when mode is changed
   */
  onModeChange: (mode: CloneMode) => void;

  /**
   * Whether the toggle is disabled
   */
  disabled?: boolean;

  /**
   * Additional CSS classes
   */
  className?: string;
}

export function CloneModeToggle({
  activeMode,
  onModeChange,
  disabled = false,
  className,
}: CloneModeToggleProps) {
  return (
    <div
      className={cn(
        "inline-flex items-center p-1 rounded-lg",
        "bg-neutral-100 dark:bg-neutral-700",
        "border border-neutral-200 dark:border-neutral-600",
        disabled && "opacity-50 cursor-not-allowed",
        className
      )}
    >
      {/* Full Page Mode Button */}
      <button
        onClick={() => onModeChange("full-page")}
        disabled={disabled}
        className={cn(
          "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium",
          "transition-all duration-200",
          activeMode === "full-page"
            ? "bg-white dark:bg-neutral-600 text-emerald-600 dark:text-emerald-400 shadow-sm"
            : "text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200"
        )}
        title="Clone entire page"
      >
        <Globe className="h-4 w-4" />
        <span>Full Page</span>
      </button>

      {/* Section Mode Button (Locked) */}
      <button
        disabled={true}
        className={cn(
          "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium",
          "transition-all duration-200",
          "text-neutral-400 dark:text-neutral-500 cursor-not-allowed",
          "opacity-60"
        )}
        title="Clone specific section (Coming soon)"
      >
        <LayoutPanelTop className="h-4 w-4" />
        <span>Section</span>
        <Lock className="h-3 w-3 ml-0.5" />
      </button>
    </div>
  );
}

export default CloneModeToggle;
