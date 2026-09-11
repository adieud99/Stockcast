from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env는 저장소 루트에 있는 것 하나만 본다.
# backend/.env와 루트 .env를 둘 다 두면 실행 위치에 따라 설정이 갈려서
# "로컬에선 됐는데 컨테이너에선 안 되네"가 생긴다.
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    # 환경변수가 .env보다 우선한다. docker compose나 CI가 덮어쓸 수 있게.
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str = "postgresql+psycopg://erp:erp_pass@localhost:5432/erp_nfc"

    # Oracle ADB(wallet) 지원. DATABASE_URL을 oracle+oracledb://... 로 바꾸면 쓴다.
    # 학교 DA# 모델링 과제에서 같은 스키마를 Oracle에 올릴 때 썼다.
    oracle_wallet_dir: str = ""
    oracle_wallet_password: str = ""

    # 외부 공공 API
    kma_api_key: str = ""
    holiday_api_key: str = ""

    # 통계청 KOSIS — 의류 소매판매액지수(거시 수요 외생변수)
    # KOSIS 통계표 화면에서 'OpenAPI'로 생성한 전체 URL(apiKey·기간 포함)을 그대로 넣는다.
    kosis_retail_url: str = ""

    # 조달청 나라장터 입찰공고정보서비스(실수요 신호) — data.go.kr 인증키(Decoding)
    nara_api_key: str = ""

    # 조달청 종합쇼핑몰 품목정보(실 계약단가) — 인증키 + (명세가 JS라) 전체 요청 URL을 받는다.
    pps_api_key: str = ""
    pps_shop_url: str = ""

    # HTTPS 도메인 (Caddy가 Let's Encrypt 인증서를 발급받는 대상)
    stockcast_domain: str = ""

    # Odoo(실제 ERP) 연동 — XML-RPC
    odoo_url: str = "http://host.docker.internal:8069"
    odoo_db: str = "stockcast"
    odoo_username: str = "admin@stockcast.local"
    odoo_password: str = ""
    odoo_api_key: str = ""

    # AI 요약·챗봇이 쓸 provider (gemini | ollama | rule)
    # rule로 두면 LLM을 아예 호출하지 않고 규칙 기반으로만 동작한다.
    llm_provider: str = "gemini"

    # Gemini (Google AI Studio 무료 등급)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"

    # 로컬 LLM (Ollama)
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"

    # 로그인 (FR-11). 관리자는 전부, 조회 계정은 읽기만 한다.
    # 비밀번호를 비워 두면 그 계정은 로그인할 수 없다.
    auth_secret: str = ""               # 토큰 서명 키. 비우면 기동할 때마다 새로 만든다
    auth_admin_username: str = "admin"
    auth_admin_password: str = ""
    auth_viewer_username: str = "viewer"
    auth_viewer_password: str = ""
    auth_token_hours: int = 12

    # 요청 로그·수집 로그를 남길 디렉터리. 컨테이너에서는 저장소가 /workspace 로
    # 마운트되니 호스트의 저장소/logs 에 남아 재시작해도 안 사라진다. 비우면 안 남긴다.
    log_dir: str = str(REPO_ROOT / "logs")


settings = Settings()
