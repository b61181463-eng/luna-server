from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI
import os
import json
import time
import subprocess
import platform
import webbrowser
import shutil
import re

from datetime import datetime, timedelta
from urllib.parse import quote_plus
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


def parse_schedule_from_message(text: str):
    text = text.strip()

    # 예: "내일 7시", "오늘 18시"
    if "내일" in text:
        base = datetime.now() + timedelta(days=1)
    elif "오늘" in text:
        base = datetime.now()
    else:
        base = datetime.now()

    match = re.search(r"(\d{1,2})\s*시", text)
    if match:
        hour = int(match.group(1))
        dt = base.replace(hour=hour, minute=0, second=0, microsecond=0)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    return None

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
TODO_FILE = DATA_DIR / "todos.json"
SCHEDULE_FILE = DATA_DIR / "schedules.json"
WORKFLOW_FILE = DATA_DIR / "workflows.json"
SITE_ACTION_FILE = DATA_DIR / "site_actions.json"
SAFE_FOLDERS_FILE = DATA_DIR / "safe_folders.json"


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


def append_memory(content: str, source: str = "client_auto", pinned: bool = False, importance: int = 55, memory_type: str = "conversation"):
    """중복을 피해서 메모리를 저장하는 공통 함수."""
    content = (content or "").strip()
    if not content:
        return None

    memories = load_memories()
    if memory_exists(memories, content):
        return None

    item = {
        "content": content,
        "source": source,
        "pinned": bool(pinned),
        "importance": int(importance),
        "memory_type": memory_type,
        "timestamp": time.time(),
    }
    memories.append(item)
    save_memories(memories)
    return item

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


def should_force_web_search(message: str) -> bool:
    """최신 정보/실시간 확인이 필요한 질문을 조금 더 넓게 잡는다."""
    text = (message or "").replace(" ", "").lower()
    realtime_keywords = [
        "오늘", "지금", "현재", "최신", "최근", "방금", "실시간",
        "검색", "찾아", "알아봐", "확인", "뉴스", "기사", "날씨",
        "주가", "환율", "일정", "가격", "순위", "업데이트", "공지",
        "2026", "이번주", "이번달", "요즘", "오늘의", "현재의",
    ]
    return any(keyword in text for keyword in realtime_keywords)


def save_web_results_to_memory(user_message: str, search_results: list):
    """검색 결과 요약을 장기 기억에 저장한다. 너무 자주 중복 저장되지 않도록 append_memory를 사용한다."""
    if not search_results:
        return None

    try:
        memory_text = summarize_search_results_for_memory(user_message, search_results)
    except Exception as e:
        print(f"[웹 기억 요약 실패] {e}")
        memory_text = ""

    memory_text = (memory_text or "").strip()
    if len(memory_text) < 10:
        return None

    return append_memory(
        content=memory_text,
        source="web_live_search",
        pinned=False,
        importance=65,
        memory_type="web_knowledge",
    )


# =========================
# 할 일 / 일정 관리 기능
# =========================
def load_todos():
    if not TODO_FILE.exists():
        return []
    try:
        with open(TODO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_todos(todos):
    with open(TODO_FILE, "w", encoding="utf-8") as f:
        json.dump(todos, f, ensure_ascii=False, indent=2)


def add_todo_item(content: str, due: str | None = None, source: str = "chat"):
    content = (content or "").strip()
    if not content:
        return None
    todos = load_todos()
    item = {
        "id": str(int(time.time() * 1000)),
        "content": content,
        "due": due,
        "done": False,
        "source": source,
        "timestamp": time.time(),
    }
    todos.append(item)
    save_todos(todos)
    return item


def list_open_todos(limit: int = 20):
    todos = [t for t in load_todos() if not t.get("done")]
    todos.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    return todos[:limit]


def complete_todo_by_keyword(keyword: str):
    keyword = (keyword or "").strip().lower()
    if not keyword:
        return 0
    todos = load_todos()
    count = 0
    for item in todos:
        if not item.get("done") and keyword in str(item.get("content", "")).lower():
            item["done"] = True
            item["done_at"] = time.time()
            count += 1
    if count:
        save_todos(todos)
    return count


def parse_todo_from_message(message: str):
    """자연어에서 간단히 할 일을 뽑는다. 완벽한 자연어 처리는 나중에 고도화."""
    text = (message or "").strip()
    lower = text.replace(" ", "")
    triggers = ["할일추가", "할일등록", "해야할일", "기억해줘", "일정추가", "일정등록", "체크해줘"]
    if not any(t in lower for t in triggers):
        return None

    cleaned = text
    for word in ["루나야", "루나", "할 일 추가", "할일 추가", "할일추가", "할 일 등록", "할일등록", "일정 추가", "일정추가", "기억해줘", "체크해줘", "해야 할 일", "해야할일"]:
        cleaned = cleaned.replace(word, "")
    cleaned = cleaned.strip(" :：,，.。")
    if len(cleaned) < 2:
        return None
    return cleaned


def format_todo_list(todos):
    if not todos:
        return "지금 남아있는 할 일은 없어."
    lines = []
    for idx, item in enumerate(todos, 1):
        due = item.get("due")
        suffix = f" ({due})" if due else ""
        lines.append(f"{idx}. {item.get('content', '')}{suffix}")
    return "지금 남아있는 할 일이야.\n" + "\n".join(lines)


# =========================
# PC 제어 기능
# =========================
APP_ALIASES = {
    "메모장": "notepad.exe",
    "계산기": "calc.exe",
    "그림판": "mspaint.exe",
    "크롬": "chrome.exe",
    "엣지": "msedge.exe",
    "탐색기": "explorer.exe",
    "파일탐색기": "explorer.exe",
}

SAFE_URL_ALIASES = {
    "구글": "https://www.google.com",
    "네이버": "https://www.naver.com",
    "유튜브": "https://www.youtube.com",
    "깃허브": "https://github.com",
    "github": "https://github.com",
}


def open_app_by_name(name: str):
    name = (name or "").strip().lower()
    for key, command in APP_ALIASES.items():
        if key.lower() in name:
            subprocess.Popen(command, shell=True)
            return True, f"{key} 열었어."
    return False, "아직 그 프로그램은 등록되어 있지 않아."


def open_url_or_site(text: str):
    raw = (text or "").strip()
    normalized = raw.replace(" ", "").lower()
    for key, url in SAFE_URL_ALIASES.items():
        if key.lower() in normalized:
            webbrowser.open(url)
            return True, f"{key} 열었어."
    if raw.startswith("http://") or raw.startswith("https://"):
        webbrowser.open(raw)
        return True, "웹사이트 열었어."
    return False, "열 사이트를 찾지 못했어."


def handle_local_command(user_message: str):
    """채팅/음성 명령 중 서버 답변 없이 바로 처리할 수 있는 로컬 기능."""
    text = (user_message or "").strip()
    compact = text.replace(" ", "")

    # 알림 도착 확인
    if any(x in compact for x in ["알림확인", "지난알림", "알림있어", "일정확인"]):
        due = due_schedules()
        if due:
            return "지금 확인할 알림이 있어.\n" + format_schedule_list(due)
        return "지금 도착한 알림은 없어."

    # 일정/알림 목록
    if any(x in compact for x in ["일정목록", "알림목록", "일정보여", "알림보여"]):
        return format_schedule_list(list_schedules())

    # 일정 완료
    if any(x in compact for x in ["일정완료", "알림완료"]):
        keyword = text
        for word in ["루나야", "루나", "일정 완료", "일정완료", "알림 완료", "알림완료"]:
            keyword = keyword.replace(word, "")
        count = complete_schedule_by_keyword(keyword.strip(" :：,，.。"))
        return f"좋아, {count}개 완료 처리했어." if count else "완료할 일정/알림을 못 찾았어."

    # 일정/알림 추가
    schedule = parse_schedule_from_message(text)
    if schedule:
        title, when = schedule
        item = add_schedule_item(title, when=when)
        return f"좋아, 일정/알림에 추가했어.\n- {item['title']}" + (f" ({item['when']})" if item.get('when') else "")

    # 할 일 목록 조회
    if any(x in compact for x in ["할일목록", "할일뭐", "해야할일", "투두목록"]):
        return format_todo_list(list_open_todos())

    # 할 일 완료 처리
    if any(x in compact for x in ["할일완료", "끝냈어", "완료했어"]):
        keyword = text
        for word in ["루나야", "루나", "할 일 완료", "할일 완료", "할일완료", "끝냈어", "완료했어"]:
            keyword = keyword.replace(word, "")
        keyword = keyword.strip(" :：,，.。")
        count = complete_todo_by_keyword(keyword)
        if count:
            return f"좋아, {count}개 완료로 표시했어."
        return "완료 처리할 할 일을 못 찾았어."

    # 할 일 추가
    todo = parse_todo_from_message(text)
    if todo:
        item = add_todo_item(todo, source="chat_command")
        append_memory(
            content=f"사용자의 할 일: {todo}",
            source="todo",
            pinned=False,
            importance=70,
            memory_type="todo",
        )
        return f"좋아, 할 일에 추가했어.\n- {item['content']}"

    # 폴더/파일 목록: "루나야 폴더 목록 D:\\ai"
    if any(x in compact for x in ["폴더목록", "파일목록"]):
        target = text
        for word in ["루나야", "루나", "폴더 목록", "폴더목록", "파일 목록", "파일목록", "보여줘"]:
            target = target.replace(word, "")
        ok, msg, items = list_folder(target.strip() or ".")
        if not ok:
            return msg
        if not items:
            return msg + "\n비어 있어."
        lines = [f"- {it['type']}: {it['name']}" for it in items[:20]]
        return msg + "\n" + "\n".join(lines)

    # 파일 검색: "루나야 파일 검색 report D:\\ai"
    if any(x in compact for x in ["파일검색", "폴더검색"]):
        target = text
        for word in ["루나야", "루나", "파일 검색", "파일검색", "폴더 검색", "폴더검색", "찾아줘", "찾아"]:
            target = target.replace(word, "")
        parts = target.strip().split(maxsplit=1)
        keyword = parts[0] if parts else ""
        folder = parts[1] if len(parts) > 1 else "."
        ok, msg, results = search_files(keyword, folder=folder)
        if not ok:
            return msg
        if not results:
            return msg
        return msg + "\n" + "\n".join(f"- {r['name']}" for r in results[:15])

    # 파일/폴더 열기: "루나야 D:\\ai 열어줘"
    if any(x in compact for x in ["파일열어", "폴더열어"]):
        target = text
        for word in ["루나야", "루나", "파일 열어줘", "파일열어줘", "폴더 열어줘", "폴더열어줘", "열어줘"]:
            target = target.replace(word, "")
        ok, msg = open_path(target.strip())
        return msg

    # 작업 플로우 실행: "루나야 플로우 실행 공부시작"
    if any(x in compact for x in ["플로우실행", "작업실행"]):
        name = text
        for word in ["루나야", "루나", "플로우 실행", "플로우실행", "작업 실행", "작업실행", "실행해줘"]:
            name = name.replace(word, "")
        ok, msg, logs = run_workflow(name.strip())
        return msg

    # 사이트 동작 실행: "루나야 사이트 동작 실행 kmooc"
    if any(x in compact for x in ["사이트동작실행", "웹동작실행"]):
        name = text
        for word in ["루나야", "루나", "사이트 동작 실행", "사이트동작실행", "웹 동작 실행", "웹동작실행", "실행해줘"]:
            name = name.replace(word, "")
        result = run_site_action(name.strip())
        if len(result) == 3:
            ok, msg, logs = result
        else:
            ok, msg = result
        return msg

    # PC 앱 실행 / 사이트 열기
    if any(x in compact for x in ["열어줘", "실행해줘", "켜줘"]):
        ok, msg = open_app_by_name(text)
        if ok:
            return msg
        ok, msg = open_url_or_site(text)
        if ok:
            return msg

    return None

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


class MemorySaveRequest(BaseModel):
    text: str
    source: str = "client_auto"
    pinned: bool = False
    importance: int = 55
    memory_type: str = "conversation"

class MemorySearchRequest(BaseModel):
    query: str
    max_items: int = 5


class MemoryDeleteRequest(BaseModel):
    keyword: str


class TodoAddRequest(BaseModel):
    content: str
    due: str | None = None

class TodoCompleteRequest(BaseModel):
    keyword: str

class PcOpenAppRequest(BaseModel):
    name: str

class PcOpenUrlRequest(BaseModel):
    url_or_name: str


class FileAllowFolderRequest(BaseModel):
    path: str

class FileListRequest(BaseModel):
    path: str = "."

class FileOpenRequest(BaseModel):
    path: str

class FileSearchRequest(BaseModel):
    keyword: str
    folder: str = "."
    limit: int = 20

class NoteCreateRequest(BaseModel):
    filename: str
    content: str

class ScheduleAddRequest(BaseModel):
    title: str
    when: str | None = None
    note: str = ""
    remind: bool = True

class ScheduleCompleteRequest(BaseModel):
    keyword: str

class SiteActionRegisterRequest(BaseModel):
    name: str
    site_key: str
    steps: list
    description: str = ""

class SiteActionRunRequest(BaseModel):
    name: str
    headed: bool = True

class WorkflowRegisterRequest(BaseModel):
    name: str
    steps: list
    description: str = ""

class WorkflowRunRequest(BaseModel):
    name: str

@app.get("/")
def serve_index():
    return FileResponse("static/index.html")

@app.get("/mobile")
def mobile():
    return FileResponse("mobile.html")

@app.get("/health")
def health():
    return {"ok": True, "status": "running", "service": "luna_server"}

@app.post("/chat")
def chat(request: ChatRequest):
    user_message = request.message

    try:
        local_reply = handle_local_command(user_message)
        if local_reply:
            auto_learn_from_turn(user_message, local_reply, search_results=None)
            clean_memories()
            return {
                "reply": local_reply,
                "used_web_search": False,
                "search_count": 0,
                "handled_locally": True,
            }

        memories = load_memories()

        # 1. 서버 기억 검색
        memory_items = search_memories(user_message, max_items=5)
        memory_context = "\n".join(
            f"- {item.get('content', '')}" for item in memory_items
        )

        # 2. 웹 검색 필요 판단
        search_results = []
        search_context = ""

        should_search_now = needs_web_search(user_message) or should_force_web_search(user_message)

        if should_search_now:
            print(f"[실시간 검색] {user_message}")
            search_results = web_search(user_message, max_items=5)
            search_context = build_search_context(search_results)

            # 검색 결과 일부를 장기 기억에 저장
            saved_web_memory = save_web_results_to_memory(user_message, search_results)
            if saved_web_memory:
                print(f"[웹 기억 저장] {saved_web_memory.get('content', '')[:80]}")

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

        [사용자 기억]
        {memory_context if memory_context else "관련 기억 없음"}

        [기억 사용 규칙]
        - 이 기억은 사용자에 대한 정보야.
        - 관련 질문이 나오면 반드시 자연스럽게 활용해.
        - 사용자가 과거 대화나 이전 정보를 물으면 기억을 먼저 참고해.
        - 억지로 끼워넣지 말고 필요할 때만 사용해.

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

        # 5. 완전 자동 학습: 중요한 정보는 사용자가 따로 말하지 않아도 저장
        learned_items = auto_learn_from_turn(user_message, reply, search_results=search_results)
        if learned_items:
            print(f"[완전 자동 학습] {len(learned_items)}개 저장")

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


@app.post("/memory/save")
def memory_save(request: MemorySaveRequest):
    """클라이언트가 대화 내용을 간단히 저장할 때 쓰는 호환 API.
    luna_voice_client.py / luna_chat_window.py에서 {"text": "..."} 형태로 호출해도 동작한다.
    """
    text = request.text.strip()
    if not text:
        return {"ok": False, "message": "빈 기억은 저장하지 않았어."}

    # 너무 짧은 감탄사/잡음은 저장하지 않음
    compact = text.replace(" ", "").strip(".,!?~…")
    if len(compact) <= 1 or compact in {"어", "음", "응", "네", "예", "요"}:
        return {"ok": True, "message": "저장할 만한 내용이 아니라 건너뛰었어.", "skipped": True}

    # 완전 자동 학습 분류기를 사용해서 중요도/고정 여부를 자동 보정
    importance = request.importance
    pinned = request.pinned
    classified = classify_memory_content(text)
    if classified:
        memory_type_auto, auto_importance, auto_pinned = classified
        importance = max(importance, auto_importance)
        pinned = pinned or auto_pinned
        if request.memory_type == "conversation":
            request.memory_type = memory_type_auto

    item = append_memory(
        content=text,
        source=request.source,
        pinned=pinned,
        importance=importance,
        memory_type=request.memory_type,
    )

    if item is None:
        return {"ok": True, "message": "이미 있거나 저장하지 않아도 되는 기억이야.", "duplicate": True}

    return {"ok": True, "message": "기억 저장 완료", "item": item}


@app.get("/memory/load")
def memory_load():
    return {"ok": True, "items": load_memories()}


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

@app.post("/search/live")
def search_live(request: ChatRequest):
    """채팅과 별개로 실시간 검색만 테스트할 때 쓰는 API."""
    try:
        results = web_search(request.message, max_items=5)
        context = build_search_context(results)
        saved = save_web_results_to_memory(request.message, results)
        return {
            "ok": True,
            "query": request.message,
            "count": len(results),
            "context": context,
            "saved_to_memory": bool(saved),
        }
    except Exception as e:
        return {"ok": False, "message": f"실시간 검색 실패: {e}"}



@app.post("/todo/add")
def todo_add(request: TodoAddRequest):
    item = add_todo_item(request.content, due=request.due, source="api")
    if not item:
        return {"ok": False, "message": "빈 할 일은 추가할 수 없어."}
    append_memory(
        content=f"사용자의 할 일: {item['content']}",
        source="todo",
        pinned=False,
        importance=70,
        memory_type="todo",
    )
    return {"ok": True, "message": "할 일 추가 완료", "item": item}


@app.get("/todo/list")
def todo_list():
    return {"ok": True, "items": list_open_todos()}


@app.post("/todo/complete")
def todo_complete(request: TodoCompleteRequest):
    count = complete_todo_by_keyword(request.keyword)
    return {"ok": True, "message": f"{count}개 완료 처리", "count": count}


@app.post("/pc/open-app")
def pc_open_app(request: PcOpenAppRequest):
    ok, msg = open_app_by_name(request.name)
    return {"ok": ok, "message": msg}


@app.post("/pc/open-url")
def pc_open_url(request: PcOpenUrlRequest):
    ok, msg = open_url_or_site(request.url_or_name)
    return {"ok": ok, "message": msg}



# =========================
# 파일 / 폴더 제어 API
# =========================
@app.get("/file/safe-folders")
def file_safe_folders():
    return {"ok": True, "folders": [str(p) for p in load_safe_folders()]}

@app.post("/file/allow-folder")
def file_allow_folder(request: FileAllowFolderRequest):
    ok, msg = add_safe_folder(request.path)
    return {"ok": ok, "message": msg, "folders": [str(p) for p in load_safe_folders()]}

@app.post("/file/list")
def file_list(request: FileListRequest):
    ok, msg, items = list_folder(request.path)
    return {"ok": ok, "message": msg, "items": items}

@app.post("/file/open")
def file_open(request: FileOpenRequest):
    ok, msg = open_path(request.path)
    return {"ok": ok, "message": msg}

@app.post("/file/search")
def file_search_api(request: FileSearchRequest):
    ok, msg, items = search_files(request.keyword, folder=request.folder, limit=request.limit)
    return {"ok": ok, "message": msg, "items": items}

@app.post("/file/create-note")
def file_create_note(request: NoteCreateRequest):
    p = create_note_file(request.filename, request.content)
    append_memory(f"사용자가 노트를 만들었어: {p.name}", source="file", importance=60, memory_type="file")
    return {"ok": True, "message": f"노트를 만들었어: {p}", "path": str(p)}

# =========================
# 일정 / 알림 API
# =========================
@app.post("/schedule/add")
def schedule_add(request: ScheduleAddRequest):
    item = add_schedule_item(request.title, when=request.when, note=request.note, remind=request.remind)
    if not item:
        return {"ok": False, "message": "빈 일정은 추가할 수 없어."}
    return {"ok": True, "message": "일정/알림 추가 완료", "item": item}

@app.get("/schedule/list")
def schedule_list():
    return {"ok": True, "items": list_schedules()}

@app.post("/schedule/complete")
def schedule_complete(request: ScheduleCompleteRequest):
    count = complete_schedule_by_keyword(request.keyword)
    return {"ok": True, "message": f"{count}개 완료 처리", "count": count}

@app.get("/schedule/check-due")
def schedule_check_due():
    items = due_schedules()
    return {"ok": True, "count": len(items), "items": items}

# =========================
# 사이트별 자동 동작 API
# =========================
@app.post("/web/action/register")
def web_action_register(request: SiteActionRegisterRequest):
    if request.site_key not in SITE_CONFIGS:
        return {"ok": False, "message": f"등록되지 않은 site_key야: {request.site_key}"}
    action = register_site_action(request.name, request.site_key, request.steps, request.description)
    return {"ok": True, "message": f"사이트 동작 등록 완료: {request.name}", "action": action}

@app.get("/web/action/list")
def web_action_list():
    return {"ok": True, "items": load_site_actions()}

@app.post("/web/action/run")
def web_action_run(request: SiteActionRunRequest):
    ok, msg, logs = run_site_action(request.name, headed=request.headed)
    return {"ok": ok, "message": msg, "logs": logs}

# =========================
# 작업 플로우 API
# =========================
@app.post("/workflow/register")
def workflow_register(request: WorkflowRegisterRequest):
    workflow = register_workflow(request.name, request.steps, request.description)
    return {"ok": True, "message": f"작업 플로우 등록 완료: {request.name}", "workflow": workflow}

@app.get("/workflow/list")
def workflow_list():
    return {"ok": True, "items": load_workflows()}

@app.post("/workflow/run")
def workflow_run(request: WorkflowRunRequest):
    ok, msg, logs = run_workflow(request.name)
    return {"ok": ok, "message": msg, "logs": logs}

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