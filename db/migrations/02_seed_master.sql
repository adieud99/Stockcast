-- ============================================================
-- StockCast — 마스터 데이터 시드 (조직/자재/이동유형/NFC)
--   출고 이력·재고·날씨 등 '대량 시계열' 데이터는 db/seeds/seed_transactions.py 가 생성.
-- ============================================================

-- 플랜트 / 저장위치
INSERT INTO plant (plant_id, name) VALUES
    ('1000', '서울 본사 물류센터');

INSERT INTO storage_location (plant_id, sloc_id, name) VALUES
    ('1000', '0001', '상온 창고'),
    ('1000', '0002', '시즌 상품 창고');

-- 자재 그룹
INSERT INTO material_group (group_code, name) VALUES
    ('HEAT',   '난방용품'),
    ('COOL',   '냉방용품'),
    ('DAILY',  '생활필수품'),
    ('BEV',    '음료');

-- 자재 마스터 (HAWA = 상품)
INSERT INTO material (material_no, description, material_type, group_code, base_uom) VALUES
    ('100001', '전기 히터',        'HAWA', 'HEAT',  'EA'),
    ('100002', '온수 매트',        'HAWA', 'HEAT',  'EA'),
    ('100003', '핫팩 (50개입)',     'HAWA', 'HEAT',  'EA'),
    ('200001', '선풍기',           'HAWA', 'COOL',  'EA'),
    ('200002', '휴대용 미니선풍기', 'HAWA', 'COOL',  'EA'),
    ('300001', '생수 2L (6입)',     'HAWA', 'BEV',   'EA'),
    ('300002', '물티슈',           'HAWA', 'DAILY', 'EA');

-- 이동 유형 (BWART) — 입고/출고
INSERT INTO movement_type (code, description, direction) VALUES
    ('101', '입고 (구매 입고)',  1),
    ('201', '출고 (소비/판매)', -1),
    ('561', '기초재고 입고',     1);

-- 재고 레코드 초기화 (수량/안전재고/ROP 는 시드 스크립트·분석엔진이 채움)
INSERT INTO stock (material_no, plant_id, sloc_id, unrestricted_qty) VALUES
    ('100001', '1000', '0002', 0),
    ('100002', '1000', '0002', 0),
    ('100003', '1000', '0002', 0),
    ('200001', '1000', '0002', 0),
    ('200002', '1000', '0002', 0),
    ('300001', '1000', '0001', 0),
    ('300002', '1000', '0001', 0);

-- NFC 태그 매핑 (데모용 UID → 자재)
INSERT INTO nfc_tag (tag_uid, material_no, plant_id, sloc_id) VALUES
    ('04:A1:B2:C3:D4:01', '100001', '1000', '0002'),
    ('04:A1:B2:C3:D4:02', '100002', '1000', '0002'),
    ('04:A1:B2:C3:D4:03', '100003', '1000', '0002'),
    ('04:A1:B2:C3:D4:04', '200001', '1000', '0002'),
    ('04:A1:B2:C3:D4:05', '200002', '1000', '0002'),
    ('04:A1:B2:C3:D4:06', '300001', '1000', '0001'),
    ('04:A1:B2:C3:D4:07', '300002', '1000', '0001');
