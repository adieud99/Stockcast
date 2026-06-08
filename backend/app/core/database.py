from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
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
