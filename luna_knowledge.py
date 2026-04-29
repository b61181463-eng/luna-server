from pathlib import Path
import json
import hashlib
import numpy as np
from openai import OpenAI

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

BASE_DIR = Path(__file__).resolve().parent
KNOW_DIR = BASE_DIR / "data" / "knowledge"
INDEX_FILE = BASE_DIR / "data" / "knowledge_index.json"

KNOW_DIR.mkdir(parents=True, exist_ok=True)

EMBED_MODEL = "text-embedding-3-small"


def file_hash(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.md5(data).hexdigest()


def read_txt_md(file: Path) -> str:
    try:
        return file.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def read_pdf(file: Path) -> str:
    if PdfReader is None:
        return ""

    try:
        reader = PdfReader(str(file))
        pages = []
        for i, page in enumerate(reader.pages[:50]):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"[{file.name} / page {i + 1}]\n{text}")
        return "\n\n".join(pages)
    except Exception:
        return ""


def load_documents():
    docs = []

    for file in KNOW_DIR.glob("*"):
        suffix = file.suffix.lower()

        if suffix in [".txt", ".md"]:
            text = read_txt_md(file)
        elif suffix == ".pdf":
            text = read_pdf(file)
        else:
            continue

        if text.strip():
            docs.append({
                "filename": file.name,
                "hash": file_hash(file),
                "text": text
            })

    return docs


def chunk_text(text: str, chunk_size: int = 900, overlap: int = 150):
    text = " ".join(text.split())
    chunks = []

    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        start += chunk_size - overlap

    return chunks


def get_embedding(text: str):
    client = OpenAI()
    response = client.embeddings.create(
        model=EMBED_MODEL,
        input=text
    )
    return response.data[0].embedding


def cosine_similarity(a, b):
    a = np.array(a)
    b = np.array(b)

    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0

    return float(np.dot(a, b) / denom)


def build_knowledge_index(force: bool = False):
    old_index = load_index()
    old_hashes = {
        item.get("filename"): item.get("file_hash")
        for item in old_index
    }

    docs = load_documents()
    index = []

    for doc in docs:
        filename = doc["filename"]
        current_hash = doc["hash"]

        # 파일이 안 바뀌었으면 기존 인덱스 재사용
        if not force and old_hashes.get(filename) == current_hash:
            reused = [
                item for item in old_index
                if item.get("filename") == filename
            ]
            index.extend(reused)
            continue

        chunks = chunk_text(doc["text"])

        for i, chunk in enumerate(chunks):
            try:
                embedding = get_embedding(chunk)
            except Exception as e:
                print(f"[knowledge] embedding 실패: {filename} chunk {i} / {e}")
                continue

            index.append({
                "filename": filename,
                "file_hash": current_hash,
                "chunk_id": i,
                "text": chunk,
                "embedding": embedding
            })

    save_index(index)
    return {
        "ok": True,
        "chunks": len(index),
        "files": len(docs)
    }


def load_index():
    if not INDEX_FILE.exists():
        return []

    try:
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_index(index):
    INDEX_FILE.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def search_knowledge(query: str, max_items: int = 4):
    index = load_index()

    # 인덱스가 없으면 자동 생성
    if not index:
        build_knowledge_index()
        index = load_index()

    if not index:
        return []

    try:
        query_embedding = get_embedding(query)
    except Exception as e:
        print(f"[knowledge] query embedding 실패: {e}")
        return []

    scored = []

    for item in index:
        score = cosine_similarity(query_embedding, item.get("embedding", []))
        scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)

    results = []
    for score, item in scored[:max_items]:
        results.append(
            f"[자료: {item['filename']} / chunk {item['chunk_id']} / 유사도 {score:.3f}]\n"
            f"{item['text']}"
        )

    return results