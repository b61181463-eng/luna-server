import requests
from luna_knowledge import build_knowledge_index
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
KNOW_DIR = BASE_DIR / "data" / "knowledge"


def search_arxiv(query, max_results=3):
    url = f"http://export.arxiv.org/api/query?search_query=all:{query}&start=0&max_results={max_results}"
    res = requests.get(url)
    return res.text


def save_arxiv_papers(query):
    xml = search_arxiv(query)

    # 매우 단순 파싱 (나중에 개선 가능)
    papers = xml.split("<entry>")[1:]

    saved = 0

    for i, paper in enumerate(papers):
        try:
            title = paper.split("<title>")[1].split("</title>")[0].strip()
            summary = paper.split("<summary>")[1].split("</summary>")[0].strip()

            content = f"제목: {title}\n\n요약: {summary}"

            file_path = KNOW_DIR / f"arxiv_{query}_{i}.txt"
            file_path.write_text(content, encoding="utf-8")

            saved += 1
        except:
            continue

    return saved


def learn_from_arxiv(query):
    count = save_arxiv_papers(query)

    # 벡터 인덱스 재생성
    build_knowledge_index(force=True)

    return f"{count}개의 논문을 학습했어."