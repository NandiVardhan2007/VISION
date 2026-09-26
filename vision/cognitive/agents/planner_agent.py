"""
Autonomous Goal Decomposition and DAG Planner Agent for VISION.
Analyzes complex multi-faceted user goals and creates structured ExecutionPlans.
"""

import json
import re
from typing import Dict, Any, Optional, List
from vision.cognitive.agents.base_agent import BaseAgent
from vision.cognitive.agents.models import ExecutionPlan, AgentTask, TaskStatus
from vision.logger import logger


PLANNER_SYSTEM_PROMPT = """You are the Lead Planning Agent for VISION Autonomous Operating System.
Your job is to take a high-level user goal and decompose it into an optimal, dependency-aware execution plan consisting of atomic sub-tasks.

AVAILABLE SPECIALIZED AGENTS:
1. "research": Web searches, web scraping, weather/fact gathering, summarizing online data.
2. "code": Writing Python scripts, executing shell commands, data analysis, computational tasks.
3. "file": Reading/writing files, creating documents (.md, .txt, .json), organizing folders, moving/cleaning directories.
4. "communication": Sending emails, sending WhatsApp messages, notifying user.
5. "browser": Complex multi-step website navigation, form filling, web app automation.
6. "general": System status, hardware checks, general logic.

OUTPUT INSTRUCTIONS:
You MUST respond with a single, valid JSON object without markdown fences, or wrapped inside a ```json ``` block.
The JSON object must follow this exact structure:
{
  "goal": "The original user goal",
  "summary": "Brief 1-line strategy description",
  "tasks": [
    {
      "id": "task_1",
      "title": "Short task title",
      "agent_type": "research | code | file | communication | browser | general",
      "description": "Clear, detailed prompt for this specific agent",
      "dependencies": [],
      "input_params": {}
    },
    {
      "id": "task_2",
      "title": "Second task title",
      "agent_type": "file",
      "description": "Write the findings into a markdown report",
      "dependencies": ["task_1"],
      "input_params": {
        "content_source": "${task_1.output}"
      }
    }
  ]
}

RULES:
- Ensure tasks are cleanly ordered. If task_2 depends on task_1, specify "dependencies": ["task_1"].
- Keep the number of tasks between 2 and 6 for maximum reliability and speed.
- Output ONLY valid JSON.
"""


class PlannerAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="PlannerAgent", agent_type="planner", allowed_tools=[])

    def get_system_prompt(self) -> str:
        return PLANNER_SYSTEM_PROMPT

    async def create_plan(self, goal: str, context: Optional[Dict[str, Any]] = None) -> ExecutionPlan:
        """Decompose goal into a structured ExecutionPlan."""
        messages = [
            {"role": "system", "content": self.get_system_prompt()},
            {"role": "user", "content": f"Create an execution plan for this goal:\nGoal: {goal}\nAdditional Context: {json.dumps(context or {})}"}
        ]

        logger.info(f"[PlannerAgent] Decomposing goal: '{goal}'")
        response = await self._call_llm(messages=messages)
        content = (response.get("content") or "").strip()

        # Parse JSON from response. Guard present-but-None `tasks` (LLM emits
        # {"tasks": null}) so we fall back instead of crashing on iteration.
        plan_dict = self._parse_json(content)
        if not plan_dict or not plan_dict.get("tasks"):
            logger.warning("[PlannerAgent] Fallback to default single-task plan.")
            return ExecutionPlan(
                goal=goal,
                summary="Direct execution plan",
                tasks=[
                    AgentTask(
                        id="task_1",
                        title="Execute user goal",
                        agent_type="general",
                        description=goal,
                        dependencies=[]
                    )
                ]
            )

        tasks = []
        for idx, t in enumerate(plan_dict.get("tasks") or []):
            if not isinstance(t, dict):
                continue
            task_id = t.get("id") or f"task_{idx+1}"
            try:
                # `or default` (not `.get(k, default)`) because the LLM commonly
                # emits explicit nulls (e.g. "dependencies": null) which pydantic
                # will NOT coerce to [] — it raises ValidationError instead.
                tasks.append(
                    AgentTask(
                        id=task_id,
                        title=t.get("title") or f"Task {idx+1}",
                        agent_type=t.get("agent_type") or "general",
                        description=t.get("description") or "",
                        dependencies=t.get("dependencies") or [],
                        input_params=t.get("input_params") or {}
                    )
                )
            except Exception as e:
                logger.warning(f"[PlannerAgent] Skipping malformed task {task_id}: {e}")
                continue

        if not tasks:
            # Every task was malformed — degrade to the single-task fallback.
            tasks = [AgentTask(id="task_1", title="Execute user goal", agent_type="general", description=goal, dependencies=[])]

        return ExecutionPlan(
            goal=goal,
            summary=plan_dict.get("summary", "Autonomous Multi-Agent Plan"),
            tasks=tasks
        )

    def _parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Safely parse JSON from raw LLM output."""
        try:
            return json.loads(text)
        except Exception:
            pass

        # Try regex block extraction. Greedy `.*` so nested task objects inside
        # the fenced payload aren't truncated at the first inner `}`.
        match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass

        # Try finding first { and last }
        try:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                return json.loads(text[start:end+1])
        except Exception:
            pass

        return None
