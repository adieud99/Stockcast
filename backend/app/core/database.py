from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

# Oracle ADB(wallet) 연결이면 wallet 경로/비번을 connect_args로 전달
_connect_args = {}
if settings.database_url.startswith("oracle"):
    if settings.oracle_wallet_dir:
        _connect_args["config_dir"] = settings.oracle_wallet_dir
        _connect_args["wallet_location"] = settings.oracle_wallet_dir
    if settings.oracle_wallet_password:
        _connect_args["wallet_password"] = settings.oracle_wallet_password

# PostgreSQL 이면 네트워크 너머에 있다고 보고 설정을 더 건다.
# 로컬 컨테이너(db:5432)일 때는 없어도 티가 안 나지만, RDS 처럼 VPC 를 건너가면
# 다음 두 가지가 실제로 문제가 된다.
#
#   1) 연결이 조용히 끊긴다. NAT·방화벽이 유휴 연결을 몇 분 뒤 버리는데,
#      풀에 들고 있던 연결을 그대로 쓰면 첫 쿼리에서 죽는다.
#      pool_pre_ping 이 잡아주긴 하지만 매번 왕복이 한 번 더 든다.
#      pool_recycle 로 미리 버리는 편이 싸다.
#   2) DB 가 멎으면 요청이 안 끝난다. connect_timeout 이 없으면 OS 기본값까지
#      기다리는데, 그 사이 워커가 다 물려서 앱 전체가 응답을 못 한다.
#      헬스체크까지 같이 죽어서 워치독이 재시작을 반복하게 된다.
if settings.database_url.startswith("postgresql"):
    _connect_args.setdefault("connect_timeout", 5)
    # 서버 쪽에서도 한 번 더 끊는다. 오래 걸리는 쿼리가 커넥션을 붙잡고 있으면
    # 풀이 마르고, 원인 찾기가 어려운 느려짐으로 나타난다.
    _connect_args.setdefault(
        "options", "-c statement_timeout=30000 -c idle_in_transaction_session_timeout=60000"
    )

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,      # 꺼낸 연결이 살아 있는지 먼저 확인한다
    pool_recycle=300,        # 5분 지난 연결은 버린다. NAT 유휴 타임아웃보다 짧게 잡았다
    connect_args=_connect_args,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """모든 ORM 모델의 베이스 클래스."""
    pass


def get_db():
    """FastAPI 의존성: 요청마다 DB 세션 생성/반납."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
