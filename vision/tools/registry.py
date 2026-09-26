"""
Tool Registry and schema generator for OpenAI/Groq function calling.
"""

import asyncio
import inspect
import functools
from typing import Callable, Dict, Any, List, Optional, Union
from vision.logger import logger


def _unwrap_annotation(annotation: Any) -> Any:
    """Reduce Optional[X] / Union[X, None] to X so type mapping and coercion see the
    real underlying type rather than falling back to 'string'."""
    if getattr(annotation, "__origin__", None) is Union:
        non_none = [a for a in annotation.__args__ if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return annotation


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Callable] = {}
        self._schemas: Dict[str, Dict[str, Any]] = {}

    def register(self, name: Optional[str] = None, description: Optional[str] = None):
        """Decorator to register a python function as an LLM tool."""
        def decorator(func: Callable):
            tool_name = name or func.__name__
            tool_doc = description or (func.__doc__ or "No description provided.").strip()

            sig = inspect.signature(func)
            properties = {}
            required = []

            for param_name, param in sig.parameters.items():
                # Skip self/cls and variadic params (*args/**kwargs) — a variadic
                # has no meaningful scalar schema and, lacking a default, would be
                # forced into `required`, producing an invalid schema.
                if param_name in ["self", "cls"] or param.kind in (
                    inspect.Parameter.VAR_POSITIONAL,
                    inspect.Parameter.VAR_KEYWORD,
                ):
                    continue

                param_type = "string"
                annotation = _unwrap_annotation(param.annotation)
                # Subscripted generics (List[str], Dict[str, Any], list[str], ...)
                # have `_name is None`; only bare List/Dict set `_name`. Detect the
                # container via `__origin__` so typed params map to array/object,
                # not a bogus "string".
                origin = getattr(annotation, "__origin__", None)
                if annotation is int:
                    param_type = "integer"
                elif annotation is float:
                    param_type = "number"
                elif annotation is bool:
                    param_type = "boolean"
                elif annotation is list or origin is list or getattr(annotation, "_name", None) == "List":
                    param_type = "array"
                elif annotation is dict or origin is dict or getattr(annotation, "_name", None) == "Dict":
                    param_type = "object"

                properties[param_name] = {
                    "type": param_type,
                    "description": f"Parameter: {param_name}"
                }

                if param.default == inspect.Parameter.empty:
                    required.append(param_name)

            schema = {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_doc,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required
                    }
                }
            }

            if tool_name in self._tools:
                logger.warning(f"[ToolRegistry] Duplicate tool name '{tool_name}' — overwriting previous registration.")
            self._tools[tool_name] = func
            self._schemas[tool_name] = schema
            logger.debug(f"[ToolRegistry] Registered tool '{tool_name}'")
            return func
        return decorator

    def get_all_schemas(self) -> List[Dict[str, Any]]:
        return list(self._schemas.values())

    async def execute(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        if name not in self._tools:
            return f"Error: Tool '{name}' is not registered."

        if not isinstance(arguments, dict):
            arguments = {}

        func = self._tools[name]
        try:
            # Auto-coerce parameter types (e.g. string "true"/"false" to bool, string digits to int)
            sig = inspect.signature(func)
            cleaned_args = {}
            for k, v in arguments.items():
                if k in sig.parameters:
                    param = sig.parameters[k]
                    annotation = _unwrap_annotation(param.annotation)
                    if annotation == bool and isinstance(v, str):
                        cleaned_args[k] = v.strip().lower() in ["true", "1", "yes"]
                    elif annotation == int and isinstance(v, str) and v.strip().lstrip("-").isdigit():
                        cleaned_args[k] = int(v)
                    elif annotation == float and isinstance(v, str):
                        try:
                            cleaned_args[k] = float(v)
                        except ValueError:
                            cleaned_args[k] = v
                    else:
                        cleaned_args[k] = v
                else:
                    cleaned_args[k] = v

            logger.info(f"[ToolRegistry] Executing tool '{name}' with args {cleaned_args}")
            if inspect.iscoroutinefunction(func):
                return await func(**cleaned_args)
            else:
                # Sync tools can block for seconds (GUI automation, network IO); run them
                # in a thread so the realtime voice/event loop is not frozen.
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, functools.partial(func, **cleaned_args))
        except Exception as e:
            logger.error(f"[ToolRegistry] Tool '{name}' execution failed: {e}")
            return f"Error executing tool '{name}': {str(e)}"


# Singleton tool registry
tool_registry = ToolRegistry()
tool = tool_registry.register
