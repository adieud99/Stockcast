from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse

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


_HOME_HTML = """
<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>StockCast</title>
<style>
 body{font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif;background:#f5f6fa;
      margin:0;color:#1E2761;display:flex;min-height:100vh;align-items:center;justify-content:center}
 .wrap{max-width:560px;width:90%;text-align:center}
 h1{font-size:34px;margin:0 0 6px}
 .sub{color:#028090;font-size:15px;margin-bottom:28px}
 .grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
 a.card{display:block;background:#fff;border-radius:14px;padding:22px 18px;text-decoration:none;
        color:#1E2761;box-shadow:0 1px 6px rgba(0,0,0,.07);transition:.15s}
 a.card:hover{transform:translateY(-2px);box-shadow:0 4px 14px rgba(0,0,0,.12)}
 .card .t{font-size:17px;font-weight:bold;margin-bottom:4px}
 .card .d{font-size:13px;color:#666}
 .foot{margin-top:26px;font-size:12px;color:#999}
</style></head><body><div class="wrap">
 <h1>StockCast</h1>
 <div class="sub">NFC 재고관리 · 수요예측 백오피스</div>
 <div class="grid">
   <a class="card" href="/dashboard"><div class="t">📊 KPI 대시보드</div><div class="d">재고회전율·결품률·발주 현황</div></a>
   <a class="card" href="/nfc"><div class="t">📡 NFC 입출고</div><div class="d">태그 스캔으로 입출고 기록</div></a>
   <a class="card" href="/docs"><div class="t">📑 API 문서</div><div class="d">전체 API 테스트·확인 (개발자용)</div></a>
   <a class="card" href="/api/forecast"><div class="t">📈 수요예측</div><div class="d">품목별 회귀모델 결과 (JSON)</div></a>
 </div>
 <div class="foot">AI 해석(W9)은 개발 예정 · 단일 기업용 PoC</div>
</div></body></html>
"""


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
)

app.include_router(materials.router)
app.include_router(stock.router)
app.include_router(nfc.router)
app.include_router(external.router)
app.include_router(forecast.router)
app.include_router(reorder.router)
app.include_router(kpi.router)
app.include_router(insight.router)
app.include_router(odoo.router)
