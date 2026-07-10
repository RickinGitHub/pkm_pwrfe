# -*- coding: utf-8 -*-
"""ChatSkill — LLM-powered intent understanding with tool calling.

Routes natural language through an LLM (DeepSeek / OpenAI) that
understands the user's intent and dynamically calls the right tool
(knowledge lookup, fetch_web, file_ops, etc.). Single LLM call for
low latency: tool result is returned directly.

Design ref: docs/telegram_llm_router_design.md
"""

from __future__ import annotations

import json
import os
from typing import Any

from skills.base import Skill, err, ok


# ======================================================================
# Tool definitions — only 4 core tools for clarity
# ======================================================================

_TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "query_knowledge",
            "description": (
                "从本地知识库搜索信息。当你需要查找、查询、搜索信息时使用此工具。"
                "支持任何中文或英文关键词。例如：'查询我的简历' → query='我的简历'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，从用户消息中提取核心搜索词",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": (
                "抓取网页内容并保存到知识库。当用户提供URL或要求抓取网页时使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "要抓取的完整网页URL（以 http:// 或 https:// 开头）",
                    }
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "读取项目中的文件内容并返回给用户。当用户要求'发给我'、'查看'某个文件时使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径，如 rag/corpus/records/resume.md",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_context",
            "description": "获取项目基本信息：项目名、版本、架构、可用技能等",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

# ======================================================================
# System prompt — comprehensive but concise
# ======================================================================

_SYSTEM_PROMPT = """你是一个智能知识助手，运行在 ai-agent-core 项目上。

## 你的能力

你拥有本地知识库，包含用户收集的各种文档（笔记、简历、文章等）。
你可以执行以下操作：

1. **query_knowledge(query)** — 搜索本地知识库
   - 用户说"查询/搜索/找/查一下/帮我查" → 提取关键词调用此工具
   - 用户说"查询我的简历" → 提取"我的简历"作为 query
   - 用户说"帮我找AI相关的文章" → 提取"AI"作为 query
   - 返回搜索结果后，直接回复用户找到的内容

2. **fetch_url(url)** — 抓取网页
   - 用户发来 URL 时，调用此工具抓取并入库
   - 完成后回复"已抓取并保存到知识库"

3. **read_file(path)** — 读取文件
   - 用户要求"发给我/发文件/查看文件"时，调用此工具
   - 返回文件内容给用户

4. **get_context()** — 项目上下文

## 重要规则

- 如果用户只是闲聊（问候、打招呼、随意聊天），不要调用任何工具，直接回复。
- 如果用户要求查询信息，优先使用 query_knowledge。
- 直接回复用户的查询结果，不要问用户"是否需要更多帮助"，直接给答案。
- 回复要简洁、有用。
"""


class ChatSkill(Skill):
    """LLM-powered chat: understand intent → call tools dynamically.

    Single LLM call for low latency. Tool results are returned directly
    without a second LLM call for "final answer".
    """

    def __init__(self, agent) -> None:
        self._agent = agent
        self._client = None
        self._model = os.environ.get("OPENAI_MODEL", "deepseek-chat")
        self._base_url = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com").rstrip("/") + "/v1"

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not set")
            self._client = OpenAI(api_key=api_key, base_url=self._base_url)
        return self._client

    def execute(self, args: dict) -> dict:
        query = args.get("query") or args.get("args", {}).get("query", "")
        if not query or not query.strip():
            return err("empty query")

        try:
            client = self._get_client()
        except ValueError as e:
            return err(str(e))
        except Exception as e:
            return err(f"client init failed: {e}")

        # Build messages with conversation history for context
        messages = self._build_messages(query)

        # Call LLM with tool definitions
        try:
            resp = client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=_TOOL_DEFINITIONS,
                tool_choice="auto",
                temperature=0.3,
                max_tokens=2048,
            )
        except Exception as e:
            return err(f"LLM call failed: {type(e).__name__}: {e}")

        msg = resp.choices[0].message

        # No tool call → direct answer
        if not msg.tool_calls:
            return ok({"answer": msg.content or "", "tool_used": None})

        # Tool call → execute once and return result directly
        tc = msg.tool_calls[0]
        fn_name = tc.function.name
        try:
            fn_args = json.loads(tc.function.arguments)
        except json.JSONDecodeError:
            fn_args = {}

        tool_result = self._execute_tool(fn_name, fn_args)

        if not tool_result.get("ok"):
            return ok({"answer": f"操作失败: {tool_result.get('error', 'unknown error')}", "tool_used": fn_name})

        # Extract and return the actual content
        raw = tool_result.get("result", "")
        if fn_name == "query_knowledge":
            if not raw or raw == "no match":
                return ok({"answer": "没有在知识库中找到相关信息，请尝试其他关键词。", "tool_used": fn_name})
            return ok({"answer": str(raw), "tool_used": fn_name, "source": "knowledge"})

        if fn_name == "read_file":
            return ok({"answer": str(raw), "tool_used": fn_name})

        if fn_name == "fetch_url":
            return ok({"answer": f"✅ 已抓取并保存到知识库。\n\n{str(raw)[:500]}", "tool_used": fn_name})

        if fn_name == "get_context":
            return ok({"answer": str(raw), "tool_used": fn_name})

        return ok({"answer": str(raw), "tool_used": fn_name})

    def _build_messages(self, query: str) -> list[dict]:
        """Build message list with recent conversation history."""
        messages = [{"role": "system", "content": _SYSTEM_PROMPT}]

        # Add recent short-term memory for context
        try:
            history = self._agent._short.recent(6)
            for entry in history:
                role = entry.get("role")
                content = entry.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": str(content)[:500]})
        except Exception:
            pass

        messages.append({"role": "user", "content": query})
        return messages

    def _execute_tool(self, name: str, args: dict) -> dict:
        """Map friendly tool names to actual agent skills/MCPs."""
        tool_map = {
            "query_knowledge": ("mcp", "knowledge", {"op": "lookup", "query": args.get("query", "")}),
            "fetch_url": ("skill", "fetch_web", {"url": args.get("url", ""), "op": "fetch"}),
            "read_file": ("skill", "file_ops", {"op": "read", "path": args.get("path", "")}),
            "get_context": ("skill", "context", {"op": "context"}),
        }

        mapping = tool_map.get(name)
        if mapping is None:
            return {"ok": False, "result": None, "error": f"unknown tool: {name}"}

        tool_type, tool_name, tool_args = mapping
        try:
            if tool_type == "skill":
                skill = self._agent._skills.get(tool_name)
                if skill is None:
                    return {"ok": False, "result": None, "error": f"unknown skill: {tool_name}"}
                return skill.execute(tool_args)
            else:
                return self._agent._mcp.call(tool_name, tool_args)
        except Exception as e:
            return {"ok": False, "result": None, "error": f"{type(e).__name__}: {e}"}
