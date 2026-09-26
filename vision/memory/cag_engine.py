"""
Cache-Augmented Generation (CAG) Engine for VISION.
Provides multi-tiered in-memory (L1) and persistent disk (L2) caching for ultra-fast,
zero-token response retrieval, fuzzy semantic matching, intelligent TTL invalidation,
and LRU capacity management.
"""

import json
import hashlib
import re
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from vision.logger import logger


# Queries containing dynamic, real-time, or system-action keywords must bypass cache
CACHE_BYPASS_PATTERNS = [
    r"\b(?:time|date|clock|current time|today's date|now)\b",
    r"\b(?:screenshot|screen|what is on my screen|describe screen|look at my screen)\b",
    r"\b(?:cpu|ram|battery|system stats|metrics|gpu|memory usage)\b",
    r"\b(?:open|launch|start|run|kill|close|terminate|shut down|restart)\b",
    r"\b(?:move|copy|delete|rename|create folder|organize|download)\b",
    r"\b(?:print|send email|unlock phone|tap|click|type text|press key)\b",
    r"\b(?:remember|forget|memory|memories|family|sister|father|mother|peddananna|peddamma|friend|friends|who is|about me|know about me|my details|profile|sync memory|sync memories)\b",
    r"\b(?:reminder|remind me|alarm|schedule|upcoming class|next class|timetable)\b",
]

STOP_WORDS = {
    "a", "an", "the", "in", "on", "at", "of", "to", "for", "is", "are", "was",
    "were", "be", "been", "being", "do", "does", "did", "tell", "me", "please",
    "can", "you", "what", "which", "who", "where", "when", "why", "how"
}

# TTL Defaults by Category (in seconds)
DEFAULT_CATEGORY_TTLS = {
    "static_knowledge": 86400,   # 24 hours
    "academic_info": 43200,      # 12 hours
    "code_snippet": 14400,       # 4 hours
    "qa_general": 7200,          # 2 hours
    "general": 3600,             # 1 hour
    "short_term": 600,           # 10 minutes
}

MAX_CACHE_ENTRIES = 500
FUZZY_SIMILARITY_THRESHOLD = 0.65


class CAGEngine:
    def __init__(self, cache_dir: Optional[str] = None, max_entries: int = MAX_CACHE_ENTRIES):
        if cache_dir is None:
            project_root = Path(__file__).resolve().parent.parent.parent
            self.cache_dir = project_root / "data" / "cache"
        else:
            self.cache_dir = Path(cache_dir)

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.store_file = self.cache_dir / "cag_store.json"
        self.max_entries = max_entries

        # L1 Memory Cache: {hash: {query, normalized_query, tokens, response, created_at, last_accessed, expires_at, category, hit_count}}
        self._l1_cache: Dict[str, Dict[str, Any]] = {}
        # Sync tools run in a thread-pool executor (tool_registry) while the main
        # event loop also reads/writes the cache — guard all mutations and
        # iterate-then-persist sections with a re-entrant lock.
        self._lock = threading.RLock()
        self.exact_hits = 0
        self.fuzzy_hits = 0
        self.misses = 0

        self._load_l2_cache()

    @property
    def hits(self) -> int:
        return self.exact_hits + self.fuzzy_hits

    def _normalize_query(self, query: str) -> str:
        """Normalize query for fuzzy matching (lowercase, strip filler punctuation)."""
        clean = query.lower().strip()
        clean = re.sub(r"[^\w\s]", " ", clean)
        # Remove common conversational prefixes & filler
        clean = re.sub(r"^(hey\s+vision|vision|please|tell\s+me|can\s+you|what\s+is|what\s+are|explain)\s+", "", clean).strip()
        clean = re.sub(r"\s+", " ", clean)
        return clean

    def _get_tokens(self, query: str) -> set:
        """Extract meaningful tokens excluding common stop words."""
        norm = self._normalize_query(query)
        words = re.findall(r"\w+", norm)
        content_words = {w for w in words if w not in STOP_WORDS and len(w) > 1}
        return content_words if content_words else set(words)

    def _generate_key(self, query: str) -> str:
        """Create SHA256 key from normalized query."""
        norm = self._normalize_query(query)
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]

    def _calculate_similarity(self, tokens1: set, tokens2: set) -> float:
        """Calculate Dice coefficient and token overlap score between two token sets."""
        if not tokens1 or not tokens2:
            return 0.0
        intersection = len(tokens1.intersection(tokens2))
        dice = (2.0 * intersection) / (len(tokens1) + len(tokens2))
        # The overlap boost (intersection / smaller-set-size) is aggressive: for a
        # single-token query a single shared word yields overlap == 1.0, and
        # 1.0 * 0.85 clears the fuzzy threshold — a false-positive cache hit
        # (e.g. "explain python" matching a cached "python is bad"). Only apply
        # the boost when both token sets are large enough for the overlap to be
        # meaningful; otherwise fall back to the stricter Dice coefficient.
        if min(len(tokens1), len(tokens2)) >= 3:
            overlap = intersection / min(len(tokens1), len(tokens2))
            return max(dice, overlap * 0.85)
        return dice

    def _load_l2_cache(self):
        """Load persistent disk cache into memory."""
        if self.store_file.exists():
            try:
                with open(self.store_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    now = time.time()
                    self._l1_cache = {}
                    for k, v in data.items():
                        if (v.get("expires_at") or 0) > now:
                            norm = v.get("normalized_query") or self._normalize_query(v.get("query", ""))
                            v["normalized_query"] = norm
                            v["tokens"] = list(self._get_tokens(norm))
                            if "last_accessed" not in v:
                                v["last_accessed"] = v.get("created_at", now)
                            if "created_at" not in v:
                                v["created_at"] = v.get("last_accessed", now)
                            self._l1_cache[k] = v
                logger.info(f"[CAG] Loaded {len(self._l1_cache)} active cache entries from disk.")
            except Exception as e:
                logger.warning(f"[CAG] Failed to load L2 cache from disk: {e}")
                self._l1_cache = {}

    def _save_l2_cache(self):
        """Persist L1 cache to disk."""
        try:
            # Snapshot under the lock so a concurrent put()/eviction from a tool
            # thread cannot mutate the dict mid-serialization.
            with self._lock:
                to_save = {k: dict(v) for k, v in self._l1_cache.items()}

            with open(self.store_file, "w", encoding="utf-8") as f:
                json.dump(to_save, f, indent=2)
        except Exception as e:
            logger.warning(f"[CAG] Failed to save L2 cache: {e}")

    def _evict_lru(self):
        """Evict oldest/least-recently-used entry if cache size exceeds max_entries."""
        if len(self._l1_cache) <= self.max_entries:
            return

        oldest_key = min(self._l1_cache.keys(), key=lambda k: self._l1_cache[k].get("last_accessed", 0))
        del self._l1_cache[oldest_key]
        logger.debug(f"[CAG] LRU evicted cache key '{oldest_key}' (Max: {self.max_entries})")

    def should_bypass(self, query: str) -> bool:
        """Determine if a query is dynamic, actionable, or real-time and must bypass cache."""
        if not query or len(query.strip()) < 3:
            return True
        clean = query.lower().strip()
        for p in CACHE_BYPASS_PATTERNS:
            if re.search(p, clean):
                return True
        return False

    def lookup(self, query: str, allow_fuzzy: bool = True) -> Optional[Dict[str, Any]]:
        """Look up response in L1/L2 cache with exact match and fuzzy semantic fallback."""
        if self.should_bypass(query):
            self.misses += 1
            return None

        now = time.time()
        key = self._generate_key(query)
        entry = self._l1_cache.get(key)

        # 1. Exact Match Check
        if entry:
            if (entry.get("expires_at") or 0) > now:
                self.exact_hits += 1
                entry["hit_count"] = entry.get("hit_count", 0) + 1
                entry["last_accessed"] = now
                logger.info(f"[CAG] Exact Cache HIT for key '{key}' (Query: '{query[:40]}...') -> Latency: <1ms")
                return {
                    "response": entry["response"],
                    "cached": True,
                    "match_type": "exact",
                    "hit_count": entry["hit_count"],
                    "age_seconds": round(now - entry.get("created_at", now), 1)
                }
            else:
                del self._l1_cache[key]

        # 2. Fuzzy Semantic Fallback Check (L1.5)
        if allow_fuzzy and len(self._l1_cache) > 0:
            query_tokens = self._get_tokens(query)
            if len(query_tokens) >= 1:
                best_match = None
                best_score = 0.0

                for k, v in list(self._l1_cache.items()):
                    if (v.get("expires_at") or 0) <= now:
                        del self._l1_cache[k]
                        continue

                    cached_tokens = set(v.get("tokens", []))
                    score = self._calculate_similarity(query_tokens, cached_tokens)
                    if score > best_score:
                        best_score = score
                        best_match = (k, v)

                if best_match and best_score >= FUZZY_SIMILARITY_THRESHOLD:
                    matched_key, matched_entry = best_match
                    self.fuzzy_hits += 1
                    matched_entry["hit_count"] = matched_entry.get("hit_count", 0) + 1
                    matched_entry["last_accessed"] = now
                    logger.info(f"[CAG] Fuzzy Semantic Cache HIT (Score: {best_score:.2f}) for key '{matched_key}'")
                    return {
                        "response": matched_entry["response"],
                        "cached": True,
                        "match_type": "fuzzy",
                        "similarity": round(best_score, 2),
                        "hit_count": matched_entry["hit_count"],
                        "age_seconds": round(now - matched_entry.get("created_at", now), 1)
                    }

        self.misses += 1
        return None

    def put(
        self,
        query: str,
        response: str,
        category: str = "general",
        ttl_seconds: Optional[int] = None
    ):
        """Store a newly generated response in the cache with dynamic TTL."""
        if self.should_bypass(query) or not response or len(response.strip()) < 5:
            return

        if ttl_seconds is None:
            ttl_seconds = DEFAULT_CATEGORY_TTLS.get(category, DEFAULT_CATEGORY_TTLS["general"])

        key = self._generate_key(query)
        now = time.time()
        norm_query = self._normalize_query(query)
        tokens = list(self._get_tokens(norm_query))

        entry = {
            "query": query,
            "normalized_query": norm_query,
            "tokens": tokens,
            "response": response,
            "category": category,
            "created_at": now,
            "last_accessed": now,
            "expires_at": now + ttl_seconds,
            "hit_count": 0
        }
        with self._lock:
            self._l1_cache[key] = entry
            self._evict_lru()
        self._save_l2_cache()
        logger.debug(f"[CAG] Stored cache entry '{key}' [Category: {category}, TTL: {ttl_seconds}s]")

    def invalidate(self, pattern: Optional[str] = None) -> int:
        """Invalidate all or matching cache entries by keyword, tag, or category."""
        if not pattern or pattern.strip().lower() in ("all", "*", ""):
            with self._lock:
                count = len(self._l1_cache)
                self._l1_cache.clear()
            self._save_l2_cache()
            logger.info(f"[CAG] Invalidated entire cache ({count} entries).")
            return count

        deleted = 0
        p_clean = pattern.lower().strip()
        with self._lock:
            keys_to_del = []
            for k, v in list(self._l1_cache.items()):
                query_str = v.get("query", "").lower()
                cat_str = v.get("category", "").lower()
                resp_str = v.get("response", "").lower()
                if p_clean in query_str or p_clean in cat_str or p_clean in resp_str:
                    keys_to_del.append(k)

            for k in keys_to_del:
                del self._l1_cache[k]
                deleted += 1

        if deleted > 0:
            self._save_l2_cache()
            logger.info(f"[CAG] Invalidated {deleted} cache entries matching '{pattern}'.")
        return deleted

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive cache performance telemetry."""
        total = self.hits + self.misses
        hit_ratio = f"{(self.hits / total * 100):.1f}%" if total > 0 else "0.0%"
        
        categories: Dict[str, int] = {}
        for v in list(self._l1_cache.values()):
            cat = v.get("category", "general")
            categories[cat] = categories.get(cat, 0) + 1

        return {
            "active_entries": len(self._l1_cache),
            "max_capacity": self.max_entries,
            "hits": self.hits,
            "total_hits": self.hits,
            "exact_hits": self.exact_hits,
            "fuzzy_hits": self.fuzzy_hits,
            "misses": self.misses,
            "total_queries": total,
            "hit_ratio": hit_ratio,
            "categories": categories,
            "storage_file": str(self.store_file)
        }


# Global CAG Engine Singleton
cag_engine = CAGEngine()
