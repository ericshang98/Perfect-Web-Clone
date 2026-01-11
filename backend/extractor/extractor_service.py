"""
Playwright Extractor Service
核心提取服务，使用 Playwright 获取网页完整信息

主要功能：
- 浏览器实例管理
- 页面渲染和等待
- DOM 结构提取
- 样式计算
- 资源收集
- 截图生成
- CSS 动画/变量/伪元素提取
- 网络请求监控
- 资源下载
- 交互状态捕获
- 分阶段提取（优化首屏加载）
"""

import asyncio
import aiohttp
import base64
import logging
import re
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from urllib.parse import urljoin, urlparse

from playwright.async_api import (
    async_playwright,
    Browser,
    Page,
    Request,
    Response,
    TimeoutError as PlaywrightTimeout
)

from .models import (
    ExtractRequest,
    ExtractionResult,
    PageMetadata,
    ElementInfo,
    ElementRect,
    ElementStyles,
    StyleSummary,
    PageAssets,
    AssetInfo,
    # 新增模型
    CSSData,
    CSSAnimation,
    CSSKeyframe,
    CSSTransitionInfo,
    CSSVariable,
    PseudoElementStyle,
    StylesheetContent,
    NetworkData,
    NetworkRequest,
    DownloadedResources,
    ResourceContent,
    InteractionData,
    InteractionState,
    TechStackData,
    ComponentAnalysisData,
    # 分阶段提取模型
    ExtractionPhase,
    QuickExtractionResult,
    # 主题相关模型
    ThemeMode,
    ThemeSupport,
    ThemeDetectionResult,
    ThemedData,
)
from .cache_manager import extraction_cache
from .tech_stack_analyzer import TechStackAnalyzer
from .component_analyzer import ComponentAnalyzer

# 设置日志
logger = logging.getLogger(__name__)


class PlaywrightExtractorService:
    """
    Playwright 提取服务
    管理浏览器实例和页面提取逻辑
    """

    def __init__(self):
        """初始化服务"""
        self._browser: Optional[Browser] = None
        self._playwright = None
        # 网络请求收集器
        self._network_requests: List[Dict[str, Any]] = []
        self._api_responses: Dict[str, Any] = {}

    async def _ensure_browser(self):
        """
        确保浏览器实例存在
        使用懒加载模式，首次调用时启动浏览器
        """
        if self._browser is None:
            logger.info("启动 Playwright 浏览器实例...")
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                ]
            )
            logger.info("浏览器实例已启动")

    async def _get_browser(self) -> Browser:
        """
        获取浏览器实例，如果不存在则自动启动

        Returns:
            Browser: Playwright 浏览器实例
        """
        await self._ensure_browser()
        return self._browser

    async def close(self):
        """关闭浏览器实例"""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("浏览器实例已关闭")

    async def extract(self, request: ExtractRequest) -> ExtractionResult:
        """
        主提取方法
        提取指定 URL 的完整页面信息

        Args:
            request: 提取请求参数

        Returns:
            ExtractionResult: 完整的提取结果
        """
        start_time = datetime.now()

        # 重置网络请求收集器
        self._network_requests = []
        self._api_responses = {}

        try:
            # 确保浏览器已启动
            await self._ensure_browser()

            # 创建新页面
            page = await self._browser.new_page(
                viewport={
                    'width': request.viewport_width,
                    'height': request.viewport_height
                }
            )

            try:
                # 设置网络监控（如果启用）
                if request.capture_network:
                    await self._setup_network_monitoring(page)

                logger.info(f"正在加载页面: {request.url}")

                # 导航到目标页面
                await page.goto(
                    request.url,
                    wait_until='load',
                    timeout=60000  # 60 秒超时
                )

                # 额外等待 2 秒让动态内容加载
                await asyncio.sleep(2)

                # 如果指定了等待选择器，则等待
                if request.wait_for_selector:
                    await page.wait_for_selector(
                        request.wait_for_selector,
                        timeout=30000
                    )

                # 获取页面加载时间
                load_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                # ========== 滚动页面触发懒加载 ==========
                await self._scroll_to_load_lazy_content(page)

                # ========== 基础提取任务（并行） ==========
                base_tasks = [
                    self._extract_metadata(page, request.url, load_time_ms),
                    self._extract_dom_tree(page, request.max_depth, request.include_hidden),
                    self._extract_assets(page),
                    self._take_screenshot(page) if request.include_screenshot else asyncio.sleep(0),
                    self._get_raw_html(page),
                ]
                base_results = await asyncio.gather(*base_tasks, return_exceptions=True)

                # 解析基础结果
                metadata = base_results[0] if not isinstance(base_results[0], Exception) else None
                dom_tree = base_results[1] if not isinstance(base_results[1], Exception) else None
                assets = base_results[2] if not isinstance(base_results[2], Exception) else None
                screenshot = base_results[3] if request.include_screenshot and not isinstance(base_results[3], Exception) else None
                raw_html = base_results[4] if not isinstance(base_results[4], Exception) else None

                # 从 DOM 树提取样式汇总
                style_summary = self._compute_style_summary(dom_tree) if dom_tree else None

                # ========== 高级提取任务（并行） ==========
                advanced_tasks = []

                # CSS 数据提取
                if request.extract_css:
                    advanced_tasks.append(self._extract_css_data(page, request.url))
                else:
                    advanced_tasks.append(asyncio.sleep(0))

                # 全页截图
                if request.full_page_screenshot:
                    advanced_tasks.append(self._take_full_screenshot(page))
                else:
                    advanced_tasks.append(asyncio.sleep(0))

                # 交互状态捕获
                if request.capture_interactions:
                    advanced_tasks.append(self._capture_interactions(page))
                else:
                    advanced_tasks.append(asyncio.sleep(0))

                advanced_results = await asyncio.gather(*advanced_tasks, return_exceptions=True)

                css_data = advanced_results[0] if request.extract_css and not isinstance(advanced_results[0], Exception) else None
                full_page_screenshot = advanced_results[1] if request.full_page_screenshot and not isinstance(advanced_results[1], Exception) else None
                interaction_data = advanced_results[2] if request.capture_interactions and not isinstance(advanced_results[2], Exception) else None

                # ========== 资源下载（独立执行，避免并发问题） ==========
                downloaded_resources = None
                if request.download_resources and assets:
                    try:
                        downloaded_resources = await self._download_resources(page, assets, request.url)
                    except Exception as e:
                        logger.error(f"资源下载失败: {str(e)}")

                # ========== 网络数据整理 ==========
                network_data = None
                if request.capture_network:
                    network_data = self._compile_network_data()

                # 记录错误（如果有）
                for i, result in enumerate(base_results + advanced_results):
                    if isinstance(result, Exception):
                        logger.error(f"提取任务失败: {str(result)}")

                return ExtractionResult(
                    success=True,
                    message="提取成功",
                    metadata=metadata,
                    screenshot=screenshot,
                    full_page_screenshot=full_page_screenshot,
                    dom_tree=dom_tree,
                    style_summary=style_summary,
                    assets=assets,
                    raw_html=raw_html,
                    css_data=css_data,
                    network_data=network_data,
                    downloaded_resources=downloaded_resources,
                    interaction_data=interaction_data
                )

            finally:
                # 关闭页面
                await page.close()

        except PlaywrightTimeout as e:
            logger.error(f"页面加载超时: {str(e)}")
            return ExtractionResult(
                success=False,
                message="页面加载超时",
                error=str(e)
            )
        except Exception as e:
            logger.error(f"提取失败: {str(e)}", exc_info=True)
            return ExtractionResult(
                success=False,
                message="提取失败",
                error=str(e)
            )

    # ==================== 分阶段提取方法 ====================

    async def extract_quick(self, request: ExtractRequest) -> QuickExtractionResult:
        """
        快速提取方法（第一阶段）
        只提取基础数据，立即返回，后续数据在后台继续处理

        Args:
            request: 提取请求参数

        Returns:
            QuickExtractionResult: 快速提取结果，包含 request_id 用于后续轮询
        """
        start_time = datetime.now()

        # 重置网络请求收集器
        self._network_requests = []
        self._api_responses = {}

        # 创建缓存条目
        request_id = await extraction_cache.create(request.url)

        try:
            # 确保浏览器已启动
            await self._ensure_browser()

            # 创建新页面
            page = await self._browser.new_page(
                viewport={
                    'width': request.viewport_width,
                    'height': request.viewport_height
                }
            )

            try:
                # 设置网络监控（如果启用）
                if request.capture_network:
                    await self._setup_network_monitoring(page)

                logger.info(f"[快速提取] 正在加载页面: {request.url}")

                # 导航到目标页面
                await page.goto(
                    request.url,
                    wait_until='domcontentloaded',  # 使用更快的等待策略
                    timeout=60000
                )

                # 减少等待时间，只等待 0.5 秒让基础内容渲染
                await asyncio.sleep(0.5)

                # 如果指定了等待选择器，则等待（但设置较短超时）
                if request.wait_for_selector:
                    try:
                        await page.wait_for_selector(
                            request.wait_for_selector,
                            timeout=5000  # 最多等待 5 秒
                        )
                    except PlaywrightTimeout:
                        logger.debug(f"等待选择器超时，继续处理: {request.wait_for_selector}")

                # 获取页面加载时间
                load_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                # ========== 滚动页面触发懒加载 ==========
                await self._scroll_to_load_lazy_content(page)

                # ========== 主题检测 ==========
                logger.debug(f"[快速提取] 开始主题检测")
                theme_detection = await self._detect_theme_support(page)
                current_theme = theme_detection.current_mode

                # ========== 快速阶段：提取基础数据 ==========
                # 首先确保在当前主题模式下
                current_theme_str = 'light' if current_theme == ThemeMode.LIGHT else 'dark'
                await page.emulate_media(color_scheme=current_theme_str)
                await asyncio.sleep(0.2)

                quick_tasks = [
                    self._extract_metadata(page, request.url, load_time_ms),
                    self._extract_assets(page),
                    self._take_screenshot(page) if request.include_screenshot else asyncio.sleep(0),
                    self._get_raw_html(page),
                ]
                quick_results = await asyncio.gather(*quick_tasks, return_exceptions=True)

                # 解析快速结果
                metadata = quick_results[0] if not isinstance(quick_results[0], Exception) else None
                assets = quick_results[1] if not isinstance(quick_results[1], Exception) else None
                screenshot = quick_results[2] if request.include_screenshot and not isinstance(quick_results[2], Exception) else None
                raw_html = quick_results[3] if not isinstance(quick_results[3], Exception) else None

                # ========== 双模式数据提取（如果支持） ==========
                light_mode_data = None
                dark_mode_data = None

                if theme_detection.support == ThemeSupport.BOTH:
                    logger.debug(f"[快速提取] 检测到双模式支持，提取两种主题数据")

                    # 提取亮色模式数据
                    light_mode_data = await self._extract_themed_data(page, ThemeMode.LIGHT, request)

                    # 提取暗色模式数据
                    dark_mode_data = await self._extract_themed_data(page, ThemeMode.DARK, request)

                    # 恢复到原始主题
                    await page.emulate_media(color_scheme=current_theme_str)

                    # 使用当前主题的截图作为默认截图
                    if current_theme == ThemeMode.LIGHT and light_mode_data.screenshot:
                        screenshot = light_mode_data.screenshot
                    elif current_theme == ThemeMode.DARK and dark_mode_data.screenshot:
                        screenshot = dark_mode_data.screenshot

                # 更新缓存
                await extraction_cache.update_quick_phase(
                    request_id,
                    metadata=metadata,
                    screenshot=screenshot,
                    assets=assets,
                    raw_html=raw_html
                )

                # 启动后台任务继续处理剩余数据
                asyncio.create_task(
                    self._extract_remaining_phases(
                        page, request, request_id, assets, raw_html
                    )
                )

                logger.info(f"[快速提取] 完成: {request.url}, request_id={request_id}, "
                           f"theme_support={theme_detection.support}")

                return QuickExtractionResult(
                    success=True,
                    message="快速提取完成，后台继续处理",
                    request_id=request_id,
                    phase=ExtractionPhase.QUICK,
                    progress=25,
                    metadata=metadata,
                    screenshot=screenshot,
                    assets=assets,
                    raw_html=raw_html,
                    theme_detection=theme_detection,
                    current_theme=current_theme,
                    light_mode_data=light_mode_data,
                    dark_mode_data=dark_mode_data
                )

            except Exception as e:
                # 出错时关闭页面
                await page.close()
                raise

        except PlaywrightTimeout as e:
            logger.error(f"[快速提取] 页面加载超时: {str(e)}")
            await extraction_cache.update_quick_phase(request_id, error=str(e))
            return QuickExtractionResult(
                success=False,
                message="页面加载超时",
                request_id=request_id,
                phase=ExtractionPhase.ERROR,
                progress=0,
                error=str(e)
            )
        except Exception as e:
            logger.error(f"[快速提取] 提取失败: {str(e)}", exc_info=True)
            await extraction_cache.update_quick_phase(request_id, error=str(e))
            return QuickExtractionResult(
                success=False,
                message="提取失败",
                request_id=request_id,
                phase=ExtractionPhase.ERROR,
                progress=0,
                error=str(e)
            )

    async def _extract_remaining_phases(
        self,
        page: Page,
        request: ExtractRequest,
        request_id: str,
        assets: Optional[PageAssets],
        raw_html: Optional[str] = None
    ):
        """
        后台继续提取剩余阶段的数据

        Args:
            page: Playwright 页面对象（保持打开状态）
            request: 原始请求参数
            request_id: 请求 ID
            assets: 已提取的资源列表
            raw_html: 原始 HTML 字符串（用于组件代码位置定位）
        """
        # 在外部定义dom_tree，以便在高级阶段使用
        dom_tree = None

        try:
            # ========== DOM 阶段 ==========
            logger.debug(f"[{request_id}] 开始 DOM 阶段")
            try:
                dom_tree = await self._extract_dom_tree(
                    page, request.max_depth, request.include_hidden
                )
                style_summary = self._compute_style_summary(dom_tree) if dom_tree else None

                await extraction_cache.update_dom_phase(
                    request_id,
                    dom_tree=dom_tree,
                    style_summary=style_summary
                )
            except Exception as e:
                logger.error(f"[{request_id}] DOM 阶段失败: {e}")
                await extraction_cache.update_dom_phase(request_id, error=str(e))

            # ========== 高级阶段 ==========
            logger.debug(f"[{request_id}] 开始高级阶段")
            try:
                advanced_tasks = []

                # CSS 数据提取
                if request.extract_css:
                    advanced_tasks.append(self._extract_css_data(page, request.url))
                else:
                    advanced_tasks.append(asyncio.sleep(0))

                # 全页截图
                if request.full_page_screenshot:
                    advanced_tasks.append(self._take_full_screenshot(page))
                else:
                    advanced_tasks.append(asyncio.sleep(0))

                # 交互状态捕获
                if request.capture_interactions:
                    advanced_tasks.append(self._capture_interactions(page))
                else:
                    advanced_tasks.append(asyncio.sleep(0))

                # 技术栈分析
                advanced_tasks.append(self._analyze_tech_stack(page, request.url))

                # 组件分析（传递dom_tree以便直接从DOM树提取section）
                advanced_tasks.append(self._analyze_components(page, request.url, raw_html, dom_tree))

                advanced_results = await asyncio.gather(*advanced_tasks, return_exceptions=True)

                css_data = advanced_results[0] if request.extract_css and not isinstance(advanced_results[0], Exception) else None
                full_page_screenshot = advanced_results[1] if request.full_page_screenshot and not isinstance(advanced_results[1], Exception) else None
                interaction_data = advanced_results[2] if request.capture_interactions and not isinstance(advanced_results[2], Exception) else None
                tech_stack = advanced_results[3] if not isinstance(advanced_results[3], Exception) else None
                components = advanced_results[4] if not isinstance(advanced_results[4], Exception) else None

                # 网络数据整理
                network_data = None
                if request.capture_network:
                    network_data = self._compile_network_data()

                await extraction_cache.update_advanced_phase(
                    request_id,
                    css_data=css_data,
                    network_data=network_data,
                    full_page_screenshot=full_page_screenshot,
                    interaction_data=interaction_data,
                    tech_stack=tech_stack,
                    components=components
                )
            except Exception as e:
                logger.error(f"[{request_id}] 高级阶段失败: {e}")
                await extraction_cache.update_advanced_phase(request_id, error=str(e))

            # ========== 完成阶段：资源下载 ==========
            logger.debug(f"[{request_id}] 开始完成阶段")
            try:
                downloaded_resources = None
                if request.download_resources and assets:
                    downloaded_resources = await self._download_resources(
                        page, assets, request.url
                    )

                await extraction_cache.update_complete_phase(
                    request_id,
                    downloaded_resources=downloaded_resources
                )
            except Exception as e:
                logger.error(f"[{request_id}] 完成阶段失败: {e}")
                await extraction_cache.update_complete_phase(request_id, error=str(e))

            logger.info(f"[{request_id}] 所有阶段完成")

        except Exception as e:
            logger.error(f"[{request_id}] 后台提取出错: {e}", exc_info=True)
        finally:
            # 关闭页面
            try:
                await page.close()
            except Exception:
                pass

    # ==================== 主题检测方法 ====================

    async def _detect_theme_support(self, page: Page) -> ThemeDetectionResult:
        """
        检测页面是否支持明暗模式切换

        通过以下方式检测：
        1. 检查 CSS 中是否有 prefers-color-scheme 媒体查询
        2. 检查是否有 .dark 类或 data-theme 属性
        3. 实际切换 colorScheme 并对比样式差异

        Args:
            page: Playwright 页面对象

        Returns:
            ThemeDetectionResult: 主题检测结果
        """
        try:
            logger.info("========== 开始主题检测 ==========")

            # 1. 检查 CSS 媒体查询和主题相关属性
            detection_info = await page.evaluate('''() => {
                const result = {
                    has_prefers_color_scheme: false,
                    has_dark_class: false,
                    has_light_class: false,
                    has_theme_attribute: false,
                    current_theme_class: null,
                    current_theme_attr: null,
                    color_scheme_css: null
                };

                // 检查 CSS 中的 prefers-color-scheme
                for (const sheet of document.styleSheets) {
                    try {
                        const rules = sheet.cssRules || sheet.rules;
                        if (!rules) continue;
                        for (const rule of rules) {
                            if (rule instanceof CSSMediaRule) {
                                if (rule.conditionText && rule.conditionText.includes('prefers-color-scheme')) {
                                    result.has_prefers_color_scheme = true;
                                    break;
                                }
                            }
                        }
                    } catch (e) {
                        // 跨域样式表
                    }
                    if (result.has_prefers_color_scheme) break;
                }

                // 检查 html/body 上的 class 和 data 属性
                const html = document.documentElement;
                const body = document.body;

                const darkClasses = ['dark', 'dark-mode', 'dark-theme', 'theme-dark'];
                const lightClasses = ['light', 'light-mode', 'light-theme', 'theme-light'];

                for (const cls of darkClasses) {
                    if (html.classList.contains(cls) || body.classList.contains(cls)) {
                        result.has_dark_class = true;
                        result.current_theme_class = 'dark';
                        break;
                    }
                }

                for (const cls of lightClasses) {
                    if (html.classList.contains(cls) || body.classList.contains(cls)) {
                        result.has_light_class = true;
                        if (!result.current_theme_class) {
                            result.current_theme_class = 'light';
                        }
                        break;
                    }
                }

                // 检查 data-theme 属性
                const themeAttr = html.getAttribute('data-theme') ||
                                  html.getAttribute('data-color-scheme') ||
                                  body.getAttribute('data-theme');
                if (themeAttr) {
                    result.has_theme_attribute = true;
                    result.current_theme_attr = themeAttr;
                }

                // 获取 color-scheme CSS 属性
                const rootStyles = getComputedStyle(html);
                result.color_scheme_css = rootStyles.colorScheme;

                return result;
            }''')

            # 打印检测信息
            logger.info(f"[主题检测] 初始检测结果:")
            logger.info(f"  - has_prefers_color_scheme: {detection_info.get('has_prefers_color_scheme')}")
            logger.info(f"  - has_dark_class: {detection_info.get('has_dark_class')}")
            logger.info(f"  - has_light_class: {detection_info.get('has_light_class')}")
            logger.info(f"  - has_theme_attribute: {detection_info.get('has_theme_attribute')}")
            logger.info(f"  - current_theme_class: {detection_info.get('current_theme_class')}")
            logger.info(f"  - current_theme_attr: {detection_info.get('current_theme_attr')}")
            logger.info(f"  - color_scheme_css: {detection_info.get('color_scheme_css')}")

            # 2. 实际对比两种模式下的样式差异
            # 保存原始状态以便恢复
            original_classes = await page.evaluate('''() => {
                return {
                    htmlClasses: document.documentElement.className,
                    bodyClasses: document.body.className,
                    dataTheme: document.documentElement.getAttribute('data-theme'),
                    dataColorScheme: document.documentElement.getAttribute('data-color-scheme')
                };
            }''')

            # 先获取当前模式的关键样式
            logger.info("[主题检测] 开始捕获 light 模式样式...")
            light_styles = await self._capture_theme_styles(page, 'light')
            logger.info("[主题检测] 开始捕获 dark 模式样式...")
            dark_styles = await self._capture_theme_styles(page, 'dark')

            # 打印捕获的样式
            logger.info(f"[主题检测] Light 模式样式:")
            logger.info(f"  - html_bg: {light_styles.get('html_bg', 'N/A')}")
            logger.info(f"  - body_bg: {light_styles.get('body_bg', 'N/A')}")
            logger.info(f"  - body_color: {light_styles.get('body_color', 'N/A')}")
            logger.info(f"  - css_variables 数量: {len(light_styles.get('css_variables', {}))}")
            logger.info(f"  - key_element_colors 数量: {len(light_styles.get('key_element_colors', []))}")

            logger.info(f"[主题检测] Dark 模式样式:")
            logger.info(f"  - html_bg: {dark_styles.get('html_bg', 'N/A')}")
            logger.info(f"  - body_bg: {dark_styles.get('body_bg', 'N/A')}")
            logger.info(f"  - body_color: {dark_styles.get('body_color', 'N/A')}")
            logger.info(f"  - css_variables 数量: {len(dark_styles.get('css_variables', {}))}")
            logger.info(f"  - key_element_colors 数量: {len(dark_styles.get('key_element_colors', []))}")

            # 恢复原始状态
            await page.evaluate('''(original) => {
                document.documentElement.className = original.htmlClasses;
                document.body.className = original.bodyClasses;
                if (original.dataTheme) {
                    document.documentElement.setAttribute('data-theme', original.dataTheme);
                } else {
                    document.documentElement.removeAttribute('data-theme');
                }
                if (original.dataColorScheme) {
                    document.documentElement.setAttribute('data-color-scheme', original.dataColorScheme);
                } else {
                    document.documentElement.removeAttribute('data-color-scheme');
                }
            }''', original_classes)

            # 计算差异
            color_diff_count = 0
            css_var_diff_count = 0
            image_diff_count = 0
            key_element_diff_count = 0

            # 比较 html 背景颜色
            if light_styles.get('html_bg') != dark_styles.get('html_bg'):
                # 排除透明背景的情况
                if (light_styles.get('html_bg') not in ['rgba(0, 0, 0, 0)', 'transparent'] or
                    dark_styles.get('html_bg') not in ['rgba(0, 0, 0, 0)', 'transparent']):
                    color_diff_count += 1

            # 比较 body 背景颜色和文字颜色
            if light_styles.get('body_bg') != dark_styles.get('body_bg'):
                if (light_styles.get('body_bg') not in ['rgba(0, 0, 0, 0)', 'transparent'] or
                    dark_styles.get('body_bg') not in ['rgba(0, 0, 0, 0)', 'transparent']):
                    color_diff_count += 1
            if light_styles.get('body_color') != dark_styles.get('body_color'):
                color_diff_count += 1

            # 比较关键元素的颜色
            light_key_colors = {item['selector']: item for item in light_styles.get('key_element_colors', [])}
            dark_key_colors = {item['selector']: item for item in dark_styles.get('key_element_colors', [])}
            for selector in set(light_key_colors.keys()) & set(dark_key_colors.keys()):
                light_item = light_key_colors[selector]
                dark_item = dark_key_colors[selector]
                if light_item.get('bg') != dark_item.get('bg'):
                    key_element_diff_count += 1
                if light_item.get('color') != dark_item.get('color'):
                    key_element_diff_count += 1

            # 比较 CSS 变量
            light_vars = light_styles.get('css_variables', {})
            dark_vars = dark_styles.get('css_variables', {})
            for var_name in set(light_vars.keys()) | set(dark_vars.keys()):
                if light_vars.get(var_name) != dark_vars.get(var_name):
                    css_var_diff_count += 1

            # 比较图片 URL
            light_images = set(light_styles.get('image_urls', []))
            dark_images = set(dark_styles.get('image_urls', []))
            image_diff_count = len(light_images.symmetric_difference(dark_images))

            # 判断是否有显著差异
            # 降低阈值，更敏感地检测主题支持
            has_significant_difference = (
                color_diff_count >= 1 or          # 至少 1 个颜色差异
                key_element_diff_count >= 1 or    # 至少 1 个关键元素颜色差异
                css_var_diff_count >= 1 or        # 至少 1 个 CSS 变量差异
                image_diff_count >= 1             # 或图片差异
            )

            logger.info(f"[主题检测] ========== 差异分析结果 ==========")
            logger.info(f"  - color_diff_count: {color_diff_count}")
            logger.info(f"  - key_element_diff_count: {key_element_diff_count}")
            logger.info(f"  - css_var_diff_count: {css_var_diff_count}")
            logger.info(f"  - image_diff_count: {image_diff_count}")
            logger.info(f"  - has_significant_difference: {has_significant_difference}")

            # 确定主题支持类型
            if has_significant_difference:
                support = ThemeSupport.BOTH
                detection_method = "style_comparison"
            elif detection_info.get('has_prefers_color_scheme'):
                # 有媒体查询但差异不大，可能是局部支持
                support = ThemeSupport.BOTH
                detection_method = "css_media"
            elif detection_info.get('has_dark_class') and not detection_info.get('has_light_class'):
                support = ThemeSupport.DARK_ONLY
                detection_method = "class_detection"
            elif detection_info.get('has_light_class') and not detection_info.get('has_dark_class'):
                support = ThemeSupport.LIGHT_ONLY
                detection_method = "class_detection"
            else:
                support = ThemeSupport.LIGHT_ONLY
                detection_method = "default"

            # 确定当前模式
            current_mode = ThemeMode.LIGHT
            if detection_info.get('current_theme_class') == 'dark':
                current_mode = ThemeMode.DARK
            else:
                # 安全处理 None 值
                theme_attr = detection_info.get('current_theme_attr') or ''
                if theme_attr.lower() in ['dark', 'dark-mode']:
                    current_mode = ThemeMode.DARK

            logger.info(f"[主题检测] ========== 最终结果 ==========")
            logger.info(f"  - support: {support}")
            logger.info(f"  - current_mode: {current_mode}")
            logger.info(f"  - detection_method: {detection_method}")
            logger.info(f"========================================")

            return ThemeDetectionResult(
                support=support,
                current_mode=current_mode,
                has_significant_difference=has_significant_difference,
                detection_method=detection_method,
                css_variables_diff_count=css_var_diff_count,
                color_diff_count=color_diff_count,
                image_diff_count=image_diff_count
            )

        except Exception as e:
            logger.error(f"主题检测失败: {e}", exc_info=True)
            return ThemeDetectionResult(
                support=ThemeSupport.UNKNOWN,
                current_mode=ThemeMode.LIGHT,
                detection_method="error"
            )

    async def _capture_theme_styles(self, page: Page, theme: str) -> Dict[str, Any]:
        """
        在指定主题模式下捕获关键样式

        支持两种主题切换方式：
        1. CSS 媒体查询 (prefers-color-scheme) - 使用 emulate_media
        2. Class-based (.dark class on html/body) - 手动添加/移除 class

        Args:
            page: Playwright 页面对象
            theme: 'light' 或 'dark'

        Returns:
            Dict: 包含关键样式信息的字典
        """
        try:
            # 1. 通过 emulate_media 触发 CSS 媒体查询
            await page.emulate_media(color_scheme=theme)

            # 2. 同时通过添加/移除 class 触发 class-based 主题
            # 这样可以同时支持两种切换方式
            await page.evaluate('''(theme) => {
                const html = document.documentElement;
                const body = document.body;

                // 要切换的 class 列表
                const darkClasses = ['dark', 'dark-mode', 'dark-theme', 'theme-dark'];
                const lightClasses = ['light', 'light-mode', 'light-theme', 'theme-light'];

                // 同时也检查 data-theme 属性
                if (theme === 'dark') {
                    // 添加 dark 相关 class
                    darkClasses.forEach(cls => {
                        html.classList.add(cls);
                    });
                    // 移除 light 相关 class
                    lightClasses.forEach(cls => {
                        html.classList.remove(cls);
                        body.classList.remove(cls);
                    });
                    // 设置 data-theme 属性
                    html.setAttribute('data-theme', 'dark');
                    html.setAttribute('data-color-scheme', 'dark');
                    html.style.colorScheme = 'dark';
                } else {
                    // 移除 dark 相关 class
                    darkClasses.forEach(cls => {
                        html.classList.remove(cls);
                        body.classList.remove(cls);
                    });
                    // 添加 light 相关 class（只有在检测到有 light class 时）
                    // 设置 data-theme 属性
                    html.setAttribute('data-theme', 'light');
                    html.setAttribute('data-color-scheme', 'light');
                    html.style.colorScheme = 'light';
                }
            }''', theme)

            # 等待样式应用（给更多时间让 CSS 变量更新）
            await asyncio.sleep(0.5)

            # 捕获关键样式
            styles = await page.evaluate('''() => {
                const result = {
                    body_bg: '',
                    body_color: '',
                    html_bg: '',
                    css_variables: {},
                    image_urls: [],
                    key_element_colors: []
                };

                // 获取 html 背景（有些网站在 html 上设置背景）
                const htmlStyles = getComputedStyle(document.documentElement);
                result.html_bg = htmlStyles.backgroundColor;

                // 获取 body 背景和颜色
                const bodyStyles = getComputedStyle(document.body);
                result.body_bg = bodyStyles.backgroundColor;
                result.body_color = bodyStyles.color;

                // 获取 CSS 变量（扩展变量名列表）
                const rootStyles = getComputedStyle(document.documentElement);

                // 通用变量名模式
                const varPatterns = [
                    // shadcn/ui 和通用模式
                    '--background', '--foreground', '--primary', '--secondary',
                    '--accent', '--muted', '--card', '--popover', '--border',
                    '--destructive', '--ring', '--input',
                    // 颜色相关
                    '--bg-primary', '--bg-secondary', '--text-primary', '--text-secondary',
                    '--color-bg', '--color-text', '--color-primary', '--color-secondary',
                    // Tailwind CSS 变量
                    '--tw-bg-opacity', '--tw-text-opacity',
                    // Chakra UI
                    '--chakra-colors-bg', '--chakra-colors-text',
                    // 其他常见模式
                    '--surface', '--on-surface', '--surface-variant',
                    '--neutral', '--neutral-content',
                    // 深色模式特定
                    '--dark-bg', '--dark-text', '--light-bg', '--light-text'
                ];

                // 获取所有 CSS 变量（从 :root 计算值）
                for (const name of varPatterns) {
                    const value = rootStyles.getPropertyValue(name).trim();
                    if (value) {
                        result.css_variables[name] = value;
                    }
                }

                // 动态获取所有 -- 开头的变量
                try {
                    for (const sheet of document.styleSheets) {
                        try {
                            const rules = sheet.cssRules || sheet.rules;
                            if (!rules) continue;
                            for (const rule of rules) {
                                if (rule instanceof CSSStyleRule &&
                                    (rule.selectorText === ':root' ||
                                     rule.selectorText === 'html' ||
                                     rule.selectorText === '.dark' ||
                                     rule.selectorText === 'html.dark')) {
                                    for (let i = 0; i < rule.style.length; i++) {
                                        const prop = rule.style[i];
                                        if (prop.startsWith('--')) {
                                            const value = rootStyles.getPropertyValue(prop).trim();
                                            if (value) {
                                                result.css_variables[prop] = value;
                                            }
                                        }
                                    }
                                }
                            }
                        } catch (e) {
                            // 跨域样式表
                        }
                    }
                } catch (e) {}

                // 获取关键元素的颜色（header, nav, main, footer）
                const keySelectors = ['header', 'nav', 'main', 'footer', '[class*="hero"]', '[class*="section"]'];
                keySelectors.forEach(selector => {
                    try {
                        const el = document.querySelector(selector);
                        if (el) {
                            const styles = getComputedStyle(el);
                            result.key_element_colors.push({
                                selector: selector,
                                bg: styles.backgroundColor,
                                color: styles.color
                            });
                        }
                    } catch (e) {}
                });

                // 获取图片 URL（只取前 10 张）
                const images = document.querySelectorAll('img[src]');
                for (let i = 0; i < Math.min(images.length, 10); i++) {
                    result.image_urls.push(images[i].src);
                }

                // 检查背景图片
                const bgElements = document.querySelectorAll('[style*="background"], [class*="bg-"]');
                bgElements.forEach(el => {
                    if (result.image_urls.length >= 20) return;
                    const bg = getComputedStyle(el).backgroundImage;
                    if (bg && bg !== 'none' && bg.includes('url(')) {
                        const match = bg.match(/url\\(["']?([^"')]+)["']?\\)/);
                        if (match && match[1]) {
                            result.image_urls.push(match[1]);
                        }
                    }
                });

                return result;
            }''')

            return styles

        except Exception as e:
            logger.error(f"捕获主题样式失败 ({theme}): {e}")
            return {}

    async def _extract_themed_data(
        self,
        page: Page,
        theme: ThemeMode,
        request: ExtractRequest
    ) -> ThemedData:
        """
        在指定主题模式下提取数据

        支持两种主题切换方式：
        1. CSS 媒体查询 (prefers-color-scheme) - 使用 emulate_media
        2. Class-based (.dark class on html/body) - 手动添加/移除 class

        Args:
            page: Playwright 页面对象
            theme: 主题模式
            request: 提取请求参数

        Returns:
            ThemedData: 该主题模式下的数据
        """
        try:
            # 切换到指定主题
            theme_str = 'light' if theme == ThemeMode.LIGHT else 'dark'

            # 1. 通过 emulate_media 触发 CSS 媒体查询
            await page.emulate_media(color_scheme=theme_str)

            # 2. 同时通过添加/移除 class 触发 class-based 主题
            await page.evaluate('''(theme) => {
                const html = document.documentElement;
                const body = document.body;
                const darkClasses = ['dark', 'dark-mode', 'dark-theme', 'theme-dark'];
                const lightClasses = ['light', 'light-mode', 'light-theme', 'theme-light'];

                if (theme === 'dark') {
                    darkClasses.forEach(cls => html.classList.add(cls));
                    lightClasses.forEach(cls => {
                        html.classList.remove(cls);
                        body.classList.remove(cls);
                    });
                    html.setAttribute('data-theme', 'dark');
                    html.setAttribute('data-color-scheme', 'dark');
                    html.style.colorScheme = 'dark';
                } else {
                    darkClasses.forEach(cls => {
                        html.classList.remove(cls);
                        body.classList.remove(cls);
                    });
                    html.setAttribute('data-theme', 'light');
                    html.setAttribute('data-color-scheme', 'light');
                    html.style.colorScheme = 'light';
                }
            }''', theme_str)

            await asyncio.sleep(0.3)  # 等待样式开始应用

            # 注意：主流程已经完成了完整滚动，切换主题后不需要再次滚动
            # 主题切换只影响 CSS 变量和样式，不会触发新的懒加载

            logger.info(f"[主题数据提取] 正在提取 {theme_str} 模式数据...")

            # 初始化所有变量，确保即使部分失败也能返回已获取的数据
            screenshot = None
            full_page_screenshot = None
            assets = None
            style_summary = None
            css_data = None
            downloaded_resources = None

            # 1. 提取截图（最重要，优先获取）
            try:
                screenshot = await self._take_screenshot(page)
                logger.info(f"[主题数据提取] {theme_str} 截图完成, size: {len(screenshot) if screenshot else 0}")
            except Exception as e:
                logger.error(f"[主题数据提取] {theme_str} 截图失败: {e}")

            # 2. 提取全页截图
            if request.full_page_screenshot:
                try:
                    full_page_screenshot = await self._take_full_page_screenshot(page)
                    logger.debug(f"[主题数据提取] {theme_str} 全页截图完成")
                except Exception as e:
                    logger.error(f"[主题数据提取] {theme_str} 全页截图失败: {e}")

            # 3. 提取资源（图片 URL 可能不同）
            try:
                assets = await self._extract_assets(page)
                logger.debug(f"[主题数据提取] {theme_str} 资源提取完成: {assets.total_images if assets else 0} images")
            except Exception as e:
                logger.error(f"[主题数据提取] {theme_str} 资源提取失败: {e}")

            # 4. 提取 CSS 数据（主要是 CSS 变量会变化）
            if request.extract_css:
                try:
                    css_data = await self._extract_css_data(page, request.url)
                    logger.debug(f"[主题数据提取] {theme_str} CSS 数据完成: {len(css_data.variables) if css_data else 0} variables")
                except Exception as e:
                    logger.error(f"[主题数据提取] {theme_str} CSS 数据提取失败: {e}")

            # 5. 下载资源（图片内容可能不同）
            if request.download_resources:
                try:
                    downloaded_resources = await self._download_resources(page, assets, request.url)
                    logger.debug(f"[主题数据提取] {theme_str} 资源下载完成")
                except Exception as e:
                    logger.error(f"[主题数据提取] {theme_str} 资源下载失败: {e}")

            logger.info(f"[主题数据提取] {theme_str} 模式数据提取完成, screenshot={screenshot is not None}")

            return ThemedData(
                screenshot=screenshot,
                full_page_screenshot=full_page_screenshot,
                style_summary=style_summary,
                css_data=css_data,
                assets=assets,
                downloaded_resources=downloaded_resources
            )

        except Exception as e:
            logger.error(f"提取 {theme} 模式数据失败: {e}", exc_info=True)
            return ThemedData()

    async def _extract_metadata(self, page: Page, url: str, load_time_ms: int) -> PageMetadata:
        """
        提取页面元数据

        Args:
            page: Playwright 页面对象
            url: 页面 URL
            load_time_ms: 加载时间

        Returns:
            PageMetadata: 页面元数据
        """
        # 在浏览器中执行 JS 获取页面信息
        page_info = await page.evaluate('''() => {
            return {
                title: document.title,
                viewportWidth: window.innerWidth,
                viewportHeight: window.innerHeight,
                pageWidth: document.documentElement.scrollWidth,
                pageHeight: document.documentElement.scrollHeight,
                totalElements: document.querySelectorAll('*').length
            };
        }''')

        # 计算 DOM 深度
        max_depth = await page.evaluate('''() => {
            function getDepth(element, currentDepth) {
                if (!element.children || element.children.length === 0) {
                    return currentDepth;
                }
                let maxChildDepth = currentDepth;
                for (const child of element.children) {
                    const childDepth = getDepth(child, currentDepth + 1);
                    if (childDepth > maxChildDepth) {
                        maxChildDepth = childDepth;
                    }
                }
                return maxChildDepth;
            }
            return getDepth(document.body, 1);
        }''')

        return PageMetadata(
            url=url,
            title=page_info['title'],
            viewport_width=page_info['viewportWidth'],
            viewport_height=page_info['viewportHeight'],
            page_width=page_info['pageWidth'],
            page_height=page_info['pageHeight'],
            total_elements=page_info['totalElements'],
            max_depth=max_depth,
            load_time_ms=load_time_ms
        )

    async def _extract_dom_tree(self, page: Page, max_depth: int, include_hidden: bool) -> ElementInfo:
        """
        提取 DOM 树结构

        Args:
            page: Playwright 页面对象
            max_depth: 最大遍历深度
            include_hidden: 是否包含隐藏元素

        Returns:
            ElementInfo: 根元素（body）的完整信息
        """
        # 在浏览器中执行提取脚本
        dom_data = await page.evaluate('''(params) => {
            const { maxDepth, includeHidden } = params;

            // 关键样式属性列表
            const STYLE_PROPS = [
                // 布局
                'display', 'position', 'float', 'clear',
                // Flexbox
                'flexDirection', 'flexWrap', 'justifyContent', 'alignItems', 'alignContent', 'gap',
                // Grid
                'gridTemplateColumns', 'gridTemplateRows', 'gridColumn', 'gridRow',
                // 尺寸
                'width', 'height', 'minWidth', 'minHeight', 'maxWidth', 'maxHeight',
                // 间距
                'margin', 'marginTop', 'marginRight', 'marginBottom', 'marginLeft',
                'padding', 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft',
                // 定位
                'top', 'right', 'bottom', 'left', 'zIndex',
                // 视觉
                'backgroundColor', 'backgroundImage', 'color', 'border', 'borderRadius',
                'boxShadow', 'opacity', 'overflow', 'visibility',
                // 文字
                'fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'textAlign',
                // 变换
                'transform'
            ];

            // 可交互元素标签
            const INTERACTIVE_TAGS = ['A', 'BUTTON', 'INPUT', 'SELECT', 'TEXTAREA', 'LABEL', 'DETAILS', 'SUMMARY'];

            // 需要提取的属性
            const IMPORTANT_ATTRS = ['href', 'src', 'alt', 'title', 'type', 'name', 'value', 'placeholder', 'role', 'aria-label'];

            // 将驼峰转为短横线
            function camelToKebab(str) {
                return str.replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase();
            }

            // 将短横线转为下划线（适配 Python）
            function kebabToSnake(str) {
                return str.replace(/-/g, '_');
            }

            // 检查元素是否可见
            function isElementVisible(el, styles) {
                if (styles.display === 'none' || styles.visibility === 'hidden' || styles.opacity === '0') {
                    return false;
                }
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            }

            // 生成简单的 CSS 选择器
            function getSelector(el) {
                if (el.id) {
                    return '#' + el.id;
                }
                let selector = el.tagName.toLowerCase();
                if (el.className && typeof el.className === 'string') {
                    selector += '.' + el.className.trim().split(/\s+/).join('.');
                }
                return selector;
            }

            // 获取直接文本内容（不含子元素文本）
            function getDirectTextContent(el) {
                let text = '';
                for (const node of el.childNodes) {
                    if (node.nodeType === Node.TEXT_NODE) {
                        text += node.textContent;
                    }
                }
                return text.trim().slice(0, 200);  // 限制长度
            }

            // 递归提取元素信息
            function extractElement(el, depth, path) {
                if (depth > maxDepth) {
                    return null;
                }

                const styles = window.getComputedStyle(el);
                const isVisible = isElementVisible(el, styles);

                // 如果不包含隐藏元素且元素不可见，跳过
                if (!includeHidden && !isVisible) {
                    return null;
                }

                const rect = el.getBoundingClientRect();

                // 提取样式
                const styleObj = {};
                for (const prop of STYLE_PROPS) {
                    const value = styles[prop];
                    if (value && value !== 'none' && value !== 'normal' && value !== 'auto' && value !== '0px') {
                        const snakeProp = kebabToSnake(camelToKebab(prop));
                        // 特殊处理 float（Python 保留字）
                        styleObj[snakeProp === 'float' ? 'float_' : snakeProp] = value;
                    }
                }

                // 提取属性
                const attrs = {};
                for (const attrName of IMPORTANT_ATTRS) {
                    if (el.hasAttribute(attrName)) {
                        attrs[attrName] = el.getAttribute(attrName);
                    }
                }

                // 提取子元素
                const children = [];
                let childIndex = 0;
                for (const child of el.children) {
                    const childInfo = extractElement(child, depth + 1, path + '/' + child.tagName.toLowerCase() + '[' + childIndex + ']');
                    if (childInfo) {
                        children.push(childInfo);
                    }
                    childIndex++;
                }

                // Calculate effective HTML length (excluding base64 images, SVGs, etc.)
                // This gives a more accurate token estimate for AI processing
                function getEffectiveHtmlLength(element) {
                    let html = element.innerHTML;

                    // 1. Replace base64 image data with placeholder
                    // data:image/png;base64,iVBORw0... → [IMG:base64]
                    html = html.replace(/data:image\/[^;]+;base64,[A-Za-z0-9+/=]+/gi, '[IMG:base64]');

                    // 2. Replace data URLs in general
                    html = html.replace(/data:[^,]+,[A-Za-z0-9+/=]{100,}/gi, '[DATA:url]');

                    // 3. Replace inline SVG content (keep just the tag)
                    // <svg ...>long path data...</svg> → <svg>[SVG_CONTENT]</svg>
                    html = html.replace(/<svg[^>]*>[\s\S]*?<\/svg>/gi, '<svg>[SVG_CONTENT]</svg>');

                    // 4. Replace very long style attributes
                    // style="very long inline styles..." → style="[STYLES]"
                    html = html.replace(/style="[^"]{200,}"/gi, 'style="[LONG_STYLES]"');

                    // 5. Replace srcset with long URLs
                    html = html.replace(/srcset="[^"]{500,}"/gi, 'srcset="[SRCSET]"');

                    return html.length;
                }

                const effectiveLength = getEffectiveHtmlLength(el);
                const rawLength = el.innerHTML.length;

                return {
                    tag: el.tagName.toLowerCase(),
                    id: el.id || null,
                    classes: el.className && typeof el.className === 'string'
                        ? el.className.trim().split(/\s+/).filter(c => c)
                        : [],
                    rect: {
                        x: rect.x,
                        y: rect.y,
                        width: rect.width,
                        height: rect.height,
                        top: rect.top,
                        right: rect.right,
                        bottom: rect.bottom,
                        left: rect.left
                    },
                    styles: styleObj,
                    text_content: getDirectTextContent(el),
                    inner_html_length: effectiveLength,
                    raw_html_length: rawLength,
                    attributes: attrs,
                    is_visible: isVisible,
                    is_interactive: INTERACTIVE_TAGS.includes(el.tagName),
                    children: children,
                    children_count: el.children.length,
                    xpath: path,
                    selector: getSelector(el)
                };
            }

            return extractElement(document.body, 1, '/body');
        }''', {'maxDepth': max_depth, 'includeHidden': include_hidden})

        return self._parse_element_data(dom_data)

    def _parse_element_data(self, data: Dict[str, Any]) -> ElementInfo:
        """
        将 JS 返回的数据转换为 ElementInfo 对象

        Args:
            data: JS 返回的原始数据

        Returns:
            ElementInfo: 解析后的元素信息
        """
        if not data:
            return None

        # 解析子元素
        children = []
        for child_data in data.get('children', []):
            child = self._parse_element_data(child_data)
            if child:
                children.append(child)

        return ElementInfo(
            tag=data['tag'],
            id=data.get('id'),
            classes=data.get('classes', []),
            rect=ElementRect(**data['rect']),
            styles=ElementStyles(**data.get('styles', {})),
            text_content=data.get('text_content'),
            inner_html_length=data.get('inner_html_length', 0),
            raw_html_length=data.get('raw_html_length', data.get('inner_html_length', 0)),
            attributes=data.get('attributes', {}),
            is_visible=data.get('is_visible', True),
            is_interactive=data.get('is_interactive', False),
            children=children,
            children_count=data.get('children_count', 0),
            xpath=data.get('xpath'),
            selector=data.get('selector')
        )

    async def _extract_assets(self, page: Page) -> PageAssets:
        """
        提取页面资源

        Args:
            page: Playwright 页面对象

        Returns:
            PageAssets: 页面资源统计
        """
        assets_data = await page.evaluate('''() => {
            const result = {
                images: [],
                scripts: [],
                stylesheets: [],
                fonts: []
            };

            // 图片
            document.querySelectorAll('img').forEach(img => {
                if (img.src) {
                    result.images.push({
                        url: img.src,
                        type: 'image'
                    });
                }
            });

            // 背景图片
            document.querySelectorAll('*').forEach(el => {
                const bg = window.getComputedStyle(el).backgroundImage;
                if (bg && bg !== 'none' && bg.includes('url(')) {
                    const match = bg.match(/url\\(["']?([^"')]+)["']?\\)/);
                    if (match && match[1]) {
                        result.images.push({
                            url: match[1],
                            type: 'background-image'
                        });
                    }
                }
            });

            // 脚本
            document.querySelectorAll('script[src]').forEach(script => {
                result.scripts.push({
                    url: script.src,
                    type: 'script'
                });
            });

            // 样式表
            document.querySelectorAll('link[rel="stylesheet"]').forEach(link => {
                result.stylesheets.push({
                    url: link.href,
                    type: 'stylesheet'
                });
            });

            // 字体（从 @font-face 规则）
            for (const sheet of document.styleSheets) {
                try {
                    for (const rule of sheet.cssRules || []) {
                        if (rule instanceof CSSFontFaceRule) {
                            const src = rule.style.getPropertyValue('src');
                            const urlMatch = src.match(/url\\(["']?([^"')]+)["']?\\)/);
                            if (urlMatch && urlMatch[1]) {
                                result.fonts.push({
                                    url: urlMatch[1],
                                    type: 'font'
                                });
                            }
                        }
                    }
                } catch (e) {
                    // 跨域样式表无法访问
                }
            }

            return result;
        }''')

        # 去重
        def dedupe(items):
            seen = set()
            result = []
            for item in items:
                if item['url'] not in seen:
                    seen.add(item['url'])
                    result.append(AssetInfo(**item))
            return result

        images = dedupe(assets_data['images'])
        scripts = dedupe(assets_data['scripts'])
        stylesheets = dedupe(assets_data['stylesheets'])
        fonts = dedupe(assets_data['fonts'])

        return PageAssets(
            images=images,
            scripts=scripts,
            stylesheets=stylesheets,
            fonts=fonts,
            total_images=len(images),
            total_scripts=len(scripts),
            total_stylesheets=len(stylesheets),
            total_fonts=len(fonts)
        )

    async def _scroll_to_load_lazy_content(
        self,
        page: Page,
        max_scrolls: int = 50,
        scroll_delay: float = 0.3
    ) -> None:
        """
        滚动页面以触发懒加载内容

        通过渐进式滚动整个页面，触发 IntersectionObserver
        和其他懒加载机制，确保所有内容都被渲染

        Args:
            page: Playwright 页面对象
            max_scrolls: 最大滚动次数（防止无限滚动页面卡死）
            scroll_delay: 每次滚动后的等待时间（秒）
        """
        try:
            logger.debug("开始滚动加载懒加载内容...")

            # 获取初始页面高度和视口高度
            dimensions = await page.evaluate('''() => {
                return {
                    viewportHeight: window.innerHeight,
                    scrollHeight: document.body.scrollHeight
                };
            }''')

            viewport_height = dimensions['viewportHeight']
            last_scroll_height = dimensions['scrollHeight']
            current_position = 0
            scroll_count = 0

            # 渐进式滚动
            while scroll_count < max_scrolls:
                # 滚动到下一个位置
                current_position += viewport_height
                await page.evaluate(f'window.scrollTo(0, {current_position})')

                # 等待懒加载内容触发
                await asyncio.sleep(scroll_delay)

                # 获取新的页面高度（可能因为懒加载而增加）
                new_scroll_height = await page.evaluate('document.body.scrollHeight')

                scroll_count += 1

                # 如果已经滚动到底部
                if current_position >= new_scroll_height:
                    # 检查是否有新内容加载（页面高度增加）
                    if new_scroll_height > last_scroll_height:
                        # 页面高度增加了，继续滚动
                        last_scroll_height = new_scroll_height
                    else:
                        # 已到底部且没有新内容，退出
                        break

                last_scroll_height = new_scroll_height

            logger.debug(f"滚动完成，共滚动 {scroll_count} 次")

            # 滚动回顶部
            await page.evaluate('window.scrollTo(0, 0)')

            # 等待渲染稳定
            await asyncio.sleep(0.5)

        except Exception as e:
            logger.warning(f"滚动加载懒加载内容时出错: {e}")
            # 确保回到顶部
            try:
                await page.evaluate('window.scrollTo(0, 0)')
            except Exception:
                pass

    async def _take_screenshot(self, page: Page) -> str:
        """
        获取页面截图（完整页面）

        Args:
            page: Playwright 页面对象

        Returns:
            str: Base64 编码的截图
        """
        screenshot_bytes = await page.screenshot(
            type='png',
            full_page=True  # 截取完整页面
        )
        return base64.b64encode(screenshot_bytes).decode('utf-8')

    def _compute_style_summary(self, dom_tree: ElementInfo) -> StyleSummary:
        """
        从 DOM 树计算样式汇总

        Args:
            dom_tree: DOM 树根节点

        Returns:
            StyleSummary: 样式汇总统计
        """
        summary = StyleSummary()

        def traverse(element: ElementInfo):
            styles = element.styles

            # 颜色统计
            if styles.color:
                summary.colors[styles.color] = summary.colors.get(styles.color, 0) + 1
            if styles.background_color:
                summary.background_colors[styles.background_color] = \
                    summary.background_colors.get(styles.background_color, 0) + 1

            # 字体统计
            if styles.font_family:
                summary.font_families[styles.font_family] = \
                    summary.font_families.get(styles.font_family, 0) + 1
            if styles.font_size:
                summary.font_sizes[styles.font_size] = \
                    summary.font_sizes.get(styles.font_size, 0) + 1

            # 间距统计
            if styles.margin and styles.margin != '0px':
                summary.margins[styles.margin] = summary.margins.get(styles.margin, 0) + 1
            if styles.padding and styles.padding != '0px':
                summary.paddings[styles.padding] = summary.paddings.get(styles.padding, 0) + 1

            # 布局统计
            if styles.display:
                summary.display_types[styles.display] = \
                    summary.display_types.get(styles.display, 0) + 1
            if styles.position:
                summary.position_types[styles.position] = \
                    summary.position_types.get(styles.position, 0) + 1

            # 递归处理子元素
            for child in element.children:
                traverse(child)

        traverse(dom_tree)

        # 按使用次数排序（只保留前 20 个）
        def sort_and_limit(d: Dict[str, int], limit: int = 20) -> Dict[str, int]:
            sorted_items = sorted(d.items(), key=lambda x: x[1], reverse=True)[:limit]
            return dict(sorted_items)

        summary.colors = sort_and_limit(summary.colors)
        summary.background_colors = sort_and_limit(summary.background_colors)
        summary.font_families = sort_and_limit(summary.font_families)
        summary.font_sizes = sort_and_limit(summary.font_sizes)
        summary.margins = sort_and_limit(summary.margins)
        summary.paddings = sort_and_limit(summary.paddings)
        summary.display_types = sort_and_limit(summary.display_types)
        summary.position_types = sort_and_limit(summary.position_types)

        return summary

    # ==================== 新增方法：原始 HTML ====================

    async def _get_raw_html(self, page: Page) -> str:
        """
        获取页面原始 HTML

        Args:
            page: Playwright 页面对象

        Returns:
            str: 完整的 HTML 源码
        """
        return await page.content()

    # ==================== 新增方法：网络监控 ====================

    async def _setup_network_monitoring(self, page: Page):
        """
        设置网络请求监控

        Args:
            page: Playwright 页面对象
        """
        async def handle_request(request: Request):
            """处理请求"""
            request_data = {
                'url': request.url,
                'method': request.method,
                'headers': dict(request.headers),
                'post_data': request.post_data,
                'resource_type': request.resource_type,
                'start_time': datetime.now()
            }
            self._network_requests.append(request_data)

        async def handle_response(response: Response):
            """处理响应"""
            try:
                # 查找对应的请求
                for req in self._network_requests:
                    if req['url'] == response.url:
                        req['response_status'] = response.status
                        req['response_headers'] = dict(response.headers)

                        # 计算耗时
                        if 'start_time' in req:
                            req['timing'] = (datetime.now() - req['start_time']).total_seconds() * 1000

                        # 对于 XHR/Fetch 请求，尝试获取响应体
                        resource_type = req.get('resource_type', '')
                        if resource_type in ['xhr', 'fetch']:
                            try:
                                body = await response.text()
                                # 限制响应体大小（最大 1MB）
                                if len(body) < 1024 * 1024:
                                    req['response_body'] = body
                                    req['response_size'] = len(body)
                            except Exception:
                                pass

                        break
            except Exception as e:
                logger.debug(f"处理响应失败: {str(e)}")

        page.on('request', handle_request)
        page.on('response', handle_response)

    def _compile_network_data(self) -> NetworkData:
        """
        整理网络请求数据

        Returns:
            NetworkData: 网络数据汇总
        """
        requests = []
        api_calls = []
        total_size = 0

        for req_data in self._network_requests:
            network_req = NetworkRequest(
                url=req_data['url'],
                method=req_data['method'],
                request_type=req_data.get('resource_type', 'other'),
                headers=req_data.get('headers', {}),
                post_data=req_data.get('post_data'),
                response_status=req_data.get('response_status'),
                response_headers=req_data.get('response_headers', {}),
                response_body=req_data.get('response_body'),
                response_size=req_data.get('response_size'),
                timing=req_data.get('timing')
            )
            requests.append(network_req)

            if req_data.get('response_size'):
                total_size += req_data['response_size']

            # 分离 API 调用
            if req_data.get('resource_type') in ['xhr', 'fetch']:
                api_calls.append(network_req)

        return NetworkData(
            requests=requests,
            api_calls=api_calls,
            total_requests=len(requests),
            total_size=total_size
        )

    # ==================== 新增方法：CSS 数据提取 ====================

    async def _extract_css_data(self, page: Page, base_url: str) -> CSSData:
        """
        提取完整的 CSS 数据

        Args:
            page: Playwright 页面对象
            base_url: 页面基础 URL

        Returns:
            CSSData: 完整的 CSS 数据
        """
        css_data = await page.evaluate('''() => {
            const result = {
                stylesheets: [],
                animations: [],
                transitions: [],
                variables: [],
                pseudo_elements: [],
                media_queries: {}
            };

            // ========== 1. 提取所有样式表 ==========
            // 内联样式
            document.querySelectorAll('style').forEach((style, index) => {
                result.stylesheets.push({
                    url: `inline-${index}`,
                    content: style.textContent || '',
                    is_inline: true
                });
            });

            // ========== 2. 提取 @keyframes 动画 ==========
            for (const sheet of document.styleSheets) {
                try {
                    const rules = sheet.cssRules || sheet.rules;
                    if (!rules) continue;

                    for (const rule of rules) {
                        // @keyframes
                        if (rule instanceof CSSKeyframesRule) {
                            const keyframes = [];
                            for (const kf of rule.cssRules) {
                                keyframes.push({
                                    offset: kf.keyText,
                                    styles: kf.style.cssText
                                });
                            }
                            result.animations.push({
                                name: rule.name,
                                keyframes: keyframes,
                                source_stylesheet: sheet.href || 'inline'
                            });
                        }

                        // @media 查询
                        if (rule instanceof CSSMediaRule) {
                            result.media_queries[rule.conditionText] = rule.cssText;
                        }
                    }
                } catch (e) {
                    // 跨域样式表无法访问 cssRules
                }
            }

            // ========== 3. 提取 CSS 变量 ==========
            const rootStyles = getComputedStyle(document.documentElement);
            // 获取 :root 定义的变量
            for (const sheet of document.styleSheets) {
                try {
                    const rules = sheet.cssRules || sheet.rules;
                    if (!rules) continue;

                    for (const rule of rules) {
                        if (rule instanceof CSSStyleRule && rule.selectorText === ':root') {
                            const style = rule.style;
                            for (let i = 0; i < style.length; i++) {
                                const prop = style[i];
                                if (prop.startsWith('--')) {
                                    result.variables.push({
                                        name: prop,
                                        value: style.getPropertyValue(prop).trim(),
                                        scope: ':root'
                                    });
                                }
                            }
                        }
                    }
                } catch (e) {
                    // 跨域样式表
                }
            }

            // ========== 4. 提取过渡效果 ==========
            document.querySelectorAll('*').forEach(el => {
                const styles = getComputedStyle(el);
                const transitionProp = styles.transitionProperty;
                const transitionDur = styles.transitionDuration;

                if (transitionProp && transitionProp !== 'none' && transitionDur !== '0s') {
                    const selector = el.id ? `#${el.id}` :
                        (el.className && typeof el.className === 'string' ?
                            el.tagName.toLowerCase() + '.' + el.className.split(' ')[0] :
                            el.tagName.toLowerCase());

                    result.transitions.push({
                        selector: selector,
                        property: transitionProp,
                        duration: transitionDur,
                        timing_function: styles.transitionTimingFunction,
                        delay: styles.transitionDelay
                    });
                }
            });

            // ========== 5. 提取伪元素样式 ==========
            const interestingElements = document.querySelectorAll(
                'a, button, div, span, h1, h2, h3, h4, h5, h6, p, li, nav, header, footer, section, article'
            );
            interestingElements.forEach(el => {
                const selector = el.id ? `#${el.id}` :
                    (el.className && typeof el.className === 'string' ?
                        el.tagName.toLowerCase() + '.' + el.className.split(' ')[0] :
                        el.tagName.toLowerCase());

                ['::before', '::after'].forEach(pseudo => {
                    const pseudoStyles = getComputedStyle(el, pseudo);
                    const content = pseudoStyles.content;

                    if (content && content !== 'none' && content !== '""' && content !== "''") {
                        const styles = {};
                        ['content', 'display', 'position', 'width', 'height',
                         'backgroundColor', 'color', 'border', 'borderRadius',
                         'transform', 'animation', 'opacity'].forEach(prop => {
                            const val = pseudoStyles[prop];
                            if (val && val !== 'none' && val !== 'normal' && val !== 'auto') {
                                styles[prop] = val;
                            }
                        });

                        if (Object.keys(styles).length > 1) {
                            result.pseudo_elements.push({
                                selector: selector,
                                pseudo: pseudo,
                                styles: styles,
                                content: content
                            });
                        }
                    }
                });
            });

            return result;
        }''')

        # 获取外部样式表内容
        stylesheets = []
        for sheet_data in css_data.get('stylesheets', []):
            stylesheets.append(StylesheetContent(
                url=sheet_data['url'],
                content=sheet_data['content'],
                is_inline=sheet_data['is_inline']
            ))

        # 下载外部样式表
        external_stylesheets = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('link[rel="stylesheet"]'))
                .map(link => link.href)
                .filter(href => href);
        }''')

        for stylesheet_url in external_stylesheets:
            try:
                response = await page.request.get(stylesheet_url)
                if response.ok:
                    content = await response.text()
                    stylesheets.append(StylesheetContent(
                        url=stylesheet_url,
                        content=content,
                        is_inline=False
                    ))
            except Exception as e:
                logger.debug(f"下载样式表失败 {stylesheet_url}: {str(e)}")

        # 解析动画
        animations = []
        for anim_data in css_data.get('animations', []):
            keyframes = []
            for kf in anim_data.get('keyframes', []):
                # 将 cssText 解析为字典
                styles = {}
                if isinstance(kf.get('styles'), str):
                    for part in kf['styles'].split(';'):
                        if ':' in part:
                            key, val = part.split(':', 1)
                            styles[key.strip()] = val.strip()
                keyframes.append(CSSKeyframe(
                    offset=kf['offset'],
                    styles=styles
                ))
            animations.append(CSSAnimation(
                name=anim_data['name'],
                keyframes=keyframes,
                source_stylesheet=anim_data.get('source_stylesheet')
            ))

        # 解析过渡
        transitions = []
        seen_transitions = set()
        for trans_data in css_data.get('transitions', []):
            key = f"{trans_data['selector']}_{trans_data['property']}"
            if key not in seen_transitions:
                seen_transitions.add(key)
                transitions.append(CSSTransitionInfo(
                    property=trans_data['property'],
                    duration=trans_data['duration'],
                    timing_function=trans_data['timing_function'],
                    delay=trans_data['delay']
                ))

        # 解析变量
        variables = [
            CSSVariable(
                name=v['name'],
                value=v['value'],
                scope=v['scope']
            ) for v in css_data.get('variables', [])
        ]

        # 解析伪元素
        pseudo_elements = []
        for pe_data in css_data.get('pseudo_elements', []):
            pseudo_elements.append(PseudoElementStyle(
                selector=pe_data['selector'],
                pseudo=pe_data['pseudo'],
                styles=pe_data.get('styles', {}),
                content=pe_data.get('content')
            ))

        return CSSData(
            stylesheets=stylesheets,
            animations=animations,
            transitions=transitions[:50],  # 限制数量
            variables=variables,
            pseudo_elements=pseudo_elements[:100],  # 限制数量
            media_queries=css_data.get('media_queries', {})
        )

    # ==================== 新增方法：全页截图 ====================

    async def _take_full_screenshot(self, page: Page) -> str:
        """
        获取全页截图

        Args:
            page: Playwright 页面对象

        Returns:
            str: Base64 编码的全页截图
        """
        screenshot_bytes = await page.screenshot(
            type='png',
            full_page=True
        )
        return base64.b64encode(screenshot_bytes).decode('utf-8')

    # ==================== 新增方法：交互状态捕获 ====================

    async def _capture_interactions(self, page: Page) -> InteractionData:
        """
        捕获元素的交互状态（hover、focus）

        Args:
            page: Playwright 页面对象

        Returns:
            InteractionData: 交互状态数据
        """
        hover_states = []
        focus_states = []

        # 获取可交互元素
        interactive_elements = await page.evaluate('''() => {
            const elements = [];
            const selectors = document.querySelectorAll(
                'a, button, input, select, textarea, [role="button"], [tabindex]'
            );

            selectors.forEach((el, index) => {
                if (el.offsetWidth > 0 && el.offsetHeight > 0) {
                    const selector = el.id ? `#${el.id}` :
                        (el.className && typeof el.className === 'string' ?
                            `${el.tagName.toLowerCase()}.${el.className.split(' ')[0]}` :
                            `${el.tagName.toLowerCase()}:nth-of-type(${index + 1})`);

                    elements.push({
                        selector: selector,
                        tag: el.tagName.toLowerCase(),
                        rect: el.getBoundingClientRect()
                    });
                }
            });

            // 只取前 20 个元素
            return elements.slice(0, 20);
        }''')

        # 捕获 hover 状态
        for elem in interactive_elements:
            try:
                selector = elem['selector']
                element = page.locator(selector).first

                # 获取原始样式
                original_styles = await page.evaluate('''(selector) => {
                    const el = document.querySelector(selector);
                    if (!el) return {};
                    const styles = getComputedStyle(el);
                    return {
                        backgroundColor: styles.backgroundColor,
                        color: styles.color,
                        transform: styles.transform,
                        boxShadow: styles.boxShadow,
                        borderColor: styles.borderColor,
                        opacity: styles.opacity
                    };
                }''', selector)

                # 模拟 hover
                await element.hover(timeout=1000)
                await asyncio.sleep(0.1)

                # 获取 hover 后的样式
                hover_styles = await page.evaluate('''(selector) => {
                    const el = document.querySelector(selector);
                    if (!el) return {};
                    const styles = getComputedStyle(el);
                    return {
                        backgroundColor: styles.backgroundColor,
                        color: styles.color,
                        transform: styles.transform,
                        boxShadow: styles.boxShadow,
                        borderColor: styles.borderColor,
                        opacity: styles.opacity
                    };
                }''', selector)

                # 只记录有变化的样式
                changed_styles = {}
                for key, val in hover_styles.items():
                    if val != original_styles.get(key):
                        changed_styles[key] = val

                if changed_styles:
                    hover_states.append(InteractionState(
                        selector=selector,
                        state='hover',
                        styles=changed_styles
                    ))

                # 移开鼠标
                await page.mouse.move(0, 0)

            except Exception as e:
                logger.debug(f"捕获 hover 状态失败 {selector}: {str(e)}")
                continue

        return InteractionData(
            hover_states=hover_states,
            focus_states=focus_states,
            active_states=[]
        )

    # ==================== 新增方法：资源下载 ====================

    async def _download_resources(
        self,
        page: Page,
        assets: PageAssets,
        base_url: str
    ) -> DownloadedResources:
        """
        下载页面资源

        Args:
            page: Playwright 页面对象
            assets: 资源列表
            base_url: 页面基础 URL

        Returns:
            DownloadedResources: 已下载的资源
        """
        downloaded = DownloadedResources()

        # 下载图片（限制数量和大小）
        for asset in assets.images[:20]:  # 最多 20 张
            try:
                content = await self._download_single_resource(page, asset.url, base_url)
                if content:
                    downloaded.images.append(content)
            except Exception as e:
                logger.debug(f"下载图片失败 {asset.url}: {str(e)}")

        # 下载字体
        for asset in assets.fonts[:10]:  # 最多 10 个
            try:
                content = await self._download_single_resource(page, asset.url, base_url)
                if content:
                    downloaded.fonts.append(content)
            except Exception as e:
                logger.debug(f"下载字体失败 {asset.url}: {str(e)}")

        # 下载脚本（只下载小脚本）
        for asset in assets.scripts[:10]:  # 最多 10 个
            try:
                content = await self._download_single_resource(
                    page, asset.url, base_url, max_size=500 * 1024  # 最大 500KB
                )
                if content:
                    downloaded.scripts.append(content)
            except Exception as e:
                logger.debug(f"下载脚本失败 {asset.url}: {str(e)}")

        return downloaded

    async def _download_single_resource(
        self,
        page: Page,
        url: str,
        base_url: str,
        max_size: int = 2 * 1024 * 1024  # 默认最大 2MB
    ) -> Optional[ResourceContent]:
        """
        下载单个资源

        Args:
            page: Playwright 页面对象
            url: 资源 URL
            base_url: 基础 URL
            max_size: 最大文件大小

        Returns:
            ResourceContent: 资源内容（如果成功）
        """
        try:
            # 处理相对 URL
            if not url.startswith(('http://', 'https://', 'data:')):
                url = urljoin(base_url, url)

            # data URL 直接解析
            if url.startswith('data:'):
                match = re.match(r'data:([^;,]+)?(?:;base64)?,(.+)', url)
                if match:
                    mime_type = match.group(1) or 'application/octet-stream'
                    content = match.group(2)
                    return ResourceContent(
                        url=url[:50] + '...',  # 截断 data URL
                        type=mime_type.split('/')[0],
                        content=content,
                        size=len(content),
                        mime_type=mime_type
                    )
                return None

            # HTTP 请求下载
            response = await page.request.get(url)
            if not response.ok:
                return None

            body = await response.body()
            if len(body) > max_size:
                logger.debug(f"资源太大，跳过: {url} ({len(body)} bytes)")
                return None

            # 确定资源类型
            content_type = response.headers.get('content-type', '')
            resource_type = 'other'
            if 'image' in content_type:
                resource_type = 'image'
            elif 'font' in content_type or url.endswith(('.woff', '.woff2', '.ttf', '.eot')):
                resource_type = 'font'
            elif 'javascript' in content_type or url.endswith('.js'):
                resource_type = 'script'
            elif 'css' in content_type or url.endswith('.css'):
                resource_type = 'stylesheet'

            # 提取文件名
            filename = urlparse(url).path.split('/')[-1] or 'unknown'

            return ResourceContent(
                url=url,
                type=resource_type,
                content=base64.b64encode(body).decode('utf-8'),
                size=len(body),
                mime_type=content_type,
                filename=filename
            )

        except Exception as e:
            logger.debug(f"下载资源失败 {url}: {str(e)}")
            return None

    async def _analyze_tech_stack(self, page: Page, url: str) -> Optional[TechStackData]:
        """
        分析页面技术栈

        Args:
            page: Playwright 页面对象
            url: 页面 URL

        Returns:
            Optional[TechStackData]: 技术栈分析结果
        """
        try:
            logger.debug("开始技术栈分析")

            # 获取 HTML 内容
            html_content = await page.content()

            # 创建分析器并执行分析
            analyzer = TechStackAnalyzer(page, html_content)
            tech_stack = await analyzer.analyze()

            logger.debug(f"技术栈分析完成，检测到 {len(tech_stack.frameworks)} 个框架")
            return tech_stack

        except Exception as e:
            logger.error(f"技术栈分析失败: {e}", exc_info=True)
            return None

    async def _analyze_components(
        self,
        page: Page,
        url: str,
        raw_html: Optional[str] = None,
        dom_tree: Optional[ElementInfo] = None
    ) -> Optional[ComponentAnalysisData]:
        """
        分析页面组件

        Args:
            page: Playwright 页面对象
            url: 页面 URL
            raw_html: 原始 HTML 字符串（用于代码位置定位）
            dom_tree: 已提取的 DOM 树（用于直接从树中提取 section）

        Returns:
            Optional[ComponentAnalysisData]: 组件分析结果
        """
        try:
            logger.debug("开始组件分析")

            # 创建分析器并执行分析（传递 dom_tree 以便直接从 DOM 树提取 section）
            analyzer = ComponentAnalyzer(page, url, raw_html, dom_tree)
            components = await analyzer.analyze()

            logger.debug(f"组件分析完成，识别出 {components.stats.get('total_components', 0)} 个组件")
            return components

        except Exception as e:
            logger.error(f"组件分析失败: {e}", exc_info=True)
            return None

    # ==================== Lightweight Resources Fetch ====================

    async def fetch_resources_only(
        self,
        url: str,
        theme: str = "light",
        viewport_width: int = 1920,
        viewport_height: int = 1080
    ) -> dict:
        """
        Lightweight method to fetch only image resources from a URL.
        Designed for WebContainer preview use case.

        Args:
            url: Target page URL
            theme: Theme mode ("light" or "dark")
            viewport_width: Viewport width
            viewport_height: Viewport height

        Returns:
            dict: {
                "success": bool,
                "images": [{ url, content, mime_type, filename, size }],
                "total_count": int,
                "total_size": int,
                "error": str (if failed)
            }
        """
        page = None
        context = None

        try:
            logger.info(f"[Resources] Starting fetch: {url}, theme: {theme}")

            # Get browser
            browser = await self._get_browser()

            # Create context with viewport
            context = await browser.new_context(
                viewport={'width': viewport_width, 'height': viewport_height},
                ignore_https_errors=True
            )

            # Create page
            page = await context.new_page()

            # Navigate to URL
            logger.debug(f"[Resources] Navigating to: {url}")
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)

            # Wait for network idle (max 5 seconds)
            try:
                await page.wait_for_load_state('networkidle', timeout=5000)
            except Exception:
                logger.debug("[Resources] Network idle timeout, continuing...")

            # Apply theme
            theme_str = theme.lower()
            await page.emulate_media(color_scheme=theme_str)

            # Also apply class-based theme switching
            await page.evaluate('''(theme) => {
                const html = document.documentElement;
                const body = document.body;
                const darkClasses = ['dark', 'dark-mode', 'dark-theme', 'theme-dark'];
                const lightClasses = ['light', 'light-mode', 'light-theme', 'theme-light'];

                if (theme === 'dark') {
                    darkClasses.forEach(cls => html.classList.add(cls));
                    lightClasses.forEach(cls => {
                        html.classList.remove(cls);
                        body.classList.remove(cls);
                    });
                    html.setAttribute('data-theme', 'dark');
                    html.setAttribute('data-color-scheme', 'dark');
                    html.style.colorScheme = 'dark';
                } else {
                    darkClasses.forEach(cls => {
                        html.classList.remove(cls);
                        body.classList.remove(cls);
                    });
                    html.setAttribute('data-theme', 'light');
                    html.setAttribute('data-color-scheme', 'light');
                    html.style.colorScheme = 'light';
                }
            }''', theme_str)

            await asyncio.sleep(0.3)  # Wait for theme to apply

            # Scroll to trigger lazy loading
            logger.debug("[Resources] Scrolling to trigger lazy load...")
            await self._scroll_to_load_lazy_content(page, max_scrolls=15, scroll_delay=0.15)

            # Extract image URLs from page
            logger.debug("[Resources] Extracting image URLs...")
            image_urls = await page.evaluate('''() => {
                const images = new Set();

                // From <img> tags
                document.querySelectorAll('img').forEach(img => {
                    if (img.src && img.src.startsWith('http')) {
                        images.add(img.src);
                    }
                    // Also check srcset
                    if (img.srcset) {
                        img.srcset.split(',').forEach(src => {
                            const url = src.trim().split(' ')[0];
                            if (url && url.startsWith('http')) {
                                images.add(url);
                            }
                        });
                    }
                    // Check data-src for lazy loading
                    if (img.dataset.src && img.dataset.src.startsWith('http')) {
                        images.add(img.dataset.src);
                    }
                });

                // From background images in computed styles
                document.querySelectorAll('*').forEach(el => {
                    const style = window.getComputedStyle(el);
                    const bgImage = style.backgroundImage;
                    if (bgImage && bgImage !== 'none') {
                        const urlMatch = bgImage.match(/url\\(["']?(https?:\\/\\/[^"')]+)["']?\\)/);
                        if (urlMatch) {
                            images.add(urlMatch[1]);
                        }
                    }
                });

                // From <picture> sources
                document.querySelectorAll('picture source').forEach(source => {
                    if (source.srcset) {
                        source.srcset.split(',').forEach(src => {
                            const url = src.trim().split(' ')[0];
                            if (url && url.startsWith('http')) {
                                images.add(url);
                            }
                        });
                    }
                });

                // From SVG use xlink:href (external SVGs)
                document.querySelectorAll('svg use').forEach(use => {
                    const href = use.getAttribute('xlink:href') || use.getAttribute('href');
                    if (href && href.startsWith('http')) {
                        images.add(href);
                    }
                });

                return Array.from(images);
            }''')

            logger.info(f"[Resources] Found {len(image_urls)} image URLs")

            # Download images (limit to 30 for performance)
            images = []
            max_images = 30
            downloaded_urls = image_urls[:max_images]

            for img_url in downloaded_urls:
                try:
                    content = await self._download_single_resource(page, img_url, url)
                    if content and content.type == 'image':
                        images.append({
                            "url": content.url,
                            "content": content.content,
                            "mime_type": content.mime_type,
                            "filename": content.filename,
                            "size": content.size
                        })
                except Exception as e:
                    logger.debug(f"[Resources] Failed to download: {img_url}, error: {e}")

            total_size = sum(img.get("size", 0) for img in images)

            logger.info(f"[Resources] Downloaded {len(images)} images, total size: {total_size} bytes")

            return {
                "success": True,
                "images": images,
                "total_count": len(images),
                "total_size": total_size
            }

        except Exception as e:
            logger.error(f"[Resources] Error: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "images": [],
                "total_count": 0,
                "total_size": 0
            }

        finally:
            # Cleanup
            if page:
                try:
                    await page.close()
                except Exception:
                    pass
            if context:
                try:
                    await context.close()
                except Exception:
                    pass
