-- =====================================================================
-- 11. 지역(주)별 고객 수·거래액·객단가·배송비 비중   → docs/02_eda.md
--   기간: 2017-01-01 ~ 2018-08-31, 취소·상품 없음 제외
--   거래액 = 상품 가격 합계, 배송비 비중 = 배송비 ÷ (상품 가격 + 배송비)
-- =====================================================================
USE olist;

-- ---------------------------------------------------------------------
-- ① 주별 집계
--   저장: chart_data/02_state_summary.csv
--      g03 "주별 고객 수"         : customer_state, n_customers (비중 = n_customers ÷ ② 전체 고객 수)
--      g04 "주별 거래액"          : customer_state, gmv, gmv_pct
--      g05 "주별 배송비 비중과 객단가": customer_state, freight_pct(x), avg_order_value(y), n_orders(점 크기)
-- ---------------------------------------------------------------------
WITH order_base AS (                           -- 주문 1건 = 1행
  SELECT o.order_id,
         c.customer_unique_id,
         c.customer_state,
         SUM(i.price)         AS gmv,
         SUM(i.freight_value) AS freight
  FROM orders o
  JOIN customers   c ON o.customer_id = c.customer_id
  JOIN order_items i ON o.order_id    = i.order_id
  WHERE o.order_purchase_timestamp >= '2017-01-01'
    AND o.order_purchase_timestamp <  '2018-09-01'
    AND o.order_status NOT IN ('canceled', 'unavailable')
  GROUP BY o.order_id, c.customer_unique_id, c.customer_state
)
SELECT customer_state,
       COUNT(DISTINCT customer_unique_id)                 AS n_customers,
       COUNT(*)                                           AS n_orders,
       ROUND(SUM(gmv), 0)                                 AS gmv,
       ROUND(100 * SUM(gmv) / SUM(SUM(gmv)) OVER (), 1)   AS gmv_pct,
       ROUND(SUM(gmv) / COUNT(*), 1)                      AS avg_order_value,   -- 객단가
       ROUND(100 * SUM(freight) / SUM(gmv + freight), 1)  AS freight_pct        -- 배송비 비중
FROM order_base
GROUP BY customer_state
ORDER BY gmv DESC;
-- [결과] SP 고객 39,648명 / 거래액 515만(38.3%) / 객단가 125.6 / 배송비 비중 12.2%


-- ---------------------------------------------------------------------
-- ② 전체 고객 수 (g03 비중의 분모)
--   주를 옮겨 주문한 고객이 있어 ①의 고객 수 합계(94,740)보다 조금 적음
-- ---------------------------------------------------------------------
SELECT COUNT(DISTINCT c.customer_unique_id) AS total_customers
FROM orders o
JOIN customers c ON o.customer_id = c.customer_id
WHERE o.order_purchase_timestamp >= '2017-01-01'
  AND o.order_purchase_timestamp <  '2018-09-01'
  AND o.order_status NOT IN ('canceled', 'unavailable')
  AND o.order_id IN (SELECT order_id FROM order_items);
-- [결과] 94,703명 → SP 39,648 ÷ 94,703 = 41.9%
