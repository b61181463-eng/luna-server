from duckduckgo_search import DDGS


def needs_web_search(text: str) -> bool:
    text = text.strip()

    keywords = [
        "최신", "최근", "뉴스", "오늘", "지금", "현재",
        "검색", "찾아", "알아봐", "확인해줘",
        "업데이트", "발표", "출시", "가격", "날씨"
    ]

    return any(k in text for k in keywords)


def web_search(query: str, max_items: int = 5):
    results = []

    try:
        with DDGS() as ddgs:
            search_results = ddgs.text(query, max_results=max_items)

            for item in search_results:
                results.append({
                    "title": item.get("title", ""),
                    "body": item.get("body", ""),
                    "href": item.get("href", ""),
                })

    except Exception:
        return []

    return results


def build_search_context(results: list) -> str:
    if not results:
        return ""

    lines = []
    for idx, item in enumerate(results, start=1):
        title = item.get("title", "").strip()
        body = item.get("body", "").strip()
        href = item.get("href", "").strip()

        lines.append(f"[{idx}] 제목: {title}")
        if body:
            lines.append(f"요약: {body}")
        if href:
            lines.append(f"링크: {href}")
        lines.append("")

    return "\n".join(lines).strip()


def summarize_search_results_for_memory(user_text: str, results: list) -> str:
    if not results:
        return ""

    first = results[0]
    title = first.get("title", "").strip()
    body = first.get("body", "").strip()

    memory_text = f"질문 '{user_text}' 관련 검색 결과: {title}"
    if body:
        memory_text += f" / {body}"

    return memory_text[:300]