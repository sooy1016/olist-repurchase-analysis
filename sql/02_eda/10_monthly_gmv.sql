-- =====================================================================
-- 10. 데이터 기간 설정 + 월별 거래액   → docs/02_eda.md
--   거래액 = 상품 가격(price) 합계 (배송비 제외)
--   취소(canceled)·상품 없음(unavailable) 주문 제외
-- =====================================================================
USE olist;

-- ---------------------------------------------------------------------
-- ① 월별 주문 수 + 마지막 기록 상태
--   전체 주문 기준 (취소 포함). 앞뒤 달의 주문 수가 매우 적어 분석 기간을 2017.01~2018.08로 정함
-- ---------------------------------------------------------------------
SELECT DATE_FORMAT(order_purchase_timestamp, '%Y-%m') AS ym,
       order_status,
       COUNT(*) AS n_orders
FROM orders
GROUP BY ym, order_status
ORDER BY ym, n_orders DESC;
-- [결과] 2016-09 4건, 2016-10 324건, 2016-12 1건, 2018-09 16건, 2018-10 4건
--        → 분석 기간 2017-01-01 ~ 2018-08-31 (제외 주문 349건)


-- ---------------------------------------------------------------------
-- ② 월별 거래액
--   저장: chart_data/01_monthly_gmv.csv
--      g01 "월별 거래액(2017.01~2018.08)", g02 "월별 거래액(2016.09~2018.09)"
-- ---------------------------------------------------------------------
WITH order_base AS (
  SELECT o.order_id,
         o.order_purchase_timestamp AS t,
         SUM(i.price)               AS gmv
  FROM orders o
  JOIN order_items i ON o.order_id = i.order_id
  WHERE o.order_status NOT IN ('canceled', 'unavailable')
  GROUP BY o.order_id, o.order_purchase_timestamp
)
SELECT YEAR(t)          AS yr,
       MONTH(t)         AS mon,
       COUNT(*)         AS n_orders,
       ROUND(SUM(gmv))  AS gmv
FROM order_base
GROUP BY yr, mon
ORDER BY yr, mon;
-- [결과] 2017-01 120,098 → 2017-11 1,003,862(최고) → 2018-03~05 약 99만 → 2018-08 848,860
