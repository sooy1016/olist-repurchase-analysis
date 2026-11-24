-- =====================================================================
-- 40. 대시보드 자동화용 데이터 내보내기
--   ① orders_mart      → outputs/orders_mart.csv      (주문 1건 = 1행)
--   ② first_purchase   → outputs/first_purchase.csv   (첫 구매 고객 1명 = 1행)
--   내보낼 때: Workbench "Limit to 500 rows" → "Don't Limit", CSV는 UTF-8로 저장
-- =====================================================================
USE olist;

-- ---------------------------------------------------------------------
-- ① orders_mart (Tableau용 쿼리 + 날짜 2개 추가)
--   추가: delivered_date, estimated_date
--   → 기준월 시점에 이미 배송됐는지를 날짜로 판단하기 위해 필요
-- ---------------------------------------------------------------------
WITH items AS (
    SELECT order_id,
           SUM(price)         AS item_price,
           SUM(freight_value) AS freight
    FROM order_items
    GROUP BY order_id
),
rev AS (
    SELECT order_id, AVG(review_score) AS review_score
    FROM order_reviews
    GROUP BY order_id
)
SELECT o.order_id,
       c.customer_unique_id,
       c.customer_state,
       CASE WHEN c.customer_state IN ('SP','RJ','MG','ES') THEN '남동부'
            WHEN c.customer_state IN ('PR','SC','RS')      THEN '남부'
            WHEN c.customer_state IN ('DF','GO','MT','MS') THEN '중서부'
            WHEN c.customer_state IN ('AC','AP','AM','PA','RO','RR','TO') THEN '북부'
            ELSE '북동부' END                                AS region,
       DATE(o.order_purchase_timestamp)                     AS purchase_date,
       o.order_status,
       i.item_price, i.freight,
       i.item_price + i.freight                             AS gmv,
       1                                                    AS is_ordered,
       (o.order_approved_at IS NOT NULL)                    AS is_approved,
       (o.order_delivered_carrier_date IS NOT NULL)         AS is_shipped,
       (o.order_delivered_customer_date IS NOT NULL)        AS is_delivered,
       (o.order_delivered_customer_date IS NOT NULL
        AND DATE(o.order_delivered_customer_date) <= DATE(o.order_estimated_delivery_date)) AS is_on_time,
       DATEDIFF(o.order_delivered_customer_date, o.order_estimated_delivery_date) AS delay_days,
       r.review_score,
       DATE(o.order_delivered_customer_date)                AS delivered_date,   -- 추가
       DATE(o.order_estimated_delivery_date)                AS estimated_date    -- 추가
FROM orders o
JOIN customers c ON c.customer_id = o.customer_id
LEFT JOIN items i ON i.order_id = o.order_id
LEFT JOIN rev r   ON r.order_id = o.order_id
WHERE o.order_purchase_timestamp >= '2017-01-01'
  AND o.order_purchase_timestamp <  '2018-09-01'
  AND NOT (o.order_status = 'delivered'
           AND (o.order_approved_at IS NULL
             OR o.order_delivered_carrier_date IS NULL
             OR o.order_delivered_customer_date IS NULL));
-- 확인: 99,069 row(s) returned


-- ---------------------------------------------------------------------
-- ② first_purchase (32_ab_simulation_58071.sql의 ①을 대시보드용으로 수정)
--   바뀐 점
--     - 남동부 조건 삭제 → 전국 고객 (region 열로 남동부 구분)
--     - "배송 완료일 + 30일 <= 2018-08-31" 조건 삭제
--       → 이 조건은 파이썬에서 "배송 완료일 + 30일 <= 기준월 말일"로 적용
--     - 첫 주문 2018-09-01 이전으로 제한 (orders_mart와 기간 맞춤)
--     - 날짜 열(first_purchase_at, delivered_at, repurchase_at) 남김
--   재구매 정의는 그대로: 첫 주문과 다른 날 처음 다시 주문, 배송 완료 후 30일 이내
-- ---------------------------------------------------------------------
WITH v AS (                                   -- 취소 아닌 모든 주문 + 고객별 주문 순서
  SELECT c.customer_unique_id,
         c.customer_state,
         o.order_status,
         o.order_purchase_timestamp       AS t,
         o.order_delivered_carrier_date   AS carrier,
         o.order_delivered_customer_date  AS delivered,
         ROW_NUMBER() OVER (PARTITION BY c.customer_unique_id
                            ORDER BY o.order_purchase_timestamp, o.order_id) AS rn
  FROM orders o
  JOIN customers c ON c.customer_id = o.customer_id
  WHERE o.order_status NOT IN ('canceled', 'unavailable')
),
first_order AS (                              -- 첫 주문 = 대상 고객
  SELECT *
  FROM v
  WHERE rn = 1
    AND t >= '2017-01-01'
    AND t <  '2018-09-01'
    AND order_status = 'delivered'
    AND carrier IS NOT NULL
    AND delivered IS NOT NULL
    AND delivered >= carrier
),
first_rep AS (                                -- 첫 재구매 시각 (첫 주문과 다른 날)
  SELECT f.customer_unique_id,
         f.customer_state,
         f.t,
         f.delivered,
         MIN(w.t) AS t2
  FROM first_order f
  LEFT JOIN v w
         ON w.customer_unique_id = f.customer_unique_id
        AND w.rn > 1
        AND DATE(w.t) > DATE(f.t)
  GROUP BY f.customer_unique_id, f.customer_state, f.t, f.delivered
)
SELECT customer_unique_id,
       customer_state,
       CASE WHEN customer_state IN ('SP','RJ','MG','ES') THEN '남동부'
            WHEN customer_state IN ('PR','SC','RS')      THEN '남부'
            WHEN customer_state IN ('DF','GO','MT','MS') THEN '중서부'
            WHEN customer_state IN ('AC','AP','AM','PA','RO','RR','TO') THEN '북부'
            ELSE '북동부' END                                AS region,
       t          AS first_purchase_at,
       delivered  AS delivered_at,
       t2         AS repurchase_at,                         -- 재구매 없으면 NULL
       CASE WHEN t2 >= delivered AND t2 < delivered + INTERVAL 30 DAY
            THEN 1 ELSE 0 END AS rep30                      -- 배송 후 30일 이내 재구매
FROM first_rep;

-- 확인 (포트폴리오 A/B 대상과 같아야 함): 남동부 + 30일 관찰 가능 → 58,071명 / 344명 / 0.592%
-- 아래는 ②를 테이블로 저장했을 때 확인용. CSV만 내보낼 거면 파이썬에서 확인해도 됨.
-- SELECT COUNT(*), SUM(rep30), ROUND(100 * AVG(rep30), 3)
-- FROM first_purchase
-- WHERE region = '남동부' AND delivered_at + INTERVAL 30 DAY <= '2018-08-31';
