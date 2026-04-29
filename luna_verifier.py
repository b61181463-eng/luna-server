from openai import OpenAI

VERIFY_MODEL = "gpt-4.1-mini"


def should_verify(user_message: str, reply: str) -> bool:
    user_message = (user_message or "").strip()
    reply = (reply or "").strip()

    if not user_message or not reply:
        return False

    # 너무 짧은 일상 답변은 검증하지 않음
    if len(reply) < 80:
        return False

    verify_keywords = [
        "왜", "원인", "설명", "분석", "비교", "검증", "정확", "논문", "연구",
        "공식", "개념", "오류", "해결", "코드", "서버", "화학", "물리", "수학",
        "교수", "박사", "깊게", "자세히", "근거"
    ]

    if any(k in user_message for k in verify_keywords):
        return True

    # 길고 정보성 답변이면 검증
    return len(reply) >= 300


def verify_and_rewrite(user_message: str, draft_reply: str, context: str = "") -> str:
    """답변을 검증하고 필요하면 더 정확한 답변으로 재작성한다.
    실패해도 원래 답변을 반환한다.
    """
    try:
        if not should_verify(user_message, draft_reply):
            return draft_reply

        client = OpenAI()

        system_prompt = """
너는 루나의 고급 검증 모듈이다.
역할은 초안 답변을 그대로 믿지 않고, 사실성/논리성/과장/누락을 점검한 뒤 더 좋은 최종 답변으로 고치는 것이다.

검증 원칙:
- 제공된 사용자 질문, 초안 답변, 참고 맥락만 기준으로 판단한다.
- 모르는 내용은 확실한 것처럼 단정하지 않는다.
- 틀릴 수 있는 부분은 완곡하게 수정한다.
- 사용자가 초보자일 가능성이 있으면 더 명확하게 설명한다.
- 불필요하게 길게 늘리지 않는다.
- 최종 답변만 출력한다. 내부 검증 과정, 점수, 체크리스트는 출력하지 않는다.
- 단, 불확실성이 실제로 중요하면 "주의:" 문장으로 짧게 알려준다.
"""

        user_prompt = f"""
[사용자 질문]
{user_message}

[참고 맥락]
{context if context else '없음'}

[초안 답변]
{draft_reply}

위 초안 답변을 검증하고, 필요하면 정확하고 자연스러운 최종 답변으로 재작성해줘.
최종 답변만 출력해.
"""

        response = client.responses.create(
            model=VERIFY_MODEL,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        final = ""
        if hasattr(response, "output_text") and response.output_text:
            final = response.output_text.strip()
        elif hasattr(response, "output"):
            try:
                final = response.output[0].content[0].text.strip()
            except Exception:
                final = ""

        return final or draft_reply

    except Exception as e:
        print("[verify_and_rewrite 오류]", e)
        return draft_reply
