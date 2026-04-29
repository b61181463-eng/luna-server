import random
from luna_research import learn_from_arxiv

TOPICS = [
    "인공지능",
    "머신러닝",
    "딥러닝",
    "음성 인식",
    "STT",
    "TTS",
    "Unity AI",
    "자연어 처리",
    "강화학습",
]

def autonomous_learning():
    topic = random.choice(TOPICS)
    try:
        result = learn_from_arxiv(topic)
        return f"[자동 학습] {topic} → {result}"
    except Exception as e:
        return f"[자동 학습 실패] {e}"