import requests
import json
import re

def save_featuremaps():
    post_url = "http://127.0.0.1:8000/api/inside/"
    get_url = "http://127.0.0.1:8000/api/inside/"

    # POST (이미지 업로드)
    files = {
        "num_image": open(
            r"C:\Users\user\OneDrive\Pictures\Screenshots\스크린샷 2025-09-23 000452.png", 
            "rb"
        )
    }
    requests.post(post_url, files=files)

    # GET (결과 가져오기)
    get_res = requests.get(get_url)
    if get_res.status_code == 200:
        data = get_res.json()
        
        # 1. JSON 문자열 변환 (들여쓰기 유지)
        json_str = json.dumps(data, ensure_ascii=False, indent=2)

        # 2. 리스트 안에서 줄바꿈 제거 (정규식 후처리)
        json_str = re.sub(r'\[\s+([\d,\s]+)\s+\]', lambda m: "[" + " ".join(m.group(1).split()) + "]", json_str)

        # 3. 저장
        with open("output.json", "w", encoding="utf-8") as f:
            f.write(json_str)

        print("✅ output.json 저장 완료 (행렬 가로 정렬)")
    else:
        print("❌ GET 실패:", get_res.status_code)

if __name__ == "__main__":
    save_featuremaps()
