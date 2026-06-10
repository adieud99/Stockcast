# Odoo Community — StockCast 실제 ERP 백본

StockCast는 수요예측·안전재고 분석 엔진이고, 실물 재고·입출고·조달은 **실제 ERP인 Odoo Community**가 담당한다. 두 시스템은 Odoo의 외부 API(XML-RPC)로 연동한다.

## 1. 실행 (맥 로컬 Docker)

```bash
cd infra/odoo
docker compose -f docker-compose.odoo.yml up -d
# 첫 기동은 이미지 다운로드로 수 분 소요. 로그 확인:
docker compose -f docker-compose.odoo.yml logs -f odoo
```

브라우저에서 http://localhost:8069 접속.

## 2. 최초 설정 (브라우저, 1회)

1. **데이터베이스 생성 마법사**
   - Master Password: `StockCastAdmin2026`
   - Database Name: `stockcast`
   - Email(=관리자 로그인 ID): `admin@stockcast.local`
   - Password: 원하는 비밀번호(예: `stockcast`)
   - Language: 한국어 / Country: South Korea
   - "Demo data" 체크 해제 → Create database
2. 로그인 후 **Apps** 메뉴 → 검색창에 `Inventory` → **재고관리(Inventory)** 설치
   - (선택) `Sales`, `Purchase`도 설치하면 판매·발주 흐름까지 실무에 가깝다.
3. **연동용 API 키 발급**
   - 우상단 사용자 → **My Profile → Account Security → New API Key**
   - 발급된 키를 StockCast `.env`의 `ODOO_API_KEY`에 넣는다(아래 3번).

## 3. StockCast 연동 환경변수 (.env)

레포 루트 `.env`에 추가:

```
ODOO_URL=http://localhost:8069
ODOO_DB=stockcast
ODOO_USERNAME=admin@stockcast.local
ODOO_API_KEY=<위에서 발급한 API 키>
```

AWS에서 돌릴 때는 `ODOO_URL`을 서버 주소로 바꾼다.

## 4. 메모리 주의 (AWS 배포 시)

Odoo는 권장 2GB+ 라 t3.micro(1GB)에는 빠듯하다. 무료로 시연하려면 EC2에 스왑을 추가:

```bash
sudo dd if=/dev/zero of=/swapfile bs=1M count=4096
sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

불안정하면 t3.small(월 ≈ 1.5만원)로 올린다.
