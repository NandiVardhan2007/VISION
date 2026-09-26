"""
Memory-Augmented Generation (MAG) Engine for VISION.
Provides persistent multi-tier memory storage:
1. Semantic Profile (Facts, Preferences, Contact Directory)
2. Episodic Timeline (Action History, Event Logging)
3. Procedural Memory (Habits, Automatic Rules)
4. Graph-Augmented Memory (Entity-Relationship Knowledge Graph for Multi-Hop Associative Recall)
with SQLite backend, fast BM25/keyword retrieval, contextual prompt injection,
and bi-directional Markdown sync (MEMORIES.md).
"""

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple, Set, Iterator
from vision.logger import logger


class MAGEngine:
    def __init__(self, db_path: Optional[str] = None):
        project_root = Path(__file__).resolve().parent.parent.parent
        self.project_root = project_root
        if db_path is None:
            data_dir = project_root / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(data_dir / "memory.db")
        else:
            self.db_path = db_path

        self.default_md_path = project_root / "MEMORIES.md"

        self._init_db()
        self._seed_default_profile()

    @contextmanager
    def _get_connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a SQLite connection that always commits on success, rolls back
        on error, and — critically for Windows — is always closed afterwards.

        The bare ``with sqlite3.connect(...) as conn:`` idiom only commits/rolls
        back; it never closes the connection, which leaks handles and keeps the
        database file locked on Windows (WinError 32). Closing here fixes that.
        """
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        try:
            # WAL improves read/write concurrency and cuts "database is locked"
            # errors when sync tools run in the executor alongside the main loop.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        """Create SQLite tables for multi-tier MAG memory and Knowledge Graph."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1. Semantic Memory (Facts, Preferences, Profiles)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS semantic_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT DEFAULT 'general',
                    content TEXT NOT NULL,
                    tags TEXT,
                    confidence REAL DEFAULT 1.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 2. Episodic Memory (Events, Actions, Chronological history)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS episodic_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 3. Procedural Memory (Habits, Preferences, Rules)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS procedural_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trigger_context TEXT NOT NULL,
                    rule_action TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 4. Knowledge Graph: Entities
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memory_entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    entity_type TEXT DEFAULT 'concept',
                    aliases TEXT,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # 5. Knowledge Graph: Relations (Multi-Hop Graph)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memory_relations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    target_name TEXT NOT NULL,
                    description TEXT,
                    confidence REAL DEFAULT 1.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def _seed_default_profile(self):
        """Seed essential environment knowledge, procedural rules, and knowledge graph."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM semantic_memories")
            row = cursor.fetchone()
            if row["cnt"] == 0:
                user_home = Path.home()
                defaults = [
                    ("profile", f"User profile username is '{user_home.name}'.", "user,profile,name"),
                    ("hardware", "Connected physical printer is Pantum P2500 Series.", "printer,hardware,pantum"),
                    ("preference", "Default document printing format is plain A4 paper with 1.5 cm border margins.", "document,print,margin,a4"),
                    ("workspace", f"Primary development workspace is located at '{self.project_root}'.", "workspace,code,project"),
                ]
                for cat, content, tags in defaults:
                    cursor.execute(
                        "INSERT INTO semantic_memories (category, content, tags) VALUES (?, ?, ?)",
                        (cat, content, tags)
                    )

            # Seed Procedural Rules if empty
            cursor.execute("SELECT COUNT(*) as cnt FROM procedural_memories")
            proc_row = cursor.fetchone()
            if proc_row["cnt"] == 0:
                rules = [
                    ("youtube,video,song,music,media,browser", "Always open YouTube and media in the Comet Browser (or taskbar shortcut)."),
                    ("fullscreen,full screen,youtube", "When user says keep it full screen, trigger full-screen mode using hotkey 'f'."),
                    ("forward,skip,rewind,youtube", "When user says forward or rewind, forward or rewind video by specified seconds (default 10s via 'l'/'j')."),
                    ("document,print", "Always print formatted bordered documents on A4 paper with 1.5 cm margins on Pantum P2500."),
                    ("code,error,debug,fix", "Diagnose compilation and runtime errors, explain the root cause, and ask to apply fix."),
                ]
                for trigger, rule in rules:
                    cursor.execute(
                        "INSERT INTO procedural_memories (trigger_context, rule_action) VALUES (?, ?)",
                        (trigger, rule)
                    )

            # Seed Knowledge Graph if empty
            cursor.execute("SELECT COUNT(*) as cnt FROM memory_relations")
            graph_row = cursor.fetchone()
            if graph_row["cnt"] == 0:
                relations = [
                    ("Nandu", "studying_at", "Aditya College of Engineering and Technology", "B.Tech 3rd Year IT A, Room 221, Surampalem"),
                    ("Nandu", "has_sister", "Nandini", "Sister born on Dec 4, 2002, phone: 9100219275"),
                    ("Nandini", "donated_old_laptop_for", "Hyderabad Ubuntu Server", "Repurposed sister old laptop running Linux server"),
                    ("Hyderabad Ubuntu Server", "hosts_application", "KPR Parking Print System", "Path /home/nandu/print-server/kpr_print.log, IP 100.93.70.63"),
                    ("Nandu", "has_mother", "Kovvuri Dhana Lakshmi (Amma)", "Mother, phone 950-586-4289"),
                    ("Nandu", "has_father", "Kovvuri Vijaya Bhaskara Reddy (Nanna)", "Father, passed away on August 1st"),
                    ("Nandu", "has_maternal_uncle", "Peddananna (Palla Reddy)", "Phone 9640019275 / 8885519275"),
                    ("Nandu", "has_maternal_aunt", "Peddamma (Nagamani)", "Mother's elder sister, married to Palla Reddy"),
                    ("Nandu", "has_friend", "Pavan (Kukka)", "Aditya College friend from Rajahmundry, phone: +91 70136 31726"),
                    ("Nandu", "has_friend", "Purnima (Pandi)", "Aditya College friend from Korukonda, phone: +91 89194 85389"),
                    ("Purnima", "has_birthday", "April 30, 2007", "Born on April 30th, 2007"),
                    ("Purnima", "is_role", "Girls Class Representative (GCR)", "Class representative of IT class from the girls side"),
                    ("Purnima", "likes_coding", "DSA (Data Structures & Algorithms)", "Loves coding in DSA"),
                    ("Purnima", "favorite_language", "Java", "Favorite programming language is Java"),
                    ("Purnima", "has_brother", "Yaswanth", "Real blood-related brother"),
                    ("Purnima", "classroom_seating", "Middle row, Second bench, Middle seat", "Classroom sitting location"),
                    ("Nandu", "has_friend", "Sriram (Sri Ram)", "Aditya College friend from Pandalapaka, phone: +91 98493 26138"),
                    ("Nandu", "has_friend", "Harshith", "Aditya College friend from Kadiyam, phone: +91 93927 88083"),
                    ("Nandu", "uses_browser_for_youtube", "Comet Browser", "Perplexity Comet Browser pinned on taskbar"),
                    ("Nandu", "uses_hardware_printer", "Pantum P2500 Series", "Laser printer for bordered A4 printing"),
                ]
                for src, rel, tgt, desc in relations:
                    cursor.execute(
                        "INSERT INTO memory_relations (source_name, relation_type, target_name, description) VALUES (?, ?, ?, ?)",
                        (src, rel, tgt, desc)
                    )

            conn.commit()

    def _invalidate_cag_cache(self, pattern: Optional[str] = None):
        """Helper to clear related CAG cache entries when memory changes."""
        try:
            from vision.memory.cag_engine import cag_engine
            cag_engine.invalidate(pattern or "all")
        except Exception as e:
            logger.debug(f"[MAG] CAG cache invalidation skipped: {e}")

    # ── Semantic Memory CRUD ───────────────────────────────────

    def remember(self, content: str, category: str = "user_preference", tags: str = "") -> int:
        """Store a fact or preference in semantic memory."""
        clean = content.strip()
        if not clean:
            return -1

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, content FROM semantic_memories WHERE content = ?", (clean,))
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    "UPDATE semantic_memories SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (existing["id"],)
                )
                conn.commit()
                self._invalidate_cag_cache()
                return existing["id"]

            cursor.execute(
                "INSERT INTO semantic_memories (category, content, tags) VALUES (?, ?, ?)",
                (category, clean, tags)
            )
            conn.commit()
            mem_id = cursor.lastrowid
            logger.info(f"[MAG] Stored new semantic memory #{mem_id}: '{clean}'")
            self._invalidate_cag_cache()
            return mem_id

    def forget(self, query: str) -> int:
        """Delete memories matching query, keyword, or semantic token overlap."""
        clean = query.strip()
        if not clean:
            return 0

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM semantic_memories WHERE content LIKE ? OR tags LIKE ?",
                (f"%{clean}%", f"%{clean}%")
            )
            deleted = cursor.rowcount

            if deleted == 0:
                # Fallback: match on individual significant words. Use WHOLE-WORD
                # matching (not substring) and delete by explicit id, so
                # "forget my printer preferences" can't wipe every row that merely
                # contains the substring "printer" or "preferences" via an OR-any
                # substring sweep.
                stop = {"from", "your", "that", "this", "only", "about", "with", "game", "rules"}
                words = [w for w in re.findall(r"\w+", clean) if len(w) >= 4 and w.lower() not in stop]
                if words:
                    cursor.execute("SELECT id, content, tags FROM semantic_memories")
                    ids = [
                        row["id"]
                        for row in cursor.fetchall()
                        if any(
                            re.search(rf"\b{re.escape(w)}\b", f"{row['content']} {row['tags'] or ''}", re.IGNORECASE)
                            for w in words
                        )
                    ]
                    if ids:
                        placeholders = ",".join(["?"] * len(ids))
                        cursor.execute(f"DELETE FROM semantic_memories WHERE id IN ({placeholders})", ids)
                        deleted = cursor.rowcount

            conn.commit()
            logger.info(f"[MAG] Deleted {deleted} memories matching '{clean}'")
            if deleted > 0:
                self._invalidate_cag_cache()
            return deleted

    def list_all(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve all active semantic memories."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM semantic_memories ORDER BY id ASC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    # ── Graph-Augmented Memory (Knowledge Graph) ───────────────

    def add_relation(
        self,
        source: str,
        relation: str,
        target: str,
        description: str = "",
        confidence: float = 1.0
    ) -> int:
        """Record an entity-to-entity relationship in the Knowledge Graph."""
        src_clean = source.strip()
        rel_clean = relation.strip()
        tgt_clean = target.strip()
        if not src_clean or not tgt_clean:
            return -1

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO memory_relations (source_name, relation_type, target_name, description, confidence) VALUES (?, ?, ?, ?, ?)",
                (src_clean, rel_clean, tgt_clean, description.strip(), confidence)
            )
            conn.commit()
            rel_id = cursor.lastrowid
            logger.info(f"[MAG-Graph] Recorded relation #{rel_id}: ({src_clean}) -[{rel_clean}]-> ({tgt_clean})")
            self._invalidate_cag_cache()
            return rel_id

    def traverse_entity_graph(self, start_entity: str, depth: int = 2) -> List[Dict[str, Any]]:
        """Multi-hop knowledge graph traversal starting from an entity."""
        clean_start = start_entity.strip().lower()
        visited_entities: Set[str] = {clean_start}
        frontier: Set[str] = {clean_start}
        all_relations: List[Dict[str, Any]] = []

        with self._get_connection() as conn:
            cursor = conn.cursor()
            for _ in range(depth):
                if not frontier:
                    break
                next_frontier: Set[str] = set()
                for entity in list(frontier):
                    cursor.execute(
                        "SELECT * FROM memory_relations WHERE LOWER(source_name) LIKE ? OR LOWER(target_name) LIKE ? OR LOWER(description) LIKE ?",
                        (f"%{entity}%", f"%{entity}%", f"%{entity}%")
                    )
                    rows = cursor.fetchall()
                    for r in rows:
                        d = dict(r)
                        if d not in all_relations:
                            all_relations.append(d)
                            src = d["source_name"].lower()
                            tgt = d["target_name"].lower()
                            if src not in visited_entities:
                                visited_entities.add(src)
                                next_frontier.add(src)
                            if tgt not in visited_entities:
                                visited_entities.add(tgt)
                                next_frontier.add(tgt)
                frontier = next_frontier

        return all_relations

    def get_entity_subgraph_prompt(self, user_query: str) -> str:
        """Scan query for entity keywords and generate multi-hop graph context."""
        q_tokens = [w.lower() for w in re.findall(r"\w+", user_query) if len(w) > 2]
        if not q_tokens:
            return ""

        stop_words = {"what", "which", "how", "when", "where", "why", "who", "does", "have", "with", "from", "that", "this", "tell", "show", "is", "are"}
        meaningful_tokens = [w for w in q_tokens if w not in stop_words]

        found_relations = []
        seen_ids = set()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            for token in meaningful_tokens:
                cursor.execute(
                    "SELECT * FROM memory_relations WHERE LOWER(source_name) LIKE ? OR LOWER(target_name) LIKE ? OR LOWER(description) LIKE ? OR LOWER(relation_type) LIKE ?",
                    (f"%{token}%", f"%{token}%", f"%{token}%", f"%{token}%")
                )
                for r in cursor.fetchall():
                    d = dict(r)
                    if d["id"] not in seen_ids:
                        seen_ids.add(d["id"])
                        found_relations.append(d)

        if not found_relations:
            return ""

        lines = ["[KNOWLEDGE GRAPH RELATIONS (MAG-GRAPH)]"]
        for r in found_relations[:8]:
            desc = f" ({r['description']})" if r.get('description') else ""
            lines.append(f"• ({r['source_name']}) —[{r['relation_type']}]—> ({r['target_name']}){desc}")
        return "\n".join(lines) + "\n"

    # ── Procedural Memory (Habits & Rules) ─────────────────────

    def record_procedural_rule(self, trigger_context: str, rule_action: str) -> int:
        """Save a habitual rule or preference (e.g. 'Use Comet browser for YouTube')."""
        clean_trig = trigger_context.strip().lower()
        clean_act = rule_action.strip()
        if not clean_act:
            return -1

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO procedural_memories (trigger_context, rule_action) VALUES (?, ?)",
                (clean_trig, clean_act)
            )
            conn.commit()
            rule_id = cursor.lastrowid
            logger.info(f"[MAG] Recorded procedural rule #{rule_id}: When '{clean_trig}' -> '{clean_act}'")
            return rule_id

    def list_procedural_rules(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Retrieve all registered procedural rules."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM procedural_memories ORDER BY id ASC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_matching_procedural_rules(self, query: str) -> List[str]:
        """Find procedural rules that match keywords in the query."""
        rules = self.list_procedural_rules(limit=50)
        q_lower = query.lower()
        q_tokens = set(re.findall(r"\w+", q_lower))

        matched = []
        for r in rules:
            triggers = [t.strip().lower() for t in r["trigger_context"].split(",") if t.strip()]
            if any(trig in q_lower or trig in q_tokens for trig in triggers):
                matched.append(r["rule_action"])
        return matched

    # ── Episodic Memory ────────────────────────────────────────

    def record_event(self, event_type: str, description: str, metadata: str = ""):
        """Log a timeline event to episodic memory."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO episodic_memories (event_type, description, metadata) VALUES (?, ?, ?)",
                (event_type, description, metadata)
            )
            conn.commit()

    def get_recent_events(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve recent episodic events."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM episodic_memories ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def search_episodic_events(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search past timeline actions and events by keyword."""
        clean = query.strip()
        if not clean:
            return self.get_recent_events(limit=limit)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM episodic_memories WHERE description LIKE ? OR event_type LIKE ? OR metadata LIKE ? ORDER BY id DESC LIMIT ?",
                (f"%{clean}%", f"%{clean}%", f"%{clean}%", limit)
            )
            return [dict(row) for row in cursor.fetchall()]

    # ── Search & Context Retrieval ─────────────────────────────

    def get_contact_number(self, query_name: str) -> Optional[str]:
        """Direct, high-precision contact phone number resolver with alias support."""
        if not query_name:
            return None
        target = query_name.strip().lower()

        alias_map = {
            "amma": ["amma", "mother", "mom", "dhana lakshmi", "kovvuri dhana lakshmi"],
            "mother": ["amma", "mother", "mom", "dhana lakshmi"],
            "mom": ["amma", "mother", "mom", "dhana lakshmi"],
            "sister": ["sister", "nandini", "akka"],
            "nandini": ["sister", "nandini", "akka"],
            "akka": ["sister", "nandini", "akka"],
            "peddananna": ["peddananna", "palla reddy", "big father"],
            "palla reddy": ["peddananna", "palla reddy", "big father"],
            "father": ["father", "nanna", "vijaya bhaskara reddy"],
            "nanna": ["father", "nanna", "vijaya bhaskara reddy"],
            "myself": ["myself", "me", "nandu", "nandi", "self"],
            "nandu": ["myself", "me", "nandu", "nandi", "self"],
            "pavan": ["pavan", "kukka"],
            "kukka": ["pavan", "kukka"],
            "purnima": ["purnima", "pandi"],
            "pandi": ["purnima", "pandi"],
            "sriram": ["sriram", "sri ram"],
            "nikhil": ["nikhil"],
            "harshith": ["harshith"],
            "swathi": ["swathi"],
            "geethika": ["geethika"],
            "tanuja": ["tanuja"],
        }

        if target in ("myself", "me", "nandu", "nandi", "self", "my number", "my phone"):
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT content FROM semantic_memories WHERE (category = 'contact' OR category = 'profile' OR tags LIKE '%self%' OR tags LIKE '%primary_phone%') AND (content LIKE '%mobile%' OR content LIKE '%phone%') ORDER BY id DESC")
                row = cursor.fetchone()
                if row:
                    num_match = re.search(r"(\+?\d[\d\s\-]{8,}\d)", row["content"])
                    if num_match:
                        digits = re.sub(r"[^\d]", "", num_match.group(1))
                        if len(digits) >= 10:
                            return digits

        search_tokens = alias_map.get(target, [target])

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT content, tags, category FROM semantic_memories WHERE category IN ('contact', 'family', 'friends_profile', 'profile', 'NICKNAMES', 'family_profile') ORDER BY CASE WHEN category = 'contact' THEN 1 ELSE 2 END, id DESC")
            rows = cursor.fetchall()

            for row in rows:
                content = row["content"]
                tags = (row["tags"] or "").lower()
                
                matched = False
                for tok in search_tokens:
                    if re.search(rf"\b{re.escape(tok)}\b", content, re.IGNORECASE) or tok in tags.split(","):
                        if tok in ("amma", "mom", "mother") and re.search(r"\bpeddamma\b", content, re.IGNORECASE) and not re.search(r"\b(?:amma|mother|mom)\b", content, re.IGNORECASE):
                            continue
                        if tok in ("nandu", "self") and not row["category"] == "contact" and "primary mobile" not in content.lower():
                            continue
                        matched = True
                        break

                if matched:
                    num_match = re.search(r"(\+?\d[\d\s\-]{8,}\d)", content)
                    if num_match:
                        digits = re.sub(r"[^\d]", "", num_match.group(1))
                        if len(digits) >= 10:
                            return digits

        return None

    def search_memories(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Rank and return relevant memories matching user query with accurate TF-IDF whole-word scoring and stem matching."""
        stop_words = {"what", "which", "how", "when", "where", "why", "who", "does", "have", "with", "from", "that", "this", "tell", "show", "the", "and", "for"}
        all_words = [w.lower() for w in re.findall(r"\w+", query) if len(w) > 2]
        clean_words = [w for w in all_words if w not in stop_words]
        if not clean_words:
            clean_words = all_words

        if not clean_words:
            return self.list_all(limit=limit)

        memories = self.list_all(limit=100)
        scored: List[Tuple[float, Dict[str, Any]]] = []

        for m in memories:
            content = m["content"]
            content_lower = content.lower()
            category = m["category"].lower()
            tags = (m.get("tags") or "").lower()
            combined_text = f"{category} {content_lower} {tags}"
            
            score = 0.0
            for word in clean_words:
                if re.search(rf"\b{re.escape(word)}\b", content, re.IGNORECASE):
                    score += 6.0
                elif word in content_lower:
                    score += 4.0
                if word in tags.split(",") or re.search(rf"\b{re.escape(word)}\b", tags):
                    score += 4.0
                if word == category:
                    score += 3.0
                elif word in combined_text:
                    score += 1.0

            if query.lower() in content_lower:
                score += 10.0

            if score > 0:
                scored.append((score, m))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:limit]]

    def get_mag_prompt_injection(self, user_query: str) -> str:
        """Generate formatted dynamic long-term memory, procedural habit, and knowledge graph context for LLM prompt injection."""
        q_lower = user_query.lower()
        broad_keywords = ["everything", "all", "know about me", "who am i", "about me", "my details", "full profile", "my profile"]
        is_broad = any(kw in q_lower for kw in broad_keywords)

        if is_broad:
            relevant = self.list_all(limit=50)
        else:
            relevant = self.search_memories(user_query, limit=15)
            if not relevant:
                relevant = self.list_all(limit=10)

        sections = []
        if relevant:
            seen = set()
            lines = ["\n[LONG-TERM USER MEMORY & PREFERENCES (MAG)]"]
            for m in relevant:
                c = m["content"].strip()
                if c.lower() not in seen:
                    seen.add(c.lower())
                    lines.append(f"• [{m['category'].upper()}] {c}")
            sections.append("\n".join(lines))

        # Check for matching Knowledge Graph relationships (multi-hop)
        graph_prompt = self.get_entity_subgraph_prompt(user_query)
        if graph_prompt:
            sections.append(graph_prompt.strip())

        # Check for matching procedural habits & execution rules
        proc_rules = self.get_matching_procedural_rules(user_query)
        if proc_rules:
            p_lines = ["[PROCEDURAL HABITS & RULES]"]
            for r in proc_rules:
                p_lines.append(f"• {r}")
            sections.append("\n".join(p_lines))

        return ("\n".join(sections) + "\n") if sections else ""

    # ── Markdown Import & Export Sync (MEMORIES.md) ─────────────

    def export_to_markdown(self, target_path: Optional[Path] = None) -> str:
        """Export all stored semantic memories into a beautifully formatted Markdown file."""
        md_file = target_path or self.default_md_path
        memories = self.list_all(limit=200)

        lines = [
            "# 🧠 VISION AI — Stored Memories & Knowledge Base",
            "",
            f"> **File:** `{md_file}`  ",
            f"> **Backend Database:** `{self.db_path}`  ",
            f"> **Total Stored Items:** {len(memories)}  ",
            f"> **Last Synchronized:** {datetime.now().strftime('%B %d, %Y - %I:%M %p')}  ",
            "",
            "---",
            "",
            "| ID | Category | Memory Content | Tags | Confidence |",
            "|:---|:---|:---|:---|:---:|"
        ]

        for m in memories:
            tags = m.get('tags') or ''
            conf = m.get('confidence', 1.0)
            lines.append(f"| **#{m['id']}** | `{m['category']}` | {m['content']} | `{tags}` | {conf} |")

        lines.extend([
            "",
            "---",
            "### Instructions for Editing:",
            "- You can update any memory content, phone number, or details directly in this file.",
            "- To add a new memory, add a new row or list item under any section.",
            "- Use the command `sync_memories_file` to sync changes into the SQLite database."
        ])

        content = "\n".join(lines)
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"[MAG] Exported {len(memories)} memories to '{md_file}'")
        return f"Successfully exported {len(memories)} memories to '{md_file}'."

    def import_from_markdown(self, source_path: Optional[Path] = None) -> Dict[str, int]:
        """Parse and import memory updates or additions from MEMORIES.md into SQLite."""
        md_file = source_path or self.default_md_path
        if not md_file.exists():
            return {"error": f"File '{md_file}' not found."}

        with open(md_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        added = 0
        updated = 0

        with self._get_connection() as conn:
            cursor = conn.cursor()
            for line in lines:
                line = line.strip()
                if not line.startswith("|") or line.startswith("| ID") or line.startswith("|:--"):
                    continue

                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= 3:
                    id_raw = parts[0].replace("**", "").replace("#", "").strip()
                    cat = parts[1].replace("`", "").strip()
                    content = parts[2].strip()
                    tags = parts[3].replace("`", "").strip() if len(parts) > 3 else "user_explicit"

                    if not content or content == "Memory Content":
                        continue

                    if id_raw.isdigit():
                        mem_id = int(id_raw)
                        cursor.execute("SELECT id FROM semantic_memories WHERE id = ?", (mem_id,))
                        if cursor.fetchone():
                            cursor.execute(
                                "UPDATE semantic_memories SET category = ?, content = ?, tags = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                (cat, content, tags, mem_id)
                            )
                            updated += 1
                            continue

                    cursor.execute(
                        "INSERT INTO semantic_memories (category, content, tags) VALUES (?, ?, ?)",
                        (cat, content, tags)
                    )
                    added += 1

            conn.commit()

        self._invalidate_cag_cache()
        logger.info(f"[MAG] Markdown sync completed: {updated} updated, {added} added.")
        return {"updated": updated, "added": added}

    # ── Background Autonomous Fact & Habit Extraction ─────────

    def auto_extract_facts(self, user_text: str, assistant_text: str):
        """Heuristic and pattern extractor that automatically captures user facts, preferences, and rules."""
        patterns = [
            r"my (?:favorite|preferred) ([\w\s]+) is ([\w\s\.-]+)",
            r"i (?:prefer|like|always use) ([\w\s\.-]+)",
            r"remember that ([\w\s\.-]+)",
            r"my (?:name|id|email|phone|city) is ([\w\s\.-@]+)",
        ]

        lower_user = user_text.lower()
        for p in patterns:
            match = re.search(p, lower_user)
            if match:
                fact = match.group(0).strip()
                if "remember that" in fact:
                    fact = fact.replace("remember that", "").strip()
                self.remember(fact.capitalize(), category="auto_learned", tags="auto,preference")
                break


# Global MAG Engine Singleton
mag_engine = MAGEngine()
