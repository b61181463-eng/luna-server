# -*- coding: utf-8 -*-
"""
Luna Auto Research
- arXiv 공개 API를 이용해 연구 자료를 검색하고 data/knowledge/auto_research 에 저장
- 저장 후 luna_knowledge.build_knowledge_index(force=True)로 벡터 인덱스 갱신
- DBpia/Google Scholar 직접 크롤링 대신 공개 API부터 안전하게 사용
"""

from __future__ import annotations

import re
import time
import html
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote_plus

import requests

BASE_DIR = Path(__file__).resolve().parent
KNOW_DIR = BASE_DIR / "data" / "knowledge"
AUTO_DIR = KNOW_DIR / "auto_research"
AUTO_DIR.mkdir(parents=True, exist_ok=True)

ARXIV_API = "https://export.arxiv.org/api/query"

RESEARCH_TRIGGERS = [
    "논문", "연구", "학술", "근거", "출처", "교수", "박사", "전문적으로",
    "깊게", "분석", "리뷰", "survey", "paper", "research", "arxiv",
]

ACADEMIC_TOPICS = [
    "ai", "인공지능", "머신러닝", "딥러닝", "llm", "rag", "음성인식", "stt", "tts",
    "화학", "물리", "미적분", "수학", "공학", "재료", "수소", "환원", "철강",
]


def _clean_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _safe_filename(text: str, max_len: int = 80) -> str:
    text = re.sub(r"[^0-9a-zA-Z가-힣_\-]+", "_", text).strip("_")
    return (text[:max_len] or "research")


def should_auto_research(query: str, knowledge_context: str = "") -> bool:
    """언제 자동 논문 검색을 할지 판단한다.
    너무 자주 검색하면 느리고 비용/시간이 늘어서 강한 신호가 있을 때만 동작.
    """
    q = (query or "").lower()
    if not q or len(q.strip()) < 4:
        return False

    if any(t in q for t in RESEARCH_TRIGGERS):
        return True

    # 전문 주제인데 현재 자료가 거의 없으면 한 번 자동 학습
    if len(knowledge_context or "") < 300 and any(t in q for t in ACADEMIC_TOPICS):
        return True

    return False


def search_arxiv(query: str, max_results: int = 3):
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    res = requests.get(ARXIV_API, params=params, timeout=(5, 20))
    res.raise_for_status()

    root = ET.fromstring(res.text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = []

    for entry in root.findall("atom:entry", ns):
        title = _clean_text(entry.findtext("atom:title", default="", namespaces=ns))
        summary = _clean_text(entry.findtext("atom:summary", default="", namespaces=ns))
        published = _clean_text(entry.findtext("atom:published", default="", namespaces=ns))
        link = ""
        for l in entry.findall("atom:link", ns):
            href = l.attrib.get("href", "")
            if "arxiv.org/abs" in href:
                link = href
                break
        authors = []
        for a in entry.findall("atom:author", ns):
            name = _clean_text(a.findtext("atom:name", default="", namespaces=ns))
            if name:
                authors.append(name)

        if title and summary:
            entries.append({
                "title": title,
                "summary": summary,
                "published": published[:10],
                "link": link,
                "authors": authors[:5],
            })

    return entries


def save_papers_to_knowledge(query: str, papers: list[dict]) -> int:
    saved = 0
    stamp = time.strftime("%Y%m%d_%H%M%S")
    qname = _safe_filename(query)

    for i, paper in enumerate(papers, start=1):
        title = paper.get("title", "")
        authors = ", ".join(paper.get("authors", []))
        content = (
            f"[자동 연구 학습]\n"
            f"검색어: {query}\n"
            f"제목: {title}\n"
            f"저자: {authors}\n"
            f"발행일: {paper.get('published', '')}\n"
            f"링크: {paper.get('link', '')}\n\n"
            f"초록 요약 원문:\n{paper.get('summary', '')}\n\n"
            f"활용 규칙: 이 자료는 arXiv 공개 초록 기반 연구 참고자료다. "
            f"확정 사실처럼 과장하지 말고, 연구 동향/개념 설명의 근거로 사용한다.\n"
        )
        path = AUTO_DIR / f"{stamp}_{qname}_{i}.txt"
        path.write_text(content, encoding="utf-8")
        saved += 1

    return saved


def rebuild_index_safely():
    try:
        from luna_knowledge import build_knowledge_index
        return build_knowledge_index(force=True)
    except Exception as e:
        return {"ok": False, "message": str(e)}


def learn_from_arxiv(query: str, max_results: int = 3) -> dict:
    query = (query or "").strip()
    if not query:
        return {"ok": False, "message": "검색어가 비어 있어."}

    try:
        papers = search_arxiv(query, max_results=max_results)
        if not papers:
            return {"ok": False, "message": f"'{query}' 관련 arXiv 자료를 찾지 못했어."}

        saved = save_papers_to_knowledge(query, papers)
        index_result = rebuild_index_safely()

        return {
            "ok": True,
            "query": query,
            "saved": saved,
            "papers": papers,
            "index": index_result,
            "message": f"'{query}' 관련 연구 자료 {saved}개를 저장하고 지식 인덱스를 갱신했어.",
        }
    except Exception as e:
        return {"ok": False, "message": f"자동 연구 학습 실패: {e}"}


def maybe_auto_research(query: str, knowledge_context: str = "", max_results: int = 2) -> dict:
    if not should_auto_research(query, knowledge_context):
        return {"ok": False, "skipped": True, "message": "자동 연구 조건 아님"}

    return learn_from_arxiv(query, max_results=max_results)
