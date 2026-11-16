-- =====================================================================
-- 22. 권역별 비교   → docs/02_eda.md
--   기준: 2017-01-01 ~ 2018-08-31, 취소·상품 없음 제외, 거래액 = 상품 가격 합계(배송비 제외)
-- =====================================================================
USE olist;

-- ---------------------------------------------------------------------
-- ① 권역별 고객·주문·거래액·객단가
--   고객 비중 분모 94,703명 = 11_state_customers_gmv.sql ② 전체 고객 수
--   (주문마다 배송지가 다른 고객이 있어 권역별 고객 수 합계는 94,726명으로 조금 많음)
-- ---------------------------------------------------------------------
WITH ob AS (                                          -- 주문 1건 = 1행
  SELECT o.order_id,
         c.customer_unique_id,
         CASE WHEN c.customer_state IN ('SP','RJ','MG','ES')                          THEN '1) 남동부'
              WHEN c.customer_state IN ('PR','SC','RS')                               THEN '2) 남부'
              WHEN c.customer_state IN ('DF','GO','MT','MS')                          THEN '3) 중서부'
              WHEN c.customer_state IN ('BA','PE','CE','MA','PB','PI','RN','AL','SE') THEN '4) 북동부'
              ELSE                                                                         '5) 북부' END AS region,
         SUM(i.price) AS gmv
  FROM orders o
  JOIN customers c   ON o.customer_id = c.customer_id
  JOIN order_items i ON o.order_id    = i.order_id
  WHERE o.order_purchase_timestamp >= '2017-01-01'
    AND o.order_purchase_timestamp <  '2018-09-01'
    AND o.order_status NOT IN ('canceled', 'unavailable')
  GROUP BY o.order_id, c.customer_unique_id, region
)
SELECT region,
       COUNT(DISTINCT customer_unique_id)                               AS n_customers,
       ROUND(100 * COUNT(DISTINCT customer_unique_id) / 94703, 1)       AS customer_pct,
       COUNT(*)                                                         AS n_orders,
       ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)                 AS order_pct,
       ROUND(COUNT(*) / COUNT(DISTINCT customer_unique_id), 3)          AS orders_per_customer,  -- 1인당 주문 수
       ROUND(SUM(gmv), 0)                                               AS gmv,
       ROUND(100 * SUM(gmv) / SUM(SUM(gmv)) OVER (), 1)                 AS gmv_pct,
       ROUND(SUM(gmv) / COUNT(*), 1)                                    AS aov,                  -- 객단가
       ROUND(SUM(gmv) / COUNT(DISTINCT customer_unique_id), 1)          AS gmv_per_customer      -- 1인당 거래액
FROM ob
GROUP BY region
ORDER BY region;
-- [결과] 남동부 64,885 / 68.5% / 67,146 / 68.6% / 1.035 / 8,794,685 / 65.4% / 131.0 / 135.5
--        합계 거래액 13,449,530, 전체 객단가 137.4


-- ---------------------------------------------------------------------
-- ② 큰 주문(200헤알 이상)
-- ---------------------------------------------------------------------
WITH ob AS (
  SELECT o.order_id,
         CASE WHEN c.customer_state IN ('SP','RJ','MG','ES') THEN '남동부'
              WHEN c.customer_state IN ('BA','PE','CE','MA','PB','PI','RN','AL','SE',
                                        'PA','AM','TO','RO','AC','AP','RR') THEN '북부+북동부'
              ELSE '기타' END AS grp,
         SUM(i.price) AS gmv
  FROM orders o
  JOIN customers c   ON o.customer_id = c.customer_id
  JOIN order_items i ON o.order_id    = i.order_id
  WHERE o.order_purchase_timestamp >= '2017-01-01'
    AND o.order_purchase_timestamp <  '2018-09-01'
    AND o.order_status NOT IN ('canceled', 'unavailable')
  GROUP BY o.order_id, grp
)
SELECT grp,
       COUNT(*)                                                    AS n_orders,
       SUM(gmv >= 200)                                             AS n_big,
       ROUND(100 * AVG(gmv >= 200), 1)                             AS big_pct,           -- 지역 주문 중 큰 주문 비율
       ROUND(100 * SUM(gmv >= 200) / SUM(SUM(gmv >= 200)) OVER (), 1) AS big_share,      -- 전국 큰 주문 중 지역 몫
       ROUND(SUM(gmv) / COUNT(*), 0)                               AS aov,
       ROUND(100 * SUM(gmv) / SUM(SUM(gmv)) OVER (), 1)            AS gmv_pct
FROM ob
GROUP BY grp;
-- [결과] 남동부 67,146 / 9,468 / 14.1% / 63.4% / 131 / 65.4%
--        북부+북동부 11,100 / 2,301 / 20.7% / 15.4% / 168 / 13.9%

-- 전국: 큰 주문 비율·평균 금액·거래액 비중
WITH ob AS (
  SELECT o.order_id, SUM(i.price) AS gmv
  FROM orders o
  JOIN order_items i ON o.order_id = i.order_id
  WHERE o.order_purchase_timestamp >= '2017-01-01'
    AND o.order_purchase_timestamp <  '2018-09-01'
    AND o.order_status NOT IN ('canceled', 'unavailable')
  GROUP BY o.order_id
)
SELECT ROUND(100 * AVG(gmv >= 200), 1)                                    AS big_order_pct,
       ROUND(AVG(CASE WHEN gmv >= 200 THEN gmv END), 0)                   AS big_order_avg,
       ROUND(100 * SUM(CASE WHEN gmv >= 200 THEN gmv END) / SUM(gmv), 1)  AS big_gmv_pct
FROM ob;
-- [결과] 15.2%(약 15%) / 449 / 49.9%
