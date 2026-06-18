"""
Conversation Pipeline (nE2)

实现 Claude Code 的对话管道处理器。

核心功能：
- LLM API 调用
- 模型降级（fallback chain）
- 错误恢复
- 流式响应处理
- Token 使用追踪
"""

from __future__ import annotations
import logging
import os
from typing import Dict, Any, List, Optional, AsyncGenerator
import anthropic

from .constants import (
    ExecutionContext,
    DEFAULT_MODEL,
    FALLBACK_MODEL_CHAIN,
    MAX_OUTPUT_TOKENS,
    get_model_context_limit,
)

logger = logging.getLogger(__name__)


class ConversationPipeline:
    """
    对话管道处理器（nE2）

    负责与 Claude API 通信，处理流式响应
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        default_model: str = DEFAULT_MODEL,
        enable_fallback: bool = True,
    ):
        """
        初始化对话管道

        Args:
            api_key: Anthropic API Key
            base_url: API 基础 URL（用于代理）
            default_model: 默认模型
            enable_fallback: 是否启用模型降级
        """
        # 从环境变量获取配置
        self.api_key = api_key or self._get_api_key()
        # 仅当显式启用代理时才使用代理 URL，避免在 USE_CLAUDE_PROXY=false 时
        # 把官方 API Key 静默转发到第三方代理。
        use_proxy = os.getenv("USE_CLAUDE_PROXY", "").lower() == "true"
        self.base_url = base_url or (os.getenv("CLAUDE_PROXY_BASE_URL") if use_proxy else None)
        self.default_model = default_model
        self.enable_fallback = enable_fallback

        # 初始化 Anthropic 客户端
        client_kwargs = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        self.client = anthropic.AsyncAnthropic(**client_kwargs)

        # 统计信息
        self._stats = {
            "requests": 0,
            "successful": 0,
            "failed": 0,
            "fallback_used": 0,
        }

        logger.info(
            f"ConversationPipeline 初始化："
            f"model={default_model}, fallback={enable_fallback}"
        )

    def _get_api_key(self) -> str:
        """
        获取 API Key

        优先级：
        1. ANTHROPIC_API_KEY
        2. CLAUDE_PROXY_API_KEY（如果使用代理）

        Returns:
            API Key

        Raises:
            ValueError: 如果未找到 API Key
        """
        # 检查是否使用代理
        use_proxy = os.getenv("USE_CLAUDE_PROXY", "").lower() == "true"

        if use_proxy:
            api_key = os.getenv("CLAUDE_PROXY_API_KEY")
            if api_key:
                logger.info("使用 Claude 代理 API Key")
                return api_key

        # 使用官方 API Key
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if api_key:
            logger.info("使用 Anthropic 官方 API Key")
            return api_key

        raise ValueError(
            "未找到 API Key。请设置环境变量：\n"
            "- ANTHROPIC_API_KEY（官方）\n"
            "- 或 CLAUDE_PROXY_API_KEY + USE_CLAUDE_PROXY=true（代理）"
        )

    async def stream_conversation(
        self,
        messages: List[Dict[str, Any]],
        context: ExecutionContext,
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        max_tokens: int = MAX_OUTPUT_TOKENS,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式对话

        Args:
            messages: 消息列表
            context: 执行上下文
            system_prompt: 系统提示
            tools: 工具定义列表
            model: 指定模型（可选）
            max_tokens: 最大输出 Token 数

        Yields:
            流式事件字典
        """
        target_model = model or context.model or self.default_model

        self._stats["requests"] += 1

        try:
            # 尝试调用 API
            async for event in self._call_api(
                messages=messages,
                system_prompt=system_prompt,
                tools=tools,
                model=target_model,
                max_tokens=max_tokens,
            ):
                # 更新 Token 使用
                if event.get("type") == "message_delta":
                    usage = event.get("usage", {})
                    context.update_token_usage(
                        output_tokens=usage.get("output_tokens", 0)
                    )

                yield event

            self._stats["successful"] += 1

        except anthropic.APIError as e:
            logger.error(f"API 调用失败：{e}", exc_info=True)

            # 尝试模型降级
            if self.enable_fallback and target_model in FALLBACK_MODEL_CHAIN:
                logger.info("尝试模型降级...")
                async for event in self._fallback_call(
                    messages=messages,
                    context=context,
                    system_prompt=system_prompt,
                    tools=tools,
                    failed_model=target_model,
                    max_tokens=max_tokens,
                ):
                    yield event
            else:
                # 无法降级，抛出错误
                self._stats["failed"] += 1
                raise

    async def _call_api(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str],
        tools: Optional[List[Dict[str, Any]]],
        model: str,
        max_tokens: int,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        调用 Anthropic API

        Args:
            messages: 消息列表
            system_prompt: 系统提示
            tools: 工具定义
            model: 模型名称
            max_tokens: 最大 Token 数

        Yields:
            API 流式响应事件
        """
        logger.info(f"调用 Claude API：model={model}, messages={len(messages)}")

        # 构建请求参数
        request_params: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "stream": True,
        }

        # 添加系统提示
        if system_prompt:
            request_params["system"] = system_prompt

        # 添加工具定义
        if tools:
            request_params["tools"] = tools

        # 流式调用
        async with self.client.messages.stream(**request_params) as stream:
            async for event in stream:
                # 转换为字典格式
                event_dict = self._parse_stream_event(event)
                yield event_dict

            # 获取最终消息
            final_message = await stream.get_final_message()

            # 返回完成事件
            yield {
                "type": "message_complete",
                "message": {
                    "id": final_message.id,
                    "role": final_message.role,
                    "content": [
                        block.model_dump() if hasattr(block, "model_dump") else block
                        for block in final_message.content
                    ],
                    "model": final_message.model,
                    "stop_reason": final_message.stop_reason,
                    "usage": {
                        "input_tokens": final_message.usage.input_tokens,
                        "output_tokens": final_message.usage.output_tokens,
                    },
                },
            }

    def _parse_stream_event(self, event: Any) -> Dict[str, Any]:
        """
        解析流式事件

        Args:
            event: Anthropic SDK 事件对象

        Returns:
            事件字典
        """
        # 根据事件类型解析
        event_type = event.type

        if event_type == "content_block_start":
            return {
                "type": "content_block_start",
                "index": event.index,
                "content_block": (
                    event.content_block.model_dump()
                    if hasattr(event.content_block, "model_dump")
                    else event.content_block
                ),
            }

        elif event_type == "content_block_delta":
            return {
                "type": "content_block_delta",
                "index": event.index,
                "delta": (
                    event.delta.model_dump()
                    if hasattr(event.delta, "model_dump")
                    else event.delta
                ),
            }

        elif event_type == "content_block_stop":
            return {
                "type": "content_block_stop",
                "index": event.index,
            }

        elif event_type == "message_start":
            return {
                "type": "message_start",
                "message": (
                    event.message.model_dump()
                    if hasattr(event.message, "model_dump")
                    else event.message
                ),
            }

        elif event_type == "message_delta":
            return {
                "type": "message_delta",
                "delta": (
                    event.delta.model_dump()
                    if hasattr(event.delta, "model_dump")
                    else event.delta
                ),
                "usage": (
                    event.usage.model_dump()
                    if hasattr(event.usage, "model_dump")
                    else event.usage
                ),
            }

        elif event_type == "message_stop":
            return {
                "type": "message_stop",
            }

        else:
            # 未知事件类型
            return {
                "type": event_type,
                "raw_event": str(event),
            }

    async def _fallback_call(
        self,
        messages: List[Dict[str, Any]],
        context: ExecutionContext,
        system_prompt: Optional[str],
        tools: Optional[List[Dict[str, Any]]],
        failed_model: str,
        max_tokens: int,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        模型降级调用

        Args:
            messages: 消息列表
            context: 执行上下文
            system_prompt: 系统提示
            tools: 工具定义
            failed_model: 失败的模型
            max_tokens: 最大 Token 数

        Yields:
            流式事件
        """
        # 找到当前模型在 fallback chain 中的位置
        try:
            current_index = FALLBACK_MODEL_CHAIN.index(failed_model)
        except ValueError:
            logger.warning(f"模型 {failed_model} 不在 fallback chain 中")
            return

        # 尝试后续模型
        for fallback_model in FALLBACK_MODEL_CHAIN[current_index + 1:]:
            logger.info(f"降级到模型：{fallback_model}")

            try:
                async for event in self._call_api(
                    messages=messages,
                    system_prompt=system_prompt,
                    tools=tools,
                    model=fallback_model,
                    max_tokens=max_tokens,
                ):
                    yield event

                # 成功，更新上下文中的模型
                context.model = fallback_model
                self._stats["fallback_used"] += 1
                self._stats["successful"] += 1

                logger.info(f"模型降级成功：{failed_model} -> {fallback_model}")
                return

            except anthropic.APIError as e:
                logger.error(f"降级模型 {fallback_model} 也失败：{e}")
                continue

        # 所有降级都失败
        self._stats["failed"] += 1
        raise RuntimeError(
            f"所有模型都失败了。Fallback chain: {FALLBACK_MODEL_CHAIN}"
        )

    async def single_message(
        self,
        message: str,
        context: ExecutionContext,
        system_prompt: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        发送单条消息（非流式）

        Args:
            message: 用户消息
            context: 执行上下文
            system_prompt: 系统提示
            tools: 工具定义
            model: 指定模型

        Returns:
            完整的响应消息
        """
        messages = [{"role": "user", "content": message}]

        final_message = None

        async for event in self.stream_conversation(
            messages=messages,
            context=context,
            system_prompt=system_prompt,
            tools=tools,
            model=model,
        ):
            if event.get("type") == "message_complete":
                final_message = event.get("message")

        if final_message is None:
            raise RuntimeError("未收到完整消息")

        return final_message

    def get_stats(self) -> Dict[str, Any]:
        """
        获取管道统计信息

        Returns:
            统计数据字典
        """
        return {
            **self._stats,
            "model": self.default_model,
            "fallback_enabled": self.enable_fallback,
        }

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"ConversationPipeline("
            f"model={self.default_model}, "
            f"requests={stats['requests']}, "
            f"success_rate={stats['successful']}/{stats['requests'] if stats['requests'] > 0 else 1})"
        )
