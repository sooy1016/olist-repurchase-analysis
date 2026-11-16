-- =====================================================================
-- 21. 같은 날 재구매   → docs/04_repurchase.md
--   13_repurchase.sql ① 에서 만든 repurchase_pair 테이블 사용 (먼저 실행)
-- =====================================================================
USE olist;

-- ---------------------------------------------------------------------
-- ① 같은 날 재구매 867건: 10분 안, 배송비, 결제수단, 할부
-- ---------------------------------------------------------------------
WITH sd AS (                                         -- 같은 날 두 번째 주문
  SELECT * FROM repurchase_pair WHERE DATE(t2) = DATE(t1)
),
fr AS (
  SELECT order_id, SUM(freight_value) AS freight FROM order_items GROUP BY order_id
),
pay AS (                                             -- 주문별 결제수단 목록, 최대 할부 개월
  SELECT order_id,
         GROUP_CONCAT(DISTINCT payment_type ORDER BY payment_type) AS pay_types,
         MAX(payment_installments)                                 AS installments
  FROM order_payments
  GROUP BY order_id
)
SELECT COUNT(*)                                                    AS n_same_day,
       ROUND(100 * AVG(TIMESTAMPDIFF(MINUTE, sd.t1, sd.t2) <= 10), 1) AS within_10min_pct,
       SUM(f1.freight > 0 AND f2.freight > 0)                      AS both_charged_freight,
       ROUND(100 * AVG(p1.pay_types = p2.pay_types), 1)            AS same_payment_pct,
       ROUND(100 * AVG(p1.installments <> p2.installments), 1)     AS diff_installments_pct
FROM sd
JOIN fr  f1 ON f1.order_id = sd.order1
JOIN fr  f2 ON f2.order_id = sd.order2
JOIN pay p1 ON p1.order_id = sd.order1
JOIN pay p2 ON p2.order_id = sd.order2;
-- [결과] 867 / 89.5%(약 90%) / 867(모두 배송비 부과) / 99.1% / 18.5%
--        같은 판매자 47.1%는 13_repurchase.sql ③ 결과


-- ---------------------------------------------------------------------
-- ② 한 주문에 판매자가 여러 명인 경우는 얼마나 되나
-- ---------------------------------------------------------------------
WITH ob AS (
  SELECT i.order_id, COUNT(*) AS n_items, COUNT(DISTINCT i.seller_id) AS n_sellers
  FROM order_items i
  JOIN orders o ON o.order_id = i.order_id
  WHERE o.order_purchase_timestamp >= '2017-01-01'
    AND o.order_purchase_timestamp <  '2018-09-01'
    AND o.order_status NOT IN ('canceled', 'unavailable')
  GROUP BY i.order_id
)
SELECT COUNT(*)                                                    AS n_orders,
       ROUND(100 * AVG(n_items > 1), 1)                            AS multi_item_pct,           -- 상품 여러 개 산 주문
       ROUND(100 * SUM(n_items > 1 AND n_sellers = 1) / SUM(n_items > 1), 1) AS one_seller_pct, -- 그중 판매자 1명
       ROUND(100 * AVG(n_sellers > 1), 1)                          AS multi_seller_pct
FROM ob;
-- [결과] 상품 여러 개 9.9%(약 10%) 중 86.9%(약 87%)가 판매자 1명, 판매자 여러 명인 주문은 전체의 1.3%
