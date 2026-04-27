루나 폰 푸시 알림 적용 방법

1) 패키지 설치
   cd /d D:\ai\luna_server
   pip install pywebpush cryptography

2) VAPID 키 생성
   python generate_vapid_keys.py

3) 출력된 값을 환경변수에 등록
   Windows 임시 테스트:
   set LUNA_VAPID_PUBLIC_KEY=출력된_PUBLIC_KEY
   set LUNA_VAPID_PRIVATE_KEY=출력된_PRIVATE_KEY
   set LUNA_VAPID_SUBJECT=mailto:본인메일@example.com

   영구 등록:
   setx LUNA_VAPID_PUBLIC_KEY "출력된_PUBLIC_KEY"
   setx LUNA_VAPID_PRIVATE_KEY "출력된_PRIVATE_KEY"
   setx LUNA_VAPID_SUBJECT "mailto:본인메일@example.com"

4) 파일 배치
   main_push_fixed.py      -> D:\ai\luna_server\main.py
   index_push_fixed.html  -> D:\ai\luna_server\static\index.html
   sw.js                 -> D:\ai\luna_server\static\sw.js
   manifest.json         -> D:\ai\luna_server\static\manifest.json
   generate_vapid_keys.py -> D:\ai\luna_server\generate_vapid_keys.py

5) 서버 재시작
   cd /d D:\ai\luna_server
   uvicorn main:app --host 127.0.0.1 --port 8000

6) 폰에서 루나 앱 접속
   - 같은 와이파이면 PC IP로 접속하거나
   - Railway 배포 주소를 사용
   - 홈 화면에 추가
   - 앱 안의 '알림' 버튼 누르기

7) 테스트
   채팅에 입력:
   폰 알림 테스트

주의:
- 로컬 127.0.0.1은 폰에서 PC를 가리키지 않음. 폰에서는 PC의 내부 IP 또는 Railway 주소를 사용해야 함.
- iPhone은 홈 화면에 추가한 웹앱에서 알림 권한을 허용해야 함.
