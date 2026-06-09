-- StockCast Oracle 스키마 (SQL Developer에서 실행)

CREATE TABLE ext_holiday (
	holiday_date DATE NOT NULL, 
	name VARCHAR2(60 CHAR) NOT NULL, 
	is_holiday SMALLINT NOT NULL, 
	PRIMARY KEY (holiday_date)
);

CREATE TABLE ext_weather (
	obs_date DATE NOT NULL, 
	region_code VARCHAR2(10 CHAR) NOT NULL, 
	avg_temp NUMERIC(5, 2), 
	min_temp NUMERIC(5, 2), 
	max_temp NUMERIC(5, 2), 
	precip_mm NUMERIC(6, 2), 
	PRIMARY KEY (obs_date)
);

CREATE TABLE material_doc_header (
	doc_no NUMBER(19) NOT NULL, 
	posting_date DATE NOT NULL, 
	doc_date DATE DEFAULT CURRENT_DATE NOT NULL, 
	source VARCHAR2(10 CHAR) NOT NULL, 
	created_at DATE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (doc_no)
);

CREATE TABLE material_group (
	group_code VARCHAR2(9 CHAR) NOT NULL, 
	name VARCHAR2(60 CHAR) NOT NULL, 
	PRIMARY KEY (group_code)
);

CREATE TABLE movement_type (
	code VARCHAR2(3 CHAR) NOT NULL, 
	description VARCHAR2(60 CHAR) NOT NULL, 
	direction SMALLINT NOT NULL, 
	PRIMARY KEY (code), 
	CHECK (direction IN (-1, 1))
);

CREATE TABLE plant (
	plant_id VARCHAR2(4 CHAR) NOT NULL, 
	name VARCHAR2(60 CHAR) NOT NULL, 
	created_at DATE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (plant_id)
);

CREATE TABLE material (
	material_no VARCHAR2(18 CHAR) NOT NULL, 
	description VARCHAR2(120 CHAR) NOT NULL, 
	material_type VARCHAR2(4 CHAR) NOT NULL, 
	group_code VARCHAR2(9 CHAR), 
	base_uom VARCHAR2(3 CHAR) NOT NULL, 
	created_at DATE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (material_no), 
	FOREIGN KEY(group_code) REFERENCES material_group (group_code)
);

CREATE TABLE storage_location (
	plant_id VARCHAR2(4 CHAR) NOT NULL, 
	sloc_id VARCHAR2(4 CHAR) NOT NULL, 
	name VARCHAR2(60 CHAR) NOT NULL, 
	PRIMARY KEY (plant_id, sloc_id), 
	FOREIGN KEY(plant_id) REFERENCES plant (plant_id)
);

CREATE TABLE material_doc_item (
	doc_no NUMBER(19) NOT NULL, 
	item_no INTEGER NOT NULL, 
	material_no VARCHAR2(18 CHAR) NOT NULL, 
	plant_id VARCHAR2(4 CHAR) NOT NULL, 
	sloc_id VARCHAR2(4 CHAR) NOT NULL, 
	movement_type VARCHAR2(3 CHAR) NOT NULL, 
	quantity NUMERIC(15, 3) NOT NULL, 
	uom VARCHAR2(3 CHAR) NOT NULL, 
	PRIMARY KEY (doc_no, item_no), 
	CHECK (quantity > 0), 
	FOREIGN KEY(plant_id, sloc_id) REFERENCES storage_location (plant_id, sloc_id), 
	FOREIGN KEY(doc_no) REFERENCES material_doc_header (doc_no) ON DELETE CASCADE, 
	FOREIGN KEY(material_no) REFERENCES material (material_no), 
	FOREIGN KEY(movement_type) REFERENCES movement_type (code)
);

CREATE TABLE nfc_tag (
	tag_uid VARCHAR2(64 CHAR) NOT NULL, 
	material_no VARCHAR2(18 CHAR) NOT NULL, 
	plant_id VARCHAR2(4 CHAR) NOT NULL, 
	sloc_id VARCHAR2(4 CHAR) NOT NULL, 
	created_at DATE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (tag_uid), 
	FOREIGN KEY(plant_id, sloc_id) REFERENCES storage_location (plant_id, sloc_id), 
	FOREIGN KEY(material_no) REFERENCES material (material_no)
);

CREATE TABLE stock (
	material_no VARCHAR2(18 CHAR) NOT NULL, 
	plant_id VARCHAR2(4 CHAR) NOT NULL, 
	sloc_id VARCHAR2(4 CHAR) NOT NULL, 
	unrestricted_qty NUMERIC(15, 3) NOT NULL, 
	safety_stock NUMERIC(15, 3) NOT NULL, 
	reorder_point NUMERIC(15, 3) NOT NULL, 
	updated_at DATE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (material_no, plant_id, sloc_id), 
	FOREIGN KEY(plant_id, sloc_id) REFERENCES storage_location (plant_id, sloc_id), 
	FOREIGN KEY(material_no) REFERENCES material (material_no)
);

CREATE TABLE stock_snapshot_history (
	snapshot_date DATE NOT NULL, 
	material_no VARCHAR2(18 CHAR) NOT NULL, 
	plant_id VARCHAR2(4 CHAR) NOT NULL, 
	sloc_id VARCHAR2(4 CHAR) NOT NULL, 
	unrestricted_qty NUMERIC(15, 3) NOT NULL, 
	created_at DATE DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (snapshot_date, material_no, plant_id, sloc_id), 
	FOREIGN KEY(plant_id, sloc_id) REFERENCES storage_location (plant_id, sloc_id), 
	FOREIGN KEY(material_no) REFERENCES material (material_no)
);
