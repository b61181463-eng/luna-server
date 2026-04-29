# -*- coding: utf-8 -*-
"""
Luna Knowledge Refiner
- main.py의 data/memory.json 안에 쌓인 knowledge 기억을 정리한다.
- 낮은 품질/중복/너무 오래된 약한 기억을 제거한다.
- 비슷한 지식은 더 중요도가 높은 항목 하나만 남긴다.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
MEMORY_FILE = DATA_DIR / "memory.json"
REFINE_REPORT_FILE = DATA_DIR / "knowledge_refine_report.json"

STOPWORDS = {
    "그리고", "그래서", "하지만", "그러나", "이것", "저것", "그것", "대한", "관련", "설명",
    "질문", "답변", "핵심", "하는", "있는", "없는", "위해", "때문", "경우", "정도",
    "the", "and", "or", "of", "to", "in", "a", "an", "is", "are", "for", "with",
}

LOW_VALUE_PATTERNS = [
    r"^응[,\s]*$",
    r"^네[,\s]*$",
    r"^알겠어",
    r"^좋아",
    r"^고마워",
    r"오류 발생:",
    r"서버 오류:",
    r"LMS 열기 실패",
    r"로그인",
    r"열었어",
    r"종료",
]


def now_ts() -> float:
    return time.time()


def normalize_text(text: str) -> str:
    text = str(text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def load_memories() -> List[Dict[str, Any]]:
    if not MEMORY_FILE.exists():
        return []
    try:
        data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_memories(memories: List[Dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text(json.dumps(memories, ensure_ascii=False, indent=2), encoding="utf-8")


def save_report(report: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REFINE_REPORT_FILE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def tokenize(text: str) -> set[str]:
    text = normalize_text(text).lower()
    # 한글/영문/숫자 토큰 추출
    tokens = re.findall(r"[가-힣A-Za-z0-9_]+", text)
    clean = set()
    for token in tokens:
        if len(token) < 2:
            continue
        if token in STOPWORDS:
            continue
        clean.add(token)
    return clean


def similarity(a: str, b: str) -> float:
    ta = tokenize(a)
    tb = tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def is_low_quality(item: Dict[str, Any]) -> Tuple[bool, str]:
    content = normalize_text(item.get("content", ""))
    importance = int(item.get("importance", 50) or 50)
    memory_type = str(item.get("memory_type", "general"))

    compact = re.sub(r"[\s\.,!?~…]+", "", content)
    if len(compact) < 8:
        return True, "too_short"

    for pattern in LOW_VALUE_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            # 사용자가 직접 pinned한 것은 보호
            if item.get("pinned"):
                return False, "pinned"
            return True, "low_value_pattern"

    # 매우 낮은 중요도 지식은 제거 후보
    if memory_type in {"knowledge", "auto_learned", "conversation"} and importance < 35:
        return True, "low_importance"

    return False, "ok"


def quality_score(item: Dict[str, Any]) -> float:
    content = normalize_text(item.get("content", ""))
    importance = int(item.get("importance", 50) or 50)
    memory_type = str(item.get("memory_type", "general"))
    timestamp = float(item.get("timestamp", 0) or 0)

    score = importance
    if item.get("pinned"):
        score += 100
    if memory_type == "user_profile":
        score += 45
    elif memory_type == "project":
        score += 35
    elif memory_type == "knowledge":
        score += 25
    elif memory_type == "web_knowledge":
        score += 20

    # 구조화된 Q/A는 가치 가산
    if "질문:" in content and ("답변" in content or "핵심" in content):
        score += 18
    if any(k in content for k in ["원인", "해결", "방법", "정의", "핵심", "한계", "예시"]):
        score += 12

    # 너무 짧거나 너무 긴 것은 살짝 감점
    if len(content) < 35:
        score -= 20
    if len(content) > 1400:
        score -= 10

    # 최신 정보에 아주 약간 가산
    age_days = (now_ts() - timestamp) / 86400 if timestamp else 999
    if age_days < 7:
        score += 5

    return score


def trim_content(content: str, max_len: int = 1200) -> str:
    content = normalize_text(content)
    if len(content) <= max_len:
        return content
    return content[:max_len].rstrip() + "..."


def refine_memories(similarity_threshold: float = 0.82, max_items: int = 350) -> Dict[str, Any]:
    memories = load_memories()
    before = len(memories)

    kept: List[Dict[str, Any]] = []
    removed: List[Dict[str, Any]] = []

    # 1) 낮은 품질 제거 + 길이 정리
    candidates: List[Dict[str, Any]] = []
    for item in memories:
        item = dict(item)
        content = normalize_text(item.get("content", ""))
        item["content"] = trim_content(content)

        low, reason = is_low_quality(item)
        if low:
            removed.append({"reason": reason, "content": content[:160]})
            continue
        candidates.append(item)

    # 2) 중복 제거: 품질 점수 높은 순으로 남김
    candidates.sort(key=quality_score, reverse=True)
    for item in candidates:
        content = item.get("content", "")
        duplicate = False
        duplicate_of = None

        # pinned/user_profile는 중복 제거를 느슨하게 적용
        threshold = 0.92 if item.get("pinned") or item.get("memory_type") == "user_profile" else similarity_threshold

        for existing in kept:
            sim = similarity(content, existing.get("content", ""))
            if sim >= threshold:
                duplicate = True
                duplicate_of = existing.get("content", "")[:120]
                break

        if duplicate:
            removed.append({"reason": "duplicate", "duplicate_of": duplicate_of, "content": content[:160]})
            continue

        kept.append(item)

    # 3) 너무 많으면 품질 높은 순으로 제한하되 pinned는 보호
    if len(kept) > max_items:
        pinned = [m for m in kept if m.get("pinned")]
        others = [m for m in kept if not m.get("pinned")]
        others.sort(key=quality_score, reverse=True)
        kept = pinned + others[: max(0, max_items - len(pinned))]
        removed.append({"reason": "max_items_trim", "count_trimmed_to": max_items})

    # 저장 전 timestamp 없는 것 보정
    current = now_ts()
    for item in kept:
        if not item.get("timestamp"):
            item["timestamp"] = current

    # 정렬: pinned/중요도 높은 순
    kept.sort(key=quality_score, reverse=True)
    save_memories(kept)

    report = {
        "ok": True,
        "before": before,
        "after": len(kept),
        "removed_count": before - len(kept),
        "removed_samples": removed[:30],
        "report_file": str(REFINE_REPORT_FILE),
        "memory_file": str(MEMORY_FILE),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_report(report)
    return report


if __name__ == "__main__":
    result = refine_memories()
    print(json.dumps(result, ensure_ascii=False, indent=2))
