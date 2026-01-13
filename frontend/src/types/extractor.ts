/**
 * Playwright Extractor Types
 * 定义网页提取相关的类型
 *
 * 与后端 Python 模型对应
 * 支持像素级网页复刻
 */

// ==================== Theme Models ====================

/**
 * 主题模式枚举
 */
export type ThemeMode = 'light' | 'dark';

/**
 * 页面主题支持类型
 */
export type ThemeSupport = 'light-only' | 'dark-only' | 'both' | 'unknown';

/**
 * 主题检测结果
 */
export interface ThemeDetectionResult {
  support: ThemeSupport;
  current_mode: ThemeMode;
  has_significant_difference: boolean;
  detection_method: string;  // css_media, class_toggle, color_scheme, style_comparison, none
  css_variables_diff_count: number;
  color_diff_count: number;
  image_diff_count: number;
}

/**
 * 按主题分类的数据
 * 用于存储 light/dark 两种模式下可能不同的数据
 */
export interface ThemedData {
  screenshot?: string | null;
  full_page_screenshot?: string | null;
  style_summary?: StyleSummary | null;
  css_data?: CSSData | null;
  assets?: PageAssets | null;
  downloaded_resources?: DownloadedResources | null;
}

// ==================== Element Models ====================

/**
 * 元素的位置和尺寸信息
 * 对应 getBoundingClientRect() 返回的数据
 */
export interface ElementRect {
  x: number;
  y: number;
  width: number;
  height: number;
  top: number;
  right: number;
  bottom: number;
  left: number;
}

/**
 * 元素的计算后样式
 * 只包含布局和视觉相关的关键样式
 */
export interface ElementStyles {
  // 布局相关
  display?: string;
  position?: string;
  float_?: string;  // float 是 JS 保留字
  clear?: string;

  // Flexbox
  flex_direction?: string;
  flex_wrap?: string;
  justify_content?: string;
  align_items?: string;
  align_content?: string;
  gap?: string;

  // Grid
  grid_template_columns?: string;
  grid_template_rows?: string;
  grid_column?: string;
  grid_row?: string;

  // 尺寸
  width?: string;
  height?: string;
  min_width?: string;
  min_height?: string;
  max_width?: string;
  max_height?: string;

  // 间距
  margin?: string;
  margin_top?: string;
  margin_right?: string;
  margin_bottom?: string;
  margin_left?: string;
  padding?: string;
  padding_top?: string;
  padding_right?: string;
  padding_bottom?: string;
  padding_left?: string;

  // 定位
  top?: string;
  right?: string;
  bottom?: string;
  left?: string;
  z_index?: string;

  // 视觉
  background_color?: string;
  background_image?: string;
  color?: string;
  border?: string;
  border_radius?: string;
  box_shadow?: string;
  opacity?: string;
  overflow?: string;
  visibility?: string;

  // 文字
  font_family?: string;
  font_size?: string;
  font_weight?: string;
  line_height?: string;
  text_align?: string;

  // 变换
  transform?: string;
}

/**
 * 单个 DOM 元素的完整信息
 */
export interface ElementInfo {
  // 基础信息
  tag: string;
  id?: string | null;
  classes: string[];

  // 位置和尺寸
  rect: ElementRect;

  // 样式
  styles: ElementStyles;

  // 内容
  text_content?: string | null;
  inner_html_length: number;

  // 属性
  attributes: Record<string, string>;

  // 元素类型标记
  is_visible: boolean;
  is_interactive: boolean;

  // 子元素
  children: ElementInfo[];
  children_count: number;

  // 路径标识
  xpath?: string | null;
  selector?: string | null;
}

// ==================== Page Level Models ====================

/**
 * 单个资源的信息
 */
export interface AssetInfo {
  url: string;
  type: string;
  size?: number | null;
}

/**
 * 页面资源统计
 */
export interface PageAssets {
  images: AssetInfo[];
  scripts: AssetInfo[];
  stylesheets: AssetInfo[];
  fonts: AssetInfo[];

  total_images: number;
  total_scripts: number;
  total_stylesheets: number;
  total_fonts: number;
}

/**
 * 页面样式汇总统计
 */
export interface StyleSummary {
  colors: Record<string, number>;
  background_colors: Record<string, number>;
  font_families: Record<string, number>;
  font_sizes: Record<string, number>;
  margins: Record<string, number>;
  paddings: Record<string, number>;
  display_types: Record<string, number>;
  position_types: Record<string, number>;
}

/**
 * 页面元数据
 */
export interface PageMetadata {
  url: string;
  title: string;
  viewport_width: number;
  viewport_height: number;
  page_width: number;
  page_height: number;
  total_elements: number;
  max_depth: number;
  load_time_ms: number;
}

/**
 * 完整的提取结果
 */
export interface ExtractionResult {
  success: boolean;
  message: string;
  metadata?: PageMetadata | null;
  screenshot?: string | null;
  full_page_screenshot?: string | null;
  dom_tree?: ElementInfo | null;
  style_summary?: StyleSummary | null;
  assets?: PageAssets | null;
  // 新增字段
  raw_html?: string | null;
  css_data?: CSSData | null;
  network_data?: NetworkData | null;
  downloaded_resources?: DownloadedResources | null;
  interaction_data?: InteractionData | null;
  tech_stack?: TechStackData | null;          // 技术栈分析
  components?: ComponentAnalysisData | null;   // 组件分析
  error?: string | null;

  // 主题相关字段
  theme_detection?: ThemeDetectionResult | null;  // 主题检测结果
  light_mode_data?: ThemedData | null;            // 亮色模式数据
  dark_mode_data?: ThemedData | null;             // 暗色模式数据
  current_theme?: ThemeMode;                       // 当前预览的主题模式
}

// ==================== CSS Animation Models ====================

/**
 * CSS 关键帧
 */
export interface CSSKeyframe {
  offset: string;
  styles: Record<string, string>;
}

/**
 * CSS @keyframes 动画定义
 */
export interface CSSAnimation {
  name: string;
  keyframes: CSSKeyframe[];
  source_stylesheet?: string | null;
}

/**
 * CSS 过渡定义
 */
export interface CSSTransitionInfo {
  property: string;
  duration: string;
  timing_function: string;
  delay: string;
}

/**
 * CSS 变量定义
 */
export interface CSSVariable {
  name: string;
  value: string;
  scope: string;
}

/**
 * 伪元素样式
 */
export interface PseudoElementStyle {
  selector: string;
  pseudo: string;
  styles: Record<string, string>;
  content?: string | null;
}

/**
 * 样式表内容
 */
export interface StylesheetContent {
  url: string;
  content: string;
  is_inline: boolean;
}

/**
 * 完整的 CSS 数据
 */
export interface CSSData {
  stylesheets: StylesheetContent[];
  animations: CSSAnimation[];
  transitions: CSSTransitionInfo[];
  variables: CSSVariable[];
  pseudo_elements: PseudoElementStyle[];
  media_queries: Record<string, string>;
}

// ==================== Network Models ====================

/**
 * 网络请求记录
 */
export interface NetworkRequest {
  url: string;
  method: string;
  request_type: string;
  headers: Record<string, string>;
  post_data?: string | null;
  response_status?: number | null;
  response_headers: Record<string, string>;
  response_body?: string | null;
  response_size?: number | null;
  timing?: number | null;
}

/**
 * 网络请求数据汇总
 */
export interface NetworkData {
  requests: NetworkRequest[];
  api_calls: NetworkRequest[];
  total_requests: number;
  total_size: number;
}

// ==================== Resource Content Models ====================

/**
 * 下载的资源内容
 */
export interface ResourceContent {
  url: string;
  type: string;
  content?: string | null;
  size: number;
  mime_type?: string | null;
  filename?: string | null;
}

/**
 * 已下载的资源汇总
 */
export interface DownloadedResources {
  images: ResourceContent[];
  fonts: ResourceContent[];
  scripts: ResourceContent[];
  stylesheets: ResourceContent[];
}

// ==================== Interaction State Models ====================

/**
 * 交互状态捕获
 */
export interface InteractionState {
  selector: string;
  state: string;
  styles: Record<string, string>;
  screenshot?: string | null;
}

/**
 * 交互状态数据汇总
 */
export interface InteractionData {
  hover_states: InteractionState[];
  focus_states: InteractionState[];
  active_states: InteractionState[];
}

// ==================== Tech Stack Models ====================

/**
 * 依赖库信息
 */
export interface DependencyInfo {
  name: string;
  version?: string | null;
  type: 'library' | 'framework' | 'tool' | 'plugin';
  confidence: number; // 0-100
}

/**
 * 技术栈分析结果
 */
export interface TechStackData {
  // 前端框架
  frameworks: DependencyInfo[];

  // UI 库和组件库
  ui_libraries: DependencyInfo[];

  // 工具库
  utilities: DependencyInfo[];

  // 构建工具和打包器
  build_tools: DependencyInfo[];

  // 样式方案
  styling: {
    preprocessor?: string | null;  // sass, less, stylus
    framework?: string | null;     // tailwind, bootstrap, bulma
    css_in_js?: string | null;     // styled-components, emotion
  };

  // 包管理器信息
  package_manager?: string | null;

  // 检测到的技术特征
  features: string[];

  // Meta 标签中的信息
  meta_tags: Record<string, string>;
}

// ==================== Component Analysis Models ====================

/**
 * 页面组件/模块信息
 */
export interface ComponentInfo {
  // 基本信息
  id: string;
  name: string;
  type: 'header' | 'footer' | 'navigation' | 'hero' | 'section' | 'sidebar' | 'modal' | 'other';

  // 定位信息
  selector: string;
  xpath?: string | null;
  rect: ElementRect;

  // 样式信息
  colors: {
    background: string[];
    text: string[];
    border: string[];
    accent: string[];
  };

  // 动效信息
  animations: {
    css_animations: string[];     // CSS animation names
    transitions: string[];         // CSS transitions
    transform_effects: string[];   // transform effects detected
  };

  // 内部链接
  internal_links: {
    url: string;
    text: string;
    type: 'navigation' | 'anchor' | 'button' | 'other';
  }[];

  // 外部链接
  external_links: {
    url: string;
    text: string;
    domain: string;
  }[];

  // 图片资源
  images: {
    src: string;
    alt?: string | null;
    width?: number | null;
    height?: number | null;
  }[];

  // 文本内容摘要
  text_summary: {
    headings: string[];
    paragraph_count: number;
    word_count: number;
  };

  // 代码位置信息（用于在原始 HTML 中定位组件）
  code_location?: {
    start_line: number;          // 在原始 HTML 中的起始行号
    end_line: number;            // 在原始 HTML 中的结束行号
    html_snippet: string;        // HTML 代码片段（前10行预览）
    full_html: string;           // 完整的 outerHTML（用于精确复制）
    char_start: number;          // 字符起始位置
    char_end: number;            // 字符结束位置
    // Token estimation (NEW)
    estimated_chars?: number;    // 估算的字符数
    estimated_tokens?: number;   // 估算的 token 数
    // Split component info (NEW)
    is_split_part?: boolean;     // 是否是拆分后的部分
    parent_id?: string;          // 父组件 ID
    part_index?: number;         // 部分索引
  } | null;

  // 子组件
  sub_components: ComponentInfo[];
}

/**
 * 页面组件分析结果
 */
export interface ComponentAnalysisData {
  // 识别出的主要组件
  components: ComponentInfo[];

  // 组件统计
  stats: {
    total_components: number;
    by_type: Record<string, number>;
    total_links: number;
    total_images: number;
  };
}

// ==================== Request Models ====================

/**
 * 提取请求参数
 */
export interface ExtractRequest {
  url: string;
  viewport_width?: number;
  viewport_height?: number;
  wait_for_selector?: string | null;
  wait_timeout?: number;
  include_screenshot?: boolean;
  max_depth?: number;
  include_hidden?: boolean;
  // 新增选项
  download_resources?: boolean;
  capture_network?: boolean;
  capture_interactions?: boolean;
  extract_css?: boolean;
  full_page_screenshot?: boolean;
}

// ==================== UI State Types ====================

/**
 * 提取状态枚举
 */
export type ExtractionStatus = 'idle' | 'loading' | 'success' | 'error';

/**
 * Tab 类型
 */
export type PlaywrightTab = 'overview' | 'layout' | 'elements' | 'styles' | 'assets' | 'css' | 'network' | 'resources' | 'techstack' | 'components';

/**
 * 元素筛选类型
 */
export type ElementFilterType =
  | 'all'
  | 'layout'       // div, section, header, main, footer, aside, nav
  | 'interactive'  // button, a, input, form, select, textarea
  | 'media'        // img, video, audio, svg, canvas
  | 'text';        // h1-h6, p, span, label

/**
 * 筛选器配置
 */
export const ELEMENT_FILTERS: Record<ElementFilterType, { label: string; tags: string[] }> = {
  all: {
    label: 'All Elements',
    tags: []
  },
  layout: {
    label: 'Layout Containers',
    tags: ['div', 'section', 'header', 'main', 'footer', 'aside', 'nav', 'article']
  },
  interactive: {
    label: 'Interactive',
    tags: ['button', 'a', 'input', 'form', 'select', 'textarea', 'label', 'details']
  },
  media: {
    label: 'Media',
    tags: ['img', 'video', 'audio', 'svg', 'canvas', 'picture', 'iframe']
  },
  text: {
    label: 'Text',
    tags: ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'span', 'strong', 'em', 'li']
  }
};
