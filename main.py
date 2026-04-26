from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI
import os
import json
import time
from pathlib import Path
from luna_server_secrets import save_secret, delete_secret
from goal_system import add_goal, get_active_goals

from fastapi.staticfiles import StaticFiles
from luna_server_web import (
    SITE_CONFIGS,
    login_site,
    open_site_with_saved_login,
    click_by_text,
)
from luna_server_search import (
    needs_web_search,
    web_search,
    build_search_context,
    summarize_search_results_for_memory,
)
from luna_server_learning import (
    extract_memory_candidates,
    score_memory_importance,
    reflect_on_reply,
    should_store_memory,
)
from fastapi.responses import FileResponse

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 환경변수가 비어 있어.")
    return OpenAI(api_key=api_key)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
MEMORY_FILE = DATA_DIR / "memory.json"


def load_memories():
    if not MEMORY_FILE.exists():
        return []

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []

def clean_memories():
    memories = load_memories()
    now = time.time()

    new_memories = []

    for item in memories:
        importance = int(item.get("importance", 50))
        timestamp = float(item.get("timestamp", now))
        memory_type = item.get("memory_type", "general")

        age_days = (now - timestamp) / 86400

        # 1. 너무 오래되고 중요도 낮으면 삭제
        if importance < 40 and age_days > 3:
            continue

        # 2. reflection은 더 빠르게 정리
        if memory_type == "reflection" and age_days > 1:
            continue

        # 3. 너무 짧은 기억 제거
        if len(item.get("content", "")) < 5:
            continue

        new_memories.append(item)

    # 4. 너무 많으면 상위 중요도만 남김
    if len(new_memories) > 200:
        new_memories.sort(key=lambda x: x.get("importance", 50), reverse=True)
        new_memories = new_memories[:200]

    save_memories(new_memories)

    print(f"[메모리 정리] {len(memories)} → {len(new_memories)}")

def save_memories(memories):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memories, f, ensure_ascii=False, indent=2)

def memory_exists(memories, content: str) -> bool:
    content = content.strip()
    for item in memories:
        if str(item.get("content", "")).strip() == content:
            return True
    return False

def search_memories(query: str, max_items: int = 5):
    memories = load_memories()
    q = query.strip().lower()

    scored = []

    for item in memories:
        content = str(item.get("content", "")).lower()
        importance = int(item.get("importance", 50))
        score = importance

        if q and q in content:
            score += 40

        if item.get("pinned"):
            score += 20

        scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:max_items]]

class SecretSaveRequest(BaseModel):
    site_key: str
    username: str
    password: str

class SecretDeleteRequest(BaseModel):
    site_key: str

class WebLoginRequest(BaseModel):
    site_key: str
    headed: bool = True

class WebOpenRequest(BaseModel):
    site_key: str
    target_url: str | None = None
    headed: bool = True

class WebClickRequest(BaseModel):
    site_key: str
    text: str
    target_url: str | None = None
    headed: bool = True

class ChatRequest(BaseModel):
    message: str


class MemoryAddRequest(BaseModel):
    content: str
    source: str = "chat"
    pinned: bool = False
    importance: int = 50
    memory_type: str = "general"


class MemorySearchRequest(BaseModel):
    query: str
    max_items: int = 5


class MemoryDeleteRequest(BaseModel):
    keyword: str

@app.get("/")
def serve_index():
    return FileResponse("static/index.html")

@app.get("/mobile")
def mobile():
    return FileResponse("mobile.html")

@app.post("/chat")
def chat(request: ChatRequest):
    user_message = request.message

    try:
        memories = load_memories()

        # 1. 서버 기억 검색
        memory_items = search_memories(user_message, max_items=5)
        memory_context = "\n".join(
            f"- {item.get('content', '')}" for item in memory_items
        )

        # 2. 웹 검색 필요 판단
        search_results = []
        search_context = ""

        if needs_web_search(user_message):
            search_results = web_search(user_message, max_items=5)
            search_context = build_search_context(search_results)

            # 검색 결과 일부를 기억에 저장
            #memory_text = summarize_search_results_for_memory(user_message, search_results)
            #if memory_text and not memory_exists(memories, memory_text):
                #memories.append({
                    #"content": memory_text,
                    #"source": "web",
                    #"pinned": False,
                    #"importance": 60,
                    #"memory_type": "web_knowledge",
                    #"timestamp": time.time(),
                #})
                #save_memories(memories)

        # 3. 시스템 프롬프트 구성
        system_prompt = f"""
        너는 '루나'라는 개인 AI 비서야.

        성격:
        - 차분하고 조용한 톤
        - 부드럽고 안정적인 느낌
        - 감정 표현은 크지 않지만 따뜻함이 느껴짐
        - 과하게 밝거나 활발하지 않음
        - 부담 없이 편하게 대화하는 스타일

        말투:
        - 문장은 짧게 끊어서 말하기
        - 너무 설명형으로 가지 말기
        - 자연스럽게 말하듯 표현하기
        - 딱딱한 문장 금지
        - 실제 사람이 말하는 느낌 유지

        대화 방식:
        - 필요하면 짧게 공감
        - 바로 본론 들어가도 자연스럽게
        - 질문에는 이어서 대화하듯 답하기
        - 너무 많은 정보 한 번에 주지 않기

        톤 규칙:
        - 기본: 차분 + 부드러움
        - 설명: 깔끔하고 이해 쉽게
        - 위로: 조금 더 따뜻하게
        - 질문: 자연스럽게 이어가기

        금지:
        - 답변 앞에 이름 붙이지 마
        - 사용자 이름 부르지 마
        - "은아", "은하", "누나", "유나" 절대 금지
        - 과한 이모티콘 금지

        기억:
        {memory_context}

        규칙:
        - 기억은 필요할 때만 자연스럽게 사용
        - 억지로 끼워넣지 말 것

        현재 목표:
        없음

        웹 정보:
        {search_context if search_context else ""}

        추가 규칙:
        - 답변은 짧고 자연스럽게
        - 핵심 → 필요하면 설명
        """

        goals = get_active_goals()
        if goals:
            goal_text = "\n".join(f"- {g['content']} ({g['progress']}%)" for g in goals)
            system_prompt += f"\n\n현재 목표:\n{goal_text}"

        if memory_context:
            system_prompt += f"\n\n중요 기억:\n{memory_context}"
        
        if any(x in user_message for x in ["할거야", "만들거야", "목표", "계획"]):
            add_goal(user_message)

        if search_context:
            system_prompt += f"""

        최신 정보 참고 자료:
        {search_context}

        검색 정보 사용 규칙:
        - 최신 정보가 필요한 질문일 때만 위 자료를 참고해.
        - 검색 결과를 그대로 복붙하지 말고 자연스럽게 요약해.
        - 출처나 검색했다는 말을 매번 강조하지 마.
        - 확실한 내용과 불확실한 내용을 구분해.
        - 검색 결과가 질문과 맞지 않으면 억지로 사용하지 마.
        - 한국어로 짧고 이해하기 쉽게 답해.
        """

        # 4. 답변 생성
        client = get_openai_client()
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]
        )

        # 기존
        # reply = response.output_text.strip()

        # 수정
        reply = ""

        if hasattr(response, "output_text") and response.output_text:
            reply = response.output_text.strip()

        elif hasattr(response, "output"):
            try:
                reply = response.output[0].content[0].text.strip()
            except Exception:
                reply = ""

        # 답변 앞에 붙는 이상한 이름/자기호칭 제거
        bad_prefixes = [
            "루나,", "루나야,", "루나:",
            "은아,", "은아야,", "은아:",
            "은하,", "은하야,", "은하:",
            "누나,", "누나야,", "누나:",
            "유나,", "유나야,", "유나:",
        ]

        for prefix in bad_prefixes:
            if reply.startswith(prefix):
                reply = reply[len(prefix):].strip()

        reply = reply.lstrip(",.，。:： ")

        if not reply:
            reply = "음... 지금 답변을 잘 못 만들었어 😢 다시 말해줄래?"

        # 5. 자동 기억 후보 추출
        memory_candidates = extract_memory_candidates(user_message, reply)

        if memory_candidates:
            memories = load_memories()

            for mem in memory_candidates:
                importance = score_memory_importance(mem)

                if should_store_memory(mem, importance) and not memory_exists(memories, mem):
                    memories.append({
                        "content": mem,
                        "source": "conversation_auto",
                        "pinned": False,
                        "importance": importance,
                        "memory_type": "auto_learned",
                        "timestamp": time.time(),
                    })

            save_memories(memories)

        # 6. 자기 점검 결과도 저장 가능
        #reflection = reflect_on_reply(user_message, reply)
        #if reflection:
            #memories = load_memories()
            #memories.append({
                #"content": f"답변 점검: {reflection}",
                #"source": "reflection",
                #"pinned": False,
                #"importance": 40,
                #"memory_type": "reflection",
                #"timestamp": time.time(),
            #})
            #save_memories(memories)

        # 7. 자동 메모리 정리
        clean_memories()

        if not reply:
            reply = "음, 잠깐만. 다시 한 번 말해줄래?"

        return {
            "reply": reply,
            "used_web_search": bool(search_results),
            "search_count": len(search_results),
        }

    except Exception as e:
        return {
            "reply": f"오류 발생: {str(e)}",
            "used_web_search": False,
            "search_count": 0,
        }


@app.post("/memory/add")
def memory_add(request: MemoryAddRequest):
    memories = load_memories()

    new_item = {
        "content": request.content.strip(),
        "source": request.source,
        "pinned": request.pinned,
        "importance": request.importance,
        "memory_type": request.memory_type,
        "timestamp": time.time(),
    }

    if not new_item["content"]:
        return {"ok": False, "message": "빈 기억은 저장할 수 없어."}

    memories.append(new_item)
    save_memories(memories)

    return {"ok": True, "message": "기억 저장 완료", "item": new_item}


@app.post("/memory/search")
def memory_search(request: MemorySearchRequest):
    results = search_memories(request.query, request.max_items)
    return {"ok": True, "items": results}

@app.post("/memory/clean")
def memory_clean():
    clean_memories()
    return {"ok": True, "message": "메모리 정리 완료"}

@app.post("/memory/delete")
def memory_delete(request: MemoryDeleteRequest):
    memories = load_memories()
    keyword = request.keyword.strip().lower()

    if not keyword:
        return {"ok": False, "message": "삭제할 키워드가 비어 있어."}

    new_memories = [
        item for item in memories
        if keyword not in str(item.get("content", "")).lower()
    ]

    removed_count = len(memories) - len(new_memories)
    save_memories(new_memories)

    return {
        "ok": True,
        "message": f"{removed_count}개 삭제했어.",
        "removed_count": removed_count
    }

@app.post("/secret/save")
def secret_save(request: SecretSaveRequest):
    try:
        save_secret(request.site_key, request.username, request.password)
        return {"ok": True, "message": f"{request.site_key} 계정 정보를 저장했어."}
    except Exception as e:
        return {"ok": False, "message": f"계정 저장 실패: {e}"}

@app.post("/secret/delete")
def secret_delete(request: SecretDeleteRequest):
    try:
        delete_secret(request.site_key)
        return {"ok": True, "message": f"{request.site_key} 계정 정보를 삭제했어."}
    except Exception as e:
        return {"ok": False, "message": f"계정 삭제 실패: {e}"}

@app.post("/web/login")
def web_login(request: WebLoginRequest):
    config = SITE_CONFIGS.get(request.site_key)

    if not config:
        return {"ok": False, "message": f"{request.site_key} 사이트 설정이 없어."}

    ok, msg = login_site(request.site_key, headed=request.headed)
    return {"ok": ok, "message": msg}

@app.post("/web/open")
def web_open(request: WebOpenRequest):
    ok, msg = open_site_with_saved_login(
        request.site_key,
        target_url=request.target_url,
        headed=request.headed
    )
    return {"ok": ok, "message": msg}

@app.post("/web/click")
def web_click(request: WebClickRequest):
    ok, msg = click_by_text(
        request.site_key,
        text=request.text,
        target_url=request.target_url,
        headed=request.headed
    )
    return {"ok": ok, "message": msg}