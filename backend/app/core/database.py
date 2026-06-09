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

engine = create_engine(settings.database_url, pool_pre_ping=True,
                       connect_args=_connect_args)
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
