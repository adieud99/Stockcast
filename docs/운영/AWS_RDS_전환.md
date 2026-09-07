# 분석계 DB를 RDS로 옮기기

지금은 EC2 한 대 안에서 Postgres 컨테이너가 돈다. 이걸 RDS로 뺀다.
Odoo와 DuckDNS는 손대지 않는다.

## 왜 옮기나

두 가지가 걸린다.

**메모리.** t3.micro 는 1GB다. 여기에 backend, postgres, odoo, odoo_db, caddy 가
다 올라간다. Odoo 18 하나가 400~600MB를 쓰는 걸 감안하면 처음부터 빠듯하다.
분석계 Postgres를 빼면 그만큼 숨통이 트인다.

**백업.** 지금 데이터는 도커 볼륨에만 있다. 인스턴스가 날아가면 같이 날아간다.
EBS 스냅샷을 따로 걸지 않는 한 되돌릴 방법이 없다. RDS는 자동 백업과 시점 복구가
기본으로 붙는다.

Odoo용 Postgres는 그대로 컨테이너에 둔다. Odoo는 자기 DB에 확장이나 설정을 직접
건드리는 일이 있어서, 굳이 RDS로 빼면 손이 더 간다. 분석계만 옮기는 게 이득이 크다.

## 비용 — 프리티어가 끝난 상태 기준

서울 리전 온디맨드 단가를 AWS Pricing API 로 직접 조회했다(2026-09 기준).
요금은 바뀌니 올리기 전에 다시 확인할 것.

| 항목 | 단가 | 월 환산(730시간) |
|---|---|---:|
| EC2 t4g.small | $0.0208/시간 | $15.18 |
| EC2 t3.small (바꾸기 전) | $0.0260/시간 | $18.98 |
| 루트 EBS gp3 20GB | $0.0912/GB·월 | $1.82 |
| 공인 IPv4 1개 | $0.0050/시간 | $3.65 |
| RDS db.t4g.micro | $0.0250/시간 | $18.25 |
| RDS gp2 20GB | $0.1310/GB·월 | $2.62 |

### 구성별 월 비용

| 구성 | 24시간 가동 | 하루 8시간 | 면접 때만(월 20시간) |
|---|---:|---:|---:|
| RDS 없이 (컨테이너 DB) | $20.65 | $8.09 | $2.34 |
| RDS 분리 (선택한 구성) | **$41.52** | $16.78 | $5.46 |

**RDS를 붙이면 24시간 기준으로 월 $20.87 이 더 든다.** DB 인스턴스가 $18.25,
스토리지가 $2.62다. 프리티어 안이었다면 둘 다 0이었지만 지금은 아니다.

인스턴스는 2GB를 유지했다. README 에 "micro(1GB)로는 Odoo 가 안 떴다"는 기록이 있어서다.
실측하면 backend 174MB + Odoo 196MB + DB 두 개 60MB 로 약 430MB 라 1GB 에도 들어가지만,
Odoo 모듈 설치와 이미지 빌드 때 크게 튄다. 그래서 메모리는 그대로 두고 아키텍처만
ARM 으로 바꿔서 `t3.small $18.98` → `t4g.small $15.18` 로 줄였다.

### 정한 것

**RDS를 쓴다.** `terraform.tfvars` 에 `use_rds = true` 로 두었다.
프리티어가 끝나서 월 $20.87 이 실제로 나가지만, DB를 인스턴스 밖에 두는 값어치가
그만큼은 된다고 봤다. 인스턴스를 날려도 데이터가 남고, 백업과 시점 복구가 따라온다.

대신 나머지에서 최대한 줄였다.

| 한 일 | 절감·효과 |
|---|---|
| 인스턴스를 t4g.small(ARM)로 | 월 $3.80 (t3.small 대비 20%, 메모리 2GB 유지) |
| 디스크 알람 기본 끄기 | 사용자 지표 월 $0.30 절약. 켜려면 에이전트도 필요하다 |
| 스토리지 자동 확장 끄기 | 조용히 20GB를 넘어가는 걸 막는다 |
| Multi-AZ 끄기 | 켜면 DB 요금이 두 배가 된다 |
| Performance Insights 끄기 | 클래스에 따라 과금될 수 있다 |
| 예산 알람 (월 $50) | 80% 도달·초과 예상 시 메일 |
| `aws_server.sh` 로 껐다 켜기 | 하루 8시간만 켜면 월 $16.78 (24시간 대비 60% 절감) |

t4g.micro 로 바꾼 건 쓰는 이미지(odoo·postgres·caddy·python) 다섯 개가 전부
arm64 를 지원하는 걸 확인하고 한 것이다. AMI 는 인스턴스 타입을 보고 아키텍처를
자동으로 고르므로, `instance_type` 만 바꾸면 나머지는 따라온다.

**24시간 켜 둘 게 아니라면 `make aws-stop` 을 쓰는 게 가장 크다.**
하루 8시간이면 $41.52 가 $16.78 로 내려간다.
정지하면 EC2 시간요금과 공인 IPv4 요금이 멈추고 스토리지만 남는다.
RDS 도 함께 정지되지만 AWS 가 7일 뒤 자동으로 다시 켜니, 오래 안 쓸 거면
스냅샷을 뜨고 지우는 편이 낫다.

## 만들어 둔 것

| 파일 | 하는 일 |
|---|---|
| `infra/terraform/rds.tf` | RDS 인스턴스·서브넷 그룹·보안그룹 |
| `docker-compose.rds.yml` | 앱이 RDS를 보도록 겹쳐 쓰는 compose 파일 |
| `scripts/migrate_to_rds.sh` | 덤프 → 적재 → 행 수 대조 |

`use_rds = false` 가 기본이라, 그냥 apply 해도 RDS는 안 생긴다.

## 순서

### 1. RDS 만들기

`infra/terraform/terraform.tfvars` 에 추가한다.

```hcl
use_rds = true
```

```bash
terraform -chdir=infra/terraform plan    # 무엇이 생기는지 먼저 본다
terraform -chdir=infra/terraform apply
```

DB가 만들어지는 데 5~10분 걸린다.

### 2. 접속 주소 받기

```bash
terraform -chdir=infra/terraform output -raw rds_database_url
terraform -chdir=infra/terraform output -raw rds_database_url_psycopg
```

`.env` 에 넣는다.

```
RDS_DATABASE_URL=postgresql+psycopg://erp:****@stockcast-db.xxxx.ap-northeast-2.rds.amazonaws.com:5432/erp_nfc
RDS_DATABASE_URL_PSYCOPG=host=stockcast-db.xxxx.ap-northeast-2.rds.amazonaws.com port=5432 dbname=erp_nfc user=erp password=****
```

이름이 `DATABASE_URL` 이 아니라 `RDS_` 로 시작하는 데는 이유가 있다.
`.env` 에는 이미 로컬용 `DATABASE_URL`(localhost) 이 있어서, 같은 이름을 쓰면
RDS 값을 안 채워도 "값이 있으니까" 그냥 넘어간다. 그러면 컨테이너가 자기 자신의
`localhost:5432` 로 붙으러 간다. 실제로 그렇게 동작하는 걸 확인하고 이름을 나눴다.
지금은 안 채우면 기동 자체가 멈춘다.

### 3. 데이터 옮기기

```bash
./scripts/migrate_to_rds.sh \
  --target "$(terraform -chdir=infra/terraform output -raw rds_database_url_psycopg)"
```

덤프 → 적재 → **테이블별 행 수 대조** 순으로 돈다. 마지막 대조가 핵심이다.
하나라도 안 맞으면 0이 아닌 코드로 끝나므로, 통과했으면 다음으로 넘어가도 된다.

**행 수가 맞는 것과 데이터가 맞는 것은 다르다.** 이 스크립트는 원본을 그대로
옮기므로, 원본이 어긋나 있으면 어긋난 채로 간다. 옮기기 전후로 정합성을 한 번씩
찍어 두고 비교한다.

```bash
curl -s localhost:8000/api/ops/integrity | python3 -m json.tool   # 옮기기 전
# ... 마이그레이션 ...
curl -s localhost:8000/api/ops/integrity | python3 -m json.tool   # 옮긴 뒤
```

두 값이 같으면 옮기는 과정은 깨끗한 것이다. 옮긴 뒤가 더 나쁘면 그때 마이그레이션을
의심한다.

**옛 데이터를 옮길 거라면 먼저 봐야 할 게 있다.** 테스트하다 C01(자재문서 합계 = 재고)이
30개 품목 전부 깨진 걸 봤다. 마이그레이션이 아니라 **데이터가 원래 그랬다.**
그 도커 볼륨의 문서들은 2026-06-11에 만들어진 것이었고, 당시 시더에는
`Σ(direction × 수량) = 재고`를 깨뜨리는 버그가 있었다. 지금 코드로 새로 시드하면
C01 불일치가 0으로 나온다.

그래서 순서를 이렇게 잡는 게 낫다.

1. 옮기기 전에 `/api/ops/integrity` 를 찍어 본다
2. C01 이 깨져 있으면 **옮기지 말고 다시 시드한다.** 깨진 데이터를 RDS 로 옮겨봐야
   깨진 채로 남는다
3. 살려야 할 실제 운영 데이터가 섞여 있다면, 옮긴 뒤 재고를 이동 합계로 다시 맞춘다

지금은 AWS 쪽에 아무것도 없어서 처음부터 새로 시드하면 되므로 이 문제는 없다.

**버전을 맞춰야 한다.** `pg_restore` 가 서버보다 새 버전이면 적재가 중간에 깨진다.
`pg_restore` 18이 넣는 `SET transaction_timeout` 을 PostgreSQL 16이 몰라서 나는
문제인데, 실제로 겪었다. 스크립트가 시작할 때 버전을 먼저 비교해서 막는다.
클라이언트를 맞추기 어려우면 컨테이너로 우회한다.

```bash
./scripts/migrate_to_rds.sh --pg-image postgres:16 --target "..."
```

### 4. 앱을 RDS로 붙이기

```bash
docker compose -f docker-compose.yml -f docker-compose.rds.yml up -d
```

`docker-compose.rds.yml` 은 `db` 서비스를 지우고 `depends_on` 을 끊은 뒤
접속 주소를 `.env` 값으로 바꾼다. 운영이니 `--reload` 도 뺀다.

확인한다.

```bash
curl -s localhost:8000/api/ops/health | python3 -m json.tool
docker compose -f docker-compose.yml -f docker-compose.rds.yml ps
```

### 5. 정리

며칠 지켜보고 문제 없으면 옛 볼륨을 지운다. **먼저 지우면 되돌릴 수 없다.**

```bash
docker volume ls | grep pgdata
docker volume rm <볼륨명>
```

## 되돌리기

RDS 쪽에 문제가 생기면 오버레이만 빼면 된다.

```bash
docker compose up -d
```

`db` 컨테이너와 `pgdata` 볼륨이 그대로 있으므로 옮기기 전 상태로 돌아간다.
볼륨을 이미 지웠다면 마이그레이션 때 남긴 덤프 파일로 되살린다.
그래서 5번을 서두르지 말라는 것이다.

## 알아 둘 것

**RDS는 공인 주소가 없다.** `publicly_accessible = false` 로 뒀고, 보안그룹도
CIDR 이 아니라 앱 EC2의 보안그룹에서 오는 5432만 연다. 노트북에서 바로 못 붙는다.
봐야 하면 EC2를 거친다.

```bash
ssh -i <키>.pem -L 5432:<RDS엔드포인트>:5432 ec2-user@<EC2공인IP>
# 다른 창에서
psql "host=localhost port=5432 dbname=erp_nfc user=erp"
```

**비밀번호가 tfstate 에 들어간다.** `terraform.tfstate` 는 `.gitignore` 에 있지만
평문이다. 파일 자체를 조심해서 다뤄야 한다. 제대로 하려면 S3 백엔드에 암호화를
걸고 비밀번호는 Secrets Manager 로 빼야 하는데, 프리티어 범위를 넘어서 여기서는
안 했다.

**삭제 보호가 켜져 있다.** `db_deletion_protection = true` 라서 지우려면 먼저
`false` 로 바꾸고 apply 한 뒤에 destroy 해야 한다. 실수로 날리는 걸 막으려는 것이다.
