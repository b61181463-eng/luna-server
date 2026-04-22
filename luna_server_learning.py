from openai import OpenAI
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def extract_memory_candidates(user_text: str, assistant_reply: str) -> list[str]:
    """
    대화에서 장기 기억 후보를 0~3개 뽑는다.
    """
    try:
        response = client.responses.create(
            model="gpt-5.4-mini",
            input=[
                {
                    "role": "system",
                    "content": (
                        "너는 대화에서 장기적으로 기억할 만한 정보만 추출하는 시스템이야. "
                        "출력은 최대 3줄. "
                        "정말 중요하거나 반복 활용 가치가 있는 사실만 뽑아. "
                        "사소한 인사, 일회성 감탄, 즉시성만 있는 정보는 제외해. "
                        "각 줄은 짧고 명확한 한국어 문장으로 출력해."
                    )
                },
                {
                    "role": "user",
                    "content": f"사용자 말: {user_text}\n루나 답변: {assistant_reply}"
                }
            ]
        )

        text = response.output_text.strip()
        if not text:
            return []

        lines = [line.strip("-• ").strip() for line in text.splitlines() if line.strip()]
        return lines[:3]

    except Exception:
        return []


def score_memory_importance(memory_text: str) -> int:
    """
    기억 중요도 0~100 점수
    """
    try:
        response = client.responses.create(
            model="gpt-5.4-mini",
            input=[
                {
                    "role": "system",
                    "content": (
                        "주어진 기억 문장의 장기 중요도를 0부터 100 사이 정수 하나로만 출력해. "
                        "사용자 취향, 프로젝트, 반복 활용 정보, 개인 선호는 높게. "
                        "일회성, 잡담, 중요도 낮은 말은 낮게."
                    )
                },
                {
                    "role": "user",
                    "content": memory_text
                }
            ]
        )

        raw = response.output_text.strip()
        score = int("".join(ch for ch in raw if ch.isdigit()) or "0")
        return max(0, min(100, score))

    except Exception:
        return 50


def reflect_on_reply(user_text: str, assistant_reply: str) -> str:
    """
    답변 품질을 짧게 자기 점검
    """
    try:
        response = client.responses.create(
            model="gpt-5.4-mini",
            input=[
                {
                    "role": "system",
                    "content": (
                        "너는 AI 답변을 짧게 자기점검하는 시스템이야. "
                        "출력은 한 줄. "
                        "답변이 충분했는지, 더 기억해야 할 포인트가 있는지 짧게 적어."
                    )
                },
                {
                    "role": "user",
                    "content": f"사용자 말: {user_text}\n루나 답변: {assistant_reply}"
                }
            ]
        )

        return response.output_text.strip()

    except Exception:
        return ""


def should_store_memory(memory_text: str, importance: int) -> bool:
    """
    규칙 기반 1차 필터
    """
    if not memory_text.strip():
        return False

    if importance < 55:
        return False

    too_generic = [
        "안녕",
        "고마워",
        "좋아",
        "그래",
        "응",
    ]

    lowered = memory_text.lower()
    if any(x in lowered for x in too_generic) and len(memory_text) < 12:
        return False

    return True