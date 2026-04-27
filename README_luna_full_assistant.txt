# 루나 완성형 확장 패키지

교체 위치:

```text
main_luna_full_assistant_fixed.py
→ D:\ai\luna_server\main.py
```

서버 재시작:

```bat
cd /d D:\ai\luna_server
uvicorn main:app --host 127.0.0.1 --port 8000
```

추가/강화된 기능:

1. 완전 자동 학습
- 사용자가 따로 “기억해줘”라고 말하지 않아도 중요한 정보 자동 저장
- 프로젝트/목표/취향/사용자 정보는 중요도 상승
- 비밀번호/카드번호 같은 민감 정보는 자동 기억에서 제외

2. 파일/폴더 제어
- 안전 폴더 안에서만 목록 보기, 검색, 열기 가능
- 기본 안전 폴더: 서버 폴더, 바탕화면, 문서, 다운로드
- 새 안전 폴더는 `/file/allow-folder`로 등록

3. 웹 자동화 강화
- 기존 `/web/login`, `/web/open`, `/web/click` 유지
- `/web/action/register`로 사이트별 자동 동작 등록
- `/web/action/run`으로 등록 동작 실행

4. 일정/알림
- `/schedule/add`, `/schedule/list`, `/schedule/check-due`
- 알림은 서버가 먼저 말을 거는 방식은 아니고, 루나에게 “알림 확인”이라고 물으면 확인 가능

5. 작업 플로우 자동 실행
- `/workflow/register`로 여러 단계를 하나의 이름으로 등록
- `/workflow/run`으로 실행
- 지원 단계: open_app, open_url, todo_add, schedule_add, web_action, search, memory_add, open_path

채팅 테스트 예시:

```text
루나야 내 프로젝트는 Unity 없이 개인 비서와 자동화 중심으로 갈 거야
루나야 내 프로젝트 방향 기억하고 있어?
루나야 할 일 추가 루나 자동화 테스트하기
루나야 일정 추가 2026-04-30 18:00 루나 테스트
루나야 알림 확인
루나야 폴더 목록 D:\ai
루나야 파일 검색 main D:\ai
루나야 계산기 열어줘
```

주의:
- PC 제어/파일 제어는 안전 폴더와 등록된 앱/사이트 위주로 제한됨.
- 캡차/2FA 우회, 타인 계정 접근 같은 기능은 넣지 않았음.
