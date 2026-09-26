"""
Autonomous Multi-Agent Goal Planning & Execution Tools for VISION.
Allows VISION to decompose and execute complex, multi-step workflows.
"""

from typing import Dict, Any, Optional
from vision.tools.registry import tool
from vision.logger import logger


@tool(
    name="execute_autonomous_multi_agent_goal",
    description="Decompose and execute a complex multi-step user goal (research, coding, document writing, emailing, multi-step workflows) using the Autonomous Multi-Agent Swarm."
)
async def execute_autonomous_multi_agent_goal(
    goal: str,
    additional_context: Optional[str] = None
) -> str:
    """
    Execute a complex compound goal across specialized sub-agents (Research, Code, File, Communication, Browser).
    
    Args:
        goal: The comprehensive user goal or task statement.
        additional_context: Any background details, URLs, or file constraints.
    """
    try:
        from vision.cognitive.agents.orchestrator import multi_agent_orchestrator
        ctx = {"details": additional_context} if additional_context else {}
        result = await multi_agent_orchestrator.execute_goal(goal=goal, context=ctx)
        
        final_text = result.get("final_output", "")
        plan_id = result.get("plan_id", "")
        status = result.get("status", "")
        elapsed = result.get("elapsed_seconds", 0)
        
        return f"Plan [{plan_id}] completed with status '{status}' in {elapsed}s.\n\n{final_text}"
    except Exception as e:
        logger.error(f"[AgentExecutionTools] Error executing goal '{goal}': {e}")
        return f"Error executing autonomous goal: {str(e)}"


@tool(
    name="get_autonomous_goal_status",
    description="Check the execution status, progress, and task outputs of a running or completed autonomous multi-agent plan by plan_id."
)
def get_autonomous_goal_status(plan_id: str) -> str:
    """
    Query current status and details of an execution plan.
    
    Args:
        plan_id: The unique ID of the execution plan.
    """
    try:
        from vision.cognitive.agents.orchestrator import multi_agent_orchestrator
        plan = multi_agent_orchestrator.get_plan(plan_id)
        if not plan:
            return f"No active or historical plan found with ID '{plan_id}'."

        tasks_summary = []
        for t in plan.tasks:
            tasks_summary.append(f"- [{t.status.value.upper()}] {t.title} (Agent: {t.agent_type})")

        return f"Plan ID: {plan.plan_id}\nGoal: {plan.goal}\nStatus: {plan.status.value}\nTasks:\n" + "\n".join(tasks_summary)
    except Exception as e:
        logger.error(f"[AgentExecutionTools] Error fetching status for plan '{plan_id}': {e}")
        return f"Error fetching autonomous goal status: {str(e)}"
