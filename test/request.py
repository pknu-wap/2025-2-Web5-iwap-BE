import requests
import time
import random
import os

API_URL = "http://127.0.0.1:8000/api/inside/" # 테스트할 API 엔드포인트
REQUEST_INTERVAL = 3  # 요청 간격 (초)

def periodic_requester():
    """지정된 간격으로 API에 이미지 파일과 함께 POST 요청을 계속 보냅니다."""
    print(f"'{API_URL}'에 {REQUEST_INTERVAL}초마다 이미지와 함께 요청을 시작합니다.")
    
    # 이미지 파일 목록 가져오기
    images_dir = "test/images"
    image_files = [f for f in os.listdir(images_dir) if f.endswith('.png')]
    
    if not image_files:
        print("test/images 디렉토리에 이미지 파일이 없습니다.")
        return
    
    while True:
        try:
            # 랜덤 이미지 선택
            selected_image = random.choice(image_files)
            image_path = os.path.join(images_dir, selected_image)
            
            start_time = time.time()
            
            # 이미지 파일을 포함한 POST 요청
            with open(image_path, 'rb') as image_file:
                files = {'num_image': (selected_image, image_file, 'image/png')}
                response = requests.post(API_URL, files=files)
            
            end_time = time.time()
            
            response_time = (end_time - start_time) * 1000  # 밀리초(ms) 단위로 변환
            
            print(f"이미지: {selected_image}, 상태 코드: {response.status_code}, 응답 시간: {response_time:.2f}ms")

        except requests.exceptions.RequestException as e:
            print(f"요청 실패: {e}")
        except FileNotFoundError as e:
            print(f"파일을 찾을 수 없습니다: {e}")
        
        time.sleep(REQUEST_INTERVAL)

if __name__ == "__main__":
    periodic_requester()