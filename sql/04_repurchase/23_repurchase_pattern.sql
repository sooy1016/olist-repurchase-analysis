-- =====================================================================
-- 23. 재구매 패턴   → docs/04_repurchase.md
--   13_repurchase.sql ⑤ 에서 만든 cohort180 / first_orders 테이블 사용 (먼저 실행)
--   대상: 첫 주문 2017.01~2018.02 첫 구매 고객 55,209명
--   재구매: 첫 주문 후 180일 안에 다른 날 다시 주문 (rep180 = 1)
-- =====================================================================
USE olist;

-- ---------------------------------------------------------------------
-- ① 권역별 재구매율 (+ 첫 구매 금액, 배송 기간)
--   → 13_repurchase.sql ⑧ 첫 번째 쿼리와 같음
-- ---------------------------------------------------------------------
SELECT region,
       COUNT(*)                     AS n_customers,
       ROUND(AVG(first_gmv), 1)     AS avg_first_gmv,
       SUM(rep180)                  AS n_rep,
       ROUND(100 * AVG(rep180), 2)  AS rep_rate,
       ROUND(AVG(transit_days), 1)  AS avg_transit_days
FROM cohort180
GROUP BY region
ORDER BY rep_rate DESC;


-- ---------------------------------------------------------------------
-- ② 경과일 구간별 재구매율
--   저장: chart_data/13_repurchase_timing.csv (아래 전체 기준 결과를 첫 행으로)
--   구간 재구매율 = 그 기간에 처음 다시 산 고객 ÷ 대상 고객
-- ---------------------------------------------------------------------
SELECT region,
       COUNT(*)    AS n_customers,
       SUM(rep180) AS n_rep,
       ROUND(100 * SUM(rep180 = 1 AND gap_days BETWEEN   1 AND  30) / COUNT(*), 2) AS d001_030,
       ROUND(100 * SUM(rep180 = 1 AND gap_days BETWEEN  31 AND  60) / COUNT(*), 2) AS d031_060,
       ROUND(100 * SUM(rep180 = 1 AND gap_days BETWEEN  61 AND  90) / COUNT(*), 2) AS d061_090,
       ROUND(100 * SUM(rep180 = 1 AND gap_days BETWEEN  91 AND 120) / COUNT(*), 2) AS d091_120,
       ROUND(100 * SUM(rep180 = 1 AND gap_days BETWEEN 121 AND 150) / COUNT(*), 2) AS d121_150,
       ROUND(100 * SUM(rep180 = 1 AND gap_days BETWEEN 151 AND 180) / COUNT(*), 2) AS d151_180,
       ROUND(100 * (1 - AVG(rep180)), 2)                                           AS no_rep
FROM cohort180
GROUP BY region
ORDER BY region;
-- [결과] 남동부 0.72 / 0.40 / 0.32 / 0.26 / 0.24 / 0.23 / 97.84%
--        재구매 시점 권역 간 차이 p = 0.70 (python/stats_tests.py)

-- 전체 첫 구매 고객 기준 + 180일 재구매 중 첫 30일 비중
SELECT COUNT(*)    AS n_customers,
       SUM(rep180) AS n_rep,
       ROUND(100 * SUM(rep180 = 1 AND gap_days BETWEEN   1 AND  30) / COUNT(*), 2) AS d001_030,
       ROUND(100 * SUM(rep180 = 1 AND gap_days BETWEEN  31 AND  60) / COUNT(*), 2) AS d031_060,
       ROUND(100 * SUM(rep180 = 1 AND gap_days BETWEEN  61 AND  90) / COUNT(*), 2) AS d061_090,
       ROUND(100 * SUM(rep180 = 1 AND gap_days BETWEEN  91 AND 120) / COUNT(*), 2) AS d091_120,
       ROUND(100 * SUM(rep180 = 1 AND gap_days BETWEEN 121 AND 150) / COUNT(*), 2) AS d121_150,
       ROUND(100 * SUM(rep180 = 1 AND gap_days BETWEEN 151 AND 180) / COUNT(*), 2) AS d151_180,
       ROUND(100 * SUM(rep180 = 1 AND gap_days <= 30) / SUM(rep180), 1)            AS first30_share
FROM cohort180;
-- [결과] 55,209 / 1,102 / 0.66 / 0.37 / 0.29 / 0.25 / 0.22 / 0.21 / 32.8%
--        → 재구매의 33%가 첫 30일에 발생


-- ---------------------------------------------------------------------
-- ③ 첫 주문 배송비 비중 × 재구매
--   배송비 비중 = 첫 주문 배송비 ÷ (상품 금액 + 배송비)
-- ---------------------------------------------------------------------
SELECT CASE WHEN fs < 0.10 THEN '1) 10% 미만'
            WHEN fs < 0.20 THEN '2) 10~20%'
            WHEN fs < 0.30 THEN '3) 20~30%'
            WHEN fs < 0.40 THEN '4) 30~40%'
            ELSE                '5) 40% 이상' END AS freight_band,
       COUNT(*)                     AS n_customers,
       SUM(rep180)                  AS n_rep,
       ROUND(100 * AVG(rep180), 2)  AS rep_rate,
       ROUND(AVG(first_gmv), 1)     AS avg_gmv,
       ROUND(AVG(first_freight), 1) AS avg_freight
FROM (SELECT *, first_freight / (first_gmv + first_freight) AS fs FROM cohort180) t
GROUP BY freight_band
ORDER BY freight_band;
-- [결과] 1.94 / 2.03 / 1.84 / 2.21 / 2.15% → 배송비 비중과 뚜렷한 관련 없음


-- ---------------------------------------------------------------------
-- ④ 첫 구매 금액 × 재구매
-- ---------------------------------------------------------------------
SELECT CASE WHEN first_gmv < 50  THEN '1) 50 미만'
            WHEN first_gmv < 100 THEN '2) 50~100'
            WHEN first_gmv < 200 THEN '3) 100~200'
            WHEN first_gmv < 500 THEN '4) 200~500'
            ELSE                      '5) 500 이상' END AS first_value_band,
       COUNT(*)                    AS n_customers,
       SUM(rep180)                 AS n_rep,
       ROUND(100 * AVG(rep180), 2) AS rep_rate
FROM cohort180
GROUP BY first_value_band
ORDER BY first_value_band;
-- [결과] 1.99 / 2.01 / 1.94 / 2.25 / 1.44% (p = 0.24)


-- ---------------------------------------------------------------------
-- ⑤ 중앙값: 첫 주문·두 번째 주문 금액
--   인원이 짝수면 가운데 두 값의 평균
-- ---------------------------------------------------------------------
WITH r AS (
  SELECT region, first_gmv, second_gmv,
         ROW_NUMBER() OVER (PARTITION BY region ORDER BY first_gmv)  AS r1,
         ROW_NUMBER() OVER (PARTITION BY region ORDER BY second_gmv) AS r2,
         COUNT(*)     OVER (PARTITION BY region)                     AS n
  FROM cohort180
  WHERE rep180 = 1
)
SELECT region,
       MAX(n)                                                                            AS n_rep,
       ROUND(AVG(CASE WHEN r1 IN (FLOOR((n + 1) / 2), CEIL((n + 1) / 2)) THEN first_gmv  END), 1) AS median_first_gmv,
       ROUND(AVG(CASE WHEN r2 IN (FLOOR((n + 1) / 2), CEIL((n + 1) / 2)) THEN second_gmv END), 1) AS median_second_gmv
FROM r
GROUP BY region
ORDER BY region;
-- [결과] 남동부 805 / 82.9 / 89.0

-- 전체 재구매 고객 중앙값 (1,102명)
WITH r AS (
  SELECT first_gmv, second_gmv,
         ROW_NUMBER() OVER (ORDER BY first_gmv)  AS r1,
         ROW_NUMBER() OVER (ORDER BY second_gmv) AS r2,
         COUNT(*)     OVER ()                    AS n
  FROM cohort180
  WHERE rep180 = 1
)
SELECT MAX(n) AS n_rep,
       ROUND(AVG(CASE WHEN r1 IN (FLOOR((n + 1) / 2), CEIL((n + 1) / 2)) THEN first_gmv  END), 1) AS median_first_gmv,
       ROUND(AVG(CASE WHEN r2 IN (FLOOR((n + 1) / 2), CEIL((n + 1) / 2)) THEN second_gmv END), 1) AS median_second_gmv
FROM r;
-- [결과] 1,102명 / 85.9 / 88.0
