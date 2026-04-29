from pathlib import Path

MAIN = Path(__file__).resolve().parent / "main.py"

if not MAIN.exists():
    raise FileNotFoundError(f"main.py를 찾지 못했어: {MAIN}")

text = MAIN.read_text(encoding="utf-8")

# 1) import 추가
import_line = "from luna_knowledge import search_knowledge\n"
verify_import = "from luna_verifier import verify_and_rewrite\n"
if verify_import not in text:
    if import_line in text:
        text = text.replace(import_line, import_line + verify_import, 1)
    else:
        text = verify_import + text

# 2) 답변 검증 삽입: bad_prefix 제거 전에 넣기
needle = """        bad_prefixes = [
            \"루나,\", \"루나야,\", \"루나:\", \"Luna:\",
"""
insert = """        # 4-1. 고급 자기검증: 답변을 다시 점검하고 필요하면 재작성
        try:
            verification_context = "\\n\\n".join([
                f"[사용자 기억]\\n{memory_context if memory_context else '없음'}",
                f"[전문 지식 자료]\\n{knowledge_context if knowledge_context else '없음'}",
                f"[웹 정보]\\n{search_context if search_context else '없음'}",
            ])
            reply = verify_and_rewrite(user_message, reply, verification_context)
        except Exception as e:
            print("[verification 오류]", e)

"""

if insert.strip() not in text:
    if needle not in text:
        raise RuntimeError("bad_prefixes 위치를 찾지 못했어. main.py 구조가 예상과 달라.")
    text = text.replace(needle, insert + needle, 1)

MAIN.write_text(text, encoding="utf-8")
print("고급 검증 시스템 패치 완료")
