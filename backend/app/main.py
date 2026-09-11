from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse

from app.core.auth import require_user
from app.core.logbuffer import RequestLogMiddleware

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

app = FastAPI(
    title="StockCast — SAP NFC 재고관리·수요예측 시스템",
    description=(
        "NFC 입출고 자동 기록 + SAP MM 구조 재고관리 + 수요예측 백오피스 (단일 기업용)\n\n"
        "※ 날짜는 `2025-01-31` 형식(하이픈)으로 입력하세요."
    ),
    version="0.1.0",
    docs_url=None,      # 한국어 커스텀 문서로 대체
    redoc_url=None,
)

# 요청 로그 링버퍼 — 운영 화면(/api/ops/logs)이 읽는다.
app.add_middleware(RequestLogMiddleware, slow_ms=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Swagger UI 화면의 기본 영어 라벨을 한국어로 치환하는 스크립트
_KO_LOCALE_SCRIPT = """
<script>
(function () {
  var MAP = {
    "Try it out": "사용해 보기", "Cancel": "취소", "Execute": "실행",
    "Clear": "지우기", "Parameters": "입력 항목", "No parameters": "입력 항목 없음",
    "Name": "이름", "Description": "설명", "Responses": "응답",
    "Response body": "응답 본문", "Response headers": "응답 헤더",
    "Request body": "요청 본문", "Media type": "형식", "Schema": "구조",
    "Example Value": "예시 값", "Code": "코드", "Links": "링크",
    "No links": "링크 없음", "Server response": "서버 응답",
    "Download": "내려받기", "Servers": "서버", "Authorize": "인증",
    "required": "필수", "Successful Response": "성공 응답",
    "Validation Error": "검증 오류", "Loading": "불러오는 중", "LOADING": "불러오는 중"
  };
  function tr(root) {
    var els = root.querySelectorAll(
      "button, .opblock-summary-description, table thead td, .tab li, " +
      "h4, h5, label, .response-col_status, .btn, " +
      ".opblock-section-header h4, .responses-inner h4");
    els.forEach(function (el) {
      if (el.dataset.koDone) return;                 // 이미 처리한 요소는 건너뜀
      var t = (el.childNodes.length === 1 && el.firstChild.nodeType === 3)
                ? el.textContent.trim() : null;
      if (t && MAP[t]) { el.textContent = MAP[t]; el.dataset.koDone = "1"; }
    });
  }
  var obs;
  function run() {
    if (obs) obs.disconnect();                       // 감시 끄고
    tr(document);                                    // 치환 후
    if (obs) obs.observe(document.body, { childList: true, subtree: true });  // 다시 켬
  }
  var pending = false;
  window.addEventListener("load", function () {
    obs = new MutationObserver(function () {
      if (pending) return;                           // 디바운스(연속 변경 한 번만)
      pending = true;
      setTimeout(function () { pending = false; run(); }, 200);
    });
    run();
  });
})();
</script>
"""


@app.get("/docs", include_in_schema=False)
def korean_docs():
    """한국어 API 문서(Swagger UI)."""
    html = get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title="StockCast API 문서",
    )
    body = html.body.decode()
    body = body.replace("</body>", _KO_LOCALE_SCRIPT + "</body>")
    return HTMLResponse(body)


@app.get("/", include_in_schema=False)
def home():
    """홈 = KPI 대시보드(매니저 바에서 NFC 입출고로 전환)."""
    return FileResponse(FRONTEND_DIR / "dashboard.html")


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    """KPI 대시보드 화면."""
    return FileResponse(FRONTEND_DIR / "dashboard.html")


@app.get("/nfc", include_in_schema=False)
def nfc_page():
    """NFC 입출고 화면."""
    return FileResponse(FRONTEND_DIR / "nfc-scan.html")


@app.get("/health", tags=["시스템"], summary="서버 상태 확인")
def health_check():
    return {"status": "ok", "service": "stockcast-backend"}


from app.api import (  # noqa: E402
    materials, stock, nfc, external, forecast, reorder, kpi, insight, odoo,
    glossary, chat, maintenance, ops, auth,
)

# 로그인 없이 열리는 API 는 둘뿐이다. 화면(HTML)과 /health 는 위에서 따로 연다.
#   /api/auth/login — 로그인
#   /api/ops/health — 워치독·배포 헬스체크가 폴링한다. 로그인 안 하면 판정만 준다
app.include_router(auth.router)
app.include_router(ops.public_router)

# 나머지는 전부 로그인이 필요하다. 조회 계정은 읽기만 통과한다(core/auth.py).
for _module in (materials, stock, nfc, external, forecast, reorder, kpi, insight, odoo,
                glossary, chat, maintenance, ops):
    app.include_router(_module.router, dependencies=[Depends(require_user)])
