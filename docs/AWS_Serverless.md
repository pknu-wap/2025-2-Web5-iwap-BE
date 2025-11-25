# AWS 비동기 서버 아키텍처

## 기술 스택

<div align="center">
<img src="https://img.shields.io/badge/docker-2496ED?style=for-the-badge&logo=docker&logoColor=white">
<img src="https://img.shields.io/badge/python-3776AB?style=for-the-badge&logo=python&logoColor=white">
<img src="https://img.shields.io/badge/ffmpeg-007808?style=for-the-badge&logo=ffmpeg&logoColor=white">
<img src="https://img.shields.io/badge/pytorch-EE4C2C?style=for-the-badge&logo=pytorch&logoColor=white">
</div>


## 사용한 서비스

<div>
<table>
<tr>
<img width="80" height="80" alt="Arch_AWS-Lambda_64" src="https://github.com/user-attachments/assets/e588776b-d499-4ff1-b408-69d1f6230af2" />
</tr>
<tr>
<img width="80" height="80" alt="Arch_Amazon-Elastic-Container-Registry_64" src="https://github.com/user-attachments/assets/5aa3be2c-c7ff-4d14-993b-3a1944e6b574" />
</tr>
<tr>
<img width="80" height="80" alt="Arch_Amazon-Simple-Storage-Service_64" src="https://github.com/user-attachments/assets/c1c935a5-5667-4d88-bff8-260295d84d9e" />
</tr>
<tr>
<img width="80" height="80" alt="Arch_Amazon-Simple-Queue-Service_64" src="https://github.com/user-attachments/assets/65c0cffa-4bef-46cc-93d8-10c74d957ac7" />
</tr>
<tr>
<img width="80" height="80" alt="Arch_Amazon-API-Gateway_64" src="https://github.com/user-attachments/assets/3755ceb2-067a-47ef-b402-324492688009" />
</tr>
</table>
</div>

## 아키텍처

<img width="1527" height="1234" alt="AWS Asynchronous Serverless Architecture ap-northeast-2 (2)" src="https://github.com/user-attachments/assets/3c7fe155-a90a-46a9-8fda-f6e242d2f656" />


## <a href="https://github.com/pknu-wap/2025-2-Web5-iwap-BE/issues/43">AWS 비동기 API 명세서</a>

## WorkFlow

### 1. Client -> API Gateway POST 요청

- Preprocessing Lambda에 요청 데이터 전송

### 2. API Gateway -> Preprocessing Lambda -> SQS

- 요청된 엔드포인트에 따라 Worker 람다에 연결된 SQS에 `task_id` 메시지 큐잉
  - string의 경우, `task_id` 외에 각종 파라미터도 함께 포함해 큐잉
- 본문에 포함된 파일은 S3에 저장
- 오디오의 경우 webm, wav -> mp3 변환 적용
- Client에게 `202 Accpeted` + `{"task_id":"..."}`를 응답

### 3. SQS -> Worker Lambda (Container from ECR)

- SQS에 연결된 Worker Lambda를 실행
- S3에 업로드된 원본 파일을 다운받아 모델 수행을 위해 사용
- inside: 추론된 결과 JSON 파일을 GZip 압축해서 S3에 업로드
- piano: 추론된 결과 MIDI 파일과 MP3 파일을 S3에 업로드
- string: 추론된 결과 JSON 파일과 이미지 파일을 S3에 업로드
- 참고: 모델은 컨테이너 로딩 시 메모리에 적재(Warm Start)됨.
  단, 프로비저닝이 적용되지 않아 Cold Start 문제가 있으며, 초기 설정 10초 초과시 실패하는 문제가 있음 (SQS 연동으로 실패해도 특정 시간 이후 재시도)

### 4. Client -> API Gateway GET 요청 (결과 조회)

- client는 `task_id`를 사용해 주기적으로 `GET` 요청을 보냄
  - 파일이 없는 경우 `202`, `{"status":"PENDING"}` 응답
  - 파일이 있는 경우 `200`, 결과값 응답
