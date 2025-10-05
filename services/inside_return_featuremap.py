import torch
import torch.nn as nn # 자동 손실, 정확도 계산해주는 라이브러리
import torch.optim as optim # 최적화 알고리즘 라이브러리
from torchvision import transforms, models
import numpy as np
import os
from typing import Optional, Dict, Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(BASE_DIR, "public", "resnet18_mnist.pth")

transform = transforms.Compose([
    transforms.Resize(224),                # ResNet18 입력 크기 224x224
    transforms.Grayscale(num_output_channels=3),  # 1채널 → 3채널
    transforms.ToTensor(),
    transforms.Normalize((0.5,), (0.5,)) 
])

class FeatureMapProcessor:
    def __init__(self):
        self.feature_maps: Dict[str, torch.Tensor] = {}
        self.fc: Dict[str, torch.Tensor] = {}
        self.last_result: Optional[Dict[str, Any]] = None
        self._model: Optional[torch.nn.Module] = None

    def load_model(self):        #모델 로드 후 캐싱
        if self._model is None:
                model = models.resnet18(weights=None)  # 학습용 ResNet18
                model.fc = nn.Linear(model.fc.in_features, 10)  # MNIST 클래스 수: 10

                if not os.path.exists(MODEL_PATH):
                    raise FileNotFoundError(f"모델 파일을 찾을 수 없습니다: {MODEL_PATH}")
                    
                state_dict = torch.load(MODEL_PATH, map_location=torch.device("cpu"))
                model.load_state_dict(state_dict)
                model.eval()    # 모델을 evaluation 모드로 전환

                device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
                model.to(device)
                
                self._model = model
        return self._model

    def register_hooks(self, model: torch.nn.Module):
        def save_feature(name):
            def hook(module, input, output):
                self.feature_maps[name] = output.detach()
            return hook

        def save_fc(name):
            def hook(module, input, output):
                self.fc[name] = output.detach()
            return hook

        for name, module in model.named_modules():
            if isinstance(module, torch.nn.Conv2d):
                module.register_forward_hook(save_feature(name))

        model.fc.register_forward_hook(save_fc("fc"))

    def process_image(self, pil_image, model: torch.nn.Module):
            tensor = transform(pil_image).unsqueeze(0)
            _ = model(tensor)   # forward 실행 → hook으로 feature 저장

    def normalization(self, arr: torch.Tensor):
        arr = arr.cpu().numpy()
        arr_min = arr.min()
        arr_max = arr.max()

        # 0~255 정규화
        normalized = ((arr - arr_min) / (arr_max - arr_min)) * 255
        normalized = normalized.astype(np.uint8) 
        return normalized

    def get_normalized_outputs(self, pil_image=None):
            if pil_image is not None:
                # 이전 결과 초기화
                self.feature_maps.clear()
                self.fc.clear()
                
                model = self.load_model()
                self.register_hooks(model)
                self.process_image(pil_image, model)

                fmap_out = {
                    layer_name: self.normalization(fmap).tolist()
                    for layer_name, fmap in self.feature_maps.items()
                }
                fc_out = {
                    layer_name: self.normalization(fmap).tolist()
                    for layer_name, fmap in self.fc.items()
                }
                self.last_result = {"layers": {**fmap_out, **fc_out}}

            return self.last_result


# 싱글톤 인스턴스 생성
processor = FeatureMapProcessor()

# 기존 함수 인터페이스 유지를 위한 래퍼 함수
def get_normalized_outputs(pil_image=None):
    """기존 인터페이스를 유지하기 위한 래퍼 함수"""
    return processor.get_normalized_outputs(pil_image)
