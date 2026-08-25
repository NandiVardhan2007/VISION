"""
Language-Independent Universal Code Runner, Interactive Stdin Feeder & Autonomous Debugger.
Supports Java (Spring Boot, Core Java, DSA), Python, C/C++, JavaScript/TypeScript, and Shell.
Compiles code, feeds custom stdin inputs, intercepts tracebacks and runtime exceptions,
and enables autonomous code repairing.
"""

import os
import sys
import time
import subprocess
import tempfile
import re
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from vision.tools.registry import tool
from vision.logger import logger
from vision.tools.file_tools import _resolve_user_path


def _detect_language(code_or_path: str, explicit_lang: Optional[str] = None) -> str:
    """Detect programming language from file extension or code syntax."""
    if explicit_lang:
        lang = explicit_lang.lower().strip()
        if lang in ("java", "core java", "spring", "spring boot"):
            return "java"
        if lang in ("python", "py"):
            return "python"
        if lang in ("cpp", "c++", "c"):
            return "cpp" if "++" in lang or "cpp" in lang else "c"
        if lang in ("javascript", "js", "typescript", "ts", "node"):
            return "javascript"
        return lang

    # Check extension
    p = Path(code_or_path)
    if p.suffix:
        ext = p.suffix.lower()
        if ext == ".java":
            return "java"
        if ext in (".py", ".pyw"):
            return "python"
        if ext in (".cpp", ".cc", ".cxx", ".hpp"):
            return "cpp"
        if ext in (".c", ".h"):
            return "c"
        if ext in (".js", ".mjs", ".ts"):
            return "javascript"
        if ext in (".sh", ".bash"):
            return "shell"

    # Analyze code contents
    code = code_or_path
    if "public static void main" in code or "System.out.print" in code or "import java." in code or "class " in code and "{" in code:
        return "java"
    if "#include <" in code or "std::cout" in code or "printf(" in code:
        return "cpp"
    if "def " in code or "import " in code or "print(" in code:
        return "python"
    if "console.log" in code or "const " in code or "function " in code:
        return "javascript"

    return "python"


def _execute_java(
    code_or_file: str,
    stdin_input: Optional[str] = None,
    working_dir: Optional[str] = None,
    timeout_sec: int = 30
) -> Dict[str, Any]:
    """Compile and execute Java code with stdin input."""
    start_time = time.time()
    temp_dir = tempfile.mkdtemp(prefix="vision_java_")

    try:
        source_file = None
        class_name = "Main"

        # Same path-vs-snippet guard as the Python runner: a bare snippet must
        # never go through fuzzy path resolution.
        candidate_p = None
        looks_like_path = (
            len(code_or_file) < 300
            and "\n" not in code_or_file
            and (("/" in code_or_file) or ("\\" in code_or_file)
                 or code_or_file.lower().endswith((".java", ".py", ".c", ".cpp", ".js")))
        )
        if looks_like_path:
            try:
                candidate_p = _resolve_user_path(code_or_file, find_existing_file=True)
            except Exception:
                candidate_p = None
        if candidate_p and candidate_p.exists() and candidate_p.is_file():
            source_file = candidate_p
            class_name = candidate_p.stem
            work_path = candidate_p.parent
        else:
            # Inline Java code snippet
            match = re.search(r"(?:public\s+)?class\s+(\w+)", code_or_file)
            if match:
                class_name = match.group(1)

            source_file = Path(temp_dir) / f"{class_name}.java"
            source_file.write_text(code_or_file, encoding="utf-8")
            work_path = Path(temp_dir)

        # 1. Compile Java file
        logger.info(f"[CodeRunner] Compiling Java: '{source_file.name}' with javac...")
        compile_proc = subprocess.run(
            ["javac", str(source_file)],
            cwd=str(work_path),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            encoding="utf-8",
            errors="replace"
        )

        if compile_proc.returncode != 0:
            elapsed = round(time.time() - start_time, 2)
            logger.warning(f"[CodeRunner] Java Compilation Error in '{source_file.name}'")
            return {
                "success": False,
                "stage": "compilation",
                "exit_code": compile_proc.returncode,
                "elapsed_sec": elapsed,
                "stdout": "",
                "stderr": compile_proc.stderr.strip() or compile_proc.stdout.strip(),
                "file_path": str(source_file)
            }

        # 2. Run compiled Java class with stdin input
        logger.info(f"[CodeRunner] Executing Java class: '{class_name}' with stdin...")
        run_proc = subprocess.run(
            ["java", "-cp", str(work_path), class_name],
            cwd=str(work_path),
            input=stdin_input if stdin_input is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            encoding="utf-8",
            errors="replace"
        )

        elapsed = round(time.time() - start_time, 2)
        return {
            "success": run_proc.returncode == 0,
            "stage": "execution",
            "exit_code": run_proc.returncode,
            "elapsed_sec": elapsed,
            "stdout": run_proc.stdout.strip(),
            "stderr": run_proc.stderr.strip(),
            "file_path": str(source_file)
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stage": "timeout",
            "exit_code": -1,
            "elapsed_sec": timeout_sec,
            "stdout": "",
            "stderr": f"Execution timed out after {timeout_sec} seconds."
        }
    except Exception as e:
        return {
            "success": False,
            "stage": "system_error",
            "exit_code": -1,
            "elapsed_sec": round(time.time() - start_time, 2),
            "stdout": "",
            "stderr": str(e)
        }
    finally:
        # Clean up temp dir if we created one for inline snippet
        if Path(temp_dir).exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def _execute_python(
    code_or_file: str,
    stdin_input: Optional[str] = None,
    working_dir: Optional[str] = None,
    timeout_sec: int = 30
) -> Dict[str, Any]:
    """Execute Python code or file with stdin input."""
    start_time = time.time()
    try:
        # Only treat the input as a FILE PATH when it actually looks like one.
        # A bare code snippet must never be fed into fuzzy path resolution —
        # it once matched an unrelated page.js on disk and executed THAT.
        candidate_p = None
        looks_like_path = (
            len(code_or_file) < 300
            and "\n" not in code_or_file
            and (("/" in code_or_file) or ("\\" in code_or_file)
                 or code_or_file.lower().endswith((".py", ".java", ".c", ".cpp", ".js")))
        )
        if looks_like_path:
            try:
                candidate_p = _resolve_user_path(code_or_file, find_existing_file=True)
            except Exception:
                candidate_p = None
        if candidate_p and candidate_p.exists() and candidate_p.is_file():
            cmd = [sys.executable, str(candidate_p)]
            cwd = working_dir or str(candidate_p.parent)
        else:
            cmd = [sys.executable, "-c", code_or_file]
            cwd = working_dir or str(Path.cwd())

        run_proc = subprocess.run(
            cmd,
            cwd=cwd,
            input=stdin_input if stdin_input is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            encoding="utf-8",
            errors="replace"
        )

        elapsed = round(time.time() - start_time, 2)
        return {
            "success": run_proc.returncode == 0,
            "stage": "execution",
            "exit_code": run_proc.returncode,
            "elapsed_sec": elapsed,
            "stdout": run_proc.stdout.strip(),
            "stderr": run_proc.stderr.strip()
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stage": "timeout",
            "exit_code": -1,
            "elapsed_sec": timeout_sec,
            "stdout": "",
            "stderr": f"Python execution timed out after {timeout_sec}s."
        }
    except Exception as e:
        return {
            "success": False,
            "stage": "system_error",
            "exit_code": -1,
            "elapsed_sec": round(time.time() - start_time, 2),
            "stdout": "",
            "stderr": str(e)
        }


def _execute_cpp(
    code_or_file: str,
    stdin_input: Optional[str] = None,
    working_dir: Optional[str] = None,
    timeout_sec: int = 30
) -> Dict[str, Any]:
    """Compile and execute C/C++ code with stdin input."""
    start_time = time.time()
    temp_dir = tempfile.mkdtemp(prefix="vision_cpp_")
    try:
        candidate_p = _resolve_user_path(code_or_file, find_existing_file=True) if len(code_or_file) < 300 else None
        if candidate_p and candidate_p.exists() and candidate_p.is_file():
            source_file = candidate_p
            out_exe = Path(temp_dir) / "prog.exe"
            work_path = candidate_p.parent
        else:
            source_file = Path(temp_dir) / "main.cpp"
            source_file.write_text(code_or_file, encoding="utf-8")
            out_exe = Path(temp_dir) / "prog.exe"
            work_path = Path(temp_dir)

        # Compile with g++
        compiler = "g++" if shutil.which("g++") else "gcc"
        compile_proc = subprocess.run(
            [compiler, "-O2", str(source_file), "-o", str(out_exe)],
            cwd=str(work_path),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            encoding="utf-8",
            errors="replace"
        )

        if compile_proc.returncode != 0:
            return {
                "success": False,
                "stage": "compilation",
                "exit_code": compile_proc.returncode,
                "elapsed_sec": round(time.time() - start_time, 2),
                "stdout": "",
                "stderr": compile_proc.stderr.strip()
            }

        # Run binary
        run_proc = subprocess.run(
            [str(out_exe)],
            cwd=str(work_path),
            input=stdin_input if stdin_input is not None else None,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            encoding="utf-8",
            errors="replace"
        )

        return {
            "success": run_proc.returncode == 0,
            "stage": "execution",
            "exit_code": run_proc.returncode,
            "elapsed_sec": round(time.time() - start_time, 2),
            "stdout": run_proc.stdout.strip(),
            "stderr": run_proc.stderr.strip()
        }
    except Exception as e:
        return {
            "success": False,
            "stage": "system_error",
            "exit_code": -1,
            "elapsed_sec": round(time.time() - start_time, 2),
            "stdout": "",
            "stderr": str(e)
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@tool(
    name="run_code_with_input",
    description="Universal language-independent code runner for Java, Python, C/C++, and JavaScript. Compiles, executes, feeds interactive stdin input (e.g. for Scanner/input()), and captures outputs/errors."
)
def run_code_with_input(
    code_or_file_path: str,
    language: Optional[str] = None,
    stdin_input: Optional[str] = None,
    working_directory: Optional[str] = None,
    timeout_seconds: int = 30
) -> str:
    """
    Executes code in Java, Python, C++, or JS with custom stdin inputs.
    """
    if not code_or_file_path or not code_or_file_path.strip():
        return "Error: Code content or file path is required."

    lang = _detect_language(code_or_file_path, language)
    logger.info(f"[CodeRunner] Running {lang.upper()} code with stdin (len={len(stdin_input or '')} chars)...")

    # Dispatch to language runner
    if lang == "java":
        res = _execute_java(code_or_file_path, stdin_input, working_directory, timeout_seconds)
    elif lang in ("cpp", "c"):
        res = _execute_cpp(code_or_file_path, stdin_input, working_directory, timeout_seconds)
    elif lang == "javascript":
        # Run via node
        node_bin = shutil.which("node") or "node"
        try:
            start_t = time.time()
            proc = subprocess.run(
                [node_bin, "-e", code_or_file_path],
                input=stdin_input,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                encoding="utf-8",
                errors="replace"
            )
            res = {
                "success": proc.returncode == 0,
                "stage": "execution",
                "exit_code": proc.returncode,
                "elapsed_sec": round(time.time() - start_t, 2),
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip()
            }
        except Exception as e:
            res = {"success": False, "stage": "error", "exit_code": -1, "stdout": "", "stderr": str(e), "elapsed_sec": 0}
    else:
        # Default Python
        res = _execute_python(code_or_file_path, stdin_input, working_directory, timeout_seconds)

    # Format result report
    status_emoji = "✅ Success" if res["success"] else "❌ Failed"
    lines = [
        f"[{lang.upper()} Execution {status_emoji} | Exit Code: {res['exit_code']} | Time: {res.get('elapsed_sec', 0)}s]"
    ]

    if stdin_input:
        lines.append(f"📥 Input Provided (stdin):\n{stdin_input.strip()}")

    if res.get("stdout"):
        lines.append(f"\n📤 Output (stdout):\n{res['stdout']}")
    elif res["success"]:
        lines.append("\n📤 Output: (Program completed with empty stdout)")

    if res.get("stderr"):
        stage_name = res.get("stage", "Execution").capitalize()
        lines.append(f"\n⚠️ {stage_name} Error / Traceback:\n{res['stderr']}")
        lines.append("\n💡 You can ask VISION: 'Fix these errors' to automatically repair this code.")

    return "\n".join(lines)


@tool(
    name="diagnose_and_fix_code_error",
    description="Analyze a compilation error or runtime exception in a Java, Python, or C++ file, diagnose the root cause, and apply the fix to the source file."
)
def diagnose_and_fix_code_error(
    file_path: str,
    error_message: Optional[str] = None,
    replacement_code: Optional[str] = None
) -> str:
    """
    Diagnoses and applies code fixes to Java/Python source files.
    """
    target = _resolve_user_path(file_path, find_existing_file=True)
    if not target or not target.exists():
        return f"Error: Target file '{file_path}' does not exist."
    if target.is_dir():
        return (
            f"Error: '{target}' is a directory, not a source file. "
            f"Please provide the full path to the .java/.py/.cpp file to fix."
        )

    current_code = target.read_text(encoding="utf-8", errors="replace")

    # If new corrected code was provided, apply and verify
    if replacement_code and replacement_code.strip():
        # Create backup
        backup_p = target.with_suffix(target.suffix + ".bak")
        backup_p.write_text(current_code, encoding="utf-8")
        target.write_text(replacement_code, encoding="utf-8")
        logger.info(f"[CodeDebugger] Applied code fix to '{target.name}'.")

        # Test verification run
        lang = _detect_language(str(target))
        if lang == "java":
            test_res = _execute_java(str(target))
        else:
            test_res = _execute_python(str(target))

        if test_res["success"]:
            return f"✅ Successfully applied fix to '{target.name}' and verified execution!\nOutput:\n{test_res.get('stdout', 'Clean execution.')}"
        else:
            return f"⚠️ Fix was written to '{target.name}', but execution reported an error:\n{test_res.get('stderr')}"

    # Provide diagnosis
    return (
        f"📄 Diagnosing '{target.name}' ({len(current_code.splitlines())} lines):\n"
        f"- Error context: {error_message or 'Checking for syntax/runtime bugs'}\n"
        f"- File is ready for patch. Please provide the fix or instruct VISION to apply the repaired code."
    )


@tool(
    name="compile_and_run_java_project",
    description="Compile all .java files in a directory/package and execute the specified main class with stdin input."
)
def compile_and_run_java_project(
    project_directory: str = "src",
    main_class: str = "Main",
    stdin_input: Optional[str] = None
) -> str:
    """Compiles multi-file Java projects and executes main class."""
    target_dir = _resolve_user_path(project_directory)
    if not target_dir.exists():
        return f"Error: Project directory '{project_directory}' does not exist."

    java_files = list(target_dir.rglob("*.java"))
    if not java_files:
        return f"Error: No .java files found in '{project_directory}'."

    bin_dir = target_dir / "bin"
    bin_dir.mkdir(exist_ok=True)

    # Compile all java files
    compile_cmd = ["javac", "-d", str(bin_dir)] + [str(f) for f in java_files]
    comp_proc = subprocess.run(compile_cmd, cwd=str(target_dir), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if comp_proc.returncode != 0:
        return f"❌ Java Project Compilation Failed:\n{comp_proc.stderr.strip()}"

    # Run main class
    run_proc = subprocess.run(
        ["java", "-cp", str(bin_dir), main_class],
        cwd=str(target_dir),
        input=stdin_input,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )

    status = "✅ Success" if run_proc.returncode == 0 else "❌ Execution Error"
    return f"[{status} | Exit Code: {run_proc.returncode}]\nOutput:\n{run_proc.stdout.strip()}\n{run_proc.stderr.strip()}"
