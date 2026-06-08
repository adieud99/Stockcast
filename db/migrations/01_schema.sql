-- ============================================================
-- StockCast — SAP MM(자재관리) 모듈 구조 차용 스키마
-- ============================================================
-- 설계 원칙:
--  1) SAP MM 핵심 테이블(MARA/MARD/MKPF/MSEG 등)의 "구조와 개념"을 차용한다.
--     - 컬럼은 가독성을 위해 영문 의미명으로 쓰되, 원본 SAP 필드명을 주석으로 병기한다.
--       (예: material_no = MATNR, posting_date = BUDAT)
--  2) 단일 기업용. 멀티테넌트(tenant_id) 개념은 두지 않는다.
--  3) 입출고는 "자재문서(Material Document)" 구조로 기록 → 재고는 그 결과로 갱신된다.
--     실무 SAP와 동일하게 '이동(movement)이 진실의 원천, 재고는 집계' 구조.
-- ============================================================

-- ----------------------------------------------------------------
-- 조직 구조 (Organizational Data)
-- ----------------------------------------------------------------

-- T001W: 플랜트(사업장/공장)
CREATE TABLE plant (
    plant_id    VARCHAR(4)  PRIMARY KEY,           -- WERKS
    name        VARCHAR(60) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- T001L: 저장위치(창고/저장 구역)
CREATE TABLE storage_location (
    plant_id    VARCHAR(4)  NOT NULL REFERENCES plant(plant_id),
    sloc_id     VARCHAR(4)  NOT NULL,              -- LGORT
    name        VARCHAR(60) NOT NULL,
    PRIMARY KEY (plant_id, sloc_id)
);

-- ----------------------------------------------------------------
-- 자재 마스터 (Material Master)
-- ----------------------------------------------------------------

-- T023: 자재 그룹
CREATE TABLE material_group (
    group_code  VARCHAR(9)  PRIMARY KEY,           -- MATKL
    name        VARCHAR(60) NOT NULL
);

-- MARA(+MAKT 명칭): 자재 마스터 일반 데이터
CREATE TABLE material (
    material_no    VARCHAR(18) PRIMARY KEY,         -- MATNR
    description    VARCHAR(120) NOT NULL,           -- MAKT-MAKTX (자재 내역)
    material_type  VARCHAR(4)  NOT NULL,            -- MTART (예: HAWA 상품, FERT 완제품)
    group_code     VARCHAR(9)  REFERENCES material_group(group_code),  -- MATKL
    base_uom       VARCHAR(3)  NOT NULL DEFAULT 'EA', -- MEINS (기본 단위: EA, KG ...)
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------
-- 재고 (Stock) — MARD: 저장위치별 재고
--   재고 수량 자체는 자재문서 전기 결과로 갱신된다.
--   안전재고/재주문점은 분석 엔진(5단계)이 계산해 여기에 기록한다.
-- ----------------------------------------------------------------
CREATE TABLE stock (
    material_no       VARCHAR(18) NOT NULL REFERENCES material(material_no),
    plant_id          VARCHAR(4)  NOT NULL,
    sloc_id           VARCHAR(4)  NOT NULL,
    unrestricted_qty  NUMERIC(15,3) NOT NULL DEFAULT 0,   -- LABST (가용재고)
    safety_stock      NUMERIC(15,3) NOT NULL DEFAULT 0,   -- 안전재고 (분석 산출)
    reorder_point     NUMERIC(15,3) NOT NULL DEFAULT 0,   -- ROP 재주문점 (분석 산출)
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (material_no, plant_id, sloc_id),
    FOREIGN KEY (plant_id, sloc_id) REFERENCES storage_location(plant_id, sloc_id)
);

-- ----------------------------------------------------------------
-- 이동 유형 (Movement Type) — BWART 룩업
--   direction: +1 입고(재고증가), -1 출고(재고감소)
-- ----------------------------------------------------------------
CREATE TABLE movement_type (
    code        VARCHAR(3)  PRIMARY KEY,            -- BWART
    description VARCHAR(60) NOT NULL,
    direction   SMALLINT    NOT NULL CHECK (direction IN (-1, 1))
);

-- ----------------------------------------------------------------
-- 자재문서 (Material Document) — 입출고의 진실의 원천
--   MKPF: 헤더(문서 단위), MSEG: 항목(라인 단위)
-- ----------------------------------------------------------------

-- MKPF: 자재문서 헤더
CREATE TABLE material_doc_header (
    doc_no       BIGSERIAL PRIMARY KEY,             -- MBLNR (문서번호)
    posting_date DATE NOT NULL,                     -- BUDAT (전기일: 재고/분석 기준일)
    doc_date     DATE NOT NULL DEFAULT CURRENT_DATE,-- BLDAT (증빙일)
    source       VARCHAR(10) NOT NULL DEFAULT 'NFC',-- 입력 출처 (NFC / MANUAL / SEED)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- MSEG: 자재문서 항목
CREATE TABLE material_doc_item (
    doc_no         BIGINT  NOT NULL REFERENCES material_doc_header(doc_no) ON DELETE CASCADE,
    item_no        INT     NOT NULL,                 -- ZEILE (항목번호)
    material_no    VARCHAR(18) NOT NULL REFERENCES material(material_no),
    plant_id       VARCHAR(4)  NOT NULL,
    sloc_id        VARCHAR(4)  NOT NULL,
    movement_type  VARCHAR(3)  NOT NULL REFERENCES movement_type(code),  -- BWART
    quantity       NUMERIC(15,3) NOT NULL CHECK (quantity > 0),          -- MENGE
    uom            VARCHAR(3)  NOT NULL DEFAULT 'EA',
    PRIMARY KEY (doc_no, item_no),
    FOREIGN KEY (plant_id, sloc_id) REFERENCES storage_location(plant_id, sloc_id)
);

-- 수요예측은 '출고 실적'을 일자별로 집계해 사용 → 조회 성능을 위한 인덱스
CREATE INDEX idx_doc_item_material ON material_doc_item(material_no);
CREATE INDEX idx_doc_header_posting ON material_doc_header(posting_date);

-- ----------------------------------------------------------------
-- NFC 태그 ↔ 자재 매핑
--   Web NFC로 읽은 태그 UID를 자재/저장위치로 해석한다.
-- ----------------------------------------------------------------
CREATE TABLE nfc_tag (
    tag_uid     VARCHAR(64) PRIMARY KEY,            -- NFC 태그 고유 UID
    material_no VARCHAR(18) NOT NULL REFERENCES material(material_no),
    plant_id    VARCHAR(4)  NOT NULL,
    sloc_id     VARCHAR(4)  NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (plant_id, sloc_id) REFERENCES storage_location(plant_id, sloc_id)
);

-- ----------------------------------------------------------------
-- 재고 스냅샷 이력 (History) — 이력성 엔터티
--   일/월말 시점의 재고 수량을 스냅샷으로 적재한다.
--   재고 회전율 등 기간 KPI 계산과 추세 분석의 근거가 된다.
--   (현재 재고는 stock 1건만 보관 → 과거 시점 재고는 이 이력에서 조회)
-- ----------------------------------------------------------------
CREATE TABLE stock_snapshot_history (
    snapshot_date     DATE        NOT NULL,            -- 스냅샷 기준일
    material_no       VARCHAR(18) NOT NULL REFERENCES material(material_no),
    plant_id          VARCHAR(4)  NOT NULL,
    sloc_id           VARCHAR(4)  NOT NULL,
    unrestricted_qty  NUMERIC(15,3) NOT NULL,          -- 해당 시점 가용재고
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_date, material_no, plant_id, sloc_id),
    FOREIGN KEY (plant_id, sloc_id) REFERENCES storage_location(plant_id, sloc_id)
);
CREATE INDEX idx_snapshot_material ON stock_snapshot_history(material_no, snapshot_date);

-- ----------------------------------------------------------------
-- 외부 데이터 (4단계에서 적재) — 수요예측 변수
-- ----------------------------------------------------------------

-- 일별 날씨 (기상청 공공 API)
CREATE TABLE ext_weather (
    obs_date    DATE PRIMARY KEY,
    region_code VARCHAR(10) NOT NULL DEFAULT '108',  -- 지점코드(서울 108 등)
    avg_temp    NUMERIC(5,2),                        -- 평균기온(℃)
    min_temp    NUMERIC(5,2),
    max_temp    NUMERIC(5,2),
    precip_mm   NUMERIC(6,2)                          -- 강수량(mm)
);

-- 공휴일 (공공 API)
CREATE TABLE ext_holiday (
    holiday_date DATE PRIMARY KEY,
    name         VARCHAR(60) NOT NULL,
    is_holiday   BOOLEAN NOT NULL DEFAULT TRUE
);
