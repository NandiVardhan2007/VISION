"""
Base class for isolated autonomous sub-agents with ReAct loop and tool execution.
"""

import json
import inspect
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from vision.cognitive.providers.openai_compatible import OpenAICompatibleProvider
from vision.cognitive.load_balancer import load_balancer
from vision.constants import DEFAULT_SUBAGENT_SYSTEM_PROMPT
from vision.tools.registry import tool_registry
from vision.logger import logger


class BaseAgent(ABC):
    def __init__(
        self,
        name: str,
        agent_type: str = "general",
        dedicated_api_key: Optional[str] = None,
        allowed_tools: Optional[List[str]] = None
    ):
        self.name = name
        self.agent_type = agent_type
        self.allowed_tools = allowed_tools or []
        self.dedicated_client = None
        if dedicated_api_key:
            self.dedicated_client = OpenAICompatibleProvider(
                name=f"{name}-Dedicated",
                api_key=dedicated_api_key,
                base_url="https://integrate.api.nvidia.com/v1",
                model="meta/llama-3.1-8b-instruct"
            )

    def get_scoped_tool_schemas(self) -> List[Dict[str, Any]]:
        """Return tool schemas filtered for this agent's specialization."""
        all_schemas = tool_registry.get_all_schemas()
        if not self.allowed_tools:
            return []
        
        # If "*" or "all", allow all tools
        if "*" in self.allowed_tools:
            return all_schemas

        return [
            s for s in all_schemas
            if s.get("function", {}).get("name") in self.allowed_tools
        ]

    async def _call_llm(self, messages: List[Dict[str, str]], tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Call either the dedicated LLM client or fallback to the load balancer."""
        if self.dedicated_client:
            try:
                return await self.dedicated_client.chat_completion(messages=messages, tools=tools)
            except Exception as e:
                logger.warning(f"[{self.name}] Dedicated LLM failed, falling back to Load Balancer: {e}")

        return await load_balancer.chat_completion(messages=messages, tools=tools)

    async def execute_task(self, task_description: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute a sub-agent task using a multi-turn ReAct loop."""
        ctx_str = json.dumps(context or {}, indent=2, ensure_ascii=False)
        user_prompt = f"Goal/Task: {task_description}\n\nContext & Inputs:\n{ctx_str}"
        
        messages = [
            {"role": "system", "content": self.get_system_prompt()},
            {"role": "user", "content": user_prompt}
        ]

        tools = self.get_scoped_tool_schemas()
        max_turns = 5
        turn_count = 0

        while turn_count < max_turns:
            turn_count += 1
            response = await self._call_llm(messages=messages, tools=tools if tools else None)
            
            tool_calls = response.get("tool_calls")
            if tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": response.get("content"),
                    "tool_calls": tool_calls
                })

                for tc in tool_calls:
                    # Guard present-but-None "function" (recovered/streamed calls
                    # can carry function: null) before .get() chaining.
                    fn = tc.get("function") or {}
                    func_name = fn.get("name")
                    raw_args = fn.get("arguments") or {}
                    args = {}
                    if isinstance(raw_args, str):
                        try:
                            args = json.loads(raw_args) if raw_args.strip() else {}
                        except Exception:
                            args = {}
                    elif isinstance(raw_args, dict):
                        args = raw_args

                    logger.info(f"[{self.name}] ReAct Action -> {func_name}({args})")
                    # Feed tool errors back to the model instead of aborting the
                    # whole ReAct turn, so it can self-correct.
                    try:
                        tool_result = await tool_registry.execute(func_name, args)
                    except Exception as e:
                        logger.warning(f"[{self.name}] Tool '{func_name}' raised: {e}")
                        tool_result = f"ERROR executing {func_name}: {e}"

                    messages.append({
                        "role": "tool",
                        "name": func_name,
                        "tool_call_id": tc.get("id"),
                        "content": str(tool_result)
                    })
            else:
                # Agent provided final response
                content = (response.get("content") or "").strip()
                return {
                    "agent": self.name,
                    "agent_type": self.agent_type,
                    "status": "success",
                    "content": content,
                    "provider": response.get("provider")
                }

        # Loop exhausted while still requesting tools: the last response's content
        # is typically empty. Do one final tool-less call to force a text summary
        # so the orchestrator doesn't record an empty "success".
        try:
            final = await self._call_llm(messages=messages, tools=None)
            final_content = (final.get("content") or "").strip()
            if final_content:
                return {
                    "agent": self.name,
                    "agent_type": self.agent_type,
                    "status": "success",
                    "content": final_content,
                    "provider": final.get("provider")
                }
        except Exception as e:
            logger.warning(f"[{self.name}] Final summary call failed: {e}")

        return {
            "agent": self.name,
            "agent_type": self.agent_type,
            "status": "partial",
            "content": (response.get("content") or "").strip()
                       or f"Reached max turns ({max_turns}) without a final answer.",
            "provider": response.get("provider")
        }

    @abstractmethod
    def get_system_prompt(self) -> str:
        return DEFAULT_SUBAGENT_SYSTEM_PROMPT
