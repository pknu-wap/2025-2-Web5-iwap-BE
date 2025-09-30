from locust import HttpUser, task, between
import random
import os

class MyApiUser(HttpUser):
    # 가상 유저가 요청 사이에 1초에서 5초 사이의 랜덤한 시간을 기다립니다.
    wait_time = between(1, 5)
    
    # 이 클래스의 host 속성은 locust 실행 시 --host 옵션으로 덮어쓸 수 있습니다.
    # host = "http://127.0.0.1:8000"
    
    def on_start(self):
        """각 가상 유저가 시작될 때 이미지 파일 목록을 로드합니다."""
        images_dir = "test/images"
        self.image_files = [f for f in os.listdir(images_dir) if f.endswith('.png')]
        if not self.image_files:
            print("test/images 디렉토리에 이미지 파일이 없습니다.")

    @task # @task 데코레이터로 이 함수가 테스트 작업임을 명시
    def get_features(self):
        if hasattr(self, 'image_files') and self.image_files:
            # 랜덤 이미지 선택
            selected_image = random.choice(self.image_files)
            image_path = os.path.join("test/images", selected_image)
            
            try:
                # 이미지 파일을 포함한 POST 요청
                with open(image_path, 'rb') as image_file:
                    files = {'num_image': (selected_image, image_file, 'image/png')}
                    self.client.post("/api/inside/", files=files)
            except FileNotFoundError:
                print(f"파일을 찾을 수 없습니다: {image_path}")
        else:
            # 이미지 파일이 없으면 기본 POST 요청
            self.client.post("/api/inside/")

    # @task(3) 처럼 가중치를 주어 다른 작업보다 3배 더 자주 실행하게 할 수도 있습니다.
    # @task(3)
    # def get_another_endpoint(self):
    #     self.client.get("/another-endpoint")