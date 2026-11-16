-- =====================================================================
-- 20. 배송비 구조   → docs/02_eda.md
--   기준: 2017-01-01 ~ 2018-08-31, 취소·상품 없음 제외 (1-1 일치율만 전체 주문)
--   order_items 는 상품 1개 = 1행, freight_value 는 주문 배송비를 상품 행마다 나눠 적은 값
-- =====================================================================
USE olist;

-- ---------------------------------------------------------------------
-- ① 상품 가격 합 + 배송비 합 = 결제 금액 인가?
--   전체 주문 기준, 1헤알 이하 차이는 같은 것으로 봄
-- ---------------------------------------------------------------------
WITH it AS (
  SELECT order_id,
         COUNT(*)                   AS n_items,
         SUM(price + freight_value) AS item_total
  FROM order_items
  GROUP BY order_id
),
pay AS (
  SELECT order_id, SUM(payment_value) AS pay_total
  FROM order_payments
  GROUP BY order_id
)
SELECT CASE WHEN it.n_items = 1 THEN '상품 1개' ELSE '상품 2개 이상' END AS order_type,
       COUNT(*)                                                  AS n_orders,
       ROUND(100 * AVG(ABS(it.item_total - p.pay_total) <= 1), 2) AS match_pct
FROM it
JOIN pay p ON p.order_id = it.order_id
GROUP BY order_type
UNION ALL
SELECT '전체', COUNT(*), ROUND(100 * AVG(ABS(it.item_total - p.pay_total) <= 1), 2)
FROM it
JOIN pay p ON p.order_id = it.order_id;
-- [결과] 상품 1개 99.74% / 2개 이상 99.78% / 전체 99.75%


-- ---------------------------------------------------------------------
-- ② 같은 상품 2개 주문의 배송비 ÷ 1개 주문의 배송비
--   같은 상품 + 같은 고객 주(거리 비슷)끼리 1개 주문과 2개 주문의 평균 배송비를 비교한 뒤 비율을 평균
-- ---------------------------------------------------------------------
WITH ob AS (                                       -- 한 종류 상품만 1개 또는 2개 산 주문
  SELECT i.order_id,
         MIN(i.product_id)          AS product_id,
         c.customer_state,
         COUNT(*)                   AS qty,
         SUM(i.freight_value)       AS freight
  FROM order_items i
  JOIN orders o    ON o.order_id    = i.order_id
  JOIN customers c ON c.customer_id = o.customer_id
  WHERE o.order_purchase_timestamp >= '2017-01-01'
    AND o.order_purchase_timestamp <  '2018-09-01'
    AND o.order_status NOT IN ('canceled', 'unavailable')
  GROUP BY i.order_id, c.customer_state
  HAVING COUNT(DISTINCT i.product_id) = 1 AND COUNT(*) IN (1, 2)
),
pair AS (                                          -- 상품 × 주 별 1개·2개 주문 평균 배송비
  SELECT product_id, customer_state,
         AVG(CASE WHEN qty = 1 THEN freight END) AS f1,
         AVG(CASE WHEN qty = 2 THEN freight END) AS f2
  FROM ob
  GROUP BY product_id, customer_state
  HAVING f1 IS NOT NULL AND f2 IS NOT NULL
)
SELECT COUNT(*)               AS n_pairs,
       ROUND(AVG(f2 / f1), 2) AS ratio_2_vs_1
FROM pair;
-- [결과] 1.98배 → 묶음 배송 할인은 거의 없음


-- ---------------------------------------------------------------------
-- ③ 주문 금액 구간별 배송비
-- ---------------------------------------------------------------------
WITH ob AS (
  SELECT o.order_id, SUM(i.price) AS gmv, SUM(i.freight_value) AS freight
  FROM orders o
  JOIN order_items i ON o.order_id = i.order_id
  WHERE o.order_purchase_timestamp >= '2017-01-01'
    AND o.order_purchase_timestamp <  '2018-09-01'
    AND o.order_status NOT IN ('canceled', 'unavailable')
  GROUP BY o.order_id
)
SELECT CASE WHEN gmv < 50   THEN '1) 50 미만'
            WHEN gmv < 100  THEN '2) 50~100'
            WHEN gmv < 200  THEN '3) 100~200'
            WHEN gmv < 500  THEN '4) 200~500'
            WHEN gmv < 1000 THEN '5) 500~1,000'
            ELSE                 '6) 1,000 이상' END AS value_band,
       COUNT(*)                                  AS n_orders,
       SUM(freight = 0)                          AS n_free_shipping,   -- 무료배송 주문 수
       ROUND(AVG(freight), 1)                    AS avg_freight,       -- 평균 배송비
       ROUND(100 * SUM(freight) / SUM(gmv), 1)   AS freight_to_gmv_pct -- 상품 금액 대비 배송비
FROM ob
GROUP BY value_band
ORDER BY value_band;
-- [결과] 50 미만 29,173 / 0 / 15.4 / 48.5% … 1,000 이상 927 / 0 / 77.5 / 4.8%


-- ---------------------------------------------------------------------
-- ④ 무료배송 주문은 누가, 언제?
-- ---------------------------------------------------------------------
WITH ob AS (
  SELECT o.order_id, o.order_purchase_timestamp AS t,
         MIN(i.seller_id) AS seller_id, SUM(i.freight_value) AS freight
  FROM orders o
  JOIN order_items i ON o.order_id = i.order_id
  WHERE o.order_purchase_timestamp >= '2017-01-01'
    AND o.order_purchase_timestamp <  '2018-09-01'
    AND o.order_status NOT IN ('canceled', 'unavailable')
  GROUP BY o.order_id, o.order_purchase_timestamp
)
SELECT seller_id, COUNT(*) AS n_free_orders, MIN(DATE(t)) AS first_day, MAX(DATE(t)) AS last_day
FROM ob
WHERE freight = 0
GROUP BY seller_id
ORDER BY n_free_orders DESC;
-- [결과] 8명, 338건 중 326건이 2018년 4~5월


-- ---------------------------------------------------------------------
-- ⑤ 권역별 주문당 평균 배송비
-- ---------------------------------------------------------------------
WITH ob AS (
  SELECT o.order_id,
         CASE WHEN c.customer_state IN ('SP','RJ','MG','ES')                          THEN '1) 남동부'
              WHEN c.customer_state IN ('PR','SC','RS')                               THEN '2) 남부'
              WHEN c.customer_state IN ('DF','GO','MT','MS')                          THEN '3) 중서부'
              WHEN c.customer_state IN ('BA','PE','CE','MA','PB','PI','RN','AL','SE') THEN '4) 북동부'
              ELSE                                                                         '5) 북부' END AS region,
         SUM(i.price) AS gmv, SUM(i.freight_value) AS freight
  FROM orders o
  JOIN customers c   ON o.customer_id = c.customer_id
  JOIN order_items i ON o.order_id    = i.order_id
  WHERE o.order_purchase_timestamp >= '2017-01-01'
    AND o.order_purchase_timestamp <  '2018-09-01'
    AND o.order_status NOT IN ('canceled', 'unavailable')
  GROUP BY o.order_id, region
)
SELECT region,
       ROUND(AVG(freight), 1)                           AS avg_freight_per_order,
       ROUND(100 * SUM(freight) / SUM(gmv + freight), 1) AS freight_share_pct     -- 배송비 ÷ (상품 + 배송비)
FROM ob
GROUP BY region
ORDER BY region;
-- [결과] 남동부 19.9 / 13.2% … 북부 41.4 / 18.5%
