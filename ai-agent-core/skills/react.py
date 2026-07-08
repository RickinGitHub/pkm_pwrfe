import json
import os
from typing import Any

from skills.base import Skill, err, ok


_MAX_STEPS_HARD_CAP = 10
_DEFAULT_MAX_STEPS = 5
_TOOL_RESULT_MAX_CHARS = 2000


class ReactSkill(Skill):
    def __init__(self, agent) -> None:
        self._agent = agent
        self._client = None
        self._model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-5-20250929")

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def _build_tool_schemas(self, allowed_tools: list[str] | None) -> list[dict]:
        schemas: list[dict] = []
        for name, skill in self._agent._skills.items():
            if name == "react":
                continue
            if allowed_tools is not None and name not in allowed_tools:
                continue
            schemas.append({
                "name": f"skill_{name}",
                "description": f"Invoke the '{name}' skill via the agent.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "args": {"type": "object", "description": "Arguments passed to skill.execute()"}
                    },
                    "required": ["args"],
                },
            })
        for name in self._agent._mcp._tools:
            if allowed_tools is not None and name not in allowed_tools:
                continue
            schemas.append({
                "name": f"mcp_{name}",
                "description": f"Invoke the '{name}' MCP server via the agent.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "args": {"type": "object", "description": "Arguments for the MCP tool"}
                    },
                    "required": ["args"],
                },
            })
        return schemas

    def _dispatch_tool(self, tool_name: str, tool_input: dict) -> dict:
        args = tool_input.get("args", {}) or {}
        if tool_name.startswith("skill_"):
            skill_name = tool_name[len("skill_"):]
            skill = self._agent._skills.get(skill_name)
            if skill is None:
                return {"error": f"unknown skill: {skill_name}"}
            try:
                return skill.execute(args)
            except Exception as e:
                return {"error": f"{type(e).__name__}: {e}"}
        elif tool_name.startswith("mcp_"):
            mcp_name = tool_name[len("mcp_"):]
            if mcp_name not in self._agent._mcp._tools:
                return {"error": f"unknown mcp: {mcp_name}"}
            try:
                return self._agent._mcp.call(mcp_name, args)
            except Exception as e:
                return {"error": f"{type(e).__name__}: {e}"}
        return {"error": f"unknown tool: {tool_name}"}

    def _truncate(self, obj: Any) -> str:
        s = json.dumps(obj, ensure_ascii=False, default=str)
        if len(s) > _TOOL_RESULT_MAX_CHARS:
            s = s[:_TOOL_RESULT_MAX_CHARS] + "...[truncated]"
        return s

    def execute(self, args: dict) -> dict:
        query = args.get("query") or args.get("args", {}).get("query")
        if not query:
            return err("react requires a 'query' argument")
        max_steps = args.get("max_steps", _DEFAULT_MAX_STEPS)
        try:
            max_steps = int(max_steps)
        except (TypeError, ValueError):
            max_steps = _DEFAULT_MAX_STEPS
        max_steps = min(max(max_steps, 1), _MAX_STEPS_HARD_CAP)
        allowed = args.get("allowed_tools")
        if allowed is not None and not isinstance(allowed, list):
            return err("allowed_tools must be a list of strings")

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return err("ANTHROPIC_API_KEY not set")

        try:
            client = self._get_client()
        except Exception as e:
            return err(f"anthropic client init failed: {e}")

        tools = self._build_tool_schemas(allowed)
        if not tools:
            return err("no tools available for ReAct loop")

        messages: list[dict] = [
            {"role": "user", "content": query},
        ]
        tool_calls: list[dict] = []
        steps = 0
        final_text = ""

        try:
            for step in range(max_steps):
                steps = step + 1
                resp = client.messages.create(
                    model=self._model,
                    max_tokens=2048,
                    tools=tools,
                    messages=messages,
                )
                assistant_blocks: list[dict] = []
                for block in resp.content:
                    if getattr(block, "type", None) == "text":
                        final_text = block.text or ""
                        assistant_blocks.append({"type": "text", "text": final_text})
                    elif getattr(block, "type", None) == "tool_use":
                        assistant_blocks.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })
                messages.append({"role": "assistant", "content": assistant_blocks})

                if resp.stop_reason != "tool_use":
                    return ok({
                        "answer": final_text,
                        "steps": steps,
                        "tool_calls": tool_calls,
                    })

                tool_results: list[dict] = []
                for block in resp.content:
                    if getattr(block, "type", None) != "tool_use":
                        continue
                    result = self._dispatch_tool(block.name, block.input or {})
                    tool_calls.append({
                        "step": steps,
                        "tool": block.name,
                        "input": block.input,
                        "result": result,
                    })
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": self._truncate(result),
                    })
                messages.append({"role": "user", "content": tool_results})

            return ok({
                "answer": final_text or "max_steps reached without final answer",
                "steps": steps,
                "tool_calls": tool_calls,
                "stopped_by": "max_steps",
            })
        except Exception as e:
            return err(f"{type(e).__name__}: {e}")
