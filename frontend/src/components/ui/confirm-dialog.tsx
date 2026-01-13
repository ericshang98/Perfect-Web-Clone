"use client";

import React from "react";
import { cn } from "@/lib/utils";
import { AlertTriangle, X } from "lucide-react";

interface ConfirmDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description: string;
  confirmText?: string;
  cancelText?: string;
  variant?: "default" | "warning" | "danger";
  isLoading?: boolean;
}

export function ConfirmDialog({
  isOpen,
  onClose,
  onConfirm,
  title,
  description,
  confirmText = "Confirm",
  cancelText = "Cancel",
  variant = "warning",
  isLoading = false,
}: ConfirmDialogProps) {
  if (!isOpen) return null;

  const variantStyles = {
    default: {
      icon: "bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400",
      confirm: "bg-blue-600 hover:bg-blue-700 text-white",
    },
    warning: {
      icon: "bg-amber-100 dark:bg-amber-900/40 text-amber-600 dark:text-amber-400",
      confirm: "bg-amber-600 hover:bg-amber-700 text-white",
    },
    danger: {
      icon: "bg-red-100 dark:bg-red-900/40 text-red-600 dark:text-red-400",
      confirm: "bg-red-600 hover:bg-red-700 text-white",
    },
  };

  const styles = variantStyles[variant];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Dialog */}
      <div
        className={cn(
          "relative z-10 w-full max-w-md mx-4",
          "bg-white dark:bg-neutral-800 rounded-2xl shadow-2xl",
          "border border-neutral-200 dark:border-neutral-700",
          "animate-in fade-in-0 zoom-in-95 duration-200"
        )}
      >
        {/* Close button */}
        <button
          onClick={onClose}
          className={cn(
            "absolute top-4 right-4 p-1.5 rounded-lg",
            "text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300",
            "hover:bg-neutral-100 dark:hover:bg-neutral-700",
            "transition-colors"
          )}
        >
          <X className="h-4 w-4" />
        </button>

        {/* Content */}
        <div className="p-6">
          {/* Icon */}
          <div className="flex justify-center mb-4">
            <div className={cn("p-3 rounded-full", styles.icon)}>
              <AlertTriangle className="h-6 w-6" />
            </div>
          </div>

          {/* Title */}
          <h3 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100 text-center mb-2">
            {title}
          </h3>

          {/* Description */}
          <p className="text-sm text-neutral-600 dark:text-neutral-400 text-center leading-relaxed">
            {description}
          </p>
        </div>

        {/* Actions */}
        <div className="flex gap-3 px-6 pb-6">
          <button
            onClick={onClose}
            disabled={isLoading}
            className={cn(
              "flex-1 px-4 py-2.5 rounded-xl text-sm font-medium",
              "bg-neutral-100 dark:bg-neutral-700",
              "text-neutral-700 dark:text-neutral-300",
              "hover:bg-neutral-200 dark:hover:bg-neutral-600",
              "transition-colors",
              "disabled:opacity-50 disabled:cursor-not-allowed"
            )}
          >
            {cancelText}
          </button>
          <button
            onClick={onConfirm}
            disabled={isLoading}
            className={cn(
              "flex-1 px-4 py-2.5 rounded-xl text-sm font-medium",
              styles.confirm,
              "transition-colors",
              "disabled:opacity-50 disabled:cursor-not-allowed",
              isLoading && "cursor-wait"
            )}
          >
            {isLoading ? (
              <span className="flex items-center justify-center gap-2">
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                    fill="none"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                  />
                </svg>
                Restoring...
              </span>
            ) : (
              confirmText
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
