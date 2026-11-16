-- =====================================================================
-- 31. A/B 테스트 시뮬레이션: 남동부 37,211명, 유효기간 14일 쿠폰   → docs/05_ab_test_design.md
--   대상: 남동부(SP, RJ, MG, ES) 첫 구매 고객
--         첫 주문 2017.01~2018.02, 배송 완료(출고일·배송 완료일 있음)
--   지표: 첫 주문 배송 완료 후 14일 안에 처음 재구매했는지 (첫 주문과 같은 날 주문 제외)
--   ab_base(rep30, rep14 포함)는 30_ab_simulation_37211.sql ① 테이블 사용
-- =====================================================================
USE olist;

-- 확인: n 37,211 / 재구매 126 / 0.339%
SELECT COUNT(*) AS n, SUM(rep14) AS rep14, ROUND(100 * AVG(rep14), 3) AS rate14
FROM ab_base;

-- ---------------------------------------------------------------------
-- ② ~ ⑤ 시드만 바꿔 반복 실행
--   시드 2개: RAND(배정 시드) / RAND(주입 시드)
--   바꿀 확률 = (0.339% × 1.33 − 0.339%) ÷ (100% − 0.339%) = 0.00112
-- ---------------------------------------------------------------------

-- ② 무작위 A/B 배정
DROP TABLE IF EXISTS ab_assigned14;
CREATE TABLE ab_assigned14 AS
SELECT customer_unique_id, rep14,
       CASE WHEN ROW_NUMBER() OVER (ORDER BY RAND(42)) <= 18606   -- ← 배정 시드
            THEN 'A' ELSE 'B' END AS grp
FROM ab_base;

-- ③ B그룹 비재구매 고객에게 쿠폰 효과 주입 (바꿀 확률 0.00112)
DROP TABLE IF EXISTS ab_sim14;
CREATE TABLE ab_sim14 AS
SELECT customer_unique_id, grp,
       rep14 AS rep14_actual,
       CASE WHEN grp = 'B' AND rep14 = 0 AND RAND(7) < 0.00112      -- ← 주입 시드
            THEN 1 ELSE rep14 END AS rep14_sim
FROM ab_assigned14;

-- ④ 그룹별 결과
SELECT grp,
       COUNT(*)                            AS n,
       SUM(rep14_actual)                   AS rep_actual,    -- 쿠폰 효과 넣기 전
       ROUND(100 * AVG(rep14_actual), 3)   AS rate_actual,
       SUM(rep14_sim)                      AS rep_sim,       -- 쿠폰 효과 넣은 후
       ROUND(100 * AVG(rep14_sim), 3)      AS rate_sim
FROM ab_sim14
GROUP BY grp;

-- ⑤ 이번 회차 검정: z값이 1.645보다 크면 단측 5%에서 유의
WITH g AS (
  SELECT SUM(grp = 'A')                               AS n_a,
         SUM(CASE WHEN grp = 'A' THEN rep14_sim END)  AS rep_a,
         SUM(grp = 'B')                               AS n_b,
         SUM(CASE WHEN grp = 'B' THEN rep14_sim END)  AS rep_b
  FROM ab_sim14
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
