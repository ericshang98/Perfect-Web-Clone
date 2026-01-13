"""
FastAPI Routes for Playwright Extractor Module
处理网页结构提取的 HTTP 端点

端点：
- POST /api/extractor/extract - 提取网页完整信息（原始同步方式）
- POST /api/extractor/extract/quick - 快速提取（分阶段，首次响应）
- GET /api/extractor/extract/{request_id}/status - 获取提取状态和后续数据
- GET /api/extractor/health - 健康检查
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import logging

from .models import (
    ExtractRequest,
    ExtractionResult,
    QuickExtractionResult,
    ExtractionStatus,
    ExtractionPhase,
)
from . import playwright_extractor_service
from .cache_manager import extraction_cache

# 设置日志
logger = logging.getLogger(__name__)

# 创建路由器 - 使用 /api/playwright 前缀 (匹配前端)
router = APIRouter(prefix="/api/playwright", tags=["playwright"])


# ==================== Health Check ====================

@router.get('/health')
async def health_check():
    """
    健康检查端点
    用于验证服务是否正常运行
    """
    return {
        'success': True,
        'status': 'healthy',
        'module': 'playwright_extractor',
        'timestamp': datetime.now().isoformat()
    }


# ==================== Extract Endpoint ====================

@router.post('/extract', response_model=ExtractionResult)
async def extract_page(request: ExtractRequest):
    """
    提取网页的完整结构信息

    Request Body:
        {
            "url": "https://example.com",
            "viewport_width": 1920,       // 可选，默认 1920
            "viewport_height": 1080,      // 可选，默认 1080
            "wait_for_selector": null,    // 可选，等待特定选择器
            "wait_timeout": 30000,        // 可选，超时时间（毫秒）
            "include_screenshot": true,   // 可选，是否包含截图
            "max_depth": 50,              // 可选，最大遍历深度
            "include_hidden": false       // 可选，是否包含隐藏元素
        }

    Returns:
        ExtractionResult: 完整的提取结果，包含：
        - metadata: 页面元数据（标题、尺寸、元素数量等）
        - screenshot: Base64 编码的页面截图
        - dom_tree: 完整的 DOM 树结构
        - style_summary: 样式使用统计
        - assets: 页面资源列表
    """
    try:
        # 验证 URL
        if not request.url:
            raise HTTPException(status_code=400, detail='URL is required')

        if not request.url.startswith(('http://', 'https://')):
            raise HTTPException(status_code=400, detail='URL must start with http:// or https://')

        logger.info(f"开始提取页面: {request.url}")
        logger.info(f"视口: {request.viewport_width}x{request.viewport_height}")

        # 调用提取服务
        result = await playwright_extractor_service.extract(request)

        if result.success:
            logger.info(f"提取成功: {request.url}")
            if result.metadata:
                logger.info(f"  - 总元素数: {result.metadata.total_elements}")
                logger.info(f"  - DOM 深度: {result.metadata.max_depth}")
                logger.info(f"  - 加载时间: {result.metadata.load_time_ms}ms")
        else:
            logger.warning(f"提取失败: {request.url} - {result.error}")

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提取异常: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Quick Extract Endpoint (分阶段提取) ====================

@router.post('/extract/quick', response_model=QuickExtractionResult)
async def extract_page_quick(request: ExtractRequest):
    """
    快速提取网页信息（分阶段提取，优化首屏加载）

    第一阶段立即返回基础数据（metadata, screenshot, assets），
    后续数据（DOM树、CSS、资源下载等）在后台继续处理，
    前端通过轮询 /extract/{request_id}/status 获取。

    Request Body:
        同 /extract 端点

    Returns:
        QuickExtractionResult: 快速提取结果，包含：
        - request_id: 用于后续轮询的唯一 ID
        - phase: 当前阶段 (quick)
        - progress: 进度百分比 (25)
        - metadata: 页面元数据
        - screenshot: 截图
        - assets: 资源列表
        - raw_html: 原始 HTML
    """
    try:
        # 验证 URL
        if not request.url:
            raise HTTPException(status_code=400, detail='URL is required')

        if not request.url.startswith(('http://', 'https://')):
            raise HTTPException(status_code=400, detail='URL must start with http:// or https://')

        logger.info(f"[快速提取] 开始: {request.url}")

        # 启动缓存清理任务
        await extraction_cache.start_cleanup_task()

        # 调用快速提取服务
        result = await playwright_extractor_service.extract_quick(request)

        if result.success:
            logger.info(f"[快速提取] 成功: {request.url}, request_id={result.request_id}")
        else:
            logger.warning(f"[快速提取] 失败: {request.url} - {result.error}")

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[快速提取] 异常: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/extract/{request_id}/status', response_model=ExtractionStatus)
async def get_extraction_status(request_id: str):
    """
    获取提取状态和后续阶段数据

    前端轮询此接口获取后台提取的进度和数据。

    Args:
        request_id: 快速提取返回的请求 ID

    Returns:
        ExtractionStatus: 当前状态和已完成阶段的数据
    """
    try:
        cache = await extraction_cache.get(request_id)

        if not cache:
            raise HTTPException(
                status_code=404,
                detail=f'Extraction request not found or expired: {request_id}'
            )

        return ExtractionStatus(
            request_id=request_id,
            phase=cache.phase,
            progress=cache.progress,
            is_complete=cache.phase == ExtractionPhase.COMPLETE,
            # DOM 阶段数据
            dom_tree=cache.dom_tree,
            style_summary=cache.style_summary,
            # 高级阶段数据
            css_data=cache.css_data,
            network_data=cache.network_data,
            full_page_screenshot=cache.full_page_screenshot,
            interaction_data=cache.interaction_data,
            tech_stack=cache.tech_stack,
            components=cache.components,
            # 完成阶段数据
            downloaded_resources=cache.downloaded_resources,
            # 错误信息
            error=cache.error
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取状态失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Cleanup Endpoint ====================

@router.post('/cleanup')
async def cleanup_browser():
    """
    清理浏览器资源
    关闭浏览器实例，释放资源
    """
    try:
        await playwright_extractor_service.close()
        return {
            'success': True,
            'message': 'Browser instance closed'
        }
    except Exception as e:
        logger.error(f"清理失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Resources Download Endpoint ====================

class ResourcesRequest(BaseModel):
    """Request model for fetching page resources (images only)"""
    url: str
    theme: Optional[str] = "light"  # "light" or "dark"
    viewport_width: int = 1920
    viewport_height: int = 1080


@router.post('/resources')
async def fetch_page_resources(request: ResourcesRequest):
    """
    Fetch image resources from a URL (lightweight endpoint for WebContainer)

    This endpoint quickly extracts and downloads image resources from a webpage,
    designed to be faster than full extraction by skipping DOM tree analysis.

    Request Body:
        {
            "url": "https://example.com",
            "theme": "light",  // or "dark"
            "viewport_width": 1920,
            "viewport_height": 1080
        }

    Returns:
        {
            "success": true,
            "images": [
                {
                    "url": "https://example.com/logo.png",
                    "content": "base64...",
                    "mime_type": "image/png",
                    "filename": "logo.png",
                    "size": 12345
                }
            ],
            "total_count": 12,
            "total_size": 123456
        }
    """
    try:
        # Validate URL
        if not request.url:
            raise HTTPException(status_code=400, detail='URL is required')

        if not request.url.startswith(('http://', 'https://')):
            raise HTTPException(status_code=400, detail='URL must start with http:// or https://')

        logger.info(f"[Resources] Fetching images from: {request.url}, theme: {request.theme}")

        # Call the service to fetch resources
        result = await playwright_extractor_service.fetch_resources_only(
            url=request.url,
            theme=request.theme or "light",
            viewport_width=request.viewport_width,
            viewport_height=request.viewport_height
        )

        if result.get("success"):
            images = result.get("images", [])
            total_size = sum(img.get("size", 0) for img in images)
            logger.info(f"[Resources] Success: {len(images)} images, {total_size} bytes")
        else:
            logger.warning(f"[Resources] Failed: {result.get('error')}")

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Resources] Exception: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
