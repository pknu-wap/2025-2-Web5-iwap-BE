import torch
import torch.nn as nn # 자동 손실, 정확도 계산해주는 라이브러리
import torch.optim as optim # 최적화 알고리즘 라이브러리
from torchvision import datasets, transforms, models
from torch.utils.data import DataLoader
import math
import numpy as np

model = models.resnet18(weights=None)  # 학습용 ResNet18
model.fc = nn.Linear(model.fc.in_features, 10)  # MNIST 클래스 수: 10

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(BASE_DIR, "public", "resnet18_mnist.pth")

state_dict = torch.load(MODEL_PATH, map_location=torch.device("cpu"))
model.load_state_dict(state_dict)


# state_dict = torch.load("resnet18_mnist.pth", map_location=torch.device("cpu"))
# model.load_state_dict(state_dict)
model.eval()    # 모델을 evaluation 모드로 전환

transform = transforms.Compose([
    transforms.Resize(224),                # ResNet18 입력 크기 224x224
    transforms.Grayscale(num_output_channels=3),  # 1채널 → 3채널
    transforms.ToTensor(),
    transforms.Normalize((0.5,), (0.5,)) 
])

train_dataset = datasets.MNIST(root='./data', train=True, download=True, transform=transform)
test_dataset  = datasets.MNIST(root='./data', train=False, download=True, transform=transform)

train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True)
test_loader  = DataLoader(test_dataset, batch_size=1, shuffle=True)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
# device = torch.device("cpu")

model.to(device)


# Conv 레이어 출력 저장용
feature_maps = {}
fc = {}
# hook 함수 정의
def save_feature(name):
    def hook(module, input, output):
        feature_maps[name] = output.detach()
    return hook

def save_fc(name):
    def hook(module, input, output):
        fc[name] = output.detach()
    return hook

# 모델의 모든 Conv2d 레이어에 hook 등록
for name, module in model.named_modules():
    if isinstance(module, torch.nn.Conv2d):
        module.register_forward_hook(save_feature(name))

model.fc.register_forward_hook(save_fc("fc"))

# Forward pass
# images = post에서 받은 이미지
# images = transform(images)
def process_image(pil_image):
    tensor = transform(pil_image).unsqueeze(0)
    _ = model(tensor)
    return get_normalized_outputs()

def normalization(arr):
    arr = arr.cpu().numpy()
    arr_min = arr.min()
    arr_max = arr.max()

    # 0~255 정규화
    normalized = ((arr - arr_min) / (arr_max - arr_min)) * 255
    normalized = normalized.astype(np.uint8) 
    return normalized

def get_normalized_outputs():
    fmap_out = {
        layer_name: normalization(fmap).tolist()
        for layer_name, fmap in feature_maps.items()
    }
    fc_out = {
        layer_name: normalization(fmap).tolist()
        for layer_name, fmap in fc.items()
    }
    return fmap_out, fc_out