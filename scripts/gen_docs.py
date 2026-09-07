"""ORM 모델에서 ERD와 테이블명세서를 만들어내는 스크립트.

테이블 명세서를 손으로 관리하면 코드가 바뀔 때마다 어긋난다. 이 저장소에도
"테이블 11개"라고 적힌 문서가 실제 18개와 안 맞는 채로 남아 있었다.
그래서 구조(테이블·컬럼·타입·PK·FK·제약)는 ORM 메타데이터에서 읽고,
사람이 쓸 설명만 아래 TABLES/COLUMNS 딕셔너리에 둔다.
컬럼을 추가하면 명세서에 자동으로 생기고, 설명을 안 채우면 실행할 때 경고로 뜬다.

실행:
  python scripts/gen_docs.py            # docs/설계/ERD.md, 테이블명세서.md 재생성
  python scripts/gen_docs.py --check    # 변경 여부만 확인(CI 드리프트 감지)
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "analytics")]

import app.models  # noqa: F401,E402  (mm + maintenance 등록)
from app.core.database import Base  # noqa: E402

OUT_DIR = ROOT / "docs" / "설계"

# ── 사람이 관리하는 부분 ────────────────────────────────────────

# 테이블: (논리명, 분류, SAP원본, 설명)
TABLES: dict[str, tuple[str, str, str, str]] = {
    "plant": ("사업장", "마스터", "T001W", "재고를 보유하는 물류센터/사업장 단위 조직"),
    "storage_location": ("저장위치", "마스터", "T001L", "사업장 내 창고·보관 구역"),
    "material_group": ("자재그룹", "코드성", "T023", "품목 분류 코드(제설·안전·냉난방 등 8종)"),
    "material": ("자재", "마스터", "MARA+MAKT", "취급 품목 마스터. 판매단가를 포함해 재고자산·ABC 산출의 기준"),
    "movement_type": ("이동유형", "코드성", "BWART", "입출고 사유 코드와 방향(+1/−1). 재고 증감을 결정한다"),
    "stock": ("재고", "재고/현황", "MARD", "저장위치별 가용재고 + 안전재고·재주문점. 자재문서의 누적 결과"),
    "material_doc_header": ("자재문서 헤더", "거래", "MKPF", "입출고 전기 단위. 전기일 기준으로 분석에 조인된다"),
    "material_doc_item": ("자재문서 항목", "거래", "MSEG", "실제 이동 내역. 출고(201) 이력이 곧 수요 시계열이 된다"),
    "nfc_tag": ("NFC 태그", "재고/현황", "—", "태그 UID ↔ 자재 매핑. 스캔 시 품목·저장위치를 해석한다"),
    "stock_snapshot_history": ("재고 스냅샷", "이력성", "—", "월말 재고 이력. 평균재고·회전율·결품률 계산 근거"),
    "ext_weather": ("외부-날씨", "외부 공공데이터", "—", "기상청 ASOS 일별 기온·강수. 계절 수요의 주 동인"),
    "ext_holiday": ("외부-공휴일", "코드성", "—", "한국천문연구원 특일정보. 주말·휴일 수요 보정"),
    "ext_bid_notice": ("외부-입찰공고", "외부 공공데이터", "—", "조달청 나라장터 물품 입찰공고. 실수요 신호"),
    "ext_shop_price": ("외부-계약단가", "외부 공공데이터", "—", "조달청 종합쇼핑몰 MAS 실 계약단가. 실가격 근거"),
    "ext_retail_index": ("외부-소매지수", "외부 공공데이터", "—", "통계청 KOSIS 소매판매액지수(선택). 거시 수요 외생변수"),
    "equipment": ("설비", "설비 유지보수", "EQUI+EQKT", "정비 대상 설비 마스터. 상태와 예방정비 주기를 갖는다"),
    "maintenance_order": ("정비오더", "설비 유지보수", "AUFK/AFIH", "설비 1대에 대한 정비 작업 지시. 요청→진행→완료"),
    "maintenance_order_part": ("정비 사용자재", "설비 유지보수", "RESB→MSEG", "정비가 소비하는 부품. 완료 시 이동유형 261로 전기된다"),
}

# "테이블.컬럼": (논리명, SAP필드, 설명)
COLUMNS: dict[str, tuple[str, str, str]] = {
    "plant.plant_id": ("플랜트코드", "WERKS", "사업장 식별코드"),
    "plant.name": ("플랜트명", "", "사업장명"),
    "plant.created_at": ("생성일시", "", "등록 시각"),

    "storage_location.plant_id": ("플랜트코드", "WERKS", "소속 사업장"),
    "storage_location.sloc_id": ("저장위치코드", "LGORT", "창고 식별코드"),
    "storage_location.name": ("저장위치명", "", "창고명"),

    "material_group.group_code": ("자재그룹코드", "MATKL", "품목 분류 코드"),
    "material_group.name": ("자재그룹명", "", "분류명"),

    "material.material_no": ("자재번호", "MATNR", "품목 식별코드"),
    "material.description": ("자재내역", "MAKTX", "품목명"),
    "material.material_type": ("자재유형", "MTART", "HAWA(상품) 등"),
    "material.group_code": ("자재그룹코드", "MATKL", "소속 분류"),
    "material.base_uom": ("기본단위", "MEINS", "EA 등 계량 단위"),
    "material.unit_price": ("판매단가", "", "재고자산금액·ABC 매출액 산출 기준(원)"),
    "material.created_at": ("생성일시", "", "등록 시각"),

    "movement_type.code": ("이동유형코드", "BWART", "101 입고 / 201 출고 / 261 정비소비 / 561 기초"),
    "movement_type.description": ("이동유형명", "", "코드 설명"),
    "movement_type.direction": ("방향", "", "+1 입고 / −1 출고. 재고 증감 부호"),

    "stock.material_no": ("자재번호", "MATNR", "대상 품목"),
    "stock.plant_id": ("플랜트코드", "WERKS", "사업장"),
    "stock.sloc_id": ("저장위치코드", "LGORT", "창고"),
    "stock.unrestricted_qty": ("가용재고", "LABST", "제약 없이 출고 가능한 수량"),
    "stock.safety_stock": ("안전재고", "", "SS = Z·σ·√L 로 산출·반영"),
    "stock.reorder_point": ("재주문점", "", "ROP = 일평균수요·L + SS"),
    "stock.updated_at": ("수정일시", "", "최종 갱신 시각"),

    "material_doc_header.doc_no": ("자재문서번호", "MBLNR", "전기 단위 식별자"),
    "material_doc_header.posting_date": ("전기일", "BUDAT", "재고·분석의 기준일"),
    "material_doc_header.doc_date": ("증빙일", "BLDAT", "증빙 발생일"),
    "material_doc_header.source": ("출처", "", "NFC / MANUAL / SEED / PM"),
    "material_doc_header.created_at": ("생성일시", "", "등록 시각"),

    "material_doc_item.doc_no": ("자재문서번호", "MBLNR", "소속 헤더"),
    "material_doc_item.item_no": ("항목번호", "ZEILE", "헤더 내 일련번호"),
    "material_doc_item.material_no": ("자재번호", "MATNR", "이동 품목"),
    "material_doc_item.plant_id": ("플랜트코드", "WERKS", "사업장"),
    "material_doc_item.sloc_id": ("저장위치코드", "LGORT", "창고"),
    "material_doc_item.movement_type": ("이동유형", "BWART", "입출고 사유"),
    "material_doc_item.quantity": ("수량", "MENGE", "이동 수량(항상 양수, 부호는 방향이 결정)"),
    "material_doc_item.uom": ("단위", "MEINS", "계량 단위"),

    "nfc_tag.tag_uid": ("태그 UID", "", "NFC 태그 고유번호"),
    "nfc_tag.material_no": ("자재번호", "MATNR", "매핑된 품목"),
    "nfc_tag.plant_id": ("플랜트코드", "WERKS", "사업장"),
    "nfc_tag.sloc_id": ("저장위치코드", "LGORT", "창고"),
    "nfc_tag.created_at": ("생성일시", "", "등록 시각"),

    "stock_snapshot_history.snapshot_date": ("스냅샷일자", "", "재고를 찍은 기준일(월말)"),
    "stock_snapshot_history.material_no": ("자재번호", "MATNR", "대상 품목"),
    "stock_snapshot_history.plant_id": ("플랜트코드", "WERKS", "사업장"),
    "stock_snapshot_history.sloc_id": ("저장위치코드", "LGORT", "창고"),
    "stock_snapshot_history.unrestricted_qty": ("가용재고", "LABST", "그 시점의 재고 수량"),
    "stock_snapshot_history.created_at": ("생성일시", "", "적재 시각"),

    "ext_weather.obs_date": ("관측일", "", "기상 관측 일자"),
    "ext_weather.region_code": ("지점코드", "", "기상 관측 지점(서울 108)"),
    "ext_weather.avg_temp": ("평균기온", "", "℃. 회귀의 주 설명변수"),
    "ext_weather.min_temp": ("최저기온", "", "℃"),
    "ext_weather.max_temp": ("최고기온", "", "℃"),
    "ext_weather.precip_mm": ("강수량", "", "mm. 우의·제설 수요 동인"),

    "ext_holiday.holiday_date": ("공휴일자", "", "휴일 날짜"),
    "ext_holiday.name": ("명칭", "", "공휴일명(같은 날 중복은 합쳐 dedup)"),
    "ext_holiday.is_holiday": ("공휴일여부", "", "휴일 플래그"),

    "ext_bid_notice.bid_no": ("공고번호", "", "bidNtceNo"),
    "ext_bid_notice.bid_ord": ("공고차수", "", "bidNtceOrd"),
    "ext_bid_notice.bid_name": ("공고명", "", "bidNtceNm"),
    "ext_bid_notice.notice_agency": ("공고기관", "", "ntceInsttNm"),
    "ext_bid_notice.demand_agency": ("수요기관", "", "dminsttNm"),
    "ext_bid_notice.est_price": ("추정가격", "", "presmptPrc(원)"),
    "ext_bid_notice.notice_date": ("공고일", "", "bidNtceDt"),
    "ext_bid_notice.category": ("구분", "", "물품 등"),

    "ext_shop_price.id": ("일련번호", "", "대리키"),
    "ext_shop_price.spec_name": ("품목규격", "", "prdctSpecNm"),
    "ext_shop_price.corp_name": ("계약기업", "", "cntrctCorpNm"),
    "ext_shop_price.maker_name": ("제조사", "", "prdctMakrNm"),
    "ext_shop_price.contract_price": ("계약단가", "", "cntrctPrceAmt(원)"),
    "ext_shop_price.unit": ("단위", "", "prdctUnit"),
    "ext_shop_price.contract_method": ("계약방법", "", "cntrctMthdNm"),
    "ext_shop_price.enterprise_div": ("기업구분", "", "entrprsDivNm"),
    "ext_shop_price.delivery_days": ("납품기한", "", "dlvrTmlmtDaynum(일)"),

    "ext_retail_index.period": ("기준월", "", "YYYYMM"),
    "ext_retail_index.category": ("분류", "", "품목 분류"),
    "ext_retail_index.index_value": ("지수값", "", "소매판매액지수"),
    "ext_retail_index.unit": ("단위", "", "지수 단위"),

    "equipment.equipment_no": ("설비번호", "EQUNR", "설비 식별코드"),
    "equipment.name": ("설비명", "EQKTX", "설비 이름"),
    "equipment.category": ("분류", "", "하역·반송·공조·포장·전기·방재"),
    "equipment.plant_id": ("플랜트코드", "WERKS", "설치 사업장"),
    "equipment.sloc_id": ("저장위치코드", "LGORT", "설치 창고"),
    "equipment.manufacturer": ("제조사", "", "제작 업체"),
    "equipment.install_date": ("설치일", "INBDT", "도입 일자"),
    "equipment.status": ("상태", "", "RUN 정상 / CHECK 점검중 / DOWN 고장 / SCRAP 폐기"),
    "equipment.pm_cycle_days": ("정비주기", "", "예방정비 주기(일). 0이면 PM 비대상"),
    "equipment.last_pm_date": ("최근정비일", "", "다음 예정일 = 최근정비일 + 정비주기"),
    "equipment.created_at": ("생성일시", "", "등록 시각"),

    "maintenance_order.order_no": ("오더번호", "AUFNR", "정비오더 식별자"),
    "maintenance_order.equipment_no": ("설비번호", "EQUNR", "정비 대상"),
    "maintenance_order.order_type": ("정비유형", "", "PM 예방 / CM 사후(고장)"),
    "maintenance_order.status": ("상태", "", "REQ 요청 / WIP 진행 / DONE 완료 / CANCEL 취소"),
    "maintenance_order.priority": ("우선순위", "", "H / M / L"),
    "maintenance_order.title": ("제목", "", "정비 작업명"),
    "maintenance_order.description": ("내용", "", "상세 내역·완료 메모"),
    "maintenance_order.requester": ("요청자", "", "접수자"),
    "maintenance_order.request_date": ("요청일", "", "접수 일자"),
    "maintenance_order.planned_date": ("예정일", "", "지연 판정 기준일"),
    "maintenance_order.completed_date": ("완료일", "", "MTTR 산출에 사용"),
    "maintenance_order.labor_cost": ("인건비", "", "투입 비용(원)"),
    "maintenance_order.created_at": ("생성일시", "", "등록 시각"),

    "maintenance_order_part.order_no": ("오더번호", "AUFNR", "소속 정비오더"),
    "maintenance_order_part.item_no": ("항목번호", "", "오더 내 일련번호"),
    "maintenance_order_part.material_no": ("자재번호", "MATNR", "사용 부품"),
    "maintenance_order_part.quantity": ("수량", "", "소비 수량"),
    "maintenance_order_part.uom": ("단위", "", "계량 단위"),
    "maintenance_order_part.posted_doc_no": ("전기문서번호", "MBLNR", "이동유형 261 자재문서. NULL이면 미전기(예약) 상태"),
}

# ERD 관계 라벨 — (부모, 자식, 라벨)
RELATIONS = [
    ("PLANT", "STORAGE_LOCATION", "보유"),
    ("PLANT", "STOCK", "재고"),
    ("STORAGE_LOCATION", "STOCK", "위치별"),
    ("STORAGE_LOCATION", "MATERIAL_DOC_ITEM", "위치"),
    ("STORAGE_LOCATION", "NFC_TAG", "위치"),
    ("STORAGE_LOCATION", "STOCK_SNAPSHOT_HISTORY", "위치"),
    ("STORAGE_LOCATION", "EQUIPMENT", "설치"),
    ("MATERIAL_GROUP", "MATERIAL", "분류"),
    ("MATERIAL", "STOCK", "재고"),
    ("MATERIAL", "MATERIAL_DOC_ITEM", "입출고"),
    ("MATERIAL", "NFC_TAG", "태그"),
    ("MATERIAL", "STOCK_SNAPSHOT_HISTORY", "스냅샷"),
    ("MATERIAL", "MAINTENANCE_ORDER_PART", "부품"),
    ("MATERIAL_DOC_HEADER", "MATERIAL_DOC_ITEM", "포함"),
    ("MOVEMENT_TYPE", "MATERIAL_DOC_ITEM", "유형"),
    ("EQUIPMENT", "MAINTENANCE_ORDER", "정비대상"),
    ("MAINTENANCE_ORDER", "MAINTENANCE_ORDER_PART", "소비"),
]

# ERD 박스에 표시할 주요 컬럼(전부 넣으면 그림이 읽히지 않는다)
ERD_KEY_COLUMNS = {
    "plant": ["plant_id", "name"],
    "storage_location": ["plant_id", "sloc_id", "name"],
    "material_group": ["group_code", "name"],
    "material": ["material_no", "description", "group_code", "unit_price"],
    "movement_type": ["code", "description", "direction"],
    "stock": ["material_no", "plant_id", "sloc_id", "unrestricted_qty",
              "safety_stock", "reorder_point"],
    "material_doc_header": ["doc_no", "posting_date", "source"],
    "material_doc_item": ["doc_no", "item_no", "material_no", "movement_type", "quantity"],
    "nfc_tag": ["tag_uid", "material_no"],
    "stock_snapshot_history": ["snapshot_date", "material_no", "unrestricted_qty"],
    "ext_weather": ["obs_date", "avg_temp", "precip_mm"],
    "ext_holiday": ["holiday_date", "name"],
    "ext_bid_notice": ["bid_no", "bid_name", "est_price"],
    "ext_shop_price": ["id", "spec_name", "contract_price"],
    "ext_retail_index": ["period", "index_value"],
    "equipment": ["equipment_no", "name", "status", "pm_cycle_days", "last_pm_date"],
    "maintenance_order": ["order_no", "equipment_no", "order_type", "status",
                          "planned_date", "completed_date"],
    "maintenance_order_part": ["order_no", "item_no", "material_no", "quantity",
                               "posted_doc_no"],
}

CATEGORY_ORDER = ["마스터", "코드성", "거래", "재고/현황", "이력성",
                  "외부 공공데이터", "설비 유지보수"]


# ── 생성 ────────────────────────────────────────────────────────

def _mermaid_type(col) -> str:
    """mermaid erDiagram이 받아들이는 단순 타입명."""
    t = str(col.type).lower()
    if "varchar" in t or "char" in t or "text" in t:
        return "string"
    if "bigint" in t:
        return "bigint"
    if "smallint" in t or "integer" in t or t == "int":
        return "int"
    if "numeric" in t or "decimal" in t or "float" in t:
        return "numeric"
    if "datetime" in t or "timestamp" in t:
        return "datetime"
    if "date" in t:
        return "date"
    if "bool" in t:
        return "boolean"
    return "string"


def _sorted_tables():
    """분류 → 테이블명 순으로 정렬."""
    def key(name):
        cat = TABLES.get(name, ("", "기타", "", ""))[1]
        return (CATEGORY_ORDER.index(cat) if cat in CATEGORY_ORDER else 99, name)
    return sorted(Base.metadata.tables, key=key)


def build_erd() -> str:
    md = Base.metadata
    lines = ["```mermaid", "erDiagram"]
    for parent, child, label in RELATIONS:
        lines.append(f'    {parent} ||--o{{ {child} : "{label}"')
    lines.append("")
    for name in _sorted_tables():
        t = md.tables[name]
        keys = ERD_KEY_COLUMNS.get(name)
        cols = [c for c in t.columns if not keys or c.name in keys]
        lines.append(f"    {name.upper()} {{")
        for c in cols:
            mark = "PK" if c.primary_key else ("FK" if c.foreign_keys else "")
            lines.append(f"        {_mermaid_type(c)} {c.name}{(' ' + mark) if mark else ''}")
        lines.append("    }")
    lines.append("```")
    return "\n".join(lines)


def build_entity_table() -> str:
    md = Base.metadata
    rows = ["| No | 엔터티(논리) | 테이블(물리) | 분류 | SAP 원본 | PK | 설명 |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"]
    for i, name in enumerate(_sorted_tables(), 1):
        logical, cat, sap, desc = TABLES.get(name, (name, "기타", "—", ""))
        pk = " + ".join(c.name for c in md.tables[name].primary_key.columns)
        rows.append(f"| {i} | {logical} | `{name}` | {cat} | {sap} | `{pk}` | {desc} |")
    return "\n".join(rows)


def build_column_spec() -> str:
    md = Base.metadata
    out = []
    for name in _sorted_tables():
        t = md.tables[name]
        logical, cat, sap, desc = TABLES.get(name, (name, "기타", "—", ""))
        out.append(f"### `{name}` — {logical}\n")
        out.append(f"{desc}  \n*분류: {cat} · SAP 원본: {sap}*\n")
        out.append("| 컬럼(물리) | 컬럼(논리) | 타입 | PK | FK 참조 | Null | SAP 필드 | 설명 |")
        out.append("| :--- | :--- | :--- | :---: | :--- | :---: | :--- | :--- |")
        for c in t.columns:
            lg, sapf, cdesc = COLUMNS.get(f"{name}.{c.name}", ("", "", ""))
            fk = ", ".join(f"`{f.column.table.name}.{f.column.name}`"
                           for f in c.foreign_keys) or "—"
            out.append(
                f"| `{c.name}` | {lg} | {c.type} | {'●' if c.primary_key else ''} "
                f"| {fk} | {'Y' if c.nullable else 'N'} | {sapf or '—'} | {cdesc} |")
        # Table.constraints는 set이라 순회 순서가 매번 달라진다.
        # 정렬하지 않으면 생성 결과가 실행마다 바뀌어 --check가 오탐한다.
        checks = sorted(str(cst.sqltext) for cst in t.constraints
                        if cst.__class__.__name__ == "CheckConstraint")
        if checks:
            out.append("")
            out.append("제약: " + " · ".join(f"`{c}`" for c in checks))
        out.append("")
    return "\n".join(out)


HEADER = ("<!-- 이 문서는 scripts/gen_docs.py 가 ORM 모델에서 생성합니다. "
          "직접 수정하지 마세요. -->\n")


def render_erd_doc() -> str:
    md = Base.metadata
    return f"""{HEADER}# StockCast 데이터 모델 (ERD)

엔터티 {len(md.tables)}개. SAP의 MM(자재관리)과 PM(설비 유지보수) 구조를 가져다 썼다.

*생성일 {date.today()} · 원천 `backend/app/models/`*

---

## 1. 재고는 고치는 값이 아니라 계산되는 값이다

이 모델에서 재고 수량을 직접 UPDATE 하는 코드는 없다. 입출고가 생기면 자재문서
(`material_doc_header` + `material_doc_item`)를 남기고, 재고(`stock`)는 그 문서들을
누적한 결과로 나온다.

```
NFC 스캔 / 수기 입력 / 정비 부품 소비
    → 자재문서 생성 (헤더 1건 + 항목 N건)
    → 이동유형 방향(+1/−1) × 수량
    → stock.unrestricted_qty 갱신
```

번거로워 보이지만 이렇게 하면 세 가지가 따라온다.

우선 감사 추적이 남는다. 언제 무엇이 왜(이동유형) 움직였는지가 전부 기록되니까,
재고가 이상해도 거슬러 올라가 원인을 찾을 수 있다.

그리고 출고(이동유형 201) 이력이 그대로 수요 시계열이 된다. 수요예측을 위해
따로 데이터를 만들 필요가 없다.

마지막이 제일 중요한데, `Σ(방향 × 수량) = 재고` 라는 등식이 항상 성립해야 한다는
뜻이 된다. 이 등식이 깨졌다면 이동 없이 재고가 바뀐 것이므로 어딘가 문제가 있다.
운영 화면의 정합성 점검 C01이 이걸 계속 감시한다. 정비오더가 쓴 부품도 이동유형
261 자재문서로 남기 때문에 같은 식에 포함된다.

---

## 2. ERD

{build_erd()}

외부 공공데이터(`ext_*`)는 FK로 묶지 않았다. 수집 주기도 다르고 키 체계도 내부
마스터와 안 맞는데다, 커넥터 하나가 실패해도 핵심 데이터는 살아야 하기 때문이다.
분석할 때 날짜로 조인한다.

---

## 3. 엔터티 정의서

{build_entity_table()}

---

## 4. 설계하면서 정한 것들

**정규화** — 운영 테이블은 3NF까지 맞췄다. 반정규화는 스냅샷 이력
(`stock_snapshot_history`) 하나에만 썼는데, 월말 재고를 매번 자재문서에서
역산하면 회전율 조회가 너무 느려서다.

**복합 PK** — `stock`(자재+플랜트+저장위치)이나 `material_doc_item`(문서+항목)처럼
업무적으로 의미가 있는 식별자는 그대로 PK로 썼다. 대리키는 자연키가 마땅치 않은
`ext_shop_price`에만 쓴다.

**멀티테넌트 안 함** — `tenant_id` 같은 컬럼은 일부러 넣지 않았다. 단일 기업
백오피스가 목표라 조직 구조는 플랜트/저장위치 2단계로 충분하다.

**BigInteger 변형** — `BigInteger().with_variant(Integer, "sqlite")`를 쓴다.
운영은 PostgreSQL의 BIGSERIAL이지만 테스트는 SQLite 인메모리라, 이렇게 해야
양쪽에서 자동증가가 똑같이 동작한다.

---

## 5. 같이 보면 좋은 문서

- 컬럼 단위 명세는 [테이블명세서.md](테이블명세서.md)
- Oracle DDL은 `db/oracle/stockcast_oracle_schema.sql` (모델링 툴 리버스 엔지니어링용)
- 왜 이런 기술을 골랐는지는 [설계_및_결정.md](설계_및_결정.md)
"""


def render_spec_doc() -> str:
    md = Base.metadata
    return f"""{HEADER}# StockCast 테이블 명세서

테이블 {len(md.tables)}개의 컬럼 명세.

*생성일 {date.today()} · 원천 `backend/app/models/`*

타입은 SQLAlchemy 표기 그대로다. 운영 DBMS는 PostgreSQL 16이고, Oracle DDL이
필요하면 `db/oracle/stockcast_oracle_schema.sql`에 따로 있다.

---

{build_column_spec()}
---

## 참고

엔터티 관계도와 설계 배경은 [ERD.md](ERD.md)에 있다.

이 문서는 `python scripts/gen_docs.py` 로 만든다. 모델을 고쳤으면 다시 돌려서
문서를 맞춰야 한다. CI에서 `--check`로 검사하므로, 안 맞추면 빌드가 막힌다.
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="파일을 쓰지 않고 변경 여부만 확인(드리프트 감지)")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = {OUT_DIR / "ERD.md": render_erd_doc(),
               OUT_DIR / "테이블명세서.md": render_spec_doc()}

    stale = []
    for path, content in targets.items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == content:
            print(f"   변경 없음 — {path.relative_to(ROOT)}")
            continue
        stale.append(path)
        if not args.check:
            path.write_text(content, encoding="utf-8")
            print(f"✅ 생성 — {path.relative_to(ROOT)}")

    if args.check and stale:
        names = ", ".join(str(p.relative_to(ROOT)) for p in stale)
        raise SystemExit(f"❌ 문서가 모델과 어긋납니다: {names}\n"
                         f"   python scripts/gen_docs.py 로 재생성하세요.")

    # 누락된 설명을 드러내 문서 품질을 스스로 감시한다
    missing = [f"{t}.{c.name}" for t in Base.metadata.tables
               for c in Base.metadata.tables[t].columns
               if f"{t}.{c.name}" not in COLUMNS]
    if missing:
        print(f"\n⚠️  설명이 없는 컬럼 {len(missing)}개: {', '.join(missing[:10])}"
              + (" …" if len(missing) > 10 else ""))


if __name__ == "__main__":
    main()
