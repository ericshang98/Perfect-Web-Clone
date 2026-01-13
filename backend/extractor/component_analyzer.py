"""
Component Analyzer - Fine-grained Section Extraction from DOM Tree
组件分析器 - 从DOM树中精细提取Section

核心功能：
- 直接从已提取的dom_tree中识别页面Section
- 递归拆分过大的Section，确保每个Section的token数不超过阈值
- 确保Section互斥且完整覆盖整个页面
- 提取每个Section的完整HTML内容供Worker Agent使用
"""

import logging
import re
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlparse
from playwright.async_api import Page
from .models import (
    ComponentInfo, ComponentAnalysisData, ElementRect,
    SectionStyles, ElementInfo
)

logger = logging.getLogger(__name__)


def clean_html_for_tokens(html: str) -> str:
    """
    清理 HTML 内容，移除不应计入 token 的部分

    移除/替换：
    1. Base64 图片数据 → [IMG:base64]
    2. Data URLs → [DATA:url]
    3. 内联 SVG → [SVG]
    4. 超长 style 属性 → [STYLES]
    5. 超长 srcset → [SRCSET]

    Args:
        html: 原始 HTML 字符串

    Returns:
        清理后的 HTML 字符串
    """
    if not html:
        return ""

    # 1. 替换 base64 图片数据
    # data:image/png;base64,iVBORw0... → [IMG:base64]
    html = re.sub(
        r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+',
        '[IMG:base64]',
        html,
        flags=re.IGNORECASE
    )

    # 2. 替换其他 data URLs（超过100字符的）
    html = re.sub(
        r'data:[^,]+,[A-Za-z0-9+/=]{100,}',
        '[DATA:url]',
        html,
        flags=re.IGNORECASE
    )

    # 3. 替换内联 SVG 内容
    # <svg ...>...</svg> → <svg>[SVG]</svg>
    html = re.sub(
        r'<svg[^>]*>[\s\S]*?</svg>',
        '<svg>[SVG]</svg>',
        html,
        flags=re.IGNORECASE
    )

    # 4. 替换超长 style 属性（超过200字符）
    html = re.sub(
        r'style="[^"]{200,}"',
        'style="[LONG_STYLES]"',
        html,
        flags=re.IGNORECASE
    )

    # 5. 替换超长 srcset（超过500字符）
    html = re.sub(
        r'srcset="[^"]{500,}"',
        'srcset="[SRCSET]"',
        html,
        flags=re.IGNORECASE
    )

    return html


class ComponentAnalyzer:
    """
    组件分析器 - 精细粒度Section提取（纯规则驱动，无AI）

    核心策略（三原则）：
    1. 块之间相互独立，不重叠
    2. 块组装起来能构成整个页面，不遗漏
    3. 块大小要小于 10K token，大于则拆分

    分区流程：
    1. 从DOM树提取所有潜在Section
    2. 检测超过10K的Section，深度优先递归拆分
    3. 处理水平并排的布局（左右两栏等）
    4. 合并间隙到相邻Section（不创建空Section）
    5. 验证三原则
    6. 统一命名为 section_1, section_2, ...
    """

    # Token限制 - 每个section不应超过此值（10K）
    MAX_SECTION_TOKENS = 10000  # 约40000字符
    MAX_SECTION_CHARS = 40000

    # 最小Section尺寸
    MIN_SECTION_HEIGHT = 50
    MIN_SECTION_WIDTH_RATIO = 0.2  # 相对于页面宽度（降低以支持并排布局）

    # 对于大token节点，放宽宽度限制
    LARGE_TOKEN_THRESHOLD = 1000  # 超过此值的节点即使较窄也应处理

    # 最小token阈值 - 过滤掉太小的section
    MIN_SECTION_TOKENS = 50  # 小于此值的section会被跳过

    # 水平重叠阈值 - 用于判断是否并排
    HORIZONTAL_OVERLAP_THRESHOLD = 0.3  # 垂直重叠超过30%认为是并排

    # 容器标签 - 这些标签的子元素应该被检查
    CONTAINER_TAGS = {'body', 'main', 'div', 'section', 'article'}

    # 跳过的标签
    SKIP_TAGS = {'script', 'style', 'head', 'meta', 'link', 'noscript', 'svg', 'path', 'br', 'hr'}

    def __init__(
        self,
        page: Page,
        base_url: str,
        raw_html: Optional[str] = None,
        dom_tree: Optional[ElementInfo] = None
    ):
        """
        初始化组件分析器

        Args:
            page: Playwright Page对象（用于获取HTML内容）
            base_url: 页面URL
            raw_html: 原始HTML（可选）
            dom_tree: 已提取的DOM树（必须提供以实现精细分块）
        """
        self.page = page
        self.base_url = base_url
        self.base_domain = urlparse(base_url).netloc
        self.raw_html = raw_html
        self.dom_tree = dom_tree
        self.components: List[ComponentInfo] = []
        self.page_width = 0
        self.page_height = 0

    async def analyze(self) -> ComponentAnalysisData:
        """
        执行精细Section分析（纯规则驱动）

        流程：
        1. 获取页面尺寸
        2. 从DOM树提取Section（支持水平并排）
        3. 拆分超过10K token的Section（深度优先递归）
        4. 去重并处理重叠
        5. 合并间隙到相邻Section
        6. 验证三原则
        7. 统一命名为 section_1, section_2, ...

        Returns:
            ComponentAnalysisData: 分析结果
        """
        try:
            logger.info("Starting rule-based section analysis (no AI)...")

            # Step 1: 获取页面尺寸
            page_info = await self._get_page_dimensions()
            self.page_width = page_info['width']
            self.page_height = page_info['height']
            logger.info(f"Page dimensions: {self.page_width}x{self.page_height}")

            # Step 2: 从DOM树中递归提取Section（支持水平并排）
            if self.dom_tree:
                sections = self._extract_sections_recursive(self.dom_tree)
            else:
                logger.warning("No dom_tree provided, falling back to page extraction")
                sections = await self._extract_sections_from_page(page_info)

            logger.info(f"Extracted {len(sections)} raw sections from DOM tree")

            # Step 3: 拆分超过50K token的Section
            sections = self._split_large_sections(sections)
            logger.info(f"After splitting large sections: {len(sections)} sections")

            # Step 4: 处理水平并排的Section
            sections = self._handle_horizontal_layout(sections)
            logger.info(f"After handling horizontal layout: {len(sections)} sections")

            # Step 5: 去重并处理重叠
            sections = self._remove_overlaps(sections)
            logger.info(f"After removing overlaps: {len(sections)} sections")

            # Step 6: 合并间隙到相邻Section（不创建空Section）
            sections = self._merge_gaps(sections)
            logger.info(f"After merging gaps: {len(sections)} sections")

            # Step 7: 验证三原则
            validation = self._validate_three_principles(sections)
            if validation['errors']:
                logger.warning(f"Validation errors: {validation['errors']}")

            # Step 8: 获取每个Section的HTML内容并创建ComponentInfo
            self.components = await self._create_component_infos(sections)
            logger.info(f"Created {len(self.components)} component infos")

            # Step 9: 统一命名为 section_1, section_2, ...
            self._unify_naming()

            # Step 10: 统计
            stats = self._calculate_stats()
            stats['validation'] = validation

            return ComponentAnalysisData(
                components=self.components,
                stats=stats,
            )

        except Exception as e:
            logger.error(f"Error in analyze: {e}", exc_info=True)
            return ComponentAnalysisData(
                components=[],
                stats={
                    "total_components": 0,
                    "by_type": {},
                    "total_links": 0,
                    "total_images": 0,
                    "error": str(e),
                },
            )

    async def _get_page_dimensions(self) -> Dict[str, int]:
        """获取页面尺寸"""
        return await self.page.evaluate('''
            () => ({
                width: document.documentElement.scrollWidth,
                height: document.documentElement.scrollHeight,
                viewportWidth: window.innerWidth,
                viewportHeight: window.innerHeight
            })
        ''')

    def _extract_sections_recursive(self, dom_tree: ElementInfo) -> List[Dict[str, Any]]:
        """
        递归提取Section（简化版，统一类型为section）

        策略：
        1. 从根节点开始遍历
        2. 找到有意义的Section容器
        3. 先不拆分，后续步骤会处理大Section
        4. 支持水平并排的元素
        """
        sections = []
        min_width = self.page_width * self.MIN_SECTION_WIDTH_RATIO

        def estimate_tokens(node: ElementInfo) -> int:
            """估算节点的token数"""
            return node.inner_html_length // 4

        def is_valid_section(node: ElementInfo) -> bool:
            """判断节点是否是有效的Section候选"""
            tag = node.tag.lower()

            # 跳过无效标签
            if tag in self.SKIP_TAGS:
                return False

            # 高度检查
            if node.rect.height < self.MIN_SECTION_HEIGHT:
                return False

            # 宽度检查 - 对于大token节点放宽限制
            tokens = estimate_tokens(node)
            if node.rect.width < min_width:
                # 如果token很多，即使较窄也接受（支持并排布局）
                if tokens < self.LARGE_TOKEN_THRESHOLD:
                    return False

            return True

        def create_section_dict(node: ElementInfo) -> Dict[str, Any]:
            """从节点创建section字典（统一类型为section）"""
            return {
                'tag': node.tag,
                'id': node.id,
                'classes': node.classes,
                'selector': self._generate_selector(node),
                'type': 'section',  # 统一类型
                'rect': {
                    'x': node.rect.x,
                    'y': node.rect.y,
                    'width': node.rect.width,
                    'height': node.rect.height,
                    'top': node.rect.top,
                    'bottom': node.rect.bottom,
                    'left': node.rect.left,
                    'right': node.rect.right,
                },
                'styles': {
                    'background_color': node.styles.background_color if node.styles else None,
                    'background_image': node.styles.background_image if node.styles else None,
                    'color': node.styles.color if node.styles else None,
                    'padding': node.styles.padding if node.styles else None,
                },
                'inner_html_length': node.inner_html_length,
                'estimated_tokens': estimate_tokens(node),
                'children_count': node.children_count,
                'children': node.children,  # 保留子节点引用，用于后续拆分
            }

        def extract_from_node(node: ElementInfo, depth: int = 0) -> List[Dict]:
            """从节点提取section"""
            result = []
            tag = node.tag.lower()

            # 跳过无效节点
            if tag in self.SKIP_TAGS:
                return result

            # 检查是否是有效section
            if not is_valid_section(node):
                # 即使当前节点无效，仍然检查子节点
                for child in node.children:
                    result.extend(extract_from_node(child, depth + 1))
                return result

            tokens = estimate_tokens(node)

            # 如果节点太小，跳过
            if tokens < self.MIN_SECTION_TOKENS:
                return result

            # 直接添加为section（不管大小，后续步骤会拆分）
            result.append(create_section_dict(node))
            return result

        # 从根节点开始，但跳过html/body等容器，直接从有意义的子元素开始
        def find_main_content(node: ElementInfo) -> List[ElementInfo]:
            """找到主要内容节点"""
            tag = node.tag.lower()

            # 如果是body或html，返回其子元素
            if tag in ['html', 'body']:
                result = []
                for child in node.children:
                    result.extend(find_main_content(child))
                return result

            # 如果是大容器div（几乎和页面一样大），继续向下
            if tag == 'div':
                # 检查是否是全页面容器
                if (node.rect.width >= self.page_width * 0.9 and
                    node.rect.height >= self.page_height * 0.9):
                    result = []
                    for child in node.children:
                        result.extend(find_main_content(child))
                    if result:
                        return result

            # 返回当前节点
            return [node]

        # 找到主要内容节点
        main_nodes = find_main_content(dom_tree)

        # 从每个主要内容节点提取section
        for node in main_nodes:
            sections.extend(extract_from_node(node))

        return sections

    def _generate_selector(self, node: ElementInfo) -> str:
        """生成元素的CSS选择器"""
        if node.id:
            return f"#{node.id}"

        selector = node.tag.lower()
        if node.classes:
            # 使用第一个有效的class
            for cls in node.classes:
                if cls and not cls[0].isdigit() and not cls.startswith('-'):
                    selector += f".{cls}"
                    break

        return selector

    def _split_large_sections(self, sections: List[Dict]) -> List[Dict]:
        """
        拆分超过10K token的Section

        策略：深度优先递归拆分
        - 对每个超过阈值的section，递归拆分直到所有子section都小于阈值
        - 处理完一个section后，再处理下一个
        - 这确保了每个section都被完全处理
        """
        MAX_RECURSION_DEPTH = 15  # 防止无限递归

        def create_child_section(child) -> Dict:
            """从ElementInfo创建section字典"""
            child_tokens = child.inner_html_length // 4
            return {
                'tag': child.tag,
                'id': child.id,
                'classes': child.classes,
                'selector': self._generate_selector(child),
                'type': 'section',
                'rect': {
                    'x': child.rect.x,
                    'y': child.rect.y,
                    'width': child.rect.width,
                    'height': child.rect.height,
                    'top': child.rect.top,
                    'bottom': child.rect.bottom,
                    'left': child.rect.left,
                    'right': child.rect.right,
                },
                'styles': {
                    'background_color': child.styles.background_color if child.styles else None,
                    'background_image': child.styles.background_image if child.styles else None,
                    'color': child.styles.color if child.styles else None,
                    'padding': child.styles.padding if child.styles else None,
                },
                'inner_html_length': child.inner_html_length,
                'estimated_tokens': child_tokens,
                'children_count': child.children_count,
                'children': child.children,
            }

        def split_until_small(section: Dict, depth: int = 0) -> List[Dict]:
            """
            递归拆分单个section直到所有子section都小于阈值

            这是核心的深度优先拆分函数：
            1. 如果section小于阈值，直接返回
            2. 如果section大于阈值，拆分成子section
            3. 对每个子section递归调用本函数
            4. 合并所有结果返回
            """
            tokens = section.get('estimated_tokens', 0)
            tag = section.get('tag', 'unknown')

            # 基础情况1：小于阈值，不需要拆分
            if tokens <= self.MAX_SECTION_TOKENS:
                return [section]

            # 基础情况2：达到最大递归深度，强制停止
            if depth >= MAX_RECURSION_DEPTH:
                logger.warning(
                    f"[Depth {depth}] Max recursion depth reached for section <{tag}> "
                    f"with {tokens} tokens. Keeping as-is."
                )
                return [section]

            # 获取子节点
            children = section.get('children', [])
            if not children:
                # 没有子节点，无法继续拆分
                logger.warning(
                    f"[Depth {depth}] Cannot split section <{tag}> with {tokens} tokens - "
                    f"no children available. This section will remain oversized."
                )
                return [section]

            logger.info(
                f"[Depth {depth}] Splitting section <{tag}> ({tokens} tokens) "
                f"into {len(children)} children..."
            )

            # 筛选有效的子节点
            valid_children = []
            for child in children:
                # 跳过无效标签
                if child.tag.lower() in self.SKIP_TAGS:
                    continue

                # 跳过太小的元素（但对于大元素放宽限制）
                child_tokens = child.inner_html_length // 4
                if child.rect.height < self.MIN_SECTION_HEIGHT and child_tokens < self.LARGE_TOKEN_THRESHOLD:
                    continue

                # 跳过token太少的元素
                if child_tokens < self.MIN_SECTION_TOKENS:
                    continue

                valid_children.append(child)

            # 如果没有有效子节点，无法拆分
            if not valid_children:
                logger.warning(
                    f"[Depth {depth}] Cannot split section <{tag}> with {tokens} tokens - "
                    f"no valid children after filtering. This section will remain oversized."
                )
                return [section]

            # 对每个有效子节点创建section，然后递归拆分
            result = []
            for child in valid_children:
                child_section = create_child_section(child)
                child_tokens = child_section.get('estimated_tokens', 0)

                # 递归拆分这个子section
                # 注意：这里是关键 - 先完全处理一个子section，再处理下一个
                split_results = split_until_small(child_section, depth + 1)
                result.extend(split_results)

            # 如果拆分后没有结果（不应该发生），返回原section
            if not result:
                logger.warning(
                    f"[Depth {depth}] Split produced no results for section <{tag}> "
                    f"with {tokens} tokens. Keeping original."
                )
                return [section]

            logger.info(
                f"[Depth {depth}] Section <{tag}> ({tokens} tokens) split into "
                f"{len(result)} sub-sections"
            )

            return result

        # 主流程：对每个section进行深度优先拆分
        result = []
        total_input = len(sections)

        for idx, section in enumerate(sections):
            tokens = section.get('estimated_tokens', 0)
            tag = section.get('tag', 'unknown')

            if tokens > self.MAX_SECTION_TOKENS:
                logger.info(
                    f"Processing section {idx + 1}/{total_input}: <{tag}> "
                    f"with {tokens} tokens (>{self.MAX_SECTION_TOKENS}, needs splitting)"
                )
                split_results = split_until_small(section, 0)
                result.extend(split_results)
            else:
                result.append(section)

        # 统计和日志
        oversized = [s for s in result if s.get('estimated_tokens', 0) > self.MAX_SECTION_TOKENS]
        if oversized:
            logger.warning(
                f"After splitting: {len(result)} sections total, "
                f"{len(oversized)} still exceed {self.MAX_SECTION_TOKENS} tokens"
            )
            for s in oversized:
                logger.warning(
                    f"  - <{s.get('tag', 'unknown')}> with {s.get('estimated_tokens', 0)} tokens"
                )
        else:
            logger.info(
                f"All {len(result)} sections are under {self.MAX_SECTION_TOKENS} tokens"
            )

        return result

    def _handle_horizontal_layout(self, sections: List[Dict]) -> List[Dict]:
        """
        处理水平并排的布局

        如果多个section在垂直方向上重叠较多，则它们是并排的，
        应该按照从左到右、从上到下的顺序排列
        """
        if len(sections) <= 1:
            return sections

        # 按Y坐标初步排序
        sections.sort(key=lambda s: (s['rect']['y'], s['rect']['x']))

        # 分组：找出垂直重叠的section组
        groups = []
        current_group = [sections[0]]

        for i in range(1, len(sections)):
            current = sections[i]
            prev = current_group[-1]

            # 计算垂直重叠
            overlap_top = max(current['rect']['top'], prev['rect']['top'])
            overlap_bottom = min(current['rect']['bottom'], prev['rect']['bottom'])
            overlap_height = max(0, overlap_bottom - overlap_top)

            current_height = current['rect']['bottom'] - current['rect']['top']
            prev_height = prev['rect']['bottom'] - prev['rect']['top']
            min_height = min(current_height, prev_height)

            # 如果垂直重叠超过30%，认为是同一行（并排）
            if min_height > 0 and overlap_height / min_height > self.HORIZONTAL_OVERLAP_THRESHOLD:
                current_group.append(current)
            else:
                # 新的一行
                groups.append(current_group)
                current_group = [current]

        groups.append(current_group)

        # 对每组内部按X坐标排序，然后合并
        result = []
        for group in groups:
            # 组内按X坐标排序（从左到右）
            group.sort(key=lambda s: s['rect']['x'])
            result.extend(group)

        return result

    def _remove_overlaps(self, sections: List[Dict]) -> List[Dict]:
        """
        去重并处理重叠（原则1：块之间不重叠）

        策略：如果两个section重叠过多，保留token更多的那个
        """
        if len(sections) <= 1:
            return sections

        kept = []

        for section in sections:
            s_rect = section['rect']
            s_area = s_rect['width'] * s_rect['height']

            is_redundant = False
            remove_existing = None

            for k in kept:
                k_rect = k['rect']

                # 计算重叠区域
                overlap_left = max(s_rect['left'], k_rect['left'])
                overlap_right = min(s_rect['right'], k_rect['right'])
                overlap_top = max(s_rect['top'], k_rect['top'])
                overlap_bottom = min(s_rect['bottom'], k_rect['bottom'])

                overlap_width = max(0, overlap_right - overlap_left)
                overlap_height = max(0, overlap_bottom - overlap_top)
                overlap_area = overlap_width * overlap_height

                # 如果重叠超过较小区域的50%，认为是重叠
                min_area = min(s_area, k_rect['width'] * k_rect['height'])
                if min_area > 0 and overlap_area / min_area > 0.5:
                    # 保留token更多的那个
                    if section['estimated_tokens'] > k['estimated_tokens']:
                        remove_existing = k
                        break
                    else:
                        is_redundant = True
                        break

            if remove_existing:
                kept.remove(remove_existing)
                kept.append(section)
            elif not is_redundant:
                kept.append(section)

        return kept

    def _merge_gaps(self, sections: List[Dict]) -> List[Dict]:
        """
        合并间隙到相邻Section（原则2：不遗漏，但不创建空Section）

        策略：如果有间隙，扩展相邻section的rect来覆盖
        """
        if not sections:
            return sections

        # 按Y坐标排序
        sections.sort(key=lambda s: s['rect']['y'])

        gap_threshold = 30  # 小于30px的间隙忽略

        # 处理顶部间隙 - 扩展第一个section
        first = sections[0]
        if first['rect']['top'] > gap_threshold:
            first['rect']['top'] = 0
            first['rect']['y'] = 0
            first['rect']['height'] = first['rect']['bottom']

        # 处理中间间隙 - 扩展前一个section的bottom
        for i in range(1, len(sections)):
            prev = sections[i - 1]
            current = sections[i]

            gap = current['rect']['top'] - prev['rect']['bottom']
            if gap > gap_threshold:
                # 将间隙分配给前一个section（扩展其bottom）
                mid_point = prev['rect']['bottom'] + gap / 2
                prev['rect']['bottom'] = mid_point
                prev['rect']['height'] = prev['rect']['bottom'] - prev['rect']['top']
                current['rect']['top'] = mid_point
                current['rect']['y'] = mid_point
                current['rect']['height'] = current['rect']['bottom'] - current['rect']['top']

        # 处理底部间隙 - 扩展最后一个section
        last = sections[-1]
        if self.page_height - last['rect']['bottom'] > gap_threshold:
            last['rect']['bottom'] = self.page_height
            last['rect']['height'] = last['rect']['bottom'] - last['rect']['top']

        return sections

    def _validate_three_principles(self, sections: List[Dict]) -> Dict[str, Any]:
        """
        验证三原则：
        1. 不重叠
        2. 不遗漏
        3. 不超过10K token
        """
        errors = []
        warnings = []

        # 原则1：检查重叠
        for i, s1 in enumerate(sections):
            for j, s2 in enumerate(sections):
                if i >= j:
                    continue

                # 计算重叠
                overlap_left = max(s1['rect']['left'], s2['rect']['left'])
                overlap_right = min(s1['rect']['right'], s2['rect']['right'])
                overlap_top = max(s1['rect']['top'], s2['rect']['top'])
                overlap_bottom = min(s1['rect']['bottom'], s2['rect']['bottom'])

                if overlap_left < overlap_right and overlap_top < overlap_bottom:
                    overlap_area = (overlap_right - overlap_left) * (overlap_bottom - overlap_top)
                    if overlap_area > 100:  # 超过100平方像素的重叠
                        warnings.append(f"Overlap detected: section {i+1} and section {j+1} ({overlap_area:.0f}px²)")

        # 原则2：检查覆盖率
        if sections:
            total_coverage = 0
            for s in sections:
                total_coverage += s['rect']['width'] * s['rect']['height']

            page_area = self.page_width * self.page_height
            coverage_ratio = total_coverage / page_area if page_area > 0 else 0

            if coverage_ratio < 0.8:
                warnings.append(f"Low coverage: {coverage_ratio*100:.1f}% of page area")

        # 原则3：检查token大小
        for i, s in enumerate(sections):
            tokens = s.get('estimated_tokens', 0)
            if tokens > self.MAX_SECTION_TOKENS:
                errors.append(f"Section {i+1} exceeds {self.MAX_SECTION_TOKENS} tokens: {tokens} tokens")

        return {
            'errors': errors,
            'warnings': warnings,
            'section_count': len(sections),
            'principles_met': len(errors) == 0,
        }

    async def _extract_sections_from_page(self, page_info: Dict) -> List[Dict]:
        """备用方法：如果没有dom_tree，从页面直接提取"""
        sections = await self.page.evaluate('''
            (pageWidth, pageHeight, maxTokens) => {
                const results = [];
                const minWidth = pageWidth * 0.4;
                const minHeight = 50;

                function getSelector(el) {
                    if (el.id) return '#' + el.id;
                    let selector = el.tagName.toLowerCase();
                    if (el.className && typeof el.className === 'string') {
                        const cls = el.className.trim().split(/\\s+/)[0];
                        if (cls && !/^\\d/.test(cls) && !cls.startsWith('-')) {
                            selector += '.' + cls;
                        }
                    }
                    return selector;
                }

                function estimateTokens(el) {
                    return el.innerHTML.length / 4;
                }

                function extractSections(el, depth = 0) {
                    const tag = el.tagName.toLowerCase();
                    if (['script', 'style', 'head', 'meta', 'link', 'noscript', 'svg'].includes(tag)) {
                        return;
                    }

                    const rect = el.getBoundingClientRect();
                    const scrollY = window.scrollY;

                    if (rect.width < minWidth || rect.height < minHeight) {
                        return;
                    }

                    const tokens = estimateTokens(el);

                    // 如果足够小，直接添加
                    if (tokens <= maxTokens || depth > 5) {
                        results.push({
                            tag: tag,
                            id: el.id || null,
                            classes: el.className ? el.className.split(/\\s+/).filter(c => c) : [],
                            selector: getSelector(el),
                            type: 'section',
                            rect: {
                                x: rect.left,
                                y: rect.top + scrollY,
                                width: rect.width,
                                height: rect.height,
                                top: rect.top + scrollY,
                                bottom: rect.bottom + scrollY,
                                left: rect.left,
                                right: rect.right
                            },
                            inner_html_length: el.innerHTML.length,
                            estimated_tokens: Math.floor(tokens),
                            children_count: el.children.length
                        });
                        return;
                    }

                    // 太大，检查子元素
                    for (const child of el.children) {
                        extractSections(child, depth + 1);
                    }
                }

                // 从body开始
                extractSections(document.body, 0);

                results.sort((a, b) => a.rect.y - b.rect.y);
                return results;
            }
        ''', page_info['width'], page_info['height'], self.MAX_SECTION_TOKENS)

        return sections

    async def _create_component_infos(
        self,
        sections: List[Dict]
    ) -> List[ComponentInfo]:
        """为每个Section创建ComponentInfo对象"""
        components = []
        used_ranges: List[Tuple[int, int]] = []  # 跟踪已分配的字符范围
        html_fingerprints: Dict[str, str] = {}  # Track HTML fingerprints to detect duplicates

        for idx, section in enumerate(sections):
            try:
                # 获取HTML内容（如果不是间隙section）
                html_content = ""
                cleaned_html = ""
                if not section.get('is_gap') and section['selector']:
                    # Pass rect to distinguish elements with same selector
                    section_rect = section.get('rect', {})
                    html_content = await self._get_section_html(section['selector'], section_rect)
                    # 清理 HTML：移除 base64 图片、SVG、超长样式等
                    cleaned_html = clean_html_for_tokens(html_content)

                    # DEBUG: Check for duplicate HTML at extraction time
                    if html_content:
                        fingerprint = html_content[:200]  # First 200 chars as fingerprint
                        if fingerprint in html_fingerprints:
                            logger.warning(
                                f"[_create_component_infos] DUPLICATE HTML detected at extraction!\n"
                                f"  Section idx={idx}, selector='{section['selector']}', rect.y={section_rect.get('y')}\n"
                                f"  Duplicate of: {html_fingerprints[fingerprint]}\n"
                                f"  HTML preview: {fingerprint[:80]}..."
                            )
                        else:
                            html_fingerprints[fingerprint] = f"idx={idx}, selector='{section['selector']}'"

                # 计算在原始HTML中的字符位置（传入已使用的范围避免重复）
                char_start, char_end = self._find_html_position_in_raw(
                    html_content,
                    section.get('selector', ''),
                    section.get('tag', ''),
                    section.get('id'),
                    section.get('classes', []),
                    used_ranges
                )

                # 记录已使用的范围
                if char_start > 0 and char_end > char_start:
                    used_ranges.append((char_start, char_end))

                # 估算 token - 使用清理后的 HTML 长度
                # 这才是传递给 Worker Agent 的实际内容长度
                if cleaned_html:
                    html_length = len(cleaned_html)
                elif section.get('inner_html_length', 0) > 0:
                    # inner_html_length 已经在 extractor_service 中被清理过了
                    html_length = section['inner_html_length']
                elif section.get('estimated_tokens', 0) > 0:
                    html_length = section['estimated_tokens'] * 4
                else:
                    html_length = 0

                estimated_tokens = html_length // 4

                # 创建样式对象
                styles_dict = section.get('styles', {})
                styles = SectionStyles(
                    background_color=styles_dict.get('background_color'),
                    background_image=styles_dict.get('background_image'),
                    color=styles_dict.get('color'),
                    padding=styles_dict.get('padding'),
                )

                # 创建ComponentInfo
                component = ComponentInfo(
                    id=f"section-{idx + 1}",
                    name=f"section_{idx + 1}",
                    type=section.get('type', 'section'),
                    selector=section['selector'],
                    rect=ElementRect(
                        x=section['rect']['x'],
                        y=section['rect']['y'],
                        width=section['rect']['width'],
                        height=section['rect']['height'],
                        top=section['rect']['top'],
                        bottom=section['rect']['bottom'],
                        left=section['rect']['left'],
                        right=section['rect']['right']
                    ),
                    styles=styles,
                    code_location={
                        # 存储清理后的 HTML（移除了 base64 图片、SVG 等）
                        # 这是传递给 Worker Agent 的实际内容
                        "full_html": cleaned_html[:50000] if cleaned_html else "",
                        "estimated_chars": html_length,
                        "estimated_tokens": estimated_tokens,
                        "char_start": char_start,
                        "char_end": char_end,
                        "start_line": self._char_to_line(char_start) if char_start > 0 else 0,
                        "end_line": self._char_to_line(char_end) if char_end > 0 else 0,
                        # 保留原始长度供参考
                        "raw_html_length": len(html_content) if html_content else 0,
                    }
                )

                # 提取链接和图片
                if not section.get('is_gap'):
                    await self._extract_section_content(component, section['selector'])

                components.append(component)

            except Exception as e:
                logger.warning(f"Failed to create component for {section.get('selector', 'unknown')}: {e}")
                continue

        return components

    def _find_html_position_in_raw(
        self,
        html_content: str,
        selector: str,
        tag: str,
        element_id: Optional[str],
        classes: List[str],
        used_ranges: List[Tuple[int, int]]
    ) -> Tuple[int, int]:
        """
        在原始HTML中查找元素的字符位置

        Args:
            html_content: 元素的HTML内容
            selector: CSS选择器
            tag: 标签名
            element_id: 元素ID
            classes: 元素的class列表
            used_ranges: 已使用的字符范围列表，避免重复匹配

        Returns:
            Tuple[int, int]: (char_start, char_end)，如果找不到返回 (0, 0)
        """
        if not self.raw_html:
            return (0, 0)

        import re

        def is_position_used(start: int, end: int) -> bool:
            """检查位置是否与已使用的范围重叠"""
            for used_start, used_end in used_ranges:
                # 如果有重叠
                if start < used_end and end > used_start:
                    return True
            return False

        def find_unused_match(pattern: str, estimate_end_func) -> Tuple[int, int]:
            """找到第一个未使用的匹配位置"""
            try:
                for match in re.finditer(pattern, self.raw_html, re.IGNORECASE):
                    char_start = match.start()
                    char_end = estimate_end_func(char_start)
                    char_end = min(char_end, len(self.raw_html))

                    if not is_position_used(char_start, char_end):
                        return (char_start, char_end)
            except:
                pass
            return (0, 0)

        # 策略1: 如果有HTML内容，直接搜索
        if html_content and len(html_content) > 50:
            # 取前200个字符作为搜索模式（增加长度减少碰撞）
            search_prefix = html_content[:200].strip()
            search_prefix_escaped = re.escape(search_prefix)

            result = find_unused_match(
                search_prefix_escaped,
                lambda start: start + len(html_content)
            )
            if result != (0, 0):
                return result

        # 策略2: 基于标签和ID搜索
        if element_id:
            pattern = f'<{tag}[^>]*id=["\']?{re.escape(element_id)}["\']?[^>]*>'

            def find_closing(start):
                closing_tag = f'</{tag}>'
                closing_pos = self.raw_html.find(closing_tag, start)
                if closing_pos > start:
                    return closing_pos + len(closing_tag)
                return start + 1000

            result = find_unused_match(pattern, find_closing)
            if result != (0, 0):
                return result

        # 策略3: 基于标签和class搜索
        if classes and len(classes) > 0:
            first_class = classes[0]
            if first_class and not first_class[0].isdigit():
                pattern = f'<{tag}[^>]*class=["\'][^"\']*{re.escape(first_class)}[^"\']*["\'][^>]*>'

                def find_closing(start):
                    closing_tag = f'</{tag}>'
                    closing_pos = self.raw_html.find(closing_tag, start)
                    if closing_pos > start:
                        return closing_pos + len(closing_tag)
                    return start + 1000

                result = find_unused_match(pattern, find_closing)
                if result != (0, 0):
                    return result

        # 策略4: 简单标签搜索
        if tag:
            pattern = f'<{tag}[^>]*>'

            def find_closing(start):
                closing_tag = f'</{tag}>'
                closing_pos = self.raw_html.find(closing_tag, start)
                if closing_pos > start:
                    return closing_pos + len(closing_tag)
                return start + 1000

            result = find_unused_match(pattern, find_closing)
            if result != (0, 0):
                return result

        return (0, 0)

    def _char_to_line(self, char_pos: int) -> int:
        """将字符位置转换为行号"""
        if not self.raw_html or char_pos <= 0:
            return 0

        # 计算到char_pos为止有多少换行符
        text_before = self.raw_html[:char_pos]
        return text_before.count('\n') + 1

    async def _get_section_html(self, selector: str, rect: dict = None) -> str:
        """
        获取Section的HTML内容

        多策略获取：
        1. 使用 querySelectorAll + rect 位置匹配（处理相同selector的多个元素）
        2. 回退到 querySelector 精确选择
        3. 尝试模糊匹配（只用标签和第一个class）
        """
        # 策略1: 使用 querySelectorAll + rect 位置匹配
        if rect and rect.get('y') is not None:
            try:
                result = await self.page.evaluate('''
                    (params) => {
                        try {
                            const { selector, targetY, tolerance } = params;
                            const elements = document.querySelectorAll(selector);

                            // Debug info
                            const debug = {
                                selector: selector,
                                targetY: targetY,
                                elementCount: elements.length,
                                candidates: []
                            };

                            if (elements.length === 0) return { html: '', debug };
                            if (elements.length === 1) {
                                const el = elements[0];
                                const rect = el.getBoundingClientRect();
                                const scrollY = window.scrollY || document.documentElement.scrollTop;
                                debug.candidates.push({
                                    y: rect.top + scrollY,
                                    distance: 0,
                                    selected: true
                                });
                                return { html: el.outerHTML, debug };
                            }

                            // Find element closest to target Y position
                            let bestMatch = null;
                            let bestDistance = Infinity;
                            let bestIndex = -1;

                            for (let i = 0; i < elements.length; i++) {
                                const el = elements[i];
                                const rect = el.getBoundingClientRect();
                                const scrollY = window.scrollY || document.documentElement.scrollTop;
                                const elY = rect.top + scrollY;
                                const distance = Math.abs(elY - targetY);

                                debug.candidates.push({
                                    index: i,
                                    y: elY,
                                    distance: distance,
                                    selected: false
                                });

                                if (distance < bestDistance) {
                                    bestDistance = distance;
                                    bestMatch = el;
                                    bestIndex = i;
                                }
                            }

                            // Mark selected
                            if (bestIndex >= 0 && debug.candidates[bestIndex]) {
                                debug.candidates[bestIndex].selected = true;
                            }

                            return { html: bestMatch ? bestMatch.outerHTML : '', debug };
                        } catch (e) {
                            return { html: '', debug: { error: e.toString() } };
                        }
                    }
                ''', {"selector": selector, "targetY": rect.get('y', 0), "tolerance": 50})

                if result and isinstance(result, dict):
                    html = result.get('html', '')
                    debug = result.get('debug', {})

                    # Log debug info
                    element_count = debug.get('elementCount', 0)
                    if element_count > 1:
                        candidates = debug.get('candidates', [])
                        selected = [c for c in candidates if c.get('selected')]
                        logger.info(
                            f"[_get_section_html] Multiple elements for '{selector}': "
                            f"count={element_count}, targetY={debug.get('targetY')}, "
                            f"selected y={selected[0].get('y') if selected else 'none'}"
                        )

                    if html:
                        return html
            except Exception as e:
                logger.warning(f"[_get_section_html] Strategy 1 failed for '{selector}': {e}")
                pass

        # 策略2: 精确选择器（回退）
        try:
            html = await self.page.evaluate('''
                (selector) => {
                    try {
                        const el = document.querySelector(selector);
                        return el ? el.outerHTML : '';
                    } catch (e) {
                        return '';
                    }
                }
            ''', selector)
            if html:
                return html
        except:
            pass

        # 策略3: 解析选择器，尝试简化版本
        try:
            # 尝试用更简单的选择器
            simplified_selectors = self._generate_fallback_selectors(selector)
            for simple_selector in simplified_selectors:
                try:
                    html = await self.page.evaluate('''
                        (selector) => {
                            try {
                                const el = document.querySelector(selector);
                                return el ? el.outerHTML : '';
                            } catch (e) {
                                return '';
                            }
                        }
                    ''', simple_selector)
                    if html:
                        logger.debug(f"Fallback selector matched: {simple_selector}")
                        return html
                except:
                    continue
        except:
            pass

        return ''

    def _generate_fallback_selectors(self, selector: str) -> List[str]:
        """生成备用选择器列表"""
        fallbacks = []

        # 如果是ID选择器，直接返回
        if selector.startswith('#'):
            return [selector]

        # 解析选择器
        parts = selector.split('.')
        if len(parts) >= 1:
            tag = parts[0]

            # 只用标签
            if tag:
                fallbacks.append(tag)

            # 标签+第一个class
            if len(parts) >= 2 and parts[1]:
                first_class = parts[1].split(':')[0].split('[')[0]  # 移除伪类和属性选择器
                if first_class and not first_class[0].isdigit():
                    fallbacks.append(f"{tag}.{first_class}")

        return fallbacks

    async def _extract_section_content(self, component: ComponentInfo, selector: str):
        """提取Section中的链接和图片"""
        try:
            content = await self.page.evaluate('''
                (selector, baseDomain) => {
                    const el = document.querySelector(selector);
                    if (!el) return { links: [], images: [], headings: [] };

                    const links = [];
                    el.querySelectorAll('a[href]').forEach(a => {
                        const href = a.href;
                        const text = a.textContent?.trim() || '';
                        const isExternal = !href.includes(baseDomain) && href.startsWith('http');
                        links.push({ href, text, isExternal });
                    });

                    const images = [];
                    el.querySelectorAll('img').forEach(img => {
                        images.push({
                            src: img.src,
                            alt: img.alt || '',
                            width: img.naturalWidth,
                            height: img.naturalHeight
                        });
                    });

                    const headings = [];
                    el.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach(h => {
                        headings.push({
                            level: parseInt(h.tagName[1]),
                            text: h.textContent?.trim() || ''
                        });
                    });

                    return { links, images, headings };
                }
            ''', selector, self.base_domain)

            if content:
                internal_links = [l for l in content.get('links', []) if not l.get('isExternal')]
                external_links = [l for l in content.get('links', []) if l.get('isExternal')]

                component.internal_links = internal_links[:20]
                component.external_links = external_links[:20]
                component.images = content.get('images', [])[:20]

                headings = content.get('headings', [])
                component.text_summary = {
                    "headings": [h.get('text', '') for h in headings[:5]],
                    "heading_count": len(headings),
                }

        except Exception as e:
            logger.debug(f"Failed to extract content for {selector}: {e}")

    def _unify_naming(self):
        """
        统一命名为 section_1, section_2, ...

        按照从上到下、从左到右的顺序编号
        """
        # 按Y坐标排序，Y相同则按X坐标
        self.components.sort(key=lambda c: (c.rect.y, c.rect.x))

        # 统一命名
        for idx, component in enumerate(self.components):
            component.name = f"section_{idx + 1}"
            component.id = f"section-{idx + 1}"
            component.type = "section"  # 确保类型也统一

    def _calculate_stats(self) -> Dict[str, Any]:
        """计算统计信息"""
        by_type = {}
        total_links = 0
        total_images = 0
        total_tokens = 0

        for comp in self.components:
            comp_type = comp.type
            by_type[comp_type] = by_type.get(comp_type, 0) + 1

            if comp.internal_links:
                total_links += len(comp.internal_links)
            if comp.external_links:
                total_links += len(comp.external_links)
            if comp.images:
                total_images += len(comp.images)

            # 统计tokens
            if comp.code_location and 'estimated_tokens' in comp.code_location:
                total_tokens += comp.code_location['estimated_tokens']

        return {
            "total_components": len(self.components),
            "by_type": by_type,
            "total_links": total_links,
            "total_images": total_images,
            "total_tokens": total_tokens,
            "avg_tokens_per_section": total_tokens // len(self.components) if self.components else 0,
        }


async def analyze_components(
    page: Page,
    base_url: str,
    raw_html: Optional[str] = None,
    dom_tree: Optional[ElementInfo] = None
) -> ComponentAnalysisData:
    """
    分析页面组件的便捷函数

    Args:
        page: Playwright Page对象
        base_url: 页面URL
        raw_html: 原始HTML（可选）
        dom_tree: 已提取的DOM树（必须提供以实现精细分块）

    Returns:
        ComponentAnalysisData: 分析结果
    """
    analyzer = ComponentAnalyzer(page, base_url, raw_html, dom_tree)
    return await analyzer.analyze()
