"""ORM 모델 패키지.

여기서 모든 모델 모듈을 import 해두면 `Base.metadata.create_all()`이
테이블을 빠짐없이 생성한다. (모듈을 import 해야 매퍼가 등록된다)
"""
from app.models import mm as mm  # noqa: F401
from app.models import maintenance as maintenance  # noqa: F401
