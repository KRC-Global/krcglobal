"""
CN_web app.py 포트 5002 패치 스크립트
실행: python 04_CN앱_포트설정_패치.py
"""
import os
import re

script_dir = os.path.dirname(os.path.abspath(__file__))
app_py = os.path.join(script_dir, '..', '..', 'CN_web', 'cn_web', 'app.py')
app_py = os.path.normpath(app_py)

if not os.path.exists(app_py):
    print(f"오류: app.py 파일을 찾을 수 없습니다.")
    print(f"경로: {app_py}")
    print("CN_web/cn_web/app.py 가 존재하는지 확인하세요.")
    input("엔터를 눌러 종료...")
    exit(1)

with open(app_py, 'r', encoding='utf-8') as f:
    content = f.read()

# app.run() 호출을 포트 5002로 변경
new_content = re.sub(
    r'app\.run\([^)]*\)',
    "app.run(host='0.0.0.0', port=5002, debug=False)",
    content
)

if new_content == content:
    # app.run()이 없으면 파일 끝에 추가
    if "if __name__" not in content:
        new_content += "\n\nif __name__ == '__main__':\n    app.run(host='0.0.0.0', port=5002, debug=False)\n"
    else:
        print("app.run() 구문을 찾지 못했습니다. app.py를 직접 확인하세요.")
        print(f"파일 경로: {app_py}")
        input("엔터를 눌러 종료...")
        exit(1)

with open(app_py, 'w', encoding='utf-8') as f:
    f.write(new_content)

print(f"패치 완료: {app_py}")
print("CN_web이 포트 5002로 실행됩니다.")
print("이제 03_CN앱_실행.bat 를 실행하세요.")
input("엔터를 눌러 종료...")
