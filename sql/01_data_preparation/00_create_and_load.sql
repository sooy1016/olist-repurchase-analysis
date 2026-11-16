-- =====================================================================
-- 00. 테이블 생성 + 데이터 적재 (MySQL 8)
-- =====================================================================
--   CSV 9개를 한 폴더에 두고 'C:/olist_data/' 를 실제 경로로 변경 (경로 구분자는 /)
--   LOCAL INFILE 허용 필요
-- =====================================================================

CREATE DATABASE IF NOT EXISTS olist DEFAULT CHARACTER SET utf8mb4;
USE olist;

-- ---------------------------------------------------------------------
-- 1. 테이블 생성
--   우편번호는 앞자리 0이 있어(예: 01037) 문자로 저장
-- ---------------------------------------------------------------------

DROP TABLE IF EXISTS orders;
CREATE TABLE orders (
  order_id                      VARCHAR(32) PRIMARY KEY,
  customer_id                   VARCHAR(32) NOT NULL,
  order_status                  VARCHAR(20),
  order_purchase_timestamp      DATETIME,
  order_approved_at             DATETIME NULL,
  order_delivered_carrier_date  DATETIME NULL,   -- 출고 시점
  order_delivered_customer_date DATETIME NULL,   -- 배송 완료 시점
  order_estimated_delivery_date DATETIME NULL,   -- 예상 배송일
  INDEX idx_orders_customer (customer_id)
);

DROP TABLE IF EXISTS customers;
CREATE TABLE customers (
  customer_id              VARCHAR(32) PRIMARY KEY,  -- 주문마다 새로 생기는 ID
  customer_unique_id       VARCHAR(32) NOT NULL,     -- 실제 고객 ID
  customer_zip_code_prefix VARCHAR(5),
  customer_city            VARCHAR(100),
  customer_state           CHAR(2),
  INDEX idx_customers_unique (customer_unique_id)
);

DROP TABLE IF EXISTS order_items;
CREATE TABLE order_items (
  order_id            VARCHAR(32),
  order_item_id       INT,              -- 주문 안에서 상품 순번 (같은 상품 2개면 행 2개)
  product_id          VARCHAR(32),
  seller_id           VARCHAR(32),
  shipping_limit_date DATETIME,
  price               DECIMAL(10,2),
  freight_value       DECIMAL(10,2),    -- 운임
  PRIMARY KEY (order_id, order_item_id),
  INDEX idx_items_product (product_id),
  INDEX idx_items_seller (seller_id)
);

DROP TABLE IF EXISTS order_payments;
CREATE TABLE order_payments (
  order_id             VARCHAR(32),
  payment_sequential   INT,             -- 한 주문에 결제수단을 여러 개 쓰면 1, 2, 3...
  payment_type         VARCHAR(20),
  payment_installments INT,             -- 할부 개월 수
  payment_value        DECIMAL(10,2),
  PRIMARY KEY (order_id, payment_sequential)
);

DROP TABLE IF EXISTS order_reviews;
CREATE TABLE order_reviews (
  review_id               VARCHAR(32),  -- 중복이 있어서 PRIMARY KEY로 쓸 수 없음
  order_id                VARCHAR(32),
  review_score            TINYINT,
  review_comment_title    VARCHAR(255) NULL,
  review_comment_message  TEXT NULL,
  review_creation_date    DATETIME,
  review_answer_timestamp DATETIME,
  INDEX idx_reviews_order (order_id),
  INDEX idx_reviews_id (review_id)
);

DROP TABLE IF EXISTS products;
CREATE TABLE products (
  product_id                 VARCHAR(32) PRIMARY KEY,
  product_category_name      VARCHAR(100) NULL,  -- 포르투갈어
  product_name_lenght        INT NULL,           -- 원본 컬럼명 오타(lenght) 그대로 유지
  product_description_lenght INT NULL,
  product_photos_qty         INT NULL,
  product_weight_g           INT NULL,
  product_length_cm          INT NULL,
  product_height_cm          INT NULL,
  product_width_cm           INT NULL
);

DROP TABLE IF EXISTS sellers;
CREATE TABLE sellers (
  seller_id              VARCHAR(32) PRIMARY KEY,
  seller_zip_code_prefix VARCHAR(5),
  seller_city            VARCHAR(100),
  seller_state           CHAR(2)
);

DROP TABLE IF EXISTS category_translation;
CREATE TABLE category_translation (
  product_category_name         VARCHAR(100) PRIMARY KEY,
  product_category_name_english VARCHAR(100)
);

DROP TABLE IF EXISTS geolocation;
CREATE TABLE geolocation (
  geolocation_zip_code_prefix VARCHAR(5),  -- 우편번호 하나에 좌표 여러 개 → PK 없음
  geolocation_lat             DOUBLE,
  geolocation_lng             DOUBLE,
  geolocation_city            VARCHAR(100),
  geolocation_state           CHAR(2),
  INDEX idx_geo_zip (geolocation_zip_code_prefix)
);

-- ---------------------------------------------------------------------
-- 2. 데이터 적재
--   ESCAPED BY '' : 리뷰 중 \ 로 끝나는 글이 있어 이스케이프 처리 해제
--   빈 칸은 NULLIF로 NULL 처리 (빈 날짜가 0000-00-00으로 들어가는 것 방지)
--   리뷰, 번역 파일은 줄바꿈이 \r\n
-- ---------------------------------------------------------------------

LOAD DATA LOCAL INFILE 'C:/olist_data/olist_orders_dataset.csv'
INTO TABLE orders
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY ''
LINES TERMINATED BY '\n'
IGNORE 1 LINES
(order_id, customer_id, order_status, order_purchase_timestamp,
 @approved, @carrier, @delivered, @estimated)
SET order_approved_at             = NULLIF(@approved, ''),
    order_delivered_carrier_date  = NULLIF(@carrier, ''),
    order_delivered_customer_date = NULLIF(@delivered, ''),
    order_estimated_delivery_date = NULLIF(@estimated, '');

LOAD DATA LOCAL INFILE 'C:/olist_data/olist_customers_dataset.csv'
INTO TABLE customers
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY ''
LINES TERMINATED BY '\n'
IGNORE 1 LINES;

LOAD DATA LOCAL INFILE 'C:/olist_data/olist_order_items_dataset.csv'
INTO TABLE order_items
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY ''
LINES TERMINATED BY '\n'
IGNORE 1 LINES;

LOAD DATA LOCAL INFILE 'C:/olist_data/olist_order_payments_dataset.csv'
INTO TABLE order_payments
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY ''
LINES TERMINATED BY '\n'
IGNORE 1 LINES;

LOAD DATA LOCAL INFILE 'C:/olist_data/olist_order_reviews_dataset.csv'
INTO TABLE order_reviews
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY ''
LINES TERMINATED BY '\r\n'
IGNORE 1 LINES
(review_id, order_id, review_score, @title, @msg, review_creation_date, review_answer_timestamp)
SET review_comment_title   = NULLIF(@title, ''),
    review_comment_message = NULLIF(@msg, '');

LOAD DATA LOCAL INFILE 'C:/olist_data/olist_products_dataset.csv'
INTO TABLE products
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY ''
LINES TERMINATED BY '\n'
IGNORE 1 LINES
(product_id, @cat, @name_len, @desc_len, @photos, @weight, @len, @height, @width)
SET product_category_name      = NULLIF(@cat, ''),
    product_name_lenght        = NULLIF(@name_len, ''),
    product_description_lenght = NULLIF(@desc_len, ''),
    product_photos_qty         = NULLIF(@photos, ''),
    product_weight_g           = NULLIF(@weight, ''),
    product_length_cm          = NULLIF(@len, ''),
    product_height_cm          = NULLIF(@height, ''),
    product_width_cm           = NULLIF(@width, '');

LOAD DATA LOCAL INFILE 'C:/olist_data/olist_sellers_dataset.csv'
INTO TABLE sellers
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY ''
LINES TERMINATED BY '\n'
IGNORE 1 LINES;

LOAD DATA LOCAL INFILE 'C:/olist_data/product_category_name_translation.csv'
INTO TABLE category_translation
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY ''
LINES TERMINATED BY '\r\n'
IGNORE 1 LINES;

LOAD DATA LOCAL INFILE 'C:/olist_data/olist_geolocation_dataset.csv'
INTO TABLE geolocation
FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY ''
LINES TERMINATED BY '\n'
IGNORE 1 LINES;

-- ---------------------------------------------------------------------
-- 3. 적재 확인
--   orders 99,441 / customers 99,441 / order_items 112,650 / order_payments 103,886
--   order_reviews 99,224 / products 32,951 / sellers 3,095 / category_translation 71
--   geolocation 1,000,163
-- ---------------------------------------------------------------------
SELECT 'orders' AS tbl, COUNT(*) AS n_rows FROM orders
UNION ALL SELECT 'customers', COUNT(*) FROM customers
UNION ALL SELECT 'order_items', COUNT(*) FROM order_items
UNION ALL SELECT 'order_payments', COUNT(*) FROM order_payments
UNION ALL SELECT 'order_reviews', COUNT(*) FROM order_reviews
UNION ALL SELECT 'products', COUNT(*) FROM products
UNION ALL SELECT 'sellers', COUNT(*) FROM sellers
UNION ALL SELECT 'category_translation', COUNT(*) FROM category_translation
UNION ALL SELECT 'geolocation', COUNT(*) FROM geolocation;
