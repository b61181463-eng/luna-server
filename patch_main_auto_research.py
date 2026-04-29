# -*- coding: utf-8 -*-
"""
main.py 자동 패치 스크립트
사용법:
1) 이 파일과 luna_auto_research.py를 D:\ai\luna_server 에 복사
2) PowerShell/CMD에서:
   cd /d D:\ai\luna_server
   python patch_main_auto_research.py
3) main.py가 자동 백업되고 자동 연구 학습 코드가 삽입됨
"""

from pathlib import Path
import time

MAIN = Path("main.py")
if not MAIN.exists():
    raise SystemExit("main.py를 찾지 못했어. D:\\ai\\luna_server 폴더에서 실행해줘.")

text = MAIN.read_text(encoding="utf-8")
backup = Path(f"main_backup_before_auto_research_{time.strftime('%Y%m%d_%H%M%S')}.py")
backup.write_text(text, encoding="utf-8")

# 1) import 추가
if "from luna_auto_research import" not in text:
    marker = "from openai import OpenAI\n"
    insert = (
        "try:\n"
        "    from luna_knowledge import search_knowledge\n"
        "except Exception:\n"
        "    def search_knowledge(query, max_items=4):\n"
        "        return []\n"
        "try:\n"
        "    from luna_auto_research import learn_from_arxiv, maybe_auto_research\n"
        "except Exception:\n"
        "    def learn_from_arxiv(query, max_results=3):\n"
        "        return {'ok': False, 'message': '자동 연구 모듈을 불러오지 못했어.'}\n"
        "    def maybe_auto_research(query, knowledge_context='', max_results=2):\n"
        "        return {'ok': False, 'skipped': True}\n"
    )
    if marker in text:
        text = text.replace(marker, marker + insert, 1)

# 2) 내장 명령 추가
if "# 자동 연구/논문 학습" not in text:
    marker = "    msg = normalize_text(user_message)\n"
    block = r'''

    # 자동 연구/논문 학습
    if any(k in msg for k in ["논문 학습", "연구 자료 찾아", "자료 학습", "arxiv 학습"]):
        try:
            query = msg
            for k in ["논문 학습", "연구 자료 찾아", "자료 학습", "arxiv 학습", "루나야", "루나"]:
                query = query.replace(k, "")
            query = query.strip()
            if not query:
                return "무슨 주제로 연구 자료를 찾을지 말해줘. 예: '논문 학습 RAG'"
            result = learn_from_arxiv(query, max_results=3)
            return result.get("message", str(result)) if isinstance(result, dict) else str(result)
        except Exception as e:
            return f"논문 학습 실패: {e}"
'''
    if marker in text:
        text = text.replace(marker, marker + block, 1)

# 3) 기억 검색 뒤 knowledge_context 생성 추가
if "auto_research_result = maybe_auto_research" not in text:
    # 케이스 A: 이미 knowledge_items가 없는 기본 main.py
    old = "        memory_items = search_memories(user_message, max_items=8)\n        memory_context = \"\\n\".join(f\"- {item.get('content', '')}\" for item in memory_items)\n"
    new = "        memory_items = search_memories(user_message, max_items=12)\n        memory_context = \"\\n\".join(\n            f\"- ({item.get('memory_type','')}) {item.get('content','')}\"\n            for item in memory_items\n        )\n\n        # 전문 지식 자료 검색 + 부족하면 자동 연구 학습\n        knowledge_items = search_knowledge(user_message, max_items=4)\n        knowledge_context = \"\\n\\n\".join(knowledge_items)\n        auto_research_note = \"\"\n        auto_research_result = maybe_auto_research(user_message, knowledge_context, max_results=2)\n        if isinstance(auto_research_result, dict) and auto_research_result.get('ok'):\n            auto_research_note = auto_research_result.get('message', '')\n            knowledge_items = search_knowledge(user_message, max_items=4)\n            knowledge_context = \"\\n\\n\".join(knowledge_items)\n"
    if old in text:
        text = text.replace(old, new, 1)
    else:
        # 케이스 B: 이미 knowledge_context가 있는 main.py라면 그 아래 자동 연구만 추가
        marker = "        knowledge_context = \"\\n\\n\".join(knowledge_items)\n"
        add = "        auto_research_note = \"\"\n        auto_research_result = maybe_auto_research(user_message, knowledge_context, max_results=2)\n        if isinstance(auto_research_result, dict) and auto_research_result.get('ok'):\n            auto_research_note = auto_research_result.get('message', '')\n            knowledge_items = search_knowledge(user_message, max_items=4)\n            knowledge_context = \"\\n\\n\".join(knowledge_items)\n"
        if marker in text:
            text = text.replace(marker, marker + add, 1)

# 4) 프롬프트에 전문 지식/자동 연구 결과 추가
if "[전문 지식 자료]" not in text:
    marker = "[웹 정보]\n{search_context if search_context else '없음'}\n"
    add = "\n[전문 지식 자료]\n{knowledge_context if knowledge_context else '없음'}\n\n[자동 연구 학습 결과]\n{auto_research_note if auto_research_note else '없음'}\n"
    if marker in text:
        text = text.replace(marker, marker + add, 1)

# 5) API 추가
if "@app.post(\"/research/arxiv\")" not in text:
    api = r'''

# =========================================================
# 자동 연구 학습 API
# =========================================================
@app.post("/research/arxiv")
def research_arxiv(q: str, max_results: int = 3):
    try:
        result = learn_from_arxiv(q, max_results=max_results)
        return result
    except Exception as e:
        return {"ok": False, "message": str(e)}
'''
    text = text.rstrip() + api + "\n"

MAIN.write_text(text, encoding="utf-8")
print("패치 완료")
print(f"백업 파일: {backup.name}")
print("이제 서버/루나를 완전히 재시작해줘.")
