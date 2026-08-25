"""
File management, exploration, and smart organization tools for VISION.
Supports full CRUD, search, recursive directory sorting, and fuzzy path resolution.
"""

import os
import shutil
import re
from pathlib import Path
from typing import List, Dict, Optional, Union
from vision.tools.registry import tool
from vision.memory.working_memory import working_memory
from vision.logger import logger

# Category definitions for smart organization
FILE_CATEGORIES: Dict[str, List[str]] = {
    "Documents": [".pdf", ".docx", ".doc", ".txt", ".rtf", ".odt", ".pptx", ".ppt", ".xlsx", ".xls", ".csv", ".tsv"],
    "Images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".tiff", ".ico"],
    "Audio": [".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a", ".wma"],
    "Video": [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm"],
    "Archives": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"],
    "Code_and_Scripts": [".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json", ".yaml", ".yml", ".xml", ".sql", ".sh", ".bat", ".ps1", ".cpp", ".c", ".java", ".rs", ".go"],
    "Executables": [".exe", ".msi", ".dmg", ".pkg", ".apk", ".deb"]
}


def _normalize_name(name: str) -> str:
    """Normalize string for fuzzy comparison (remove punctuation, lower case)."""
    return re.sub(r"[^a-zA-Z0-9]", "", name.lower())


def _find_fuzzy_match_in_directory(parent_dir: Path, target_name: str, recursive: bool = True) -> Optional[Path]:
    """Look for an exact or fuzzy matching file in parent_dir, filtering out system/Recent caches."""
    if not parent_dir.exists() or not parent_dir.is_dir():
        return None

    target_norm = _normalize_name(target_name)
    if not target_norm:
        return None

    try:
        raw_items = list(parent_dir.rglob("*") if recursive else parent_dir.iterdir())
    except Exception:
        return None

    # Filter out hidden/AppData/Recent/cache paths and directories — this helper
    # locates FILES; a same-named directory must never shadow the real file.
    items = [
        item for item in raw_items
        if item.is_file()
        and "appdata" not in str(item).lower()
        and not item.name.startswith(".")
    ]

    # 1. Exact match on full name (prefer real files over .lnk)
    for item in items:
        if not item.name.endswith(".lnk") and _normalize_name(item.name) == target_norm:
            return item

    # 2. Match on stem (ignoring extension)
    for item in items:
        if not item.name.endswith(".lnk") and _normalize_name(item.stem) == target_norm:
            return item

    # 3. Substring match
    for item in items:
        stem_norm = _normalize_name(item.stem)
        if not item.name.endswith(".lnk") and (target_norm in stem_norm or stem_norm in target_norm):
            return item

    return None


def _resolve_user_path(path_str: str, find_existing_file: bool = False) -> Path:
    """
    Resolve user-friendly aliases ('Downloads', 'Desktop', 'D:', '~'),
    clean up hallucinated placeholders like '[Your Username]',
    and leverage Working Memory and prioritized recursive searching.
    """
    user_home = Path.home()
    clean = path_str.strip().strip("'\"`").rstrip(":,;.")

    # Task tracker special alias
    if clean.lower() in ["tasktracker", "task_tracker", "tasktracker.xlsx", "task tracker", "task tracker excel", "task tracker excel sheet", "tasktracker excel"]:
        tracker_file = Path("D:/VISION/data/VISION_Task_Tracker.xlsx")
        if tracker_file.exists():
            return tracker_file
        alt = Path("D:/VISION/tasktracker.xlsx")
        if alt.exists():
            return alt

    # 1. Check Working Memory first if looking for an existing file
    if find_existing_file:
        mem_match = working_memory.lookup_file(clean)
        if mem_match and Path(mem_match).exists() and not mem_match.endswith(".lnk"):
            return Path(mem_match)

    # 2. Handle drive letters like "D:" or "d:" or "D drive" -> "D:\"
    drive_match = re.match(r"^([a-zA-Z]):?(\s*drive)?$", clean, re.IGNORECASE)
    if drive_match:
        drive_letter = drive_match.group(1).upper()
        return Path(f"{drive_letter}:\\")

    # 3. Replace bracketed username placeholders like [Your Username]
    clean = re.sub(r"\[.*?username.*?\]", user_home.name, clean, flags=re.IGNORECASE)
    clean = re.sub(r"<.*?username.*?>", user_home.name, clean, flags=re.IGNORECASE)

    clean_lower = clean.lower().replace("\\", "/").strip("/")

    aliases = {
        "downloads": user_home / "Downloads",
        "download": user_home / "Downloads",
        "desktop": user_home / "Desktop",
        "documents": user_home / "Documents",
        "document": user_home / "Documents",
        "pictures": user_home / "Pictures",
        "music": user_home / "Music",
        "videos": user_home / "Videos",
        "tasktracker": Path("D:/VISION/data/VISION_Task_Tracker.xlsx"),
        "tasktracker.xlsx": Path("D:/VISION/data/VISION_Task_Tracker.xlsx")
    }

    # Direct alias match (e.g. 'Downloads' -> 'C:\Users\NANDU\Downloads')
    if clean_lower in aliases:
        return aliases[clean_lower]

    # Prefix alias matching (e.g. 'Downloads/Experiment_2.pdf' -> 'C:\Users\NANDU\Downloads\Experiment_2.pdf')
    for alias_name, alias_path in aliases.items():
        if clean_lower.startswith(f"{alias_name}/") or clean_lower.startswith(f"{alias_name}\\"):
            relative_part = clean[len(alias_name) + 1:]
            resolved_parent = alias_path
            target_candidate = resolved_parent / relative_part
            if target_candidate.exists() or not find_existing_file:
                return target_candidate
            # Recursive fuzzy match inside that alias folder
            matched = _find_fuzzy_match_in_directory(resolved_parent, relative_part, recursive=True)
            if matched:
                return matched
            return target_candidate

    resolved = Path(clean).expanduser()
    if not resolved.is_absolute():
        resolved = (user_home / clean).resolve()

    if (resolved.exists() and not str(resolved).endswith(".lnk")) or not find_existing_file:
        return resolved

    # Prioritized recursive search across standard user libraries FIRST (Downloads, Documents, Desktop, D:\)
    for search_dir in [user_home / "Downloads", user_home / "Documents", user_home / "Desktop", Path("D:\\")]:
        if search_dir.exists():
            matched = _find_fuzzy_match_in_directory(search_dir, resolved.name, recursive=True)
            if matched:
                return matched

    return resolved


@tool(name="list_files", description="List files and folders inside a directory (e.g. 'Downloads', 'Desktop', 'D:\\'). Automatically indexes files into working memory.")
def list_files(directory_path: str = "Downloads", pattern: str = "*", recursive: bool = True) -> str:
    """List directory contents with automatic Working Memory indexing."""
    p = _resolve_user_path(directory_path, find_existing_file=False)
    if not p.exists():
        return f"Error: Directory '{p}' does not exist."
    if not p.is_dir():
        return f"Error: Path '{p}' is a file, not a directory."

    try:
        working_memory.last_directory = str(p)
        items = list(p.rglob(pattern) if recursive else p.glob(pattern))
        if not items:
            return f"No items found in '{p}' matching pattern '{pattern}'."

        # Register found files into working memory
        working_memory.record_files([str(item) for item in items if item.is_file()])

        lines = [f"Contents of {p} ({len(items)} items):"]
        for item in items[:50]:
            kind = "[DIR] " if item.is_dir() else "[FILE]"
            size = f"({item.stat().st_size} bytes)" if item.is_file() else ""
            lines.append(f"  {kind} {item.relative_to(p)} {size}")
        if len(items) > 50:
            lines.append(f"  ... and {len(items) - 50} more items.")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing directory: {e}"


@tool(name="find_files", description="Search for files by name or extension in a directory (e.g. name='report', directory='Downloads').")
def find_files(name_query: str, directory: str = "Downloads") -> str:
    """Search for files matching name_query and register them into Working Memory."""
    p = _resolve_user_path(directory, find_existing_file=False)
    if not p.exists() or not p.is_dir():
        return f"Error: Directory '{p}' does not exist."

    clean_query = _normalize_name(name_query)
    matches = []

    try:
        for item in p.rglob("*"):
            if item.is_file():
                if clean_query in _normalize_name(item.name) or clean_query in _normalize_name(item.stem):
                    matches.append(item)

        if not matches:
            return f"No files found matching '{name_query}' in '{p}'."

        # Register found files into working memory
        working_memory.record_files([str(m) for m in matches])

        lines = [f"Found {len(matches)} matching files:"]
        for m in matches[:25]:
            lines.append(f"  - {m}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error searching files: {e}"


@tool(name="open_file", description="Open any file or folder with its default Windows application (e.g. 'Experiment_2.pdf' or 'Downloads').")
def open_file(file_path: str) -> str:
    """Open a file or folder using the default OS application."""
    p = _resolve_user_path(file_path, find_existing_file=True)
    if not p.exists():
        return f"Error: File or folder '{p}' does not exist."

    try:
        os.startfile(str(p))
        working_memory.record_file(str(p))
        logger.info(f"[FileTool] Opened file: {p}")
        return f"Successfully opened '{p.name}' ({p})."
    except Exception as e:
        return f"Failed to open '{p}': {e}"


@tool(name="read_file_content", description="Read text contents of a file (e.g. .txt, .py, .json, .md, .csv).")
def read_file_content(file_path: str, max_chars: int = 4000) -> str:
    """Read the content of a readable text file."""
    p = _resolve_user_path(file_path, find_existing_file=True)
    if not p.exists() or not p.is_file():
        return f"Error: File '{p}' does not exist."

    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(max_chars)
        working_memory.record_file(str(p))
        return f"Content of '{p.name}':\n{content}"
    except Exception as e:
        return f"Failed to read '{p}': {e}"


@tool(name="rename_file", description="Rename an existing file or directory.")
def rename_file(source_path: str, new_name: str) -> str:
    """Rename a file or folder."""
    src = _resolve_user_path(source_path, find_existing_file=True)
    if not src.exists():
        return f"Error: Source file '{src}' does not exist."

    dst = src.parent / new_name
    try:
        src.rename(dst)
        working_memory.record_file(str(dst))
        logger.info(f"[FileTool] Renamed {src} -> {dst}")
        return f"Successfully renamed '{src.name}' to '{new_name}' at '{dst}'."
    except Exception as e:
        return f"Failed to rename '{src}': {e}"


@tool(name="move_file", description="Move a file or folder from source to destination directory (e.g. 'Downloads/report.pdf' to 'D:\\').")
def move_file(source_path: str, destination_dir: str) -> str:
    """Move a file to a new directory."""
    src = _resolve_user_path(source_path, find_existing_file=True)
    dst_dir = _resolve_user_path(destination_dir, find_existing_file=False)

    if not src.exists():
        return f"Error: Source '{src}' does not exist."

    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name

    try:
        shutil.move(str(src), str(dst))
        working_memory.record_file(str(dst))
        logger.info(f"[FileTool] Moved {src} -> {dst}")
        return f"Successfully moved '{src.name}' to '{dst_dir}'."
    except Exception as e:
        return f"Failed to move '{src}': {e}"


@tool(name="copy_file", description="Copy a file or directory to a destination folder.")
def copy_file(source_path: str, destination_dir: str) -> str:
    """Copy a file or folder to a destination."""
    src = _resolve_user_path(source_path, find_existing_file=True)
    dst_dir = _resolve_user_path(destination_dir, find_existing_file=False)

    if not src.exists():
        return f"Error: Source '{src}' does not exist."

    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name

    try:
        if src.is_dir():
            shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
        else:
            shutil.copy2(str(src), str(dst))
        working_memory.record_file(str(dst))
        logger.info(f"[FileTool] Copied {src} -> {dst}")
        return f"Successfully copied '{src.name}' to '{dst_dir}'."
    except Exception as e:
        return f"Failed to copy '{src}': {e}"


@tool(name="delete_file", description="Permanently delete a file or directory.")
def delete_file(file_path: str) -> str:
    """Delete a file or folder."""
    p = _resolve_user_path(file_path, find_existing_file=True)
    if not p.exists():
        return f"Error: File or directory '{p}' does not exist."

    try:
        if p.is_dir():
            shutil.rmtree(str(p))
        else:
            p.unlink()
        logger.info(f"[FileTool] Deleted: {p}")
        return f"Successfully deleted '{p.name}'."
    except Exception as e:
        return f"Failed to delete '{p}': {e}"


@tool(name="create_folder", description="Create a new folder at the specified directory path.")
def create_folder(folder_path: str) -> str:
    """Create a new folder."""
    p = _resolve_user_path(folder_path, find_existing_file=False)
    try:
        p.mkdir(parents=True, exist_ok=True)
        logger.info(f"[FileTool] Created folder: {p}")
        return f"Successfully created folder '{p}'."
    except Exception as e:
        return f"Failed to create folder '{p}': {e}"


@tool(name="organize_directory", description="Automatically sort and organize all unorganized files in a directory into category subfolders (Documents, Images, Audio, Video, Archives, Code, Executables).")
def organize_directory(directory_path: str = "Downloads") -> str:
    """Sort all unorganized files in directory_path into category folders."""
    p = _resolve_user_path(directory_path, find_existing_file=False)
    if not p.exists() or not p.is_dir():
        return f"Error: Directory '{p}' does not exist."

    ext_to_category: Dict[str, str] = {}
    for cat, exts in FILE_CATEGORIES.items():
        for ext in exts:
            ext_to_category[ext.lower()] = cat

    moved_counts: Dict[str, int] = {}
    total_moved = 0

    try:
        for item in list(p.iterdir()):
            # Skip hidden files, system files, and shortcuts on desktop
            if item.is_file() and not item.name.startswith(".") and item.suffix.lower() not in [".ini", ".lnk"]:
                ext = item.suffix.lower()
                category = ext_to_category.get(ext, "Others")

                cat_folder = p / category
                cat_folder.mkdir(parents=True, exist_ok=True)
                dest = cat_folder / item.name

                shutil.move(str(item), str(dest))
                working_memory.record_file(str(dest))
                moved_counts[category] = moved_counts.get(category, 0) + 1
                total_moved += 1

        if total_moved == 0:
            return f"Directory '{p.name}' is already organized. No loose files to sort."

        summary_lines = [f"Successfully organized {total_moved} files in '{p.name}':"]
        for cat, cnt in sorted(moved_counts.items(), key=lambda x: x[1], reverse=True):
            summary_lines.append(f"  • {cat}: {cnt} file(s)")
        return "\n".join(summary_lines)
    except Exception as e:
        return f"Error organizing directory: {e}"


@tool(name="organize_downloads", description="Automatically sort and tidy all loose files in the Downloads folder into neat categorized subfolders (Documents, Images, Archives, Executables, Code).")
def organize_downloads(clean_empty_folders: bool = True) -> str:
    """Smart Downloads organizer that sorts loose files into structured categories."""
    downloads_path = Path.home() / "Downloads"
    res = organize_directory(str(downloads_path))
    if clean_empty_folders:
        clean_empty_directories(str(downloads_path))
    return res


@tool(name="organize_desktop", description="Automatically tidy the Desktop by sorting loose files into organized categories while preserving app shortcuts and links.")
def organize_desktop(preserve_shortcuts: bool = True) -> str:
    """Cleans up the Windows Desktop, sorting loose media, documents, and code into Desktop/Organized/."""
    desktop_path = Path.home() / "Desktop"
    if not desktop_path.exists():
        return "Error: Desktop folder not found."

    target_org_dir = desktop_path / "Organized"
    target_org_dir.mkdir(parents=True, exist_ok=True)

    ext_to_category: Dict[str, str] = {}
    for cat, exts in FILE_CATEGORIES.items():
        for ext in exts:
            ext_to_category[ext.lower()] = cat

    moved_counts: Dict[str, int] = {}
    total_moved = 0

    try:
        for item in list(desktop_path.iterdir()):
            if item.is_file() and not item.name.startswith("."):
                # Preserve desktop shortcuts and Windows desktop.ini
                if preserve_shortcuts and item.suffix.lower() in [".lnk", ".url", ".ini"]:
                    continue

                ext = item.suffix.lower()
                category = ext_to_category.get(ext, "Others")
                cat_folder = target_org_dir / category
                cat_folder.mkdir(parents=True, exist_ok=True)

                dest = cat_folder / item.name
                shutil.move(str(item), str(dest))
                working_memory.record_file(str(dest))
                moved_counts[category] = moved_counts.get(category, 0) + 1
                total_moved += 1

        if total_moved == 0:
            return "Desktop is already clean and organized! No loose files found."

        summary_lines = [f"Successfully organized {total_moved} loose file(s) on your Desktop into 'Desktop/Organized/':"]
        for cat, cnt in sorted(moved_counts.items(), key=lambda x: x[1], reverse=True):
            summary_lines.append(f"  • {cat}: {cnt} file(s)")
        summary_lines.append("App shortcuts and icons were preserved.")
        return "\n".join(summary_lines)
    except Exception as e:
        return f"Error organizing Desktop: {e}"


@tool(name="clean_empty_directories", description="Scan a folder (like Downloads or Desktop) and safely remove empty, orphaned subfolders.")
def clean_empty_directories(target_directory: str = "Downloads") -> str:
    """Removes empty subdirectories."""
    p = _resolve_user_path(target_directory, find_existing_file=False)
    if not p.exists() or not p.is_dir():
        return f"Directory '{p}' does not exist."

    removed = []
    try:
        for root, dirs, files in os.walk(str(p), topdown=False):
            for d in dirs:
                dir_full = Path(root) / d
                try:
                    if dir_full.exists() and not any(dir_full.iterdir()):
                        dir_full.rmdir()
                        removed.append(d)
                except Exception:
                    pass

        if not removed:
            return f"No empty folders found in '{p.name}'."
        return f"Cleaned up {len(removed)} empty folder(s) in '{p.name}': {', '.join(removed[:5])}."
    except Exception as e:
        return f"Error cleaning empty folders: {e}"


@tool(name="create_or_write_file", description="Create a new text file or save written notes/code/documents directly to disk in Downloads, Desktop, Documents, or any folder.")
def create_or_write_file(file_name: str, content: str, folder_path: str = "Downloads") -> str:
    """Save content directly to a file on disk."""
    if not file_name:
        return "Error: file_name is required."

    dir_p = _resolve_user_path(folder_path, find_existing_file=False)
    dir_p.mkdir(parents=True, exist_ok=True)

    target_file = dir_p / file_name
    try:
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(content)
        working_memory.record_file(str(target_file))
        logger.info(f"[FileTool] Saved file: {target_file}")
        return f"Successfully saved '{file_name}' to '{dir_p}'."
    except Exception as e:
        return f"Failed to save file: {e}"
