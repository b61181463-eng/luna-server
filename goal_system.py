import json
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
GOAL_FILE = BASE_DIR / "data" / "goals.json"


def load_goals():
    if not GOAL_FILE.exists():
        return []
    try:
        with open(GOAL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []


def save_goals(goals):
    with open(GOAL_FILE, "w", encoding="utf-8") as f:
        json.dump(goals, f, ensure_ascii=False, indent=2)


def add_goal(text):
    goals = load_goals()
    goal = {
        "content": text,
        "status": "active",
        "progress": 0,
        "created_at": time.time(),
    }
    goals.append(goal)
    save_goals(goals)
    return goal


def get_active_goals():
    goals = load_goals()
    return [g for g in goals if g["status"] == "active"]


def update_goal_progress(keyword, progress):
    goals = load_goals()
    for g in goals:
        if keyword in g["content"]:
            g["progress"] = progress
    save_goals(goals)


def complete_goal(keyword):
    goals = load_goals()
    for g in goals:
        if keyword in g["content"]:
            g["status"] = "done"
    save_goals(goals)