-- =====================================================================
-- 13. 재구매 분석   → docs/04_repurchase.md
--   PART A (①~④) 재구매 현황: 2017.01~2018.08 주문, 취소·상품 없음 제외
--   PART B (⑤~⑨) 180일 재구매율: 첫 주문이 2017.01~2018.02인 첫 구매 고객
--   고객: customer_unique_id
-- =====================================================================
USE olist;

-- ---------------------------------------------------------------------
-- ① 고객별 첫 주문과 두 번째 주문을 한 행으로 만든 테이블
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS repurchase_pair;
CREATE TABLE repurchase_pair AS
WITH v AS (
  SELECT c.customer_unique_id,
         o.order_id,
         o.order_purchase_timestamp,
         ROW_NUMBER() OVER (PARTITION BY c.customer_unique_id
                            ORDER BY o.order_purchase_timestamp) AS rn   -- 고객별 주문 순서
  FROM orders o
  JOIN customers c ON o.customer_id = c.customer_id
  WHERE o.order_status NOT IN ('canceled', 'unavailable')
    AND o.order_purchase_timestamp >= '2017-01-01'
    AND o.order_purchase_timestamp <  '2018-09-01'
)
SELECT a.customer_unique_id,
       a.order_id                 AS order1,
       b.order_id                 AS order2,
       a.order_purchase_timestamp AS t1,
       b.order_purchase_timestamp AS t2
FROM v a
JOIN v b
  ON a.customer_unique_id = b.customer_unique_id
 AND a.rn = 1                     -- 첫 주문
 AND b.rn = 2;                    -- 두 번째 주문
-- [결과] 2,875행 = 2번 이상 구매한 고객 수 (전체 94,707명의 3.0%)


-- ---------------------------------------------------------------------
-- ② 첫 주문 → 두 번째 주문까지 걸린 기간
--   저장: chart_data/06_repurchase_gap.csv
--      g09 "두 번째 주문까지 걸린 기간": gap_band, n_customers, pct
-- ---------------------------------------------------------------------
SELECT CASE WHEN DATEDIFF(t2, t1) = 0   THEN '0) 같은 날'
            WHEN DATEDIFF(t2, t1) <= 7   THEN '1) 1~7일'
            WHEN DATEDIFF(t2, t1) <= 30  THEN '2) 8~30일'
            WHEN DATEDIFF(t2, t1) <= 90  THEN '3) 31~90일'
            WHEN DATEDIFF(t2, t1) <= 180 THEN '4) 91~180일'
            WHEN DATEDIFF(t2, t1) <= 365 THEN '5) 181~365일'
            ELSE                              '6) 365일 초과' END AS gap_band,
       COUNT(*)                                         AS n_customers,
       ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM repurchase_pair
GROUP BY gap_band
ORDER BY gap_band;
-- [결과] 같은 날 867명(30.2%) / 1~7일 207 / 8~30일 390 / 31~90일 503 / 91~180일 423 / 181~365일 406 / 365일 초과 79


-- ---------------------------------------------------------------------
-- ③ 같은 날 두 번째 주문: 주문 간격, 같은 판매자·상품 포함 여부
-- ---------------------------------------------------------------------
SELECT COUNT(*)                                       AS n_same_day,
       SUM(TIMESTAMPDIFF(MINUTE, t1, t2) <= 10)       AS within_10min,
       SUM(TIMESTAMPDIFF(MINUTE, t1, t2) <= 60)       AS within_60min
FROM repurchase_pair
WHERE DATE(t2) = DATE(t1);
-- [결과] 867명 중 776명(89.5%)이 10분 안에, 834명(96.2%)이 1시간 안에 다시 주문

SELECT CASE WHEN DATE(t2) = DATE(t1) THEN '같은 날' ELSE '다른 날' END AS grp,
       COUNT(*) AS n,
       SUM(EXISTS (SELECT 1 FROM order_items x
                   JOIN order_items y ON x.seller_id = y.seller_id
                   WHERE x.order_id = p.order1 AND y.order_id = p.order2))  AS same_seller,
       SUM(EXISTS (SELECT 1 FROM order_items x
                   JOIN order_items y ON x.product_id = y.product_id
                   WHERE x.order_id = p.order1 AND y.order_id = p.order2)) AS same_product
FROM repurchase_pair p
GROUP BY grp;
-- [결과] 같은 날: 같은 판매자 47.1%, 같은 상품 23.8% / 다른 날: 같은 판매자 25.2%, 같은 상품 14.7%
-- [결정] 같은 날 주문은 대부분 같은 쇼핑 중 나눠서 결제한 것 → 재구매에서 제외


-- ---------------------------------------------------------------------
-- ④ 재구매(다른 날)까지 걸린 기간: 사분위수
-- ---------------------------------------------------------------------
WITH g AS (
  SELECT DATEDIFF(t2, t1)                             AS gap_days,
         ROW_NUMBER() OVER (ORDER BY DATEDIFF(t2, t1)) AS r,
         COUNT(*) OVER ()                              AS n
  FROM repurchase_pair
  WHERE DATE(t2) > DATE(t1)
)
SELECT MAX(n)                                          AS n_customers,
       MAX(CASE WHEN r = CEIL(n * 0.25) THEN gap_days END) AS p25,
       MAX(CASE WHEN r = CEIL(n * 0.50) THEN gap_days END) AS median,
       MAX(CASE WHEN r = CEIL(n * 0.75) THEN gap_days END) AS p75,
       ROUND(AVG(gap_days), 1)                         AS mean
FROM g;
-- [결과] 2,008명, 25% 23일 / 중앙값 75일 / 75% 175일 / 평균 114.4일


-- =====================================================================
-- PART B. 배송 경험·지역·리뷰와 180일 재구매
-- =====================================================================

-- ---------------------------------------------------------------------
-- ⑤ 첫 구매 고객 테이블 first_orders (한 번만 실행, 23_repurchase_pattern.sql 에서도 사용)
--   - 고객의 "첫 주문" = 취소 아닌 전체 주문 중 가장 이른 주문 (2016년에 산 고객은 자동 제외)
--   - 첫 주문이 2017.01~2018.02 → 데이터 끝(2018.08)까지 180일을 모두 관찰할 수 있음
--   - 첫 주문이 배송 완료된 고객만 (배송 경험을 봐야 하므로)
--   - 재구매 = 첫 주문과 "다른 날" 주문 중 가장 이른 주문이 180일 안에 있으면 1
--   - 같은 시각 주문이 있는 고객이 있어 정렬에 order_id 추가 (첫 주문 고정)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS first_orders;
CREATE TABLE first_orders AS
WITH v AS (                                    -- 취소 아닌 모든 주문 + 고객별 순서
  SELECT c.customer_unique_id,
         c.customer_state,
         o.order_id,
         o.order_purchase_timestamp       AS t,
         o.order_delivered_carrier_date   AS carrier,
         o.order_delivered_customer_date  AS delivered,
         o.order_estimated_delivery_date  AS estimated,
         ROW_NUMBER() OVER (PARTITION BY c.customer_unique_id
                            ORDER BY o.order_purchase_timestamp, o.order_id) AS rn,
         MIN(o.order_purchase_timestamp) OVER (PARTITION BY c.customer_unique_id) AS first_t
  FROM orders o
  JOIN customers c ON o.customer_id = c.customer_id
  WHERE o.order_status NOT IN ('canceled', 'unavailable')
),
nxt AS (                                       -- 첫 주문과 다른 날 주문에 순서 매기기 → k = 1 이 재구매 주문
  SELECT customer_unique_id, order_id, t,
         ROW_NUMBER() OVER (PARTITION BY customer_unique_id ORDER BY t, order_id) AS k
  FROM v
  WHERE DATE(t) > DATE(first_t)
),
amt AS (                                       -- 주문별 상품 금액, 배송비
  SELECT order_id, SUM(price) AS gmv, SUM(freight_value) AS freight
  FROM order_items
  GROUP BY order_id
)
SELECT f.customer_unique_id,
       f.customer_state,
       CASE WHEN f.customer_state IN ('SP','RJ','MG','ES')                          THEN '1) 남동부'
            WHEN f.customer_state IN ('PR','SC','RS')                               THEN '2) 남부'
            WHEN f.customer_state IN ('DF','GO','MT','MS')                          THEN '3) 중서부'
            WHEN f.customer_state IN ('BA','PE','CE','MA','PB','PI','RN','AL','SE') THEN '4) 북동부'
            ELSE                                                                         '5) 북부' END AS region,
       f.order_id   AS first_order_id,
       f.t          AS first_t,
       f.carrier,
       f.delivered,
       f.estimated,
       a1.gmv       AS first_gmv,                -- 첫 주문 상품 금액
       a1.freight   AS first_freight,            -- 첫 주문 배송비
       n.order_id   AS second_order_id,          -- 재구매 주문 (다른 날 첫 주문)
       n.t          AS second_t,
       a2.gmv       AS second_gmv,
       DATEDIFF(n.t, f.t) AS gap_days,           -- 첫 주문 → 재구매까지 일수
       CASE WHEN n.t < f.t + INTERVAL 180 DAY THEN 1 ELSE 0 END AS rep180
FROM v f
LEFT JOIN nxt n  ON n.customer_unique_id = f.customer_unique_id AND n.k = 1
LEFT JOIN amt a1 ON a1.order_id = f.order_id
LEFT JOIN amt a2 ON a2.order_id = n.order_id
WHERE f.rn = 1
  AND f.t >= '2017-01-01' AND f.t < '2018-03-01'
  AND f.delivered IS NOT NULL;

-- 출고일까지 정상인 고객만 (배송 기간을 계산할 수 있는 고객) → 대부분의 표가 이 테이블 사용
DROP TABLE IF EXISTS cohort180;
CREATE TABLE cohort180 AS
SELECT *, DATEDIFF(delivered, carrier) AS transit_days      -- 출고 → 도착 일수
FROM first_orders
WHERE carrier IS NOT NULL
  AND delivered >= carrier;

SELECT (SELECT COUNT(*) FROM first_orders) AS n_first_orders,
       (SELECT COUNT(*) FROM cohort180)    AS n_cohort180,
       (SELECT SUM(rep180) FROM cohort180) AS n_rep180;
-- [결과] 55,227 / 55,209 / 1,102


-- ---------------------------------------------------------------------
-- ⑥ 예상일 지연 여부 × 180일 재구매
-- ---------------------------------------------------------------------
SELECT CASE WHEN DATE(delivered) > DATE(estimated) THEN '늦게 도착' ELSE '제때 도착' END AS arrival,
       COUNT(*)                     AS n_customers,
       SUM(rep180)                  AS n_rep,
       ROUND(100 * AVG(rep180), 2)  AS rep_rate
FROM first_orders
GROUP BY arrival;
-- [결과] 제때 51,560명 / 1,043 / 2.02%, 늦게 3,667명 / 59 / 1.61%  (p = 0.083, python/stats_tests.py)


-- ---------------------------------------------------------------------
-- ⑦ 출고 → 배송 완료 기간 × 180일 재구매
--   저장: chart_data/12_transit_repurchase.csv
-- ---------------------------------------------------------------------
SELECT CASE WHEN transit_days <= 3  THEN '1) 0~3일'
            WHEN transit_days <= 7  THEN '2) 4~7일'
            WHEN transit_days <= 14 THEN '3) 8~14일'
            WHEN transit_days <= 21 THEN '4) 15~21일'
            ELSE                         '5) 22일 이상' END AS transit_band,
       COUNT(*)                                                 AS n_customers,
       SUM(rep180)                                              AS n_rep,
       ROUND(100 * AVG(rep180), 2)                              AS rep_rate,
       ROUND(AVG(CASE WHEN rep180 = 1 THEN gap_days END), 0)    AS avg_days_to_rep   -- 재구매까지 평균
FROM cohort180
GROUP BY transit_band
ORDER BY transit_band;
-- [결과] 2.19% / 2.17% / 2.00% / 1.64% / 1.42%  (추세 p = 0.0002)


-- ---------------------------------------------------------------------
-- ⑧ 권역별·주별 180일 재구매율
-- ---------------------------------------------------------------------
SELECT region,
       COUNT(*)                         AS n_customers,
       ROUND(AVG(first_gmv), 1)         AS avg_first_gmv,     -- 첫 구매 금액 평균
       SUM(rep180)                      AS n_rep,
       ROUND(100 * AVG(rep180), 2)      AS rep_rate,
       ROUND(AVG(transit_days), 1)      AS avg_transit_days   -- 배송 기간(출고→도착)
FROM cohort180
GROUP BY region
ORDER BY rep_rate DESC;
-- [결과] 남동부 37,211 / 805 / 2.16% / 8.3일 … 북동부 5,433 / 79 / 1.45% / 17.3일

SELECT customer_state,
       COUNT(*)                     AS n_customers,
       ROUND(100 * AVG(rep180), 2)  AS rep_rate,
       ROUND(AVG(transit_days), 1)  AS avg_transit_days
FROM cohort180
GROUP BY customer_state
ORDER BY n_customers DESC
LIMIT 7;
-- [결과] SP 21,921 / 2.24% / 6.3일, RJ 7,438 / 2.12% / 12.7일 …


-- ---------------------------------------------------------------------
-- ⑨ 첫 주문 리뷰 점수 × 180일 재구매
--   리뷰가 2개 이상인 주문은 평균 점수 사용
-- ---------------------------------------------------------------------
WITH rv AS (
  SELECT order_id, AVG(review_score) AS score
  FROM order_reviews
  GROUP BY order_id
)
SELECT CASE WHEN rv.score <= 2 THEN '1) 1~2점'
            WHEN rv.score < 4  THEN '2) 3점'
            ELSE                    '3) 4~5점' END AS first_review,
       COUNT(*)                       AS n_customers,
       SUM(f.rep180)                  AS n_rep,
       ROUND(100 * AVG(f.rep180), 2)  AS rep_rate
FROM first_orders f
JOIN rv ON rv.order_id = f.first_order_id
GROUP BY first_review
ORDER BY first_review;
-- [결과] 1~2점 7,182 / 120 / 1.67%, 3점 4,810 / 96 / 2.00%, 4~5점 42,826 / 881 / 2.06%  (p = 0.031)


-- ---------------------------------------------------------------------
-- ⑩ 통계 검정용 고객 단위 데이터 내보내기
--   저장: outputs/first_orders_for_test.csv → python/stats_tests.py 입력 (p값 계산)
-- ---------------------------------------------------------------------
WITH rv AS (
  SELECT order_id, AVG(review_score) AS score
  FROM order_reviews
  GROUP BY order_id
)
SELECT f.customer_unique_id,
       f.customer_state,
       f.region,
       (f.carrier IS NOT NULL AND f.delivered >= f.carrier)     AS in_cohort180,   -- 1 = cohort180 대상
       DATEDIFF(f.delivered, f.carrier)                          AS transit_days,
       (DATE(f.delivered) > DATE(f.estimated))                   AS is_late,
       f.first_gmv,
       f.first_freight,
       f.gap_days,
       f.rep180,
       rv.score                                                  AS first_review
FROM first_orders f
LEFT JOIN rv ON rv.order_id = f.first_order_id;
