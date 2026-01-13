"""
Code Generation Configuration
后端配置文件
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ==================== Claude Proxy Configuration ====================
# 中转服务配置

USE_CLAUDE_PROXY = True
CLAUDE_PROXY_API_KEY = os.getenv("CLAUDE_PROXY_API_KEY", "")
CLAUDE_PROXY_BASE_URL = os.getenv("CLAUDE_PROXY_BASE_URL", "https://api.anthropic.com/v1/messages")
CLAUDE_PROXY_MODEL = os.getenv("CLAUDE_PROXY_MODEL", "claude-3-5-sonnet-20241022")

# Direct Anthropic API (fallback)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ==================== Gemini Proxy Configuration ====================
# Gemini 中转服务配置

USE_GEMINI_PROXY = os.getenv("USE_GEMINI_PROXY", "false").lower() == "true"
GEMINI_PROXY_API_KEY = os.getenv("GEMINI_PROXY_API_KEY", "")
GEMINI_PROXY_BASE_URL = os.getenv("GEMINI_PROXY_BASE_URL", "")
GEMINI_PROXY_MODEL = os.getenv("GEMINI_PROXY_MODEL", "gemini-1.5-flash")

# ==================== Server Configuration ====================
# 服务器配置

SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "5100"))

# ==================== Cache Configuration ====================
# 缓存配置

CACHE_MAX_SIZE = int(os.getenv("CACHE_MAX_SIZE", "100"))
CACHE_TTL_HOURS = int(os.getenv("CACHE_TTL_HOURS", "24"))
