import requests
import json
import re
import sys
import io

# Windows 콘솔에서 유니코드 출력을 위한 설정
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def save_featuremaps(image_path: str = None):
    """Feature map을 저장하는 함수"""
    post_url = "http://127.0.0.1:8000/api/inside/"
    get_url = "http://127.0.0.1:8000/api/inside/"
    
    # 기본 이미지 경로 설정
    if image_path is None:
        image_path = r"C:\Users\user\Desktop\!WAP\images.png"

    try:
        # POST (이미지 업로드) - with 문으로 파일 자동 닫기
        with open(image_path, "rb") as image_file:
            files = {"num_image": image_file}
            post_res = requests.post(post_url, files=files)
            
            if post_res.status_code != 200:
                print(f"[ERROR] POST 실패: {post_res.status_code}")
                return

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

            print("[SUCCESS] output.json 저장 완료 (행렬 가로 정렬)")
        else:
            print(f"[ERROR] GET 실패: {get_res.status_code}")
            
    except FileNotFoundError:
        print(f"[ERROR] 이미지 파일을 찾을 수 없습니다: {image_path}")
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] 네트워크 오류: {e}")
    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON 파싱 오류: {e}")
    except Exception as e:
        print(f"[ERROR] 예상치 못한 오류: {e}")

if __name__ == "__main__":
    save_featuremaps()
