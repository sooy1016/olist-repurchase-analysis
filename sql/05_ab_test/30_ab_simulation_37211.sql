-- =====================================================================
-- 30. A/B 테스트 시뮬레이션: 남동부 37,211명 (30일 쿠폰)   → docs/05_ab_test_design.md
--   (시드별 1회 실험. 1,000번 반복·검정력은 python/ab_simulation.py)
--   대상: 남동부(SP, RJ, MG, ES) 첫 구매 고객
--         첫 주문 2017.01~2018.02, 배송 완료(출고일·배송 완료일 있음)
--         (180일 재구매 분석과 같은 대상: 13_repurchase.sql cohort180 의 남동부 고객)
--   지표: 첫 주문 배송 완료 후 30일 / 14일 안에 처음 재구매했는지 (첫 주문과 같은 날 주문 제외)
-- =====================================================================
USE olist;

-- ---------------------------------------------------------------------
-- ① 대상 고객 + 30일·14일 재구매 여부 (한 번만 실행)
--   저장: outputs/ab_base.csv → python/ab_simulation.py 입력
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS ab_base;
CREATE TABLE ab_base AS
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
    AND t >= '2017-01-01' AND t < '2018-03-01'
    AND order_status = 'delivered'
    AND carrier IS NOT NULL
    AND delivered IS NOT NULL
    AND delivered >= carrier
    AND customer_state IN ('SP', 'RJ', 'MG', 'ES')
),
first_rep AS (                                -- 첫 재구매 시각 (첫 주문과 다른 날)
  SELECT f.customer_unique_id,
         f.delivered,
         MIN(w.t) AS t2
  FROM first_order f
  LEFT JOIN v w
         ON w.customer_unique_id = f.customer_unique_id
        AND w.rn > 1
        AND DATE(w.t) > DATE(f.t)
  GROUP BY f.customer_unique_id, f.delivered
)
SELECT customer_unique_id,
       CASE WHEN t2 >= delivered AND t2 < delivered + INTERVAL 30 DAY
            THEN 1 ELSE 0 END AS rep30,       -- 배송 후 30일 안 재구매
       CASE WHEN t2 >= delivered AND t2 < delivered + INTERVAL 14 DAY
            THEN 1 ELSE 0 END AS rep14        -- 배송 후 14일 안 재구매
FROM first_rep;

-- 확인: n 37,211 / 재구매 216 / 0.580%
SELECT COUNT(*) AS n, SUM(rep30) AS rep, ROUND(100 * AVG(rep30), 3) AS rate
FROM ab_base;

-- 확인: n 37,211 / 재구매 126 / 0.339%
SELECT COUNT(*) AS n, SUM(rep14) AS rep14, ROUND(100 * AVG(rep14), 3) AS rate14
FROM ab_base;


-- ---------------------------------------------------------------------
-- ② ~ ⑤ 시드만 바꿔 반복 실행
--   시드 2개: RAND(배정 시드) / RAND(주입 시드)
-- ---------------------------------------------------------------------

-- ② 무작위 A/B 배정
DROP TABLE IF EXISTS ab_assigned;
CREATE TABLE ab_assigned AS
SELECT customer_unique_id, rep30,
       CASE WHEN ROW_NUMBER() OVER (ORDER BY RAND(42)) <= 18606   -- ← 배정 시드 (A 18,606명 / B 18,605명)
            THEN 'A' ELSE 'B' END AS grp
FROM ab_base;

-- ③ B그룹 비재구매 고객에게 쿠폰 효과 주입 (바꿀 확률 0.00193)
--   바꿀 확률 = (0.580% × 1.33 − 0.580%) ÷ (100% − 0.580%) = 0.00193
--   최소 효과 37%로 바꿔 보려면 0.00216 (= 0.580% × 0.37 ÷ 99.42%)
DROP TABLE IF EXISTS ab_sim;
CREATE TABLE ab_sim AS
SELECT customer_unique_id, grp,
       rep30 AS rep30_actual,
       CASE WHEN grp = 'B' AND rep30 = 0 AND RAND(7) < 0.00193      -- ← 주입 시드
            THEN 1 ELSE rep30 END AS rep30_sim
FROM ab_assigned;

-- ④ 그룹별 결과
SELECT grp,
       COUNT(*)                            AS n,
       SUM(rep30_actual)                   AS rep_actual,    -- 쿠폰 효과 넣기 전
       ROUND(100 * AVG(rep30_actual), 3)   AS rate_actual,
       SUM(rep30_sim)                      AS rep_sim,       -- 쿠폰 효과 넣은 후
       ROUND(100 * AVG(rep30_sim), 3)      AS rate_sim
FROM ab_sim
GROUP BY grp;


-- ⑤ 이번 회차 검정: z값이 1.645보다 크면 단측 5%에서 유의
WITH g AS (
  SELECT SUM(grp = 'A')                               AS n_a,
         SUM(CASE WHEN grp = 'A' THEN rep30_sim END)  AS rep_a,
         SUM(grp = 'B')                               AS n_b,
         SUM(CASE WHEN grp = 'B' THEN rep30_sim END)  AS rep_b
  FROM ab_sim
),
s AS (
  SELECT n_a, rep_a, n_b, rep_b,
         rep_a / n_a                     AS rate_a,
         rep_b / n_b                     AS rate_b,
         (rep_a + rep_b) / (n_a + n_b)   AS p_pool
  FROM g
)
SELECT ROUND(100 * rate_a, 3)                                         AS rate_a_pct,
       ROUND(100 * rate_b, 3)                                         AS rate_b_pct,
       ROUND(rate_b / rate_a, 2)                                      AS b_div_a,
       ROUND((rate_b - rate_a)
             / SQRT(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b)), 2)  AS z,
       CASE WHEN (rate_b - rate_a)
                 / SQRT(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b)) > 1.645
            THEN '유의함' ELSE '유의하지 않음' END                       AS result
FROM s;

-- ---------------------------------------------------------------------
-- (참고) 14일 기준은 31_ab_simulation_37211_14d.sql
-- ---------------------------------------------------------------------
