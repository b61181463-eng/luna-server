from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from openai import OpenAI
import os
import json
import time
import re
import subprocess
import webbrowser
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

# =========================================================
# 안전 import: 일부 파일이 없어도 서버가 바로 죽지 않게 처리
# =========================================================
try:
    from luna_server_secrets import save_secret, delete_secret
except Exception:
    def save_secret(site_key, username, password):
        return False
    def delete_secret(site_key):
        return False

try:
    from goal_system import add_goal, get_active_goals
except Exception:
    def add_goal(content):
        return None
    def get_active_goals():
        return []

try:
    from luna_server_web import (
        SITE_CONFIGS,
        login_site,
        open_site_with_saved_login,
        click_by_text,
    )
except Exception:
    SITE_CONFIGS = {}
    def login_site(site_key, headed=True):
        return False, "웹 자동화 모듈이 아직 연결되지 않았어."
    def open_site_with_saved_login(site_key, target_url=None, headed=True):
        if target_url:
            webbrowser.open(target_url)
            return True, f"{target_url} 열었어."
        return False, "열 사이트 주소가 없어."
    def click_by_text(site_key, text, target_url=None, headed=True):
        return False, "클릭 자동화 모듈이 아직 연결되지 않았어."

try:
    from luna_server_search import (
        needs_web_search,
        web_search,
        build_search_context,
        summarize_search_results_for_memory,
    )
except Exception:
    def needs_web_search(message: str) -> bool:
        keywords = ["오늘", "지금", "최신", "검색", "뉴스", "날씨", "가격", "확인", "알려줘", "실시간"]
        return any(k in message for k in keywords)
    def web_search(query: str, max_items: int = 5):
        return []
    def build_search_context(results):
        return ""
    def summarize_search_results_for_memory(query, results):
        return ""

try:
    from luna_server_learning import (
        extract_memory_candidates,
        score_memory_importance,
        reflect_on_reply,
        should_store_memory,
    )
except Exception:
    def extract_memory_candidates(user_message: str, reply: str = ""):
        text = (user_message or "").strip()
        candidates = []
        strong = ["기억해", "기억해줘", "잊지마", "내 이름", "나는 ", "내가 ", "좋아해", "싫어해", "목표", "계획", "프로젝트"]
        if len(text) >= 8 and any(k in text for k in strong):
            candidates.append(text)
        return candidates
    def score_memory_importance(mem: str):
        score = 55
        if any(k in mem for k in ["기억해", "기억해줘", "잊지마", "내 이름"]):
            score += 25
        if any(k in mem for k in ["목표", "계획", "프로젝트", "전과", "과제"]):
            score += 15
        return min(score, 100)
    def reflect_on_reply(user_message: str, reply: str):
        return ""
    def should_store_memory(mem: str, importance: int):
        return importance >= 60

# =========================================================
# 기본 경로/앱 설정
# =========================================================
app = FastAPI()
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
MEMORY_FILE = DATA_DIR / "memory.json"
TODO_FILE = DATA_DIR / "todos.json"
SCHEDULE_FILE = DATA_DIR / "schedules.json"
WORKFLOW_FILE = DATA_DIR / "workflows.json"
RECENT_FILE = DATA_DIR / "recent_turns.json"

STATIC_DIR = BASE_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# =========================================================
# 모델
# =========================================================
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
    target_url: Optional[str] = None
    headed: bool = True

class WebClickRequest(BaseModel):
    site_key: str
    text: str
    target_url: Optional[str] = None
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

class TodoRequest(BaseModel):
    text: str

class ScheduleRequest(BaseModel):
    text: str
    when: Optional[str] = None

class FileOpenRequest(BaseModel):
    path: str

class WorkflowRequest(BaseModel):
    name: str
    steps: List[Dict[str, Any]] = []

class WorkflowRunRequest(BaseModel):
    name: str

# =========================================================
# 공통 유틸
# =========================================================
def get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 환경변수가 비어 있어.")
    return OpenAI(api_key=api_key)


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if data is not None else default
    except Exception:
        return default


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def now_ts():
    return time.time()


def normalize_text(text: str):
    return (text or "").strip()

# =========================================================
# 일정 파싱: 이전 오류 해결용 핵심 함수
# =========================================================
def parse_schedule_from_message(text: str):
    """한국어 간단 일정 파서.
    예:
    - 오늘 7시
    - 내일 오후 3시 30분
    - 모레 18시
    - 1분 뒤 / 10초 뒤 / 2시간 뒤 / 30분 후
    반환: YYYY-MM-DD HH:MM:SS 또는 None
    """
    text = normalize_text(text)
    if not text:
        return None

    now = datetime.now()

    rel_seconds = 0
    sec_match = re.search(r"(\d{1,3})\s*초\s*(뒤|후|있다가)", text)
    min_match = re.search(r"(\d{1,3})\s*분\s*(뒤|후|있다가)", text)
    hour_rel_match = re.search(r"(\d{1,2})\s*시간\s*(뒤|후|있다가)", text)

    if sec_match:
        rel_seconds += int(sec_match.group(1))
    if min_match:
        rel_seconds += int(min_match.group(1)) * 60
    if hour_rel_match:
        rel_seconds += int(hour_rel_match.group(1)) * 3600

    if rel_seconds > 0:
        dt = now + timedelta(seconds=rel_seconds)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    base = now
    if "모레" in text:
        base = base + timedelta(days=2)
    elif "내일" in text:
        base = base + timedelta(days=1)

    hour_match = re.search(r"(\d{1,2})\s*시", text)
    minute_match = re.search(r"(\d{1,2})\s*분", text)

    if not hour_match:
        return None

    hour = int(hour_match.group(1))
    minute = int(minute_match.group(1)) if minute_match else 0

    if any(k in text for k in ["오후", "저녁", "밤"]) and hour < 12:
        hour += 12
    if "오전" in text and hour == 12:
        hour = 0

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    dt = base.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if "오늘" not in text and "내일" not in text and "모레" not in text and dt <= now:
        dt = dt + timedelta(days=1)

    return dt.strftime("%Y-%m-%d %H:%M:%S")

# =========================================================
# 메모리 시스템
# =========================================================
def load_memories():
    data = load_json(MEMORY_FILE, [])
    return data if isinstance(data, list) else []


def save_memories(memories):
    save_json(MEMORY_FILE, memories)


def memory_exists(memories, content: str) -> bool:
    content = normalize_text(content)
    for item in memories:
        if normalize_text(str(item.get("content", ""))) == content:
            return True
    return False


def append_memory(content: str, source: str = "client_auto", pinned: bool = False, importance: int = 55, memory_type: str = "conversation"):
    content = normalize_text(content)
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
        "timestamp": now_ts(),
    }
    memories.append(item)
    save_memories(memories)
    return item


def is_low_quality_memory(text: str) -> bool:
    t = normalize_text(text)
    compact = t.replace(" ", "").strip(".,!?~…")
    if len(compact) <= 2:
        return True
    skip_exact = {"안녕", "응", "네", "예", "어", "음", "요", "아", "오", "ㅋㅋ", "ㅎㅎ"}
    if compact in skip_exact:
        return True
    return False


def clean_memories():
    memories = load_memories()
    current = now_ts()
    new_memories = []

    for item in memories:
        content = str(item.get("content", ""))
        importance = int(item.get("importance", 50))
        timestamp = float(item.get("timestamp", current))
        memory_type = item.get("memory_type", "general")
        age_days = (current - timestamp) / 86400

        if is_low_quality_memory(content):
            continue
        if item.get("pinned"):
            new_memories.append(item)
            continue
        if importance < 40 and age_days > 3:
            continue
        if memory_type == "reflection" and age_days > 1:
            continue
        new_memories.append(item)

    if len(new_memories) > 250:
        new_memories.sort(key=lambda x: x.get("importance", 50), reverse=True)
        new_memories = new_memories[:250]

    save_memories(new_memories)
    return {"before": len(memories), "after": len(new_memories)}


def search_memories(query: str, max_items: int = 8):
    memories = load_memories()
    q = normalize_text(query).lower()
    tokens = [t for t in re.split(r"\s+", q) if t]
    scored = []

    for item in memories:
        content_raw = str(item.get("content", ""))
        content = content_raw.lower()
        importance = int(item.get("importance", 50))
        score = importance

        if q and q in content:
            score += 50
        for token in tokens:
            if token and token in content:
                score += 12
        if item.get("pinned"):
            score += 25
        if item.get("memory_type") in ["auto_learned", "user_profile", "project", "goal"]:
            score += 10

        scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:max_items]]


def load_recent_turns(max_items: int = 12):
    data = load_json(RECENT_FILE, [])
    if not isinstance(data, list):
        return []
    return data[-max_items:]


def append_recent_turn(user_message: str, reply: str):
    turns = load_json(RECENT_FILE, [])
    if not isinstance(turns, list):
        turns = []
    turns.append({
        "user": user_message,
        "reply": reply,
        "timestamp": now_ts(),
    })
    turns = turns[-20:]
    save_json(RECENT_FILE, turns)

# =========================================================
# 완전 자동 학습: 이전 오류 해결용 핵심 함수
# =========================================================
def auto_learn_from_turn(user_message: str, reply: str):
    """대화 1턴에서 중요한 내용만 자동 기억한다.
    오류가 나도 채팅 전체가 죽지 않도록 내부에서 보호한다.
    """
    learned = []
    try:
        user_message = normalize_text(user_message)
        reply = normalize_text(reply)
        if not user_message or is_low_quality_memory(user_message):
            return learned

        candidates = []

        # 1) 외부/기존 학습 모듈 후보
        try:
            candidates.extend(extract_memory_candidates(user_message, reply) or [])
        except Exception:
            pass

        # 2) 강제 자동 학습 규칙
        strong_keywords = [
            "기억해", "기억해줘", "잊지마", "저장해",
            "내 이름", "나는 ", "내가 ", "좋아해", "싫어해",
            "목표", "계획", "프로젝트", "전과", "과제", "학교",
            "앞으로", "다음부터", "원해", "하고 싶어",
        ]
        if len(user_message) >= 8 and any(k in user_message for k in strong_keywords):
            candidates.append(user_message)

        # 3) 프로젝트 관련은 조금 더 적극 저장
        if "루나" in user_message and len(user_message) >= 8:
            candidates.append(user_message)

        # 중복 제거
        deduped = []
        seen = set()
        for c in candidates:
            c = normalize_text(str(c))
            if not c or c in seen or is_low_quality_memory(c):
                continue
            seen.add(c)
            deduped.append(c)

        memories = load_memories()
        for mem in deduped:
            try:
                importance = int(score_memory_importance(mem))
            except Exception:
                importance = 65

            pinned = False
            memory_type = "auto_learned"
            if any(k in mem for k in ["기억해", "기억해줘", "잊지마", "내 이름"]):
                importance = max(importance, 80)
                pinned = True
                memory_type = "user_profile"
            elif any(k in mem for k in ["목표", "계획", "프로젝트", "전과", "과제"]):
                importance = max(importance, 70)
                memory_type = "project"

            try:
                ok = should_store_memory(mem, importance)
            except Exception:
                ok = importance >= 60

            if ok and not memory_exists(memories, mem):
                item = {
                    "content": mem,
                    "source": "conversation_auto",
                    "pinned": pinned,
                    "importance": importance,
                    "memory_type": memory_type,
                    "timestamp": now_ts(),
                }
                memories.append(item)
                learned.append(item)

        if learned:
            save_memories(memories)

    except Exception as e:
        print("[auto_learn_from_turn 오류]", e)

    return learned

# =========================================================
# 할 일 / 일정 / 파일 / PC 제어 / 워크플로우
# =========================================================
def load_todos():
    data = load_json(TODO_FILE, [])
    return data if isinstance(data, list) else []


def save_todos(todos):
    save_json(TODO_FILE, todos)


def add_todo(text: str):
    text = normalize_text(text)
    if not text:
        return None
    todos = load_todos()
    item = {"id": int(time.time() * 1000), "text": text, "done": False, "timestamp": now_ts()}
    todos.append(item)
    save_todos(todos)
    return item


def complete_todo(keyword: str):
    todos = load_todos()
    keyword = normalize_text(keyword)
    count = 0
    for item in todos:
        if not item.get("done") and keyword in item.get("text", ""):
            item["done"] = True
            item["done_at"] = now_ts()
            count += 1
    save_todos(todos)
    return count


def load_schedules():
    data = load_json(SCHEDULE_FILE, [])
    return data if isinstance(data, list) else []


def save_schedules(items):
    save_json(SCHEDULE_FILE, items)


def add_schedule(text: str, when: Optional[str] = None):
    text = normalize_text(text)
    when = when or parse_schedule_from_message(text)
    if not text or not when:
        return None
    items = load_schedules()
    item = {"id": int(time.time() * 1000), "text": text, "when": when, "notified": False, "timestamp": now_ts()}
    items.append(item)
    save_schedules(items)
    return item


def due_schedules():
    items = load_schedules()
    now = datetime.now()
    due = []
    changed = False
    for item in items:
        if item.get("notified"):
            continue
        try:
            dt = datetime.strptime(item.get("when"), "%Y-%m-%d %H:%M:%S")
            if dt <= now:
                due.append(item)
                item["notified"] = True
                changed = True
        except Exception:
            continue
    if changed:
        save_schedules(items)
    return due


def safe_open_path(path_text: str):
    path = Path(path_text).expanduser()
    if not path.exists():
        return False, f"경로를 찾지 못했어: {path}"
    os.startfile(str(path))
    return True, f"열었어: {path}"


ALLOWED_APPS = {
    "메모장": "notepad.exe",
    "계산기": "calc.exe",
    "그림판": "mspaint.exe",
    "탐색기": "explorer.exe",
}

ALLOWED_SITES = {
    "유튜브": "https://www.youtube.com",
    "구글": "https://www.google.com",
    "네이버": "https://www.naver.com",
    "깃허브": "https://github.com",
    "챗지피티": "https://chatgpt.com",
}


def open_app_or_site_from_message(message: str):
    for name, cmd in ALLOWED_APPS.items():
        if name in message and any(k in message for k in ["열어", "켜", "실행"]):
            subprocess.Popen(cmd, shell=True)
            return True, f"{name} 열었어."
    for name, url in ALLOWED_SITES.items():
        if name in message and any(k in message for k in ["열어", "켜", "접속"]):
            webbrowser.open(url)
            return True, f"{name} 열었어."
    return False, ""


def load_workflows():
    data = load_json(WORKFLOW_FILE, {})
    return data if isinstance(data, dict) else {}


def save_workflows(data):
    save_json(WORKFLOW_FILE, data)


def run_workflow(name: str):
    workflows = load_workflows()
    wf = workflows.get(name)
    if not wf:
        return False, f"'{name}' 워크플로우를 찾지 못했어."
    results = []
    for step in wf.get("steps", []):
        action = step.get("action")
        value = step.get("value", "")
        try:
            if action == "open_url":
                webbrowser.open(value)
                results.append(f"URL 열기: {value}")
            elif action == "open_app":
                cmd = ALLOWED_APPS.get(value, value)
                subprocess.Popen(cmd, shell=True)
                results.append(f"앱 실행: {value}")
            elif action == "open_path":
                ok, msg = safe_open_path(value)
                results.append(msg)
            else:
                results.append(f"알 수 없는 단계: {action}")
        except Exception as e:
            results.append(f"실패: {action} / {e}")
    return True, "\n".join(results)

# =========================================================
# 명령 처리
# =========================================================
def handle_builtin_command(user_message: str):
    msg = normalize_text(user_message)

    # 한밭대 포털 로그인
    if any(x in msg.lower() for x in ["한밭대", "hanbat", "포털", "portal"]):
        if any(x in msg for x in ["로그인", "로그인해줘", "들어가", "접속"]):
            ok, out = login_site("hanbat_portal", headed=True)
            return out

    # 한밭대 LMS 로그인/열기
    if any(x in msg.lower() for x in ["lms", "엘엠에스", "이클래스", "eclass", "한밭대 lms"]):
        if any(x in msg for x in ["로그인", "로그인해줘", "들어가", "접속", "열어", "켜", "보여줘"]):
            try:
                from luna_server_web import open_luna_chrome
                ok, out = open_luna_chrome("https://eclass.hanbat.ac.kr/")
                return out
            except Exception as e:
                return f"LMS 열기 실패: {e}"


    # 기능 소개
    if any(x in msg for x in ["뭐 할 수", "기능", "할 수 있어", "소개해"]):
        return (
            "나는 음성 대화, 채팅, 기억, 실시간 검색, 할 일 관리, 일정 기록, "
            "파일/폴더 열기, 메모장·계산기 같은 PC 앱 실행, 웹사이트 열기, "
            "그리고 작업 플로우 실행을 도와줄 수 있어."
        )

    # 할 일
    if "할 일 추가" in msg:
        text = msg.split("할 일 추가", 1)[-1].strip()
        item = add_todo(text)
        return f"할 일에 추가했어: {item['text']}" if item else "추가할 내용을 못 찾았어."

    if any(x in msg for x in ["할 일 목록", "할일 목록", "해야 할 일", "할 일 보여"]):
        todos = load_todos()
        active = [t for t in todos if not t.get("done")]
        if not active:
            return "지금 남아있는 할 일은 없어."
        return "남은 할 일이야:\n" + "\n".join(f"- {t['text']}" for t in active[:20])

    if any(x in msg for x in ["할 일 완료", "할일 완료"]):
        keyword = msg.replace("할 일 완료", "").replace("할일 완료", "").strip()
        count = complete_todo(keyword)
        return f"{count}개 완료 처리했어." if count else "완료할 할 일을 못 찾았어."

    # 일정/알림
    schedule_keywords = [
        "알림 등록", "알림 추가", "알람 등록", "알람 추가",
        "일정 추가", "일정 등록", "리마인드", "리마인더",
        "분 뒤", "분 후", "초 뒤", "초 후", "시간 뒤", "시간 후",
    ]
    if any(x in msg for x in schedule_keywords):
        parsed_when = parse_schedule_from_message(msg)
        if parsed_when:
            item = add_schedule(msg, parsed_when)
            if item:
                return f"알림으로 저장했어. 시간은 {item['when']} 이야."
        return "알림 시간을 잘 못 알아들었어. 예를 들면 '1분 뒤 알림 등록' 또는 '내일 오후 7시에 알림 등록'처럼 말해줘."

    if any(x in msg for x in ["알림 확인", "일정 확인", "알림 목록", "일정 목록"]):
        items = load_schedules()
        if not items:
            return "저장된 일정이나 알림이 없어."
        upcoming = [i for i in items if not i.get("notified")]
        if not upcoming:
            return "앞으로 남은 알림은 없어."
        return "남은 알림이야:\n" + "\n".join(f"- {i['when']} / {i['text']}" for i in upcoming[:20])

    # 파일/폴더 열기: "경로 열어 D:\\ai" 또는 "D:\\ai 열어"
    if "경로 열어" in msg:
        p = msg.split("경로 열어", 1)[-1].strip()
        ok, out = safe_open_path(p)
        return out

    # 앱/사이트 열기
    ok, out = open_app_or_site_from_message(msg)
    if ok:
        return out

    # 워크플로우 실행
    if "워크플로우 실행" in msg:
        name = msg.split("워크플로우 실행", 1)[-1].strip()
        ok, out = run_workflow(name)
        return out

    return None

# =========================================================
# 라우트
# =========================================================
@app.get("/")
def serve_index():
    static_index = STATIC_DIR / "index.html"
    if static_index.exists():
        return FileResponse(str(static_index))
    return {"ok": True, "message": "루나 서버 실행 중"}

@app.get("/mobile")
def mobile():
    mobile_file = BASE_DIR / "mobile.html"
    if mobile_file.exists():
        return FileResponse(str(mobile_file))
    static_index = STATIC_DIR / "index.html"
    if static_index.exists():
        return FileResponse(str(static_index))
    return {"ok": True, "message": "루나 모바일 페이지 파일이 없어."}

@app.get("/health")
def health():
    return {"ok": True, "status": "running", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

@app.post("/chat")
def chat(request: ChatRequest):
    user_message = normalize_text(request.message)
    if not user_message:
        return {"reply": "뭐라고 말할지 입력해줘.", "used_web_search": False, "search_count": 0}

    try:
        # 0. 내장 명령 먼저 처리
        builtin_reply = handle_builtin_command(user_message)
        if builtin_reply:
            append_recent_turn(user_message, builtin_reply)
            auto_learn_from_turn(user_message, builtin_reply)
            return {"reply": builtin_reply, "used_web_search": False, "search_count": 0}

        # 1. 기억 검색
        memory_items = search_memories(user_message, max_items=12)
        memory_context = "\n".join(
            f"- ({item.get('memory_type','')}) {item.get('content','')}"
            for item in memory_items
        )

        recent_turns = load_recent_turns(max_items=12)
        recent_context = "\n".join(
            f"사용자: {t.get('user','')}\n루나: {t.get('reply','')}" for t in recent_turns
        )

        # 2. 웹 검색
        search_results = []
        search_context = ""
        force_search_keywords = ["오늘", "지금", "최신", "실시간", "뉴스", "날씨", "가격", "검색", "확인"]
        try:
            need_search = needs_web_search(user_message) or any(k in user_message for k in force_search_keywords)
        except Exception:
            need_search = any(k in user_message for k in force_search_keywords)

        if need_search:
            try:
                search_results = web_search(user_message, max_items=5) or []
                search_context = build_search_context(search_results) if search_results else ""
                memory_text = summarize_search_results_for_memory(user_message, search_results) if search_results else ""
                if memory_text:
                    append_memory(memory_text, source="web", pinned=False, importance=60, memory_type="web_knowledge")
            except Exception as e:
                search_context = f"웹 검색 중 오류가 있었어: {e}"

        # 3. 시스템 프롬프트
        goals = get_active_goals()
        goal_text = "\n".join(f"- {g.get('content','')} ({g.get('progress',0)}%)" for g in goals) if goals else "없음"

        system_prompt = f"""
        너는 '루나'라는 개인 AI 비서이자, 광민의 AI 프로젝트 파트너야.

        [루나의 정체성]
        - 이름은 루나.
        - 광민이 만들고 있는 개인 AI 비서/캐릭터 프로젝트의 핵심 인격이야.
        - 단순 챗봇이 아니라, 광민의 작업을 이어서 도와주는 조용하고 믿음직한 파트너야.

        [성격]
        - 차분하고 다정해.
        - 너무 들뜨지 않고 안정적이야.
        - 광민이 막히거나 불안해하면 먼저 정리해주고 안심시켜.
        - 칭찬은 자연스럽게 하되 과하게 하지 않아.
        - 장난스러운 말투보다는 부드럽고 현실적인 말투를 써.

        [말투]
        - 한국어로 답해.
        - 문장은 짧게 끊어.
        - 핵심부터 말해.
        - 설명이 필요하면 단계별로 말해.
        - 코드나 설정을 줄 때는 복붙하기 쉽게 줘.
        - 답변 앞에 '루나:'를 붙이지 마.
        - 이모티콘은 거의 쓰지 마.
        - 광민 이름은 꼭 필요할 때만 자연스럽게 불러.

        [광민을 돕는 방식]
        - 광민은 Unity + Python 기반 음성 AI 캐릭터 '루나'를 만들고 있어.
        - 광민은 완성본 코드, 단계별 가이드, 꼬이지 않는 순서를 선호해.
        - 광민이 “다음은?”, “뭐 해야 해?”라고 물으면 현재 진행 단계 기준으로 바로 다음 행동을 말해.
        - 광민이 파일을 보내면 기존 구조를 최대한 유지하고 필요한 부분만 수정해.
        - 모르면 추측하지 말고, 필요한 파일이나 에러 로그를 정확히 말해.
        - 이미 안 쓰기로 한 파일이나 방식은 다시 제안하지 마.

        [현재 큰 진행 순서]
        1단계: 서버/폰/PWA/알림 연결 안정화.
        2단계: 루나 성격/기억 강화.
        3단계: 웹 로그인 자동화 + 과제 사이트 확인.
        4단계: 알림/일정/과제 확인 자동화 고도화.
        5단계: Unity/3D 표정·감정 시스템 연결.

        [중요한 현재 상태]
        - luna_realtime.py는 사용하지 않기로 했다.
        - 현재 핵심 서버 파일은 main.py다.
        - 현재 PC 채팅창은 luna_chat_window.py를 사용한다.
        - 기억 저장은 data/memory.json을 사용한다.
        - 최근 대화는 data/recent_turns.json을 사용한다.
        - 음성 클라이언트는 별도 파일 luna_voice_client.py 쪽으로 분리되어 있다.
        - 종료 명령은 채팅과 음성이 같이 꺼지는 방향을 유지해야 한다.

        [사용자 기억]
        {memory_context if memory_context else '관련 기억 없음'}

        [기억 사용 규칙]
        - 위 기억은 광민에 대한 장기 기억이야.
        - 관련 있는 질문에서만 자연스럽게 사용해.
        - “이전에”, “아까”, “지난번”, “어디까지”, “다음 단계” 같은 말이 나오면 기억과 최근 대화를 적극 참고해.
        - 기억 내용을 매번 티내지 마.
        - 틀릴 가능성이 있으면 “내가 기억하기로는”처럼 조심스럽게 말해.
        - 새로 중요한 정보가 나오면 저장될 수 있도록 답변을 구성해.

        [최근 대화]
        {recent_context if recent_context else '최근 대화 없음'}

        [현재 목표]
        {goal_text}

        [웹 정보]
        {search_context if search_context else '없음'}

        [답변 규칙]
        - 가장 먼저 결론을 말해.
        - 그다음 필요한 단계만 짧게 제시해.
        - 한 번에 너무 많은 선택지를 주지 마.
        - 지금 당장 해야 할 작업을 우선시해.
        - 코드 수정 요청이면 전체 코드 또는 교체 블록을 명확히 줘.
        - 사용자가 초보자처럼 보이면 버튼 위치, 파일명, 붙여넣을 위치까지 쉽게 말해.
        - 사용자가 이미 알고 있는 설명은 반복하지 마.
        - 오류 메시지가 있으면 원인 → 해결 순서로 말해.
        - 최신 정보가 필요한 질문이면 웹 정보가 있을 때만 확신해서 말해.
        """

        # 목표 자동 저장
        if any(x in user_message for x in ["할거야", "만들거야", "목표", "계획"]):
            try:
                add_goal(user_message)
            except Exception:
                pass

        # 4. 답변 생성
        client = get_openai_client()
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )

        reply = ""
        if hasattr(response, "output_text") and response.output_text:
            reply = response.output_text.strip()
        elif hasattr(response, "output"):
            try:
                reply = response.output[0].content[0].text.strip()
            except Exception:
                reply = ""

        bad_prefixes = [
            "루나,", "루나야,", "루나:", "Luna:",
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
            reply = "음, 지금 답변을 잘 못 만들었어. 다시 말해줄래?"

        # 5. 자동 학습 + 최근 대화 저장 + 정리
        auto_learn_from_turn(user_message, reply)
        append_recent_turn(user_message, reply)
        try:
            clean_memories()
        except Exception:
            pass

        return {"reply": reply, "used_web_search": bool(search_results), "search_count": len(search_results)}

    except Exception as e:
        return {"reply": f"오류 발생: {str(e)}", "used_web_search": False, "search_count": 0}

# =========================================================
# 메모리 API
# =========================================================
@app.post("/memory/save")
def memory_save(request: MemorySaveRequest):
    text = normalize_text(request.text)
    if not text:
        return {"ok": False, "message": "빈 기억은 저장하지 않았어."}
    if is_low_quality_memory(text):
        return {"ok": True, "message": "저장할 만한 내용이 아니라 건너뛰었어.", "skipped": True}

    importance = request.importance
    pinned = request.pinned
    memory_type = request.memory_type
    if any(word in text for word in ["기억해", "기억해줘", "잊지마", "저장해", "내 이름", "내가 좋아하는"]):
        importance = max(importance, 80)
        pinned = True
        memory_type = "user_profile"

    item = append_memory(text, request.source, pinned, importance, memory_type)
    if item is None:
        return {"ok": True, "message": "이미 있거나 저장하지 않아도 되는 기억이야.", "duplicate": True}
    return {"ok": True, "message": "기억 저장 완료", "item": item}

@app.get("/memory/load")
def memory_load():
    return {"ok": True, "items": load_memories()}

@app.post("/memory/add")
def memory_add(request: MemoryAddRequest):
    item = append_memory(request.content, request.source, request.pinned, request.importance, request.memory_type)
    if item is None:
        return {"ok": False, "message": "빈 기억이거나 이미 있는 기억이야."}
    return {"ok": True, "message": "기억 저장 완료", "item": item}

@app.post("/memory/search")
def memory_search(request: MemorySearchRequest):
    return {"ok": True, "items": search_memories(request.query, request.max_items)}

@app.post("/memory/clean")
def memory_clean():
    result = clean_memories()
    return {"ok": True, "message": "메모리 정리 완료", "result": result}

@app.post("/memory/delete")
def memory_delete(request: MemoryDeleteRequest):
    memories = load_memories()
    keyword = normalize_text(request.keyword).lower()
    if not keyword:
        return {"ok": False, "message": "삭제할 키워드가 비어 있어."}
    new_memories = [item for item in memories if keyword not in str(item.get("content", "")).lower()]
    removed_count = len(memories) - len(new_memories)
    save_memories(new_memories)
    return {"ok": True, "message": f"{removed_count}개 삭제했어.", "removed_count": removed_count}

# =========================================================
# 할 일 / 일정 / 파일 / 워크플로우 API
# =========================================================
@app.post("/todo/add")
def todo_add(request: TodoRequest):
    item = add_todo(request.text)
    return {"ok": bool(item), "item": item}

@app.get("/todo/list")
def todo_list():
    return {"ok": True, "items": load_todos()}

@app.post("/todo/complete")
def todo_complete(request: TodoRequest):
    count = complete_todo(request.text)
    return {"ok": True, "completed": count}

@app.post("/schedule/add")
def schedule_add(request: ScheduleRequest):
    item = add_schedule(request.text, request.when)
    return {"ok": bool(item), "item": item, "message": "시간을 이해하지 못했어." if not item else "일정 저장 완료"}

@app.get("/schedule/list")
def schedule_list():
    return {"ok": True, "items": load_schedules()}

@app.get("/schedule/due")
def schedule_due():
    return {"ok": True, "items": due_schedules()}

@app.post("/file/open")
def file_open(request: FileOpenRequest):
    ok, msg = safe_open_path(request.path)
    return {"ok": ok, "message": msg}

@app.post("/workflow/save")
def workflow_save(request: WorkflowRequest):
    workflows = load_workflows()
    workflows[request.name] = {"name": request.name, "steps": request.steps, "timestamp": now_ts()}
    save_workflows(workflows)
    return {"ok": True, "message": f"{request.name} 워크플로우 저장 완료"}

@app.post("/workflow/run")
def workflow_run(request: WorkflowRunRequest):
    ok, msg = run_workflow(request.name)
    return {"ok": ok, "message": msg}

@app.get("/workflow/list")
def workflow_list():
    return {"ok": True, "items": load_workflows()}

# =========================================================
# 웹/계정 자동화 API
# =========================================================
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
    ok, msg = open_site_with_saved_login(request.site_key, target_url=request.target_url, headed=request.headed)
    return {"ok": ok, "message": msg}

@app.post("/web/click")
def web_click(request: WebClickRequest):
    ok, msg = click_by_text(request.site_key, text=request.text, target_url=request.target_url, headed=request.headed)
    return {"ok": ok, "message": msg}

# =========================================================
# 검색 테스트 API
# =========================================================
@app.get("/search/live")
def search_live(q: str):
    try:
        results = web_search(q, max_items=5)
        return {"ok": True, "query": q, "results": results, "context": build_search_context(results)}
    except Exception as e:
        return {"ok": False, "message": str(e), "results": []}

@app.post("/knowledge/refine")
def knowledge_refine():
    try:
        from luna_knowledge_refiner import refine_memories
        result = refine_memories()
        return result
    except Exception as e:
        return {"ok": False, "message": str(e)}

