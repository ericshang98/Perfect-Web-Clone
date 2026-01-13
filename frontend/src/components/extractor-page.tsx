"use client";

import React, { useState, useCallback, useMemo, useEffect, useRef } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Loader2,
  AlertCircle,
  Eye,
  Layout,
  Layers,
  Palette,
  FolderOpen,
  Download,
  Database,
  CheckCircle,
  Code2,
  Globe,
  Package,
  Save,
  Boxes,
  Cpu,
  Lock,
  ArrowRight,
  Lightbulb,
  ArrowUpRight,
  Key,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

// Playwright components
import {
  UrlInput,
  ExtractOptions,
  OverviewTab,
  LayoutTab,
  ElementsTab,
  StylesTab,
  AssetsTab,
  CSSTab,
  NetworkTab,
  ResourcesTab,
  TechStackTab,
  ComponentsTab,
  ThemeSelectModal,
  ThemeToggleButton,
  CloneModeToggle,
  type CloneMode,
} from "@/components/extractor";

// API and types
import {
  extractPageQuick,
  pollExtractionStatus,
  type ExtractionPhase,
  type ExtractionStatusResponse,
} from "@/lib/api/extractor";
import { saveToSources } from "@/lib/api/sources";
import type {
  ExtractionResult,
  ExtractionStatus,
  PlaywrightTab,
  ElementInfo,
  ComponentInfo,
  ThemeMode,
  ThemeDetectionResult,
  ThemedData,
} from "@/types/extractor";

/**
 * Tab Loading Placeholder Component
 * 当 Tab 数据还在加载时显示的占位组件
 */
function TabLoadingPlaceholder({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16">
      <Loader2 className="h-8 w-8 text-blue-500 animate-spin mb-3" />
      <p className="text-sm text-neutral-500 dark:text-neutral-400">{message}</p>
    </div>
  );
}

/**
 * Tab Configuration
 * Tab 配置
 */
const TABS: {
  id: PlaywrightTab;
  label: string;
  icon: React.ElementType;
}[] = [
  { id: "overview", label: "Overview", icon: Eye },
  { id: "layout", label: "Layout", icon: Layout },
  { id: "elements", label: "Elements", icon: Layers },
  { id: "styles", label: "Styles", icon: Palette },
  { id: "assets", label: "Assets", icon: FolderOpen },
  // 新增 Tab - 像素级复刻功能
  { id: "css", label: "CSS", icon: Code2 },
  { id: "network", label: "Network", icon: Globe },
  { id: "resources", label: "Resources", icon: Package },
  // 新增 Tab - 技术栈和组件分析
  { id: "techstack", label: "Tech Stack", icon: Cpu },
  { id: "components", label: "Components", icon: Boxes },
];

/**
 * Playwright Page Component
 * Playwright 网页分析主页面
 *
 * 功能：
 * - URL 输入和配置
 * - 调用后端 Playwright 服务提取页面信息
 * - 多 Tab 展示提取结果
 * - 数据导出
 */
export function PlaywrightPage() {
  // Router for navigation
  const router = useRouter();
  const searchParams = useSearchParams();

  // Track if auto-extract has been triggered
  const autoExtractTriggered = useRef(false);

  // Extraction state
  const [status, setStatus] = useState<ExtractionStatus>("idle");
  const [result, setResult] = useState<ExtractionResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Phased loading state (分阶段加载状态)
  const [loadingPhase, setLoadingPhase] = useState<ExtractionPhase | null>(null);
  const [progress, setProgress] = useState(0);
  const [requestId, setRequestId] = useState<string | null>(null);

  // UI state
  const [activeTab, setActiveTab] = useState<PlaywrightTab>("overview");
  const [selectedElement, setSelectedElement] = useState<ElementInfo | null>(null);
  const [selectedComponent, setSelectedComponent] = useState<ComponentInfo | null>(null);

  // Cache storage state (Save to Cache for Agent)
  const [isSavingToCache, setIsSavingToCache] = useState(false);
  const [cacheStoreSuccess, setCacheStoreSuccess] = useState(false);
  const [currentUrl, setCurrentUrl] = useState<string>("");

  // Directly Clone state (直接克隆状态)
  const [isDirectlyCloning, setIsDirectlyCloning] = useState(false);

  // RAG and Agent store state
  const [ragStoreSuccess, setRagStoreSuccess] = useState(false);
  const [agentStoreSuccess, setAgentStoreSuccess] = useState(false);

  // Theme state (主题相关状态)
  const [themeDetection, setThemeDetection] = useState<ThemeDetectionResult | null>(null);
  const [currentPreviewTheme, setCurrentPreviewTheme] = useState<ThemeMode>("light");
  const [lightModeData, setLightModeData] = useState<ThemedData | null>(null);
  const [darkModeData, setDarkModeData] = useState<ThemedData | null>(null);

  // Theme selection modal state (主题选择弹框状态)
  const [themeModalOpen, setThemeModalOpen] = useState(false);
  const [pendingExportAction, setPendingExportAction] = useState<
    "cache" | "raw" | "directly-clone" | null
  >(null);

  // Clone mode state (克隆模式状态)
  const [cloneMode, setCloneMode] = useState<CloneMode>("full-page");

  /**
   * 处理提取请求（分阶段加载）
   * 1. 快速提取基础数据，立即显示
   * 2. 后台轮询获取剩余数据，逐步更新
   */
  const handleExtract = useCallback(
    async (url: string, options: ExtractOptions) => {
      // 重置状态
      setStatus("loading");
      setError(null);
      setResult(null);
      setSelectedElement(null);
      setSelectedComponent(null);
      setRagStoreSuccess(false);
      setAgentStoreSuccess(false);
      setCurrentUrl(url);
      setLoadingPhase("quick");
      setProgress(0);
      setRequestId(null);
      // 重置主题状态
      setThemeDetection(null);
      setCurrentPreviewTheme("light");
      setLightModeData(null);
      setDarkModeData(null);

      try {
        // ========== 第一阶段：快速提取 ==========
        const quickResult = await extractPageQuick({
          url,
          viewport_width: options.viewportWidth,
          viewport_height: options.viewportHeight,
          include_hidden: options.includeHidden,
          max_depth: options.maxDepth,
          include_screenshot: true,
          extract_css: true,        // 需要为主题切换提取 CSS 数据
          download_resources: true, // 需要为主题切换下载资源
        });

        if (!quickResult.success) {
          setError(quickResult.error || quickResult.message);
          setStatus("error");
          setLoadingPhase("error");
          return;
        }

        // 立即显示快速结果（Overview Tab 可用）
        const initialResult: ExtractionResult = {
          success: true,
          message: quickResult.message,
          metadata: quickResult.metadata || null,
          screenshot: quickResult.screenshot || null,
          assets: quickResult.assets || null,
          raw_html: quickResult.raw_html || null,
          // 以下数据将在后续阶段填充
          dom_tree: null,
          style_summary: null,
          css_data: null,
          network_data: null,
          downloaded_resources: null,
          full_page_screenshot: null,
          interaction_data: null,
          // 主题相关数据
          theme_detection: quickResult.theme_detection || null,
          current_theme: quickResult.current_theme || "light",
          light_mode_data: quickResult.light_mode_data || null,
          dark_mode_data: quickResult.dark_mode_data || null,
        };

        setResult(initialResult);
        setStatus("success");  // 立即切换到成功状态，显示页面
        setLoadingPhase("quick");
        setProgress(25);
        setRequestId(quickResult.request_id);

        // 设置主题相关状态
        if (quickResult.theme_detection) {
          setThemeDetection(quickResult.theme_detection);
          setCurrentPreviewTheme(quickResult.current_theme || "light");
          setLightModeData(quickResult.light_mode_data || null);
          setDarkModeData(quickResult.dark_mode_data || null);
        }

        // ========== 第二阶段：轮询获取剩余数据 ==========
        pollExtractionStatus(
          quickResult.request_id,
          (statusResponse: ExtractionStatusResponse) => {
            // 更新进度
            setLoadingPhase(statusResponse.phase);
            setProgress(statusResponse.progress);

            // 合并新数据到 result
            setResult((prev) => {
              if (!prev) return prev;
              return {
                ...prev,
                // DOM 阶段数据
                dom_tree: statusResponse.dom_tree as ExtractionResult["dom_tree"] ?? prev.dom_tree,
                style_summary: statusResponse.style_summary as ExtractionResult["style_summary"] ?? prev.style_summary,
                // 高级阶段数据
                css_data: statusResponse.css_data as ExtractionResult["css_data"] ?? prev.css_data,
                network_data: statusResponse.network_data as ExtractionResult["network_data"] ?? prev.network_data,
                full_page_screenshot: statusResponse.full_page_screenshot ?? prev.full_page_screenshot,
                interaction_data: statusResponse.interaction_data as ExtractionResult["interaction_data"] ?? prev.interaction_data,
                tech_stack: statusResponse.tech_stack as ExtractionResult["tech_stack"] ?? prev.tech_stack,
                components: statusResponse.components as ExtractionResult["components"] ?? prev.components,
                // 完成阶段数据
                downloaded_resources: statusResponse.downloaded_resources as ExtractionResult["downloaded_resources"] ?? prev.downloaded_resources,
              };
            });

            // 如果有错误，显示但不中断
            if (statusResponse.error) {
              console.warn("[Phased Loading] Phase error:", statusResponse.error);
            }
          },
          {
            interval: 1000,     // 每秒轮询
            maxAttempts: 120,   // 最多 2 分钟
          }
        ).then(() => {
          // 轮询完成
          setLoadingPhase("complete");
          setProgress(100);
          console.log("[Phased Loading] All phases complete");
        }).catch((pollError) => {
          // 轮询出错（不影响已显示的数据）
          console.error("[Phased Loading] Polling error:", pollError);
          setLoadingPhase("complete");
        });

      } catch (err) {
        console.error("Extraction failed:", err);
        setError(err instanceof Error ? err.message : "Extraction failed");
        setStatus("error");
        setLoadingPhase("error");
      }
    },
    []
  );

  /**
   * Auto-extract when URL parameter is present
   * 当 URL 参数存在时自动执行提取
   */
  useEffect(() => {
    const urlParam = searchParams.get("url");
    if (urlParam && !autoExtractTriggered.current) {
      autoExtractTriggered.current = true;
      // Default extraction options
      const defaultOptions: ExtractOptions = {
        viewportWidth: 1920,
        viewportHeight: 1080,
        includeHidden: false,
        maxDepth: 50,
      };
      handleExtract(urlParam, defaultOptions);
    }
  }, [searchParams, handleExtract]);

  /**
   * 处理元素选择（跨 Tab 同步）
   */
  const handleSelectElement = useCallback((element: ElementInfo) => {
    setSelectedElement(element);
  }, []);

  /**
   * 处理组件选择（从 Layout Tab 同步到 Components Tab）
   */
  const handleSelectComponent = useCallback((component: ComponentInfo) => {
    setSelectedComponent(component);
    // Auto switch to components tab when a component is selected
    setActiveTab("components");
  }, []);

  /**
   * 导出 JSON 数据
   */
  const handleExportJSON = useCallback(() => {
    if (!result) return;

    const blob = new Blob([JSON.stringify(result, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `playwright-extract-${Date.now()}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }, [result]);

  /**
   * 存储到 RAG 系统
   * 将原始 JSON 进行模块化切片后存储到后端 RAG 数据库
   */
  const handleStoreToRAG = useCallback(async () => {
    if (!result || !currentUrl) return;

    setIsStoringToRAG(true);
    setRagStoreSuccess(false);

    try {
      // 保存到文件系统 Sources
      const response = await saveToSources({
        url: currentUrl,
        data: result as unknown as Record<string, unknown>,
        title: result.metadata?.title,
        theme: (result.current_theme as "light" | "dark") || "light",
      });

      if (response.success) {
        setRagStoreSuccess(true);
        console.log("[Sources] Store success:", response.id);
        // 3 秒后重置成功状态
        setTimeout(() => setRagStoreSuccess(false), 3000);
      } else {
        console.error("[Sources] Store failed:", response.error);
      }
    } catch (err) {
      console.error("[Sources] Store error:", err);
    } finally {
      setIsStoringToRAG(false);
    }
  }, [result, currentUrl]);

  /**
   * 保存到 Agent（文件系统存储）
   * 将原始 JSON 数据存储到 Sources，供 Clone Agent 使用
   */
  const handleSaveToAgent = useCallback(async () => {
    if (!result || !currentUrl) return;

    setIsStoringToAgent(true);
    setAgentStoreSuccess(false);

    try {
      const response = await saveToSources({
        url: currentUrl,
        data: result as unknown as Record<string, unknown>,
        title: result.metadata?.title,
        theme: (result.current_theme as "light" | "dark") || "light",
      });

      if (response.success) {
        setAgentStoreSuccess(true);
        console.log("[Sources] Save to Agent success:", response.id);
        // 3 秒后重置成功状态
        setTimeout(() => setAgentStoreSuccess(false), 3000);
      } else {
        console.error("[Sources] Save to Agent failed:", response.error);
      }
    } catch (err) {
      console.error("[Sources] Save to Agent error:", err);
    } finally {
      setIsStoringToAgent(false);
    }
  }, [result, currentUrl]);

  // ==================== Theme Related Functions ====================

  /**
   * 检查是否支持双主题模式
   */
  const hasDualThemeSupport = themeDetection?.support === "both";

  /**
   * 处理主题切换预览
   * 切换主题后，各 Tab 通过 useMemo 计算的 themed* 变量自动获取对应主题的数据
   */
  const handleThemePreviewChange = useCallback(
    (theme: ThemeMode) => {
      setCurrentPreviewTheme(theme);
    },
    []
  );

  /**
   * 获取当前预览主题的主题数据
   * 用于在 UI 中显示主题感知的数据
   */
  const currentThemedData = useMemo(() => {
    if (!hasDualThemeSupport) return null;
    return currentPreviewTheme === "light" ? lightModeData : darkModeData;
  }, [hasDualThemeSupport, currentPreviewTheme, lightModeData, darkModeData]);

  /**
   * 计算当前主题的各字段数据
   * 使用 useMemo 确保当主题切换时数据自动更新
   */
  const themedScreenshot = useMemo(() => {
    if (hasDualThemeSupport && currentThemedData?.screenshot) {
      return currentThemedData.screenshot;
    }
    return result?.screenshot || null;
  }, [hasDualThemeSupport, currentThemedData, result?.screenshot]);

  const themedFullPageScreenshot = useMemo(() => {
    if (hasDualThemeSupport && currentThemedData?.full_page_screenshot) {
      return currentThemedData.full_page_screenshot;
    }
    return result?.full_page_screenshot || null;
  }, [hasDualThemeSupport, currentThemedData, result?.full_page_screenshot]);

  const themedAssets = useMemo(() => {
    if (hasDualThemeSupport && currentThemedData?.assets) {
      return currentThemedData.assets;
    }
    return result?.assets || null;
  }, [hasDualThemeSupport, currentThemedData, result?.assets]);

  const themedStyleSummary = useMemo(() => {
    if (hasDualThemeSupport && currentThemedData?.style_summary) {
      return currentThemedData.style_summary;
    }
    return result?.style_summary || null;
  }, [hasDualThemeSupport, currentThemedData, result?.style_summary]);

  const themedCssData = useMemo(() => {
    if (hasDualThemeSupport && currentThemedData?.css_data) {
      return currentThemedData.css_data;
    }
    return result?.css_data || null;
  }, [hasDualThemeSupport, currentThemedData, result?.css_data]);

  const themedDownloadedResources = useMemo(() => {
    if (hasDualThemeSupport && currentThemedData?.downloaded_resources) {
      return currentThemedData.downloaded_resources;
    }
    return result?.downloaded_resources || null;
  }, [hasDualThemeSupport, currentThemedData, result?.downloaded_resources]);

  /**
   * 获取指定主题的数据用于导出
   * 包含所有主题相关字段的完整合并
   */
  const getThemedResultForExport = useCallback(
    (theme: ThemeMode): ExtractionResult | null => {
      if (!result) return null;

      const themedData = theme === "light" ? lightModeData : darkModeData;

      // 如果没有主题特定数据，返回原始结果
      if (!themedData) return result;

      // 合并主题特定数据（包含所有主题相关字段）
      return {
        ...result,
        screenshot: themedData.screenshot || result.screenshot,
        full_page_screenshot: themedData.full_page_screenshot || result.full_page_screenshot,
        style_summary: themedData.style_summary || result.style_summary,
        css_data: themedData.css_data || result.css_data,
        assets: themedData.assets || result.assets,
        downloaded_resources: themedData.downloaded_resources || result.downloaded_resources,
        current_theme: theme,
      };
    },
    [result, lightModeData, darkModeData]
  );

  /**
   * Save to cache (for Agent to read)
   * 保存到缓存（供 Agent 读取）
   */
  const handleSaveToCacheWithTheme = useCallback(
    async (themedResult: ExtractionResult) => {
      if (!currentUrl) return;

      setIsSavingToCache(true);
      setCacheStoreSuccess(false);

      try {
        const response = await saveToSources({
          url: currentUrl,
          data: themedResult as unknown as Record<string, unknown>,
          title: themedResult.metadata?.title,
          theme: (themedResult.current_theme as "light" | "dark") || "light",
        });

        if (response.success) {
          setCacheStoreSuccess(true);
          console.log("[Sources] Store success:", response.id);
          setTimeout(() => setCacheStoreSuccess(false), 3000);
        } else {
          console.error("[Sources] Store failed:", response.error);
        }
      } catch (err) {
        console.error("[Sources] Store error:", err);
      } finally {
        setIsSavingToCache(false);
      }
    },
    [currentUrl]
  );

  /**
   * Directly Clone - Save to cache and navigate to Agent page
   * 直接克隆 - 保存到缓存并跳转到 Agent 页面
   */
  const handleDirectlyClone = useCallback(
    async (themedResult: ExtractionResult) => {
      if (!currentUrl) return;

      setIsDirectlyCloning(true);

      try {
        const theme = (themedResult.current_theme as "light" | "dark") || "light";
        const response = await saveToSources({
          url: currentUrl,
          data: themedResult as unknown as Record<string, unknown>,
          title: themedResult.metadata?.title,
          theme,
        });

        if (response.success && response.id) {
          console.log("[Sources] Saved for clone:", response.id);
          // Navigate to Agent page with source ID and theme
          router.push(`/agent?source=${response.id}&theme=${theme}&autoClone=true`);
        } else {
          console.error("[Directly Clone] Save failed:", response.error);
          alert("Failed to save to cache: " + (response.error || "Unknown error"));
          setIsDirectlyCloning(false);
        }
      } catch (err) {
        console.error("[Directly Clone] Error:", err);
        alert("Error: " + (err instanceof Error ? err.message : "Unknown error"));
        setIsDirectlyCloning(false);
      }
      // Note: Don't reset isDirectlyCloning here - we're navigating away
    },
    [currentUrl, router]
  );

  /**
   * 带主题的 Raw JSON 导出
   */
  const handleExportJSONWithTheme = useCallback(
    (themedResult: ExtractionResult) => {
      const blob = new Blob([JSON.stringify(themedResult, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `playwright-extract-${themedResult.current_theme || "light"}-${Date.now()}.json`;
      link.click();
      URL.revokeObjectURL(url);
    },
    []
  );

  /**
   * 执行实际的导出操作
   */
  const executeExportAction = useCallback(
    (action: "cache" | "raw" | "directly-clone", theme: ThemeMode) => {
      const themedResult = getThemedResultForExport(theme);
      if (!themedResult) return;

      switch (action) {
        case "cache":
          handleSaveToCacheWithTheme(themedResult);
          break;
        case "raw":
          handleExportJSONWithTheme(themedResult);
          break;
        case "directly-clone":
          handleDirectlyClone(themedResult);
          break;
      }
    },
    [
      getThemedResultForExport,
      handleSaveToCacheWithTheme,
      handleExportJSONWithTheme,
      handleDirectlyClone,
    ]
  );

  /**
   * 处理导出按钮点击
   * 如果支持双主题，弹出选择框；否则直接执行
   */
  const handleExportClick = useCallback(
    (action: "cache" | "raw" | "directly-clone") => {
      if (hasDualThemeSupport) {
        // 双主题模式：弹出选择框
        setPendingExportAction(action);
        setThemeModalOpen(true);
      } else {
        // 单主题模式：直接执行
        executeExportAction(action, currentPreviewTheme);
      }
    },
    [hasDualThemeSupport, currentPreviewTheme, executeExportAction]
  );

  /**
   * 处理主题选择弹框确认
   */
  const handleThemeSelectConfirm = useCallback(
    (theme: ThemeMode) => {
      setThemeModalOpen(false);
      if (pendingExportAction) {
        executeExportAction(pendingExportAction, theme);
        setPendingExportAction(null);
      }
    },
    [pendingExportAction, executeExportAction]
  );

  return (
    <div className="flex h-screen bg-neutral-100 dark:bg-neutral-900">
      {/* Main Content */}
      <main className="flex-1 overflow-hidden flex flex-col">
        {/* Header */}
        <header className="bg-neutral-100 dark:bg-neutral-900 px-6 py-4 border-b border-neutral-200 dark:border-neutral-800">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              {/* Back to Home */}
              <Link
                href="/"
                className="text-sm text-neutral-500 hover:text-neutral-700 dark:text-neutral-400 dark:hover:text-neutral-200"
              >
                ← Home
              </Link>
              <div>
                <div className="flex items-center gap-2">
                  <Layers className="h-5 w-5 text-neutral-700 dark:text-neutral-300" />
                  <h1 className="text-lg font-semibold text-neutral-800 dark:text-neutral-100">
                    Web Extractor
                  </h1>
                </div>
                <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-0.5">
                  Extract and analyze webpage structure, styles, and layout
                </p>
              </div>
            </div>

            {/* Export Buttons */}
            {result && status === "success" && (
              <div className="flex items-center gap-3">
                {/* Save to Cache (for Agent) */}
                <button
                  onClick={() => handleExportClick("cache")}
                  disabled={isSavingToCache}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md",
                    "transition-all shadow-sm",
                    cacheStoreSuccess
                      ? "bg-green-600 text-white"
                      : "bg-gradient-to-r from-violet-600 to-purple-600 text-white hover:from-violet-700 hover:to-purple-700",
                    isSavingToCache && "opacity-70 cursor-wait"
                  )}
                  title={hasDualThemeSupport ? "Save to Cache (select theme)" : "Save extraction to cache for Agent"}
                >
                  {isSavingToCache ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : cacheStoreSuccess ? (
                    <CheckCircle className="h-3.5 w-3.5" />
                  ) : (
                    <Database className="h-3.5 w-3.5" />
                  )}
                  {isSavingToCache
                    ? "Saving..."
                    : cacheStoreSuccess
                    ? "Saved!"
                    : "Save to Cache"}
                </button>
                {/* Export Raw JSON */}
                <button
                  onClick={() => handleExportClick("raw")}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md",
                    "bg-neutral-600 dark:bg-neutral-700 text-white",
                    "hover:bg-neutral-700 dark:hover:bg-neutral-600",
                    "transition-colors"
                  )}
                  title={hasDualThemeSupport ? "Export Raw JSON (select theme)" : "Export Raw JSON"}
                >
                  <Download className="h-3.5 w-3.5" />
                  Raw
                </button>

                {/* Directly Clone - Save and navigate to Agent */}
                <button
                  onClick={() => handleExportClick("directly-clone")}
                  disabled={isDirectlyCloning}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md",
                    "transition-all shadow-sm",
                    "bg-gradient-to-r from-emerald-600 to-teal-600 text-white",
                    "hover:from-emerald-700 hover:to-teal-700",
                    isDirectlyCloning && "opacity-70 cursor-wait"
                  )}
                  title={hasDualThemeSupport ? "Clone website directly (select theme)" : "Save to cache and open in Agent"}
                >
                  {isDirectlyCloning ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <ArrowRight className="h-3.5 w-3.5" />
                  )}
                  {isDirectlyCloning ? "Cloning..." : "Directly Clone"}
                </button>
              </div>
            )}
          </div>
        </header>

        {/* Theme Selection Modal */}
        <ThemeSelectModal
          isOpen={themeModalOpen}
          onClose={() => {
            setThemeModalOpen(false);
            setPendingExportAction(null);
          }}
          onSelect={handleThemeSelectConfirm}
          title="Select Theme to Export"
          description="This page supports both light and dark modes. Choose which version to export."
        />

        {/* Content - 与侧边栏背景一致 */}
        <div className="flex-1 overflow-auto p-4 md:p-6 bg-neutral-100 dark:bg-neutral-900">
          <div className={cn(
            "mx-auto",
            status === "success" && result ? "flex gap-6 max-w-7xl" : "max-w-6xl"
          )}>
            {/* Main Content */}
            <div className={cn(
              "space-y-4",
              status === "success" && result ? "flex-1 min-w-0" : ""
            )}>
            {/* URL Input Section - 卡片风格 */}
            <div
              className={cn(
                "p-4 rounded-xl",
                "bg-white dark:bg-neutral-800",
                "shadow-sm"
              )}
            >
              <UrlInput
                onSubmit={handleExtract}
                isLoading={status === "loading"}
                initialUrl={searchParams.get("url") || ""}
              />
            </div>

            {/* Loading State */}
            {status === "loading" && (
              <div
                className={cn(
                  "flex flex-col items-center justify-center p-12 rounded-xl",
                  "bg-white dark:bg-neutral-800",
                  "shadow-sm"
                )}
              >
                <Loader2 className="h-10 w-10 text-blue-500 animate-spin mb-4" />
                <p className="text-base font-medium text-neutral-700 dark:text-neutral-300">
                  Analyzing webpage...
                </p>
                <p className="text-sm text-neutral-500 dark:text-neutral-400 mt-1">
                  Launching browser, rendering page, and extracting data
                </p>
              </div>
            )}

            {/* Error State */}
            {status === "error" && error && (
              <div
                className={cn(
                  "flex items-start gap-3 p-4 rounded-xl",
                  "bg-red-50 dark:bg-red-900/20",
                  "shadow-sm"
                )}
              >
                <AlertCircle className="h-5 w-5 text-red-500 flex-shrink-0 mt-0.5" />
                <div>
                  <p className="font-medium text-red-800 dark:text-red-200">
                    Extraction Failed
                  </p>
                  <p className="text-sm text-red-600 dark:text-red-400 mt-1">
                    {error}
                  </p>
                </div>
              </div>
            )}

            {/* Results Section with shadcn Tabs */}
            {status === "success" && result && (
              <div
                className={cn(
                  "rounded-xl overflow-hidden",
                  "bg-white dark:bg-neutral-800",
                  "shadow-sm"
                )}
              >
                {/* Loading Progress Indicator (分阶段加载进度) */}
                {loadingPhase && loadingPhase !== "complete" && loadingPhase !== "error" && (
                  <div className="px-4 py-2 bg-blue-50 dark:bg-blue-950/30 border-b border-blue-200 dark:border-blue-900">
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-2">
                        <Loader2 className="h-3.5 w-3.5 text-blue-500 animate-spin" />
                        <span className="text-xs font-medium text-blue-700 dark:text-blue-300">
                          {loadingPhase === "quick" && "Loading DOM structure..."}
                          {loadingPhase === "dom" && "Extracting styles and CSS..."}
                          {loadingPhase === "advanced" && "Downloading resources..."}
                        </span>
                      </div>
                      <span className="text-xs text-blue-600 dark:text-blue-400">
                        {progress}%
                      </span>
                    </div>
                    <div className="w-full bg-blue-200 dark:bg-blue-900 rounded-full h-1">
                      <div
                        className="bg-blue-600 dark:bg-blue-400 h-1 rounded-full transition-all duration-300"
                        style={{ width: `${progress}%` }}
                      />
                    </div>
                  </div>
                )}

                {/* Clone Mode and Theme Toggle Control Bar - 独立的控制栏 */}
                {result && (
                  <div className="px-4 py-3 border-b border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50">
                    <div className="flex items-center justify-between">
                      {/* Left: Clone Mode Toggle */}
                      <CloneModeToggle
                        activeMode={cloneMode}
                        onModeChange={setCloneMode}
                      />

                      {/* Right: Theme Toggle Button (only when dual theme is supported) */}
                      {hasDualThemeSupport && (
                        <ThemeToggleButton
                          activeTheme={currentPreviewTheme}
                          onThemeChange={handleThemePreviewChange}
                        />
                      )}
                    </div>
                  </div>
                )}

                <Tabs
                  value={activeTab}
                  onValueChange={(value) => setActiveTab(value as PlaywrightTab)}
                  className="w-full"
                >
                  {/* Tab Navigation - Only show when Full Page mode */}
                  {cloneMode === "full-page" && (
                  <div className="border-b border-neutral-200 dark:border-neutral-700 px-4 pt-3">
                    <TabsList className="h-10 p-1 bg-neutral-100 dark:bg-neutral-700">
                      {TABS.map(({ id, label, icon: Icon }) => (
                        <TabsTrigger
                          key={id}
                          value={id}
                          className="flex items-center gap-1.5 px-3 data-[state=active]:bg-white dark:data-[state=active]:bg-neutral-600 data-[state=active]:text-neutral-900 dark:data-[state=active]:text-neutral-100"
                        >
                          <Icon className="h-4 w-4" />
                          <span className="text-sm">{label}</span>
                        </TabsTrigger>
                      ))}
                    </TabsList>
                  </div>
                  )}

                  {/* Tab Contents - Only show when Full Page mode */}
                  {cloneMode === "full-page" && (
                  <div className="p-4">
                    {/* Overview Tab - Always available (quick phase) */}
                    {/* 使用主题感知数据：截图和资源会随主题变化 */}
                    <TabsContent value="overview" className="mt-0">
                      <OverviewTab
                        metadata={result.metadata || null}
                        screenshot={themedScreenshot}
                        fullPageScreenshot={themedFullPageScreenshot}
                        assets={themedAssets}
                      />
                    </TabsContent>

                    {/* Layout Tab - Needs DOM phase */}
                    {/* DOM 结构不受主题影响 */}
                    <TabsContent value="layout" className="mt-0">
                      {!result.dom_tree && loadingPhase !== "complete" ? (
                        <TabLoadingPlaceholder message="Loading DOM structure..." />
                      ) : (
                        <LayoutTab
                          domTree={result.dom_tree || null}
                          metadata={result.metadata || null}
                          components={result.components || null}
                          rawHtml={result.raw_html || null}
                          onSelectElement={handleSelectElement}
                          onSelectComponent={handleSelectComponent}
                        />
                      )}
                    </TabsContent>

                    {/* Elements Tab - Needs DOM phase */}
                    {/* DOM 结构不受主题影响 */}
                    <TabsContent value="elements" className="mt-0">
                      {!result.dom_tree && loadingPhase !== "complete" ? (
                        <TabLoadingPlaceholder message="Loading elements..." />
                      ) : (
                        <ElementsTab
                          domTree={result.dom_tree || null}
                          onSelectElement={handleSelectElement}
                          selectedElement={selectedElement}
                        />
                      )}
                    </TabsContent>

                    {/* Styles Tab - Needs DOM phase */}
                    {/* 使用主题感知数据：颜色统计会随主题变化 */}
                    <TabsContent value="styles" className="mt-0">
                      {!themedStyleSummary && loadingPhase !== "complete" ? (
                        <TabLoadingPlaceholder message="Computing styles..." />
                      ) : (
                        <StylesTab styleSummary={themedStyleSummary} />
                      )}
                    </TabsContent>

                    {/* Assets Tab - Available from quick phase */}
                    {/* 使用主题感知数据：图片 URL 可能随主题变化 */}
                    <TabsContent value="assets" className="mt-0">
                      <AssetsTab
                        assets={themedAssets}
                        currentTheme={currentPreviewTheme}
                        hasDualTheme={hasDualThemeSupport}
                      />
                    </TabsContent>

                    {/* CSS Tab - Needs advanced phase */}
                    {/* 使用主题感知数据：CSS 变量值会随主题变化 */}
                    <TabsContent value="css" className="mt-0">
                      {!themedCssData && loadingPhase !== "complete" ? (
                        <TabLoadingPlaceholder message="Extracting CSS data..." />
                      ) : (
                        <CSSTab cssData={themedCssData} />
                      )}
                    </TabsContent>

                    {/* Network Tab - Needs advanced phase */}
                    {/* 网络请求不受主题影响（是一次性的） */}
                    <TabsContent value="network" className="mt-0">
                      {!result.network_data && loadingPhase !== "complete" ? (
                        <TabLoadingPlaceholder message="Collecting network data..." />
                      ) : (
                        <NetworkTab networkData={result.network_data || null} />
                      )}
                    </TabsContent>

                    {/* Resources Tab - Needs complete phase */}
                    {/* 使用主题感知数据：下载的图片内容会随主题变化 */}
                    <TabsContent value="resources" className="mt-0">
                      {!themedDownloadedResources && loadingPhase !== "complete" ? (
                        <TabLoadingPlaceholder message="Downloading resources..." />
                      ) : (
                        <ResourcesTab
                          resources={themedDownloadedResources}
                          currentTheme={currentPreviewTheme}
                          hasDualTheme={hasDualThemeSupport}
                        />
                      )}
                    </TabsContent>

                    {/* Tech Stack Tab - Needs advanced phase */}
                    <TabsContent value="techstack" className="mt-0">
                      {!result.tech_stack && loadingPhase !== "complete" ? (
                        <TabLoadingPlaceholder message="Analyzing tech stack..." />
                      ) : (
                        <TechStackTab techStack={result.tech_stack || null} />
                      )}
                    </TabsContent>

                    {/* Components Tab - Needs advanced phase */}
                    <TabsContent value="components" className="mt-0">
                      {!result.components && loadingPhase !== "complete" ? (
                        <TabLoadingPlaceholder message="Analyzing components..." />
                      ) : (
                        <ComponentsTab
                          components={result.components || null}
                          selectedComponentId={selectedComponent?.id || null}
                        />
                      )}
                    </TabsContent>
                  </div>
                  )}

                  {/* Section Mode Placeholder - Show when Section mode */}
                  {cloneMode === "section" && (
                    <div className="p-8 text-center">
                      <div className="flex flex-col items-center justify-center py-12">
                        <div className="p-4 rounded-full bg-neutral-100 dark:bg-neutral-700 mb-4">
                          <Lock className="h-8 w-8 text-neutral-400 dark:text-neutral-500" />
                        </div>
                        <p className="text-lg font-medium text-neutral-600 dark:text-neutral-300">
                          Section Clone Mode
                        </p>
                        <p className="text-sm text-neutral-500 dark:text-neutral-400 mt-2 max-w-md">
                          This feature allows you to clone specific sections of a webpage.
                          Coming soon in a future update.
                        </p>
                      </div>
                    </div>
                  )}
                </Tabs>
              </div>
            )}

            {/* Empty State - 与侧边栏风格一致 */}
            {status === "idle" && (
              <div
                className={cn(
                  "flex flex-col items-center justify-center p-12 rounded-xl border-2 border-dashed",
                  "bg-white dark:bg-neutral-800/50",
                  "border-neutral-300 dark:border-neutral-700"
                )}
              >
                <div
                  className={cn(
                    "p-4 rounded-full mb-4",
                    "bg-neutral-100 dark:bg-neutral-700"
                  )}
                >
                  <Layers className="h-8 w-8 text-neutral-600 dark:text-neutral-300" />
                </div>
                <p className="text-lg font-medium text-neutral-700 dark:text-neutral-200">
                  Enter a URL to analyze
                </p>
                <p className="text-sm text-neutral-500 dark:text-neutral-400 mt-2 text-center max-w-md">
                  Extract DOM structure, computed styles, layout information, and page assets
                  from any webpage using Playwright
                </p>
              </div>
            )}
            </div>

            {/* Right Side Guide Panel - Only show when results are available */}
            {status === "success" && result && (
            <div className="hidden xl:block w-72 flex-shrink-0">
              <div
                className={cn(
                  "sticky top-4 p-4 rounded-xl border",
                  "bg-gradient-to-br from-violet-50 to-indigo-50 dark:from-violet-950/30 dark:to-indigo-950/30",
                  "border-violet-200 dark:border-violet-800/50"
                )}
              >
                <div className="flex items-center gap-2 mb-4">
                  <Lightbulb className="h-4 w-4 text-violet-600 dark:text-violet-400" />
                  <h3 className="text-sm font-semibold text-violet-800 dark:text-violet-300">
                    Quick Guide
                  </h3>
                </div>

                <div className="space-y-4 text-xs text-neutral-600 dark:text-neutral-400">
                  {/* Layout Tip */}
                  <div className="flex items-start gap-2.5">
                    <div className="p-1.5 rounded-md bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400 flex-shrink-0">
                      <Layout className="h-3.5 w-3.5" />
                    </div>
                    <div>
                      <p className="font-medium text-neutral-800 dark:text-neutral-200 mb-0.5">
                        View Page Structure
                      </p>
                      <p>
                        Click <span className="font-semibold text-blue-600 dark:text-blue-400">Layout</span> tab to see how the page is divided into sections.
                      </p>
                    </div>
                  </div>

                  {/* Directly Clone Tip */}
                  <div className="flex items-start gap-2.5">
                    <div className="p-1.5 rounded-md bg-emerald-100 dark:bg-emerald-900/40 text-emerald-600 dark:text-emerald-400 flex-shrink-0">
                      <ArrowUpRight className="h-3.5 w-3.5" />
                    </div>
                    <div>
                      <p className="font-medium text-neutral-800 dark:text-neutral-200 mb-0.5">
                        Start Cloning
                      </p>
                      <p>
                        Click{" "}
                        <span className="inline-flex items-center gap-0.5 font-semibold text-emerald-600 dark:text-emerald-400">
                          Directly Clone
                          <ArrowUpRight className="h-3 w-3" />
                        </span>{" "}
                        at the top right to generate code.
                      </p>
                    </div>
                  </div>

                  {/* API Key Reminder */}
                  <div className="flex items-start gap-2.5 pt-2 border-t border-violet-200/50 dark:border-violet-700/50">
                    <div className="p-1.5 rounded-md bg-amber-100 dark:bg-amber-900/40 text-amber-600 dark:text-amber-400 flex-shrink-0">
                      <Key className="h-3.5 w-3.5" />
                    </div>
                    <div>
                      <p className="font-medium text-neutral-800 dark:text-neutral-200 mb-0.5">
                        API Key Required
                      </p>
                      <p>
                        Make sure to configure your <span className="font-semibold text-amber-600 dark:text-amber-400">Claude API Key</span> in the backend <code className="text-[10px] bg-neutral-200 dark:bg-neutral-700 px-1 py-0.5 rounded">.env</code> file before cloning.
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
