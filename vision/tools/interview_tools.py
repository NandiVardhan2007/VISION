"""
AI Mock Interview Coach & Voice Interview Simulator for VISION AI OS.
Conducts realistic spoken technical & behavioral interviews, provides instant feedback,
tracks scores, and generates detailed evaluation reports into Notepad.
"""

import time
from typing import Dict, List, Optional, Any, Tuple
from vision.tools.registry import tool
from vision.logger import logger
from vision.tools.input_tools import type_text_into_application
from vision.platform import IS_WINDOWS, open_path


class InterviewManager:
    """Singleton managing active mock interview sessions and scoring."""

    def __init__(self):
        self.is_active: bool = False
        self.role_or_topic: str = "Software Engineering"
        self.interview_type: str = "Technical"  # Technical, Behavioral, HR, DSA, System Design
        self.difficulty: str = "Medium"
        self.current_question_index: int = 0
        self.questions: List[str] = []
        self.history: List[Dict[str, Any]] = []  # [{question, answer, feedback, score}]
        self.start_time: float = 0.0

    def start_session(self, topic: str = "Software Engineering", interview_type: str = "Technical", difficulty: str = "Medium") -> str:
        self.is_active = True
        self.role_or_topic = (topic or "").strip() or "Software Engineering"
        self.interview_type = ((interview_type or "").strip() or "Technical").capitalize()
        self.difficulty = ((difficulty or "").strip() or "Medium").capitalize()
        self.current_question_index = 0
        self.history = []
        self.start_time = time.time()

        # Curated foundational question bank depending on topic
        t_lower = self.role_or_topic.lower()
        if "python" in t_lower:
            self.questions = [
                "Explain the difference between mutable and immutable types in Python, and how memory is managed.",
                "How do Python decorators and generators work under the hood?",
                "What is the Global Interpreter Lock (GIL) and how does it impact multi-threading in Python?",
                "Explain how list comprehensions, lambda functions, and dictionary lookups achieve O(1) average time complexity.",
                "Can you walk me through a Python project or backend application you built recently?"
            ]
        elif "hr" in t_lower or "behavioral" in t_lower:
            self.questions = [
                "Tell me about yourself, your background in B.Tech, and what drives your passion for technology.",
                "Describe a challenging technical obstacle you faced in a project and how you resolved it.",
                "How do you prioritize tasks when dealing with tight project deadlines and multiple commitments?",
                "Tell me about a time you had a disagreement with a team member and how you handled it.",
                "Where do you see yourself in the next 3 to 5 years in the tech industry?"
            ]
        elif "dsa" in t_lower or "algorithm" in t_lower:
            self.questions = [
                "How would you detect a cycle in a singly linked list with O(1) auxiliary memory?",
                "Explain the difference between BFS and DFS. In what scenarios would you choose one over the other?",
                "What is Dynamic Programming? How does memoization differ from tabulation?",
                "How does a Hash Map handle collisions under the hood?",
                "What is the time and space complexity of QuickSort vs MergeSort, and why is MergeSort preferred for linked lists?"
            ]
        elif "web" in t_lower or "frontend" in t_lower or "full stack" in t_lower:
            self.questions = [
                "Explain the critical rendering path in the browser from HTML parsing to pixel rasterization.",
                "What are WebSockets and how do they differ from HTTP long-polling and Server-Sent Events?",
                "How do React Virtual DOM and state reconciliation work?",
                "Explain CORS (Cross-Origin Resource Sharing) and how you configure secure API headers.",
                "How do you optimize web application performance, asset bundling, and Time to First Byte (TTFB)?"
            ]
        else:
            # General Software Engineering & CS Fundamentals
            self.questions = [
                f"Tell me about your experience and why you are interested in the {self.role_or_topic} domain.",
                "Explain the four core principles of Object-Oriented Programming (OOP) with real-world analogies.",
                "What is the difference between SQL and NoSQL databases, and how do you choose indexing strategies?",
                "Explain the concept of RESTful API architecture and idempotency in HTTP methods.",
                "Walk me through how you design, test, and deploy a software project from start to finish."
            ]

        first_q = self.questions[0]
        return (
            f"🎯 Mock Interview Session Started for {self.role_or_topic} ({self.interview_type}) - Difficulty: {self.difficulty}!\n\n"
            f"[INSTRUCTION FOR VISION]: You are the INTERVIEWER asking Nandu (the candidate) questions. "
            f"Speak to Nandu and ask him Question 1: \"{first_q}\". "
            f"Do NOT answer the question yourself! Ask the question and wait for Nandu's answer."
        )

    def record_answer_and_get_next(self, answer: str, feedback: str, score: int) -> Tuple[str, bool]:
        """Record candidate answer with score and return next question or completion signal."""
        curr_q = self.questions[self.current_question_index] if self.current_question_index < len(self.questions) else "General Question"
        
        self.history.append({
            "question_num": self.current_question_index + 1,
            "question": curr_q,
            "answer": answer,
            "feedback": feedback,
            "score": score
        })

        self.current_question_index += 1

        if self.current_question_index < len(self.questions):
            next_q = self.questions[self.current_question_index]
            msg = (
                f"Answer Evaluated! Score: {score}/10. Feedback: {feedback}\n\n"
                f"[INSTRUCTION FOR VISION]: Deliver your brief score and feedback to Nandu, then ask him Question {self.current_question_index + 1}: \"{next_q}\". "
                f"Do NOT answer the question yourself! Wait for Nandu to answer."
            )
            return msg, False
        else:
            self.is_active = False
            msg = (
                f"🎉 Mock Interview Complete, Nandu!\n"
                f"Answer Evaluated (Score: {score}/10): {feedback}\n\n"
                f"You've answered all questions! Generating your comprehensive feedback report now..."
            )
            return msg, True

    def generate_report(self) -> str:
        """Generates a complete markdown assessment report."""
        if not self.history:
            return "No interview history recorded."

        total_score = sum(h["score"] for h in self.history)
        avg_score = round(total_score / len(self.history), 1)
        duration_mins = round((time.time() - self.start_time) / 60, 1)

        lines = [
            "=================================================================",
            f"       VISION AI — CANDIDATE INTERVIEW EVALUATION REPORT",
            "=================================================================",
            f"Candidate: Kovvuri Nandi Vardhan Reddy",
            f"Topic / Role: {self.role_or_topic} ({self.interview_type})",
            f"Difficulty: {self.difficulty}",
            f"Duration: {duration_mins} minute(s)",
            f"Overall Score: {avg_score} / 10",
            "-----------------------------------------------------------------\n",
            "DETAILED QUESTION-BY-QUESTION BREAKDOWN:\n"
        ]

        for h in self.history:
            lines.append(f"Q{h['question_num']}: {h['question']}")
            lines.append(f"Your Answer: {h['answer']}")
            lines.append(f"Score: {h['score']} / 10")
            lines.append(f"Feedback & Tips: {h['feedback']}\n")

        lines.append("-----------------------------------------------------------------")
        lines.append("KEY STRENGTHS & RECOMMENDATIONS:")
        if avg_score >= 8.0:
            lines.append("• Strong conceptual clarity and articulate communication.")
            lines.append("• Excellent practical examples. Keep practicing system design!")
        elif avg_score >= 6.0:
            lines.append("• Good foundational knowledge. Strengthen in-depth technical terminology.")
            lines.append("• Use the STAR method (Situation, Task, Action, Result) for structured answers.")
        else:
            lines.append("• Review fundamental definitions and core architecture concepts.")
            lines.append("• Practice speaking with concise, structured bullet points.")

        lines.append("=================================================================")
        return "\n".join(lines)


interview_manager = InterviewManager()


@tool(name="start_mock_interview", description="Start an interactive AI voice mock interview session with VISION for technical topics (Python, DSA, Full Stack, Core CS) or HR/Behavioral.")
def start_mock_interview(role_or_topic: str = "Software Engineering", interview_type: str = "Technical", difficulty: str = "Medium") -> str:
    """Initialize a mock interview session."""
    return interview_manager.start_session(topic=role_or_topic, interview_type=interview_type, difficulty=difficulty)


@tool(name="evaluate_interview_answer", description="Submit and evaluate your answer to the current interview question. Evaluates clarity, technical accuracy, assigns a score (1-10), and presents the next question.")
def evaluate_interview_answer(answer_summary: str, constructive_feedback: str, score_out_of_10: int = 8) -> str:
    """Evaluates candidate response and delivers next question or completes the interview."""
    if not interview_manager.is_active:
        return "No mock interview is currently active, Nandu! Say 'Hey VISION, start a mock interview for Python' to begin."

    try:
        score = int(score_out_of_10 or 0)
    except (TypeError, ValueError):
        score = 0

    msg, is_finished = interview_manager.record_answer_and_get_next(
        answer=(answer_summary or "").strip() or "(no answer provided)",
        feedback=(constructive_feedback or "").strip() or "(no feedback provided)",
        score=max(1, min(10, score))
    )

    if is_finished:
        return msg + "\n\n" + interview_manager.generate_report()

    return msg


@tool(name="end_mock_interview", description="End the current mock interview session early and get your overall score and feedback summary.")
def end_mock_interview(write_to_notepad: bool = False) -> str:
    """Conclude the active interview session and return summary."""
    if not interview_manager.history and not interview_manager.is_active:
        return "No mock interview session is currently active, Nandu!"

    interview_manager.is_active = False
    report = interview_manager.generate_report()

    if write_to_notepad:
        try:
            if IS_WINDOWS:
                type_text_into_application(text=report, target_app="Notepad")
            else:
                # No Notepad on POSIX — save the report and open it in the
                # default editor/viewer instead.
                from pathlib import Path
                out_dir = Path.home() / "Documents"
                out_dir.mkdir(parents=True, exist_ok=True)
                out_file = out_dir / f"mock_interview_report_{int(time.time())}.txt"
                out_file.write_text(report, encoding="utf-8")
                open_path(str(out_file))
                logger.info(f"[InterviewTool] Saved interview report to {out_file}")
        except Exception as e:
            logger.warning(f"[InterviewTool] Could not write interview report: {e}")

    total_score = sum(h["score"] for h in interview_manager.history) if interview_manager.history else 0
    avg_score = round(total_score / len(interview_manager.history), 1) if interview_manager.history else 0

    return (
        f"🏁 Mock Interview concluded, Nandu! You completed {len(interview_manager.history)} question(s) with an overall score of {avg_score}/10. "
        f"Great effort, bro! Say 'start a mock interview' anytime you want to practice again."
    )
