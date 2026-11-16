-- =====================================================================
-- 14. 퍼널 분석   → docs/03_funnel_delivery.md
-- 기준: 2017-01-01 ~ 2018-08-31 주문
--   취소(canceled)·상품 없음(unavailable)은 이탈로 보고 포함
--   delivered인데 날짜가 빈 주문 23건은 제외 (날짜 누락이 이탈로 세어지는 것 방지)
-- 단계: 주문 → 결제 승인 → 출고 → 배송 완료 (날짜가 있으면 그 단계를 통과한 것으로 봄)
-- =====================================================================
USE olist;

-- ---------------------------------------------------------------------
-- ① 단계별 통과 주문 수와 전환율
-- ---------------------------------------------------------------------
WITH base AS (
  SELECT *
  FROM orders
  WHERE order_purchase_timestamp >= '2017-01-01'
    AND order_purchase_timestamp <  '2018-09-01'
    AND NOT (order_status = 'delivered'
             AND (order_approved_at IS NULL
               OR order_delivered_carrier_date IS NULL
               OR order_delivered_customer_date IS NULL))
),
funnel AS (
  SELECT COUNT(*)                             AS s1_ordered,
         COUNT(order_approved_at)             AS s2_approved,
         COUNT(order_delivered_carrier_date)  AS s3_shipped,
         COUNT(order_delivered_customer_date) AS s4_delivered
  FROM base
)
SELECT '1. 주문'     AS stage, s1_ordered   AS n_orders, 100.0 AS pct_of_ordered, NULL AS pct_of_prev FROM funnel
UNION ALL
SELECT '2. 결제 승인', s2_approved,  ROUND(100 * s2_approved  / s1_ordered, 2), ROUND(100 * s2_approved  / s1_ordered, 2)  FROM funnel
UNION ALL
SELECT '3. 출고',     s3_shipped,   ROUND(100 * s3_shipped   / s1_ordered, 2), ROUND(100 * s3_shipped   / s2_approved, 2) FROM funnel
UNION ALL
SELECT '4. 배송 완료', s4_delivered, ROUND(100 * s4_delivered / s1_ordered, 2), ROUND(100 * s4_delivered / s3_shipped, 2)  FROM funnel;
-- [결과] 99,069 → 98,948 (99.9%) → 97,355 (98.4%) → 96,189 (98.8%)

-- ---------------------------------------------------------------------
-- ② 어느 단계에서 멈췄나: 멈춘 단계 × 주문 상태 (참고용)
-- ---------------------------------------------------------------------
WITH base AS (
  SELECT *
  FROM orders
  WHERE order_purchase_timestamp >= '2017-01-01'
    AND order_purchase_timestamp <  '2018-09-01'
    AND NOT (order_status = 'delivered'
             AND (order_approved_at IS NULL
               OR order_delivered_carrier_date IS NULL
               OR order_delivered_customer_date IS NULL))
)
SELECT CASE WHEN order_approved_at IS NULL             THEN '1. 결제 승인 전'
            WHEN order_delivered_carrier_date IS NULL  THEN '2. 승인 후 출고 전'
            WHEN order_delivered_customer_date IS NULL THEN '3. 출고 후 배송 완료 전'
       END AS stopped_at,
       order_status,
       COUNT(*) AS n_orders
FROM base
WHERE order_delivered_customer_date IS NULL
GROUP BY stopped_at, order_status
ORDER BY stopped_at, n_orders DESC;

-- ---------------------------------------------------------------------
-- ③ 단계별 소요 시간 (배송 완료 주문, 음수 구간은 그 구간에서만 제외, 참고용)
-- ---------------------------------------------------------------------
WITH base AS (
  SELECT order_purchase_timestamp       AS t1,
         order_approved_at              AS t2,
         order_delivered_carrier_date   AS t3,
         order_delivered_customer_date  AS t4
  FROM orders
  WHERE order_purchase_timestamp >= '2017-01-01'
    AND order_purchase_timestamp <  '2018-09-01'
    AND order_status = 'delivered'
    AND order_approved_at IS NOT NULL
    AND order_delivered_carrier_date IS NOT NULL
    AND order_delivered_customer_date IS NOT NULL
)
SELECT '주문 → 결제 승인' AS step,
       ROUND(AVG(TIMESTAMPDIFF(MINUTE, t1, t2)) / 60, 1) AS avg_hours,
       ROUND(AVG(TIMESTAMPDIFF(MINUTE, t1, t2)) / 60 / 24, 1) AS avg_days,
       SUM(t2 >= t1) AS n_orders
FROM base WHERE t2 >= t1
UNION ALL
SELECT '결제 승인 → 출고',
       ROUND(AVG(TIMESTAMPDIFF(MINUTE, t2, t3)) / 60, 1),
       ROUND(AVG(TIMESTAMPDIFF(MINUTE, t2, t3)) / 60 / 24, 1),
       SUM(t3 >= t2)
FROM base WHERE t3 >= t2
UNION ALL
SELECT '출고 → 배송 완료',
       ROUND(AVG(TIMESTAMPDIFF(MINUTE, t3, t4)) / 60, 1),
       ROUND(AVG(TIMESTAMPDIFF(MINUTE, t3, t4)) / 60 / 24, 1),
       SUM(t4 >= t3)
FROM base WHERE t4 >= t3
UNION ALL
SELECT '전체 (주문 → 배송 완료)',
       ROUND(AVG(TIMESTAMPDIFF(MINUTE, t1, t4)) / 60, 1),
       ROUND(AVG(TIMESTAMPDIFF(MINUTE, t1, t4)) / 60 / 24, 1),
       SUM(t4 >= t1)
FROM base WHERE t4 >= t1;

-- ---------------------------------------------------------------------
-- ④ 예상 배송일보다 늦게 도착한 비율과 리뷰 점수 (참고용)
-- ---------------------------------------------------------------------
--   리뷰는 주문별 평균 점수로 1행으로 만든 뒤 붙임 (fan-out 방지)
WITH rv AS (
  SELECT order_id, AVG(review_score) AS score
  FROM order_reviews
  GROUP BY order_id
),
base AS (
  SELECT o.order_id,
         CASE WHEN DATE(o.order_delivered_customer_date) > DATE(o.order_estimated_delivery_date)
              THEN '지연' ELSE '제때' END AS on_time,
         rv.score
  FROM orders o
  LEFT JOIN rv ON o.order_id = rv.order_id
  WHERE o.order_purchase_timestamp >= '2017-01-01'
    AND o.order_purchase_timestamp <  '2018-09-01'
    AND o.order_status = 'delivered'
    AND o.order_delivered_customer_date IS NOT NULL
)
SELECT on_time,
       COUNT(*)                                          AS n_orders,
       ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)  AS order_pct,
       ROUND(AVG(score), 2)                              AS avg_review,
       ROUND(100 * AVG(score <= 2), 1)                   AS low_review_pct   -- 1~2점 비율
FROM base
GROUP BY on_time;

-- ---------------------------------------------------------------------
-- ⑤ 확장 퍼널: 배송 완료 이후 고객 경험 단계까지
--   저장: chart_data/07_funnel_experience.csv
--      g10 "주문부터 고객 만족까지 퍼널": 4단계 주문 수
--   제때 도착 = 실제 배송일이 예상 배송일 당일 또는 그 이전 (날짜만 비교)
--   만족 = 주문별 평균 리뷰 4점 이상 (리뷰가 없는 주문은 만족으로 세지 않음)
-- ---------------------------------------------------------------------
WITH rv AS (
  SELECT order_id, AVG(review_score) AS score
  FROM order_reviews
  GROUP BY order_id
),
base AS (
  SELECT o.*, rv.score,
         (o.order_delivered_customer_date IS NOT NULL
          AND DATE(o.order_delivered_customer_date) <= DATE(o.order_estimated_delivery_date)) AS on_time
  FROM orders o
  LEFT JOIN rv ON o.order_id = rv.order_id
  WHERE o.order_purchase_timestamp >= '2017-01-01'
    AND o.order_purchase_timestamp <  '2018-09-01'
    AND NOT (o.order_status = 'delivered'
             AND (o.order_approved_at IS NULL
               OR o.order_delivered_carrier_date IS NULL
               OR o.order_delivered_customer_date IS NULL))
)
SELECT COUNT(*)                             AS s1_ordered,
       COUNT(order_delivered_customer_date) AS s2_delivered,
       SUM(on_time)                         AS s3_on_time,
       SUM(on_time AND score IS NOT NULL)   AS reviewed_on_time,   -- 제때 도착 중 리뷰 작성
       SUM(on_time AND score >= 4)          AS s4_satisfied
FROM base;
-- [결과] 99,069 → 96,189 (97.1%) → 89,658 (90.5%) → 73,703 (74.4%), 제때 도착 중 리뷰 작성 89,168건(99.5%)

-- ---------------------------------------------------------------------
-- ⑥ 제때 vs 지연: 리뷰를 쓴 주문 중 만족(4점 이상) 비율
-- ---------------------------------------------------------------------
WITH rv AS (
  SELECT order_id, AVG(review_score) AS score
  FROM order_reviews
  GROUP BY order_id
),
base AS (
  SELECT CASE WHEN DATE(o.order_delivered_customer_date) > DATE(o.order_estimated_delivery_date)
              THEN '지연' ELSE '제때' END AS on_time,
         rv.score
  FROM orders o
  JOIN rv ON o.order_id = rv.order_id          -- 리뷰가 있는 주문만
  WHERE o.order_purchase_timestamp >= '2017-01-01'
    AND o.order_purchase_timestamp <  '2018-09-01'
    AND o.order_status = 'delivered'
    AND o.order_approved_at IS NOT NULL
    AND o.order_delivered_carrier_date IS NOT NULL
    AND o.order_delivered_customer_date IS NOT NULL
)
SELECT on_time,
       COUNT(*)                         AS n_reviewed,
       SUM(score >= 4)                  AS n_satisfied,
       ROUND(100 * AVG(score >= 4), 1)  AS satisfied_pct
FROM base
GROUP BY on_time;
-- [결과] 제때 82.7%, 지연 26.7%

-- ---------------------------------------------------------------------
-- ⑦ 예상 배송일 대비 며칠 일찍/늦게 왔나 × 리뷰
--   저장: chart_data/08_delay_band_review.csv
--      g11 "예상 배송일 대비 도착 시점별 1~2점 리뷰 비율": delay_band, low_review_pct
--   delay_days: 양수 = 늦음, 음수 = 일찍
-- ---------------------------------------------------------------------
WITH rv AS (
  SELECT order_id, AVG(review_score) AS score
  FROM order_reviews
  GROUP BY order_id
),
base AS (
  SELECT o.order_id,
         DATEDIFF(o.order_delivered_customer_date, o.order_estimated_delivery_date) AS delay_days,
         rv.score
  FROM orders o
  LEFT JOIN rv ON o.order_id = rv.order_id
  WHERE o.order_purchase_timestamp >= '2017-01-01'
    AND o.order_purchase_timestamp <  '2018-09-01'
    AND o.order_status = 'delivered'
    AND o.order_delivered_customer_date IS NOT NULL
)
SELECT CASE WHEN delay_days <= -15 THEN '1) 15일 이상 일찍'
            WHEN delay_days <= -8  THEN '2) 8~14일 일찍'
            WHEN delay_days <= -1  THEN '3) 1~7일 일찍'
            WHEN delay_days = 0    THEN '4) 예상일 당일'
            WHEN delay_days <= 3   THEN '5) 1~3일 지연'
            WHEN delay_days <= 7   THEN '6) 4~7일 지연'
            WHEN delay_days <= 14  THEN '7) 8~14일 지연'
            ELSE                        '8) 15일 이상 지연' END AS delay_band,
       COUNT(*)                                         AS n_orders,
       ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS order_pct,
       ROUND(AVG(score), 2)                             AS avg_review,
       ROUND(100 * AVG(score <= 2), 1)                  AS low_review_pct
FROM base
GROUP BY delay_band
ORDER BY delay_band;
-- [결과] 1~2점 비율 9.0 / 8.9 / 10.2 / 12.3 / 32.2 / 67.6 / 80.1 / 78.2%

-- ---------------------------------------------------------------------
-- ⑧ 제때 vs 지연: 주문 비중과 1~2점 리뷰 중 비중
--   리뷰가 있는 배송 완료 주문 기준
-- ---------------------------------------------------------------------
WITH rv AS (
  SELECT order_id, AVG(review_score) AS score
  FROM order_reviews
  GROUP BY order_id
),
base AS (
  SELECT CASE WHEN DATE(o.order_delivered_customer_date) > DATE(o.order_estimated_delivery_date)
              THEN '지연' ELSE '제때' END AS on_time,
         rv.score
  FROM orders o
  JOIN rv ON o.order_id = rv.order_id
  WHERE o.order_purchase_timestamp >= '2017-01-01'
    AND o.order_purchase_timestamp <  '2018-09-01'
    AND o.order_status = 'delivered'
    AND o.order_approved_at IS NOT NULL
    AND o.order_delivered_carrier_date IS NOT NULL
    AND o.order_delivered_customer_date IS NOT NULL
)
SELECT on_time,
       ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 1)               AS order_pct,       -- 배송 주문 비중
       SUM(score <= 2)                                                AS n_low_review,    -- 1~2점 리뷰 수
       ROUND(100 * SUM(score <= 2) / SUM(SUM(score <= 2)) OVER (), 1) AS low_review_share -- 1~2점 리뷰 중 비중
FROM base
GROUP BY on_time;
-- [결과] 제때 93.3% / 8,214건 / 67.4%, 지연 6.7% / 3,977건 / 32.6%


-- ---------------------------------------------------------------------
-- ⑨ 예상 배송일 vs 실제 배송일 (평균)
-- ---------------------------------------------------------------------
WITH rv AS (
  SELECT order_id FROM order_reviews GROUP BY order_id
)
SELECT COUNT(*) AS n_reviewed,
       ROUND(AVG(DATEDIFF(o.order_estimated_delivery_date, o.order_purchase_timestamp)), 1)        AS avg_promised_days,
       ROUND(AVG(TIMESTAMPDIFF(MINUTE, o.order_purchase_timestamp, o.order_delivered_customer_date)) / 1440, 1) AS avg_actual_days,
       ROUND(100 * AVG(DATE(o.order_delivered_customer_date) < DATE(o.order_estimated_delivery_date)), 1) AS early_pct
FROM orders o
JOIN rv ON o.order_id = rv.order_id
WHERE o.order_purchase_timestamp >= '2017-01-01'
  AND o.order_purchase_timestamp <  '2018-09-01'
  AND o.order_status = 'delivered'
  AND o.order_approved_at IS NOT NULL
  AND o.order_delivered_carrier_date IS NOT NULL
  AND o.order_delivered_customer_date IS NOT NULL;
-- [결과] 95,545건 / 24.3일 / 12.5일 / 92.0%


-- ---------------------------------------------------------------------
-- ⑩ 주별: 지연 비율과 제때·지연 주문의 1~2점 비율
-- ---------------------------------------------------------------------
WITH rv AS (
  SELECT order_id, AVG(review_score) AS score
  FROM order_reviews
  GROUP BY order_id
),
base AS (
  SELECT c.customer_state AS state,
         (DATE(o.order_delivered_customer_date) > DATE(o.order_estimated_delivery_date)) AS is_late,
         rv.score
  FROM orders o
  JOIN customers c ON o.customer_id = c.customer_id
  JOIN rv          ON o.order_id    = rv.order_id
  WHERE o.order_purchase_timestamp >= '2017-01-01'
    AND o.order_purchase_timestamp <  '2018-09-01'
    AND o.order_status = 'delivered'
    AND o.order_approved_at IS NOT NULL
    AND o.order_delivered_carrier_date IS NOT NULL
    AND o.order_delivered_customer_date IS NOT NULL
)
SELECT state,
       COUNT(*)                                                  AS n_reviewed,
       ROUND(100 * AVG(is_late), 1)                              AS late_pct,
       ROUND(100 * AVG(CASE WHEN is_late = 0 THEN score <= 2 END), 1) AS ontime_low_pct,
       ROUND(100 * AVG(CASE WHEN is_late = 1 THEN score <= 2 END), 1) AS late_low_pct
FROM base
GROUP BY state
ORDER BY n_reviewed DESC
LIMIT 8;
-- [결과] SP 40,165 / 4.4% / 8.6% / 54.3%, RJ 12,170 / 12.0% / 10.9% / 73.0% …
