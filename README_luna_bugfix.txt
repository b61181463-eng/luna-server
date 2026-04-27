루나 긴급 버그 수정 패키지

수정 내용:
1. main.py의 parse_schedule_from_message 미정의 오류 수정
2. /health 서버 확인 API 추가
3. 채팅창 기본 서버 주소를 로컬 http://127.0.0.1:8000 으로 수정
4. 채팅 입력창이 안 보이는 문제를 줄이기 위해 창 크기/리사이즈 수정

교체 위치:
main_luna_full_assistant_bugfix.py -> D:\ai\luna_server\main.py
luna_chat_window_bugfix.py -> D:\ai\luna_chat_window.py

교체 후:
cd /d D:\ai\luna_server
uvicorn main:app --host 127.0.0.1 --port 8000

그 다음 런처 실행.
