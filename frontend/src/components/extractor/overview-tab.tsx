"use client";

import React from "react";
import {
  Globe,
  Clock,
  Layers,
  Box,
  FileCode,
  Image as ImageIcon,
  Layout,
  RefreshCw,
  ArrowUpRight,
  Lightbulb,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { PageMetadata, PageAssets } from "@/types/playwright";
import { formatLoadTime, getDomain } from "@/lib/api/playwright";

/**
 * Overview Tab Props
 */
interface OverviewTabProps {
  metadata: PageMetadata | null;
  screenshot: string | null;
  fullPageScreenshot?: string | null;  // 新增：完整页面截图
  assets: PageAssets | null;
}

/**
 * Stat Card Component
 * 统计卡片组件
 */
function StatCard({
  icon: Icon,
  label,
  value,
  subValue,
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  subValue?: string;
}) {
  return (
    <div
      className={cn(
        "p-3 rounded-lg border",
        "bg-neutral-50 dark:bg-neutral-800/50",
        "border-neutral-200 dark:border-neutral-700"
      )}
    >
      <div className="flex items-center gap-2.5">
        <div
          className={cn(
            "p-1.5 rounded-md",
            "bg-blue-100 dark:bg-blue-900/30",
            "text-blue-600 dark:text-blue-400"
          )}
        >
          <Icon className="h-4 w-4" />
        </div>
        <div>
          <p className="text-xs text-neutral-500 dark:text-neutral-400">{label}</p>
          <p className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">
            {value}
            {subValue && (
              <span className="text-[10px] font-normal text-neutral-400 dark:text-neutral-500 ml-1">
                {subValue}
              </span>
            )}
          </p>
        </div>
      </div>
    </div>
  );
}

/**
 * Overview Tab Component
 * 概览 Tab 组件
 *
 * 布局：
 * - 左侧：Screenshot Preview（独占左侧）
 * - 右侧上：Stats Grid
 * - 右侧中：Viewport
 * - 右侧下：Assets Summary
 */
export function OverviewTab({ metadata, screenshot, fullPageScreenshot, assets }: OverviewTabProps) {
  if (!metadata) {
    return (
      <div className="flex items-center justify-center h-64 text-neutral-500">
        No data available
      </div>
    );
  }

  // 优先使用完整页面截图，如果没有则使用 viewport 截图
  const displayScreenshot = fullPageScreenshot || screenshot;

  return (
    <div className="space-y-6">
      {/* Page Info Header */}
      <div
        className={cn(
          "p-4 rounded-lg border",
          "bg-white dark:bg-neutral-900",
          "border-neutral-200 dark:border-neutral-700"
        )}
      >
        <div className="flex items-center gap-3 mb-2">
          <Globe className="h-5 w-5 text-blue-500" />
          <h3 className="font-semibold text-neutral-900 dark:text-neutral-100">
            {metadata.title || "Untitled Page"}
          </h3>
        </div>
        <p className="text-sm text-neutral-500 dark:text-neutral-400 break-all">
          {metadata.url}
        </p>
        <p className="text-xs text-neutral-400 dark:text-neutral-500 mt-1">
          Domain: {getDomain(metadata.url)}
        </p>
      </div>

      {/* Main Content - 左右布局 (左侧截图占更大空间) */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] xl:grid-cols-[1fr_320px] gap-4">
        {/* 左侧：Screenshot Preview（独占左侧整个高度） */}
        <div
          className={cn(
            "rounded-lg border overflow-hidden lg:row-span-3",
            "bg-white dark:bg-neutral-900",
            "border-neutral-200 dark:border-neutral-700"
          )}
        >
          <div className="p-3 border-b border-neutral-200 dark:border-neutral-700 flex items-center justify-between">
            <h4 className="text-sm font-medium text-neutral-700 dark:text-neutral-300">
              {fullPageScreenshot ? "Full Page Screenshot" : "Screenshot Preview"}
            </h4>
            {fullPageScreenshot && (
              <span className="text-xs text-green-600 dark:text-green-400 font-medium">
                Complete
              </span>
            )}
          </div>
          {displayScreenshot ? (
            <div className="p-2 max-h-[600px] overflow-y-auto">
              <img
                src={`data:image/png;base64,${displayScreenshot}`}
                alt="Page Screenshot"
                className="w-full h-auto rounded border border-neutral-200 dark:border-neutral-700"
              />
            </div>
          ) : (
            <div className="flex items-center justify-center h-48 text-neutral-400">
              <ImageIcon className="h-8 w-8 mr-2" />
              No screenshot available
            </div>
          )}
        </div>

        {/* 右侧上：Stats Grid - 2x2 紧凑布局 */}
        <div className="grid grid-cols-2 gap-2">
          <StatCard
            icon={Layers}
            label="Total Elements"
            value={metadata.total_elements.toLocaleString()}
          />
          <StatCard
            icon={Box}
            label="DOM Depth"
            value={metadata.max_depth}
            subValue="levels"
          />
          <StatCard
            icon={Clock}
            label="Load Time"
            value={formatLoadTime(metadata.load_time_ms)}
          />
          <StatCard
            icon={FileCode}
            label="Page Size"
            value={`${metadata.page_width}×${metadata.page_height}`}
            subValue="pixels"
          />
        </div>

        {/* 右侧中：Viewport - 紧凑版 */}
        <div
          className={cn(
            "p-3 rounded-lg border",
            "bg-white dark:bg-neutral-900",
            "border-neutral-200 dark:border-neutral-700"
          )}
        >
          <h4 className="text-xs font-medium text-neutral-500 dark:text-neutral-400 mb-2">
            Viewport
          </h4>
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold text-neutral-900 dark:text-neutral-100">
              {metadata.viewport_width}
            </span>
            <span className="text-neutral-400 text-sm">×</span>
            <span className="text-lg font-bold text-neutral-900 dark:text-neutral-100">
              {metadata.viewport_height}
            </span>
            <span className="text-xs text-neutral-400 ml-1">px</span>
          </div>
        </div>

        {/* 右侧下：Assets Summary - 紧凑版 */}
        {assets && (
          <div
            className={cn(
              "p-3 rounded-lg border",
              "bg-white dark:bg-neutral-900",
              "border-neutral-200 dark:border-neutral-700"
            )}
          >
            <h4 className="text-xs font-medium text-neutral-500 dark:text-neutral-400 mb-2">
              Assets Summary
            </h4>
            <div className="grid grid-cols-4 gap-1">
              <div className="text-center p-1.5 rounded bg-neutral-50 dark:bg-neutral-800">
                <p className="text-sm font-bold text-blue-600 dark:text-blue-400">
                  {assets.total_images}
                </p>
                <p className="text-[9px] text-neutral-500">Images</p>
              </div>
              <div className="text-center p-1.5 rounded bg-neutral-50 dark:bg-neutral-800">
                <p className="text-sm font-bold text-yellow-600 dark:text-yellow-400">
                  {assets.total_scripts}
                </p>
                <p className="text-[9px] text-neutral-500">Scripts</p>
              </div>
              <div className="text-center p-1.5 rounded bg-neutral-50 dark:bg-neutral-800">
                <p className="text-sm font-bold text-green-600 dark:text-green-400">
                  {assets.total_stylesheets}
                </p>
                <p className="text-[9px] text-neutral-500">Styles</p>
              </div>
              <div className="text-center p-1.5 rounded bg-neutral-50 dark:bg-neutral-800">
                <p className="text-sm font-bold text-cyan-600 dark:text-cyan-400">
                  {assets.total_fonts}
                </p>
                <p className="text-[9px] text-neutral-500">Fonts</p>
              </div>
            </div>
          </div>
        )}

        {/* Quick Tips */}
        <div
          className={cn(
            "p-3 rounded-lg border",
            "bg-gradient-to-br from-violet-50 to-indigo-50 dark:from-violet-950/30 dark:to-indigo-950/30",
            "border-violet-200 dark:border-violet-800/50"
          )}
        >
          <div className="flex items-center gap-1.5 mb-2">
            <Lightbulb className="h-3.5 w-3.5 text-violet-600 dark:text-violet-400" />
            <h4 className="text-xs font-medium text-violet-700 dark:text-violet-300">
              Quick Tips
            </h4>
          </div>
          <div className="space-y-2 text-[11px] text-neutral-600 dark:text-neutral-400">
            <div className="flex items-start gap-2">
              <Layout className="h-3.5 w-3.5 mt-0.5 text-blue-500 flex-shrink-0" />
              <p>
                Click <span className="font-medium text-neutral-800 dark:text-neutral-200">Layout</span> tab to view page sections. Re-analyze if needed.
              </p>
            </div>
            <div className="flex items-start gap-2">
              <ArrowUpRight className="h-3.5 w-3.5 mt-0.5 text-emerald-500 flex-shrink-0" />
              <p>
                Ready to clone? Click{" "}
                <span className="inline-flex items-center gap-0.5 font-medium text-emerald-700 dark:text-emerald-400">
                  Directly Clone
                  <ArrowUpRight className="h-3 w-3" />
                </span>{" "}
                at top right.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
