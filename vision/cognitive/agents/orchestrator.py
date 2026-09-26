"""
Central Autonomous Multi-Agent Swarm Orchestrator and DAG Execution Engine for VISION.
Decomposes goals, manages dependency graphs, coordinates specialized agents, self-heals failures, and streams events.
"""

import time
import json
import asyncio
import re
from typing import Dict, Any, Optional, List
from vision.cognitive.agents.models import ExecutionPlan, AgentTask, TaskStatus
from vision.cognitive.agents.planner_agent import PlannerAgent
from vision.cognitive.agents.research_agent import ResearchAgent
from vision.cognitive.agents.code_agent import CodeAgent
from vision.cognitive.agents.file_agent import FileAgent
from vision.cognitive.agents.communication_agent import CommunicationAgent
from vision.cognitive.agents.browser_agent import BrowserAgent
from vision.cognitive.agents.base_agent import BaseAgent
from vision.cognitive.load_balancer import load_balancer
from vision.core.event_bus import event_bus
from vision.constants import VisionEvents
from vision.logger import logger


class GeneralAgent(BaseAgent):
    """Fallback agent for general system tasks and coordination."""
    def __init__(self):
        super().__init__(name="GeneralAgent", agent_type="general", allowed_tools=["*"])

    def get_system_prompt(self) -> str:
        return "You are the VISION General Assistant Agent. Execute the given task accurately and return a concise summary."


class MultiAgentOrchestrator:
    def __init__(self):
        self.planner = PlannerAgent()
        self.agents: Dict[str, BaseAgent] = {
            "research": ResearchAgent(),
            "code": CodeAgent(),
            "file": FileAgent(),
            "communication": CommunicationAgent(),
            "browser": BrowserAgent(),
            "general": GeneralAgent()
        }
        self._active_plans: Dict[str, ExecutionPlan] = {}

    def get_agent(self, agent_type: str) -> BaseAgent:
        """Get specialized agent or fallback to GeneralAgent."""
        return self.agents.get(agent_type.lower().strip(), self.agents["general"])

    def get_plan(self, plan_id: str) -> Optional[ExecutionPlan]:
        return self._active_plans.get(plan_id)

    def _substitute_variables(self, target: Any, completed_outputs: Dict[str, Any]) -> Any:
        """Recursively resolve ${task_id.output} or ${task_id} variable expressions."""
        if isinstance(target, str):
            res = target
            for task_id, output in completed_outputs.items():
                out_str = str(output) if output is not None else ""
                res = res.replace(f"${{{task_id}.output}}", out_str)
                res = res.replace(f"${{{task_id}}}", out_str)
            return res
        elif isinstance(target, dict):
            return {k: self._substitute_variables(v, completed_outputs) for k, v in target.items()}
        elif isinstance(target, list):
            return [self._substitute_variables(item, completed_outputs) for item in target]
        return target

    async def execute_goal(
        self,
        goal: str,
        context: Optional[Dict[str, Any]] = None,
        max_parallel_tasks: int = 2
    ) -> Dict[str, Any]:
        """Orchestrate end-to-end execution of a complex user goal."""
        start_time = time.time()
        logger.info(f"[Orchestrator] Initiating Multi-Agent Goal: '{goal}'")

        # 1. Generate DAG Execution Plan
        plan: ExecutionPlan = await self.planner.create_plan(goal, context=context)
        plan.status = TaskStatus.RUNNING
        self._active_plans[plan.plan_id] = plan

        await event_bus.publish(VisionEvents.AGENT_PLAN_CREATED, {
            "plan_id": plan.plan_id,
            "goal": goal,
            "summary": plan.summary,
            "tasks_count": len(plan.tasks),
            "tasks": [t.model_dump() for t in plan.tasks]
        })

        completed_outputs: Dict[str, Any] = {}

        # 2. Execution Loop
        while not plan.is_finished():
            ready_tasks = plan.get_ready_tasks()
            if not ready_tasks:
                # Check if there are any still running tasks, or if we have a deadlock/failure
                pending_count = sum(1 for t in plan.tasks if t.status == TaskStatus.PENDING)
                if pending_count > 0:
                    logger.error("[Orchestrator] Deadlock detected or dependencies failed. Marking remaining as skipped.")
                    for t in plan.tasks:
                        if t.status == TaskStatus.PENDING:
                            t.status = TaskStatus.SKIPPED
                break

            # Execute batch of ready tasks
            batch = ready_tasks[:max_parallel_tasks]
            tasks_to_run = []

            for task in batch:
                task.status = TaskStatus.RUNNING
                task.started_at = time.time()
                tasks_to_run.append(self._run_task(task, completed_outputs, plan.plan_id))

            results = await asyncio.gather(*tasks_to_run, return_exceptions=True)

            for task, res in zip(batch, results):
                if isinstance(res, Exception):
                    task.status = TaskStatus.FAILED
                    task.error = str(res)
                    task.completed_at = time.time()
                    logger.error(f"[Orchestrator] Task '{task.id}' failed with unhandled exception: {res}")
                    await event_bus.publish(VisionEvents.AGENT_STEP_FAILED, {
                        "plan_id": plan.plan_id,
                        "task_id": task.id,
                        "error": str(res)
                    })
                else:
                    # res is Dict from agent
                    if task.status == TaskStatus.COMPLETED:
                        completed_outputs[task.id] = task.output
                        await event_bus.publish(VisionEvents.AGENT_STEP_COMPLETED, {
                            "plan_id": plan.plan_id,
                            "task_id": task.id,
                            "title": task.title,
                            "agent": task.agent_type,
                            "output_snippet": str(task.output)[:200]
                        })

        plan.completed_at = time.time()
        has_failed = any(t.status == TaskStatus.FAILED for t in plan.tasks)
        plan.status = TaskStatus.FAILED if has_failed else TaskStatus.COMPLETED

        # 3. Synthesize Final Goal Summary
        final_summary = await self._synthesize_final_output(plan, completed_outputs)
        plan.final_output = final_summary
        elapsed = round(time.time() - start_time, 2)

        await event_bus.publish(VisionEvents.AGENT_GOAL_FINISHED, {
            "plan_id": plan.plan_id,
            "status": plan.status.value,
            "elapsed_seconds": elapsed,
            "summary": final_summary
        })

        logger.info(f"[Orchestrator] Goal completed in {elapsed}s with status '{plan.status.value}'.")
        return {
            "plan_id": plan.plan_id,
            "status": plan.status.value,
            "goal": goal,
            "elapsed_seconds": elapsed,
            "summary": plan.summary,
            "final_output": final_summary,
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "agent": t.agent_type,
                    "status": t.status.value,
                    "output": t.output,
                    "error": t.error
                }
                for t in plan.tasks
            ]
        }

    async def _run_task(self, task: AgentTask, completed_outputs: Dict[str, Any], plan_id: str):
        """Execute a single agent task with parameter substitution and self-healing retry loop."""
        agent = self.get_agent(task.agent_type)
        
        # Variable substitution
        resolved_description = self._substitute_variables(task.description, completed_outputs)
        resolved_params = self._substitute_variables(task.input_params, completed_outputs)
        
        await event_bus.publish(VisionEvents.AGENT_STEP_STARTED, {
            "plan_id": plan_id,
            "task_id": task.id,
            "title": task.title,
            "agent": task.agent_type,
            "description": resolved_description[:150]
        })

        while task.retries <= task.max_retries:
            try:
                task_context = {
                    "task_id": task.id,
                    "plan_id": plan_id,
                    "input_params": resolved_params,
                    "completed_tasks": completed_outputs
                }

                if task.error and task.retries > 0:
                    task_context["previous_error"] = task.error
                    task_context["retry_instruction"] = f"Previous attempt failed with error: {task.error}. Please adjust parameters and fix."

                logger.info(f"[Orchestrator] Agent [{agent.name}] running '{task.title}' (attempt {task.retries + 1})")
                result = await agent.execute_task(
                    task_description=resolved_description,
                    context=task_context
                )

                if result.get("status") == "success":
                    task.status = TaskStatus.COMPLETED
                    task.output = result.get("content")
                    task.completed_at = time.time()
                    return result
                else:
                    task.error = result.get("error", "Unknown error during execution")
                    task.retries += 1
            except Exception as e:
                task.error = str(e)
                task.retries += 1
                logger.warning(f"[Orchestrator] Attempt {task.retries} failed for task '{task.id}': {e}")
                await asyncio.sleep(0.5)

        task.status = TaskStatus.FAILED
        task.completed_at = time.time()
        return {"status": "error", "error": task.error}

    async def _synthesize_final_output(self, plan: ExecutionPlan, completed_outputs: Dict[str, Any]) -> str:
        """Create a cohesive, conversational summary of the multi-agent execution."""
        task_summaries = []
        for t in plan.tasks:
            status_symbol = "✅" if t.status == TaskStatus.COMPLETED else "❌" if t.status == TaskStatus.FAILED else "⏭️"
            snippet = str(t.output)[:250].strip() if t.output else (f"Error: {t.error}" if t.error else "Skipped")
            task_summaries.append(f"{status_symbol} **{t.title}** ({t.agent_type}):\n{snippet}")

        joined_tasks = "\n\n".join(task_summaries)
        prompt = f"""You are VISION AI OS.
Synthesize a concise, friendly, and complete final response for the user based on the executed multi-agent plan.

USER GOAL:
{plan.goal}

TASK EXECUTION RESULTS:
{joined_tasks}

INSTRUCTIONS:
1. Address the user directly (Nandu) with warmth and confidence.
2. Present the main findings, actions taken (e.g. files created, web research synthesized, messages sent), and final conclusions cleanly.
3. Keep the response well-structured with Markdown headings and bullet points.
"""
        try:
            response = await load_balancer.chat_completion(
                messages=[{"role": "system", "content": prompt}],
                temperature=0.6,
                max_tokens=800
            )
            return response.get("content") or joined_tasks
        except Exception as e:
            logger.error(f"[Orchestrator] Final synthesis error: {e}")
            return joined_tasks


# Global Orchestrator Singleton
multi_agent_orchestrator = MultiAgentOrchestrator()
