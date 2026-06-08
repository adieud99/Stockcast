# 배포 가이드 (W10) — AWS 프리티어 + Terraform + GitHub Actions

## 아키텍처 결정 (왜 이 구조인가)

**단일 EC2 t3.micro에 Docker로 PostgreSQL + 백엔드를 함께 운영한다.**

- **비용 0**: 프리티어 EC2 1대만 사용. RDS·로드밸런서 등 추가 과금 요소 배제.
- **배포 안정성**: 로컬에서 쓰던 `docker compose`를 그대로 EC2에서 실행 → "로컬에선 됐는데 서버에선 안 됨" 문제 제거.
- **확장 과제**: 트래픽이 커지면 DB를 RDS(db.t3.micro)로 분리하고 EC2를 오토스케일링/ALB 뒤에 둔다. (NFC의 BLE 비콘처럼 PoC 이후 확장 항목)

```
[사용자] → http://<EC2 IP>:8000 → EC2 t3.micro
                                    ├─ backend 컨테이너 (FastAPI)
                                    └─ db 컨테이너 (PostgreSQL)
인프라: Terraform(IaC) · 배포 자동화: GitHub Actions(CI/CD)
```

## 사전 준비 (1회)

1. **AWS 계정** + IAM 사용자(AdministratorAccess 또는 EC2 권한) 액세스 키
2. 로컬에 **Terraform**, **AWS CLI** 설치 → `aws configure`로 액세스 키 등록
3. AWS 콘솔에서 **EC2 Key Pair 생성**(.pem 다운로드) — SSH 접속용
4. **GitHub에 코드 푸시** (EC2가 clone하므로 public 권장, 또는 토큰 포함 URL)
5. 내 공인 IP 확인: https://checkip.amazonaws.com → 뒤에 `/32` 붙이기

## 배포 절차

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # 값 채우기 (키페어·IP·repo·비밀번호·API키)

terraform init       # 프로바이더 다운로드
terraform plan       # 생성될 리소스 미리보기
terraform apply      # 실제 생성 (yes 입력)
```

완료되면 출력(output)에 접속 주소가 나온다:

```
app_url       = http://<공인IP>:8000
dashboard_url = http://<공인IP>:8000/dashboard
```

EC2가 부팅하며 Docker 설치 → 코드 clone → 컨테이너 기동 → 시드 적재까지 자동 수행한다(약 2~3분 소요). 잠시 후 위 주소로 접속.

## CI/CD (GitHub Actions)

- **`.github/workflows/ci.yml`** — main/PR 푸시 시 자동으로 테스트(pytest) 실행.
- **`.github/workflows/deploy.yml`** — main 푸시 시 EC2에 SSH로 접속해 `git pull` + `docker compose up -d --build`로 무중단에 가깝게 재배포.
  - GitHub 저장소 **Settings → Secrets and variables → Actions**에 등록:
    - `EC2_HOST` = EC2 공인 IP
    - `EC2_SSH_KEY` = .pem 개인키 전체 내용

→ 이후엔 코드를 고쳐 `git push` 하면 **테스트 → 배포가 자동**으로 돌아간다.

## 정리(과금 방지)

데모가 끝나면 반드시 리소스를 내린다:

```bash
terraform destroy    # 모든 리소스 삭제 (yes)
```

## 보안 메모

- `.env`(키 포함)와 `terraform.tfvars`, `*.tfstate`는 `.gitignore`로 git 제외됨.
- 현재는 EC2 user_data에 `.env`를 직접 기록한다. 운영 단계에서는 **AWS SSM Parameter Store / Secrets Manager**로 옮기는 것이 정석.
- 데모용으로 8000 포트를 전체 공개(0.0.0.0/0)했다. 실제 운영은 ALB + HTTPS(443) + 도메인 구성 권장.
