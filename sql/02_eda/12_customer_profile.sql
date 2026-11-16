-- =====================================================================
-- 12. 주 고객층   → docs/02_eda.md
-- 기준: 2017-01-01 ~ 2018-08-31, 취소(canceled)·상품 없음(unavailable) 제외
--       고객 = customer_unique_id, 거래액 = 상품 가격(price) 합계
-- =====================================================================
USE olist;
-- ---------------------------------------------------------------------
-- A. 구매 횟수별 고객: 몇 번 산 고객이 얼마나 되나
--   저장: chart_data/03_purchase_count.csv
--      g06 "구매 횟수별 고객 1명당 거래액": purchase_cnt, gmv_per_customer, customer_pct
-- ---------------------------------------------------------------------
--   order_base: 주문 1건 = 1행 → cust: 고객 1명 = 1행
WITH order_base AS (
  SELECT o.order_id, c.customer_unique_id, SUM(i.price) AS gmv
  FROM orders o
  JOIN customers c   ON o.customer_id = c.customer_id
  JOIN order_items i ON o.order_id = i.order_id
  WHERE o.order_purchase_timestamp >= '2017-01-01'
    AND o.order_purchase_timestamp <  '2018-09-01'
    AND o.order_status NOT IN ('canceled', 'unavailable')
  GROUP BY o.order_id, c.customer_unique_id
),
cust AS (
  SELECT customer_unique_id, COUNT(*) AS n_orders, SUM(gmv) AS gmv
  FROM order_base
  GROUP BY customer_unique_id
)
SELECT CASE WHEN n_orders = 1 THEN '1회' WHEN n_orders = 2 THEN '2회' ELSE '3회 이상' END AS purchase_cnt,
       COUNT(*) AS n_customers,
       ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS customer_pct,
       ROUND(SUM(gmv), 0) AS gmv,
       ROUND(100 * SUM(gmv) / SUM(SUM(gmv)) OVER (), 1) AS gmv_pct,
       ROUND(SUM(gmv) / COUNT(*), 1) AS gmv_per_customer          -- 고객 1명당 거래액
FROM cust
GROUP BY purchase_cnt
ORDER BY purchase_cnt;
-- [결과] 1회 97.0%(거래액 94.4%, 1인당 138.3) / 2회 2.8%(245.4) / 3회 이상 0.2%(423.0)


-- ---------------------------------------------------------------------
-- B. 결제수단 (참고용, 주문 기준)
--   결제수단이 여러 개인 주문은 결제액이 가장 큰 수단을 대표로 (rn = 1)
-- ---------------------------------------------------------------------
WITH order_base AS (
  SELECT o.order_id, SUM(i.price) AS gmv
  FROM orders o
  JOIN order_items i ON o.order_id = i.order_id
  WHERE o.order_purchase_timestamp >= '2017-01-01'
    AND o.order_purchase_timestamp <  '2018-09-01'
    AND o.order_status NOT IN ('canceled', 'unavailable')
  GROUP BY o.order_id
),
main_pay AS (
  SELECT order_id, payment_type,
         ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY payment_value DESC, payment_sequential) AS rn
  FROM order_payments
)
SELECT m.payment_type,
       COUNT(*)                                          AS n_orders,
       ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)  AS order_pct,
       ROUND(SUM(b.gmv), 0)                              AS gmv,
       ROUND(100 * SUM(b.gmv) / SUM(SUM(b.gmv)) OVER (), 1) AS gmv_pct
FROM order_base b
JOIN main_pay m ON b.order_id = m.order_id AND m.rn = 1
GROUP BY m.payment_type
ORDER BY n_orders DESC;

-- ---------------------------------------------------------------------
-- C. 신용카드 할부 개월 수 (결제 건 기준, 참고용)
-- ---------------------------------------------------------------------
WITH valid AS (
  SELECT order_id FROM orders
  WHERE order_purchase_timestamp >= '2017-01-01'
    AND order_purchase_timestamp <  '2018-09-01'
    AND order_status NOT IN ('canceled', 'unavailable')
)
SELECT CASE WHEN p.payment_installments <= 1 THEN '일시불'
            WHEN p.payment_installments <= 3 THEN '2~3개월'
            WHEN p.payment_installments <= 6 THEN '4~6개월'
            ELSE '7개월 이상' END AS installments,
       COUNT(*) AS n_payments,
       ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM order_payments p
JOIN valid v ON p.order_id = v.order_id
WHERE p.payment_type = 'credit_card'
GROUP BY installments
ORDER BY MIN(p.payment_installments);

-- ---------------------------------------------------------------------
-- D. 카테고리별 주문 수 상위 10개: 고객이 무엇을 많이 사나
--   저장: chart_data/04_category_top10.csv
--      g07 "카테고리별 주문 수 상위 10개": category, n_orders, order_pct
--   카테고리명: 영어 → 포르투갈어 → 'unknown'
--   n_orders: 해당 카테고리 상품이 들어 있는 주문 수
--   (여러 카테고리 상품이 섞인 주문 783건(0.8%)은 각 카테고리에 한 번씩 셈)
-- ---------------------------------------------------------------------
WITH valid AS (
  SELECT order_id
  FROM orders
  WHERE order_purchase_timestamp >= '2017-01-01'
    AND order_purchase_timestamp <  '2018-09-01'
    AND order_status NOT IN ('canceled', 'unavailable')
)
SELECT COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS category,
       COUNT(DISTINCT i.order_id) AS n_orders,
       ROUND(100 * COUNT(DISTINCT i.order_id) / (SELECT COUNT(*) FROM valid), 1) AS order_pct
FROM valid v
JOIN order_items i ON v.order_id = i.order_id
JOIN products p    ON i.product_id = p.product_id
LEFT JOIN category_translation t ON p.product_category_name = t.product_category_name
GROUP BY category
ORDER BY n_orders DESC
LIMIT 10;
-- [결과] 1위 bed_bath_table 9,394건(9.6%), 2위 health_beauty 8,757건(8.9%) … 상위 10개 합계 63.4%

-- ---------------------------------------------------------------------
-- E. 주문 금액 구간: 한 번에 얼마나 쓰나 (주문 1건 = 1행으로 줄인 뒤 구간 나눔)
--   저장: chart_data/05_order_value_band.csv
--      g08 "주문 금액 구간별 주문 수와 거래액 구성": value_band, order_pct, gmv_pct
-- ---------------------------------------------------------------------
WITH order_base AS (
  SELECT o.order_id, SUM(i.price) AS gmv
  FROM orders o
  JOIN order_items i ON o.order_id = i.order_id
  WHERE o.order_purchase_timestamp >= '2017-01-01'
    AND o.order_purchase_timestamp <  '2018-09-01'
    AND o.order_status NOT IN ('canceled', 'unavailable')
  GROUP BY o.order_id
)
SELECT CASE WHEN gmv < 50 THEN '1) 50 미만'
            WHEN gmv < 100 THEN '2) 50~100'
            WHEN gmv < 200 THEN '3) 100~200'
            WHEN gmv < 500 THEN '4) 200~500'
            ELSE '5) 500 이상' END AS value_band,
       COUNT(*) AS n_orders,
       ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS order_pct,
       ROUND(100 * SUM(gmv) / SUM(SUM(gmv)) OVER (), 1) AS gmv_pct
FROM order_base
GROUP BY value_band
ORDER BY value_band;
-- [결과] 주문 비중 29.8 / 28.7 / 26.2 / 11.6 / 3.7%, 거래액 비중 6.9 / 15.8 / 27.4 / 25.1 / 24.8%
--        → 200헤알 이상 주문 15.3%가 거래액의 49.9%
