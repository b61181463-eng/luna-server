import json
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

GOAL_FILE = DATA_DIR / "goals.json"


def load_goals():
    if not GOAL_FILE.exists():
        return []

    try:
        with open(GOAL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            return data

        return []
    except Exception:
        return []


def save_goals(goals):
    if goals is None:
        goals = []

    with open(GOAL_FILE, "w", encoding="utf-8") as f:
        json.dump(goals, f, ensure_ascii=False, indent=2)


def add_goal(content: str):
    goals = load_goals()

    content = str(content).strip()
    if not content:
        return {"ok": False, "message": "빈 목표는 저장하지 않았어."}

    new_goal = {
        "content": content,
        "progress": 0,
        "status": "active",
        "created_at": time.time(),
        "updated_at": time.time(),
    }

    goals.append(new_goal)
    save_goals(goals)

    return {"ok": True, "goal": new_goal}


def get_active_goals():
    goals = load_goals()

    active_goals = []
    for goal in goals:
        if goal.get("status", "active") == "active":
            active_goals.append(goal)

    return active_goals


def update_goal_progress(content: str, progress: int):
    goals = load_goals()

    for goal in goals:
        if content in goal.get("content", ""):
            goal["progress"] = max(0, min(100, int(progress)))
            goal["updated_at"] = time.time()

            if goal["progress"] >= 100:
                goal["status"] = "done"

    save_goals(goals)
    return {"ok": True}


def delete_goal(keyword: str):
    goals = load_goals()

    keyword = str(keyword).strip()
    if not keyword:
        return {"ok": False, "removed_count": 0}

    new_goals = [
        goal for goal in goals
        if keyword not in goal.get("content", "")
    ]

    removed_count = len(goals) - len(new_goals)
    save_goals(new_goals)

    return {"ok": True, "removed_count": removed_count}