"""
Context Engineering & Working Memory System for VISION.
Tracks active conversational entities, recently listed/found files, active apps, and recent actions.
Injects real-time structured context into LLM prompts so VISION retains memory of all referenced files.
"""

from typing import List, Dict, Any, Optional
from pathlib import Path
from vision.logger import logger


class WorkingMemory:
    def __init__(self):
        # Short-term file memory: {normalized_name: full_absolute_path_str}
        self.file_index: Dict[str, str] = {}
        # Chronological list of recently seen file paths
        self.recent_files: List[str] = []
        # Last active target directory
        self.last_directory: str = str(Path.home() / "Downloads")
        # System/Entity State
        self.last_opened_app: Optional[str] = None
        self.last_tool_executed: Optional[str] = None

    def record_file(self, file_path: str):
        """Register a file into working memory index."""
        p = Path(file_path).resolve()
        norm_stem = p.stem.lower().replace(" ", "").replace("-", "").replace("_", "")
        norm_name = p.name.lower().replace(" ", "").replace("-", "").replace("_", "")
        
        self.file_index[norm_stem] = str(p)
        self.file_index[norm_name] = str(p)
        self.file_index[p.name.lower()] = str(p)
        
        if str(p) in self.recent_files:
            self.recent_files.remove(str(p))
        self.recent_files.insert(0, str(p))

        # Keep last 50 files (bounded). Rebuild the name index from the retained
        # window so dropped files don't leak entries or resolve to stale paths.
        if len(self.recent_files) > 50:
            self.recent_files = self.recent_files[:50]
            self._rebuild_index()

    def _rebuild_index(self):
        """Rebuild the name->path index from the current recent_files window.
        Iterates oldest→newest so the most recent path wins on key collisions."""
        self.file_index = {}
        for fp_str in reversed(self.recent_files):
            p = Path(fp_str)
            norm_stem = p.stem.lower().replace(" ", "").replace("-", "").replace("_", "")
            norm_name = p.name.lower().replace(" ", "").replace("-", "").replace("_", "")
            self.file_index[norm_stem] = fp_str
            self.file_index[norm_name] = fp_str
            self.file_index[p.name.lower()] = fp_str

    def record_files(self, file_paths: List[str]):
        """Batch record files from listing/searching."""
        for fp in file_paths:
            self.record_file(fp)

    def lookup_file(self, query: str) -> Optional[str]:
        """Check working memory for an exact or normalized match."""
        clean = query.strip().lower()
        norm = clean.replace(" ", "").replace("-", "").replace("_", "")
        
        # Direct lookup
        if clean in self.file_index:
            return self.file_index[clean]
        if norm in self.file_index:
            return self.file_index[norm]

        # Fuzzy substring lookup in recent files (snapshot: tool threads may mutate concurrently)
        for fp_str in list(self.recent_files):
            p = Path(fp_str)
            p_norm = p.stem.lower().replace(" ", "").replace("-", "").replace("_", "")
            if norm in p_norm or p_norm in norm:
                return fp_str

        return None

    def get_context_injection_prompt(self) -> str:
        """
        Generate structured dynamic context engineering prompt to inject into the LLM system prompt.
        """
        lines = ["\n[WORKING MEMORY & ACTIVE CONTEXT]"]
        
        if self.recent_files:
            lines.append("Recently Listed/Accessed Files on Host PC (Use exact paths when operating on these files):")
            for fp in self.recent_files[:15]:
                p = Path(fp)
                lines.append(f"  - '{p.name}' -> Path: '{fp}'")

        if self.last_directory:
            lines.append(f"Active Working Folder: '{self.last_directory}'")

        if self.last_opened_app:
            lines.append(f"Last Launched Application: '{self.last_opened_app}'")

        lines.append("[END CONTEXT]\n")
        return "\n".join(lines)


# Singleton working memory
working_memory = WorkingMemory()
