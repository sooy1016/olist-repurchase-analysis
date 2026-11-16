-- =====================================================================
-- 15. 지역(주)별 배송 지연   → docs/03_funnel_delivery.md
--   대상: 2017.01~2018.08 배송 완료 주문 (승인일·출고일·배송 완료일 있는 주문)
--   지연: DATE(실제 도착일) > DATE(예상 도착일)
-- =====================================================================
USE olist;

-- ---------------------------------------------------------------------
-- ① 주별 지연 주문 수·지연율
--   저장: chart_data/09_state_delay.csv
--      g12 "주별 지연 주문 수 상위 10개 주": state, n_late, late_share, late_pct, n_orders (상위 10행)
-- ---------------------------------------------------------------------
WITH rv AS (                                  -- 주문당 리뷰 점수 1개
  SELECT order_id, AVG(review_score) AS score
  FROM order_reviews
  GROUP BY order_id
),
base AS (                                     -- 배송 완료 주문 + 주 + 지연 여부
  SELECT c.customer_state AS state,
         CASE WHEN DATE(o.order_delivered_customer_date) > DATE(o.order_estimated_delivery_date)
              THEN 1 ELSE 0 END                                                     AS is_late,
         DATEDIFF(o.order_estimated_delivery_date, o.order_purchase_timestamp)       AS promised_days,
         DATEDIFF(o.order_delivered_customer_date, o.order_purchase_timestamp)       AS actual_days,
         rv.score
  FROM orders o
  JOIN customers c ON o.customer_id = c.customer_id
  LEFT JOIN rv     ON o.order_id    = rv.order_id      -- 리뷰 없는 주문도 지연율 계산엔 포함
  WHERE o.order_purchase_timestamp >= '2017-01-01'
    AND o.order_purchase_timestamp <  '2018-09-01'
    AND o.order_status = 'delivered'
    AND o.order_approved_at IS NOT NULL
    AND o.order_delivered_carrier_date IS NOT NULL
    AND o.order_delivered_customer_date IS NOT NULL
)
SELECT state,
       COUNT(*)                                              AS n_orders,         -- 배송 완료 주문 수
       SUM(is_late)                                          AS n_late,           -- 지연 주문 수
       ROUND(100 * AVG(is_late), 1)                          AS late_pct,         -- 지연율
       ROUND(100 * SUM(is_late) / SUM(SUM(is_late)) OVER (), 1) AS late_share,    -- 전체 지연 주문 중 비중
       SUM(is_late = 1 AND score <= 2)                       AS n_late_low,       -- 지연 + 1~2점 리뷰 수
       ROUND(AVG(promised_days), 1)                          AS avg_promised,     -- 평균 안내 배송일
       ROUND(AVG(actual_days), 1)                            AS avg_actual        -- 평균 실제 배송일
FROM base
GROUP BY state
ORDER BY n_late DESC;
-- [결과] 전체 지연 6,530건. SP 1,816건(27.8%, 지연율 4.5%), RJ 1,495건(22.9%, 12.1%) …
--        지연 + 1~2점 리뷰: RJ 1,063건 > SP 968건


-- ---------------------------------------------------------------------
-- ② 우편번호별 좌표 테이블 (한 번만 실행)
--   geolocation 은 우편번호 1개에 여러 행 → 우편번호별 평균 좌표로 1행으로 만듦
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS zip_coord;
CREATE TABLE zip_coord AS
SELECT geolocation_zip_code_prefix AS zip,
       AVG(geolocation_lat)        AS lat,
       AVG(geolocation_lng)        AS lng
FROM geolocation
GROUP BY geolocation_zip_code_prefix;
ALTER TABLE zip_coord ADD PRIMARY KEY (zip);
-- [결과] 19,015행


-- ---------------------------------------------------------------------
-- ③ 판매자 → 고객 거리, 안내·실제 배송일, 20일 초과 비율
--   저장: chart_data/11_state_distance.csv
--   거리: 위도·경도로 계산한 직선 거리(km, haversine 공식). 주문에 상품이 여러 개면 평균
--   여유 = 안내 배송일 − 실제 배송일
--   비교 주: 주문 1,000건 이상 주 중 판매자 평균 거리가 RJ(490km)와 ±50km 이내인 PR·MG,
--            기준점 SP(최대 시장), 원거리 참고 AM·AP·AC
-- ---------------------------------------------------------------------
WITH dist AS (
  SELECT i.order_id,
         AVG(6371 * 2 * ASIN(SQRT(
               POW(SIN(RADIANS(zc.lat - zs.lat) / 2), 2)
             + COS(RADIANS(zs.lat)) * COS(RADIANS(zc.lat))
             * POW(SIN(RADIANS(zc.lng - zs.lng) / 2), 2)))) AS km
  FROM order_items i
  JOIN orders o     ON o.order_id    = i.order_id
  JOIN customers c  ON c.customer_id = o.customer_id
  JOIN sellers s    ON s.seller_id   = i.seller_id
  JOIN zip_coord zc ON zc.zip = c.customer_zip_code_prefix     -- 고객 좌표
  JOIN zip_coord zs ON zs.zip = s.seller_zip_code_prefix       -- 판매자 좌표
  GROUP BY i.order_id
),
base AS (
  SELECT c.customer_state AS state,
         d.km,
         DATEDIFF(o.order_estimated_delivery_date, o.order_purchase_timestamp) AS promised_days,
         DATEDIFF(o.order_delivered_customer_date, o.order_purchase_timestamp) AS actual_days,
         (DATE(o.order_delivered_customer_date) > DATE(o.order_estimated_delivery_date)) AS is_late
  FROM orders o
  JOIN customers c ON o.customer_id = c.customer_id
  LEFT JOIN dist d ON d.order_id    = o.order_id
  WHERE o.order_purchase_timestamp >= '2017-01-01'
    AND o.order_purchase_timestamp <  '2018-09-01'
    AND o.order_status = 'delivered'
    AND o.order_approved_at IS NOT NULL
    AND o.order_delivered_carrier_date IS NOT NULL
    AND o.order_delivered_customer_date IS NOT NULL
)
SELECT state,
       COUNT(*)                                   AS n_orders,
       ROUND(AVG(km), 0)                          AS avg_km,           -- 평균 거리
       ROUND(AVG(promised_days), 1)               AS avg_promised,     -- 안내 배송
       ROUND(AVG(actual_days), 1)                 AS avg_actual,       -- 실제 배송
       ROUND(AVG(promised_days - actual_days), 1) AS avg_slack,        -- 여유
       ROUND(STDDEV_SAMP(actual_days), 1)         AS sd_actual,        -- 실제 배송 표준편차
       ROUND(100 * AVG(actual_days > 20), 1)      AS over20_pct,       -- 20일 초과
       ROUND(100 * AVG(is_late), 1)               AS late_pct          -- 지연율
FROM base
WHERE state IN ('SP', 'PR', 'RJ', 'MG', 'AM', 'AP', 'AC')
GROUP BY state
ORDER BY avg_km;
-- [결과] SP 249km / 19.7 / 8.7 / 11.0 / 6.7 / 4.5% / 4.5%
--        RJ 490km / 26.9 / 15.2 / 11.7 / 11.5 / 20.3% / 12.1%
--        PR 488km / 25.1 / 11.9 / 13.2 / 7.0 / 9.2% / 4.1%
--        AM·AP·AC 실제 배송 21~27일, 안내 42~47일, 지연율 3% 수준


-- ---------------------------------------------------------------------
-- ④ 판매 상품 중 SP 판매자 비중
-- ---------------------------------------------------------------------
SELECT ROUND(100 * AVG(s.seller_state = 'SP'), 1) AS sp_seller_item_pct
FROM order_items i
JOIN sellers s ON s.seller_id = i.seller_id
JOIN orders  o ON o.order_id  = i.order_id
WHERE o.order_purchase_timestamp >= '2017-01-01'
  AND o.order_purchase_timestamp <  '2018-09-01'
  AND o.order_status NOT IN ('canceled', 'unavailable');
-- [결과] 71.4%
