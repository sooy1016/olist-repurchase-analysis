-- =====================================================================
-- 01. 데이터 품질 점검 (MySQL 8)   → docs/01_data_preparation.md
-- =====================================================================
-- 분석 기준(기간, 제외할 주문, 집계 방식)을 정하기 위한 점검
-- [결과] 실행 결과 / [결정] 이후 분석에 적용한 기준
-- =====================================================================
USE olist;

-- ---------------------------------------------------------------------
-- Q1. 데이터 기간: 월별 주문 수
-- ---------------------------------------------------------------------
SELECT DATE_FORMAT(order_purchase_timestamp, '%Y-%m') AS ym,
       COUNT(*)                                       AS n_orders
FROM orders
GROUP BY ym
ORDER BY ym;
-- [결과] 2016-09 ~ 2018-10. 2016년은 9월 4건, 10월 324건, 12월 1건뿐이고
--        2018-09 16건, 2018-10 4건 → 이 구간은 수집이 끊긴 것으로 판단
-- [결정] 분석 기간 = 2017-01 ~ 2018-08 (20개월)


-- ---------------------------------------------------------------------
-- Q2. 고객 ID 두 종류 비교
-- ---------------------------------------------------------------------
SELECT COUNT(*)                           AS n_rows,
       COUNT(DISTINCT customer_id)        AS n_customer_id,
       COUNT(DISTINCT customer_unique_id) AS n_customer_unique_id
FROM customers;
-- [결과] customer_id 99,441개 = 주문 수와 같음 → 주문마다 새로 생기는 ID
--        customer_unique_id 96,096개 → 실제 고객 수
-- [결정] 고객 수, 재구매 분석은 customer_unique_id 사용


-- ---------------------------------------------------------------------
-- Q3. 주문 상태 분포
-- ---------------------------------------------------------------------
SELECT order_status,
       COUNT(*)                                      AS n_orders,
       ROUND(100 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
FROM orders
GROUP BY order_status
ORDER BY n_orders DESC;
-- [결과] delivered 97.0%, shipped 1.1%, canceled 0.6%, unavailable 0.6%, 나머지 1% 미만
-- [결정] canceled, unavailable = 취소 주문 → 거래액, 재구매 계산에서 제외


-- ---------------------------------------------------------------------
-- Q4. 상태별 타임스탬프 결측
-- ---------------------------------------------------------------------
SELECT order_status,
       COUNT(*)                                AS n_orders,
       SUM(order_approved_at IS NULL)             AS no_approved,
       SUM(order_delivered_carrier_date IS NULL)  AS no_carrier,
       SUM(order_delivered_customer_date IS NULL) AS no_delivered
FROM orders
GROUP BY order_status
ORDER BY n_orders DESC;
-- [결과] delivered인데 배송 완료일 없음 8건, 출고일 없음 2건, 승인일 없음 14건
--        나머지 결측은 상태와 맞음 (예: shipped는 배송 완료일이 없는 게 정상)
-- [결정] 퍼널은 order_status가 아니라 타임스탬프 존재 여부로 단계를 판단


-- ---------------------------------------------------------------------
-- Q5. 타임스탬프 순서 이상
--   정상 순서: 주문 → 결제 승인 → 출고 → 배송 완료
-- ---------------------------------------------------------------------
SELECT SUM(order_approved_at < order_purchase_timestamp)                 AS approved_before_purchase,
       SUM(order_delivered_carrier_date < order_purchase_timestamp)      AS carrier_before_purchase,
       SUM(order_delivered_carrier_date < order_approved_at)             AS carrier_before_approved,
       SUM(order_delivered_customer_date < order_delivered_carrier_date) AS delivered_before_carrier
FROM orders;
-- [결과] 승인 < 주문 0건 / 출고 < 주문 166건 / 출고 < 승인 1,359건 / 배송 완료 < 출고 23건
--        출고 < 승인 1,359건 중 73%가 신용카드, 평균 약 하루 차이 → 원인은 데이터로 알 수 없음 (기록 시점 오류로 추정)
-- [결정] 구간별 소요시간 계산 시 음수가 나오는 주문은 해당 구간 계산에서만 제외


-- ---------------------------------------------------------------------
-- Q6. 다른 테이블과 연결이 안 되는 주문
-- ---------------------------------------------------------------------
SELECT SUM(i.order_id IS NULL) AS orders_without_items,
       SUM(p.order_id IS NULL) AS orders_without_payments,
       SUM(r.order_id IS NULL) AS orders_without_reviews
FROM orders o
LEFT JOIN (SELECT DISTINCT order_id FROM order_items)    i ON o.order_id = i.order_id
LEFT JOIN (SELECT DISTINCT order_id FROM order_payments) p ON o.order_id = p.order_id
LEFT JOIN (SELECT DISTINCT order_id FROM order_reviews)  r ON o.order_id = r.order_id;
-- [결과] 상품 없는 주문 775건 (대부분 취소/상품 없음), 결제 없는 주문 1건, 리뷰 없는 주문 768건


-- ---------------------------------------------------------------------
-- Q7. JOIN fan-out 확인
--   한 주문에 상품 행 여러 개 × 결제 행 여러 개 → 그대로 JOIN하면 곱해짐
-- ---------------------------------------------------------------------
-- items와 payments를 바로 JOIN
SELECT ROUND(SUM(p.payment_value), 0) AS wrong_revenue
FROM order_items i
JOIN order_payments p ON i.order_id = p.order_id;

-- 결제 테이블만 합계
SELECT ROUND(SUM(payment_value), 0) AS correct_revenue
FROM order_payments;
-- [결과] 바로 JOIN 20,308,135 vs 결제 합계 16,008,872 → 27% 부풀려짐
-- [결정] 여러 테이블을 붙일 때는 서브쿼리/CTE에서 주문 단위로 먼저 집계 후 JOIN


-- ---------------------------------------------------------------------
-- Q8. 매출 정의 비교: 상품가+운임 vs 결제액
-- ---------------------------------------------------------------------
WITH item_sum AS (
  SELECT order_id, SUM(price + freight_value) AS item_total
  FROM order_items
  GROUP BY order_id
),
pay_sum AS (
  SELECT order_id, SUM(payment_value) AS pay_total
  FROM order_payments
  GROUP BY order_id
)
SELECT COUNT(*)                                         AS n_orders,
       SUM(ABS(i.item_total - p.pay_total) > 1)         AS n_diff_over_1brl,
       ROUND(SUM(i.item_total), 0)                      AS total_items,
       ROUND(SUM(p.pay_total), 0)                       AS total_payments
FROM item_sum i
JOIN pay_sum p ON i.order_id = p.order_id;
-- [결과] 98,665건 중 1헤알 넘게 차이 나는 주문 249건(0.25%). 합계는 결제액이 약 0.02% 큼
--        (할부 이자, 바우처 등으로 추정. 원인 컬럼은 없음)
-- [결정] 이후 분석의 거래액 = 상품 가격(price) 합계(배송비 제외)로 통일


-- ---------------------------------------------------------------------
-- Q9. 카테고리 결측과 번역 누락
-- ---------------------------------------------------------------------
SELECT SUM(p.product_category_name IS NULL)                                       AS no_category,
       SUM(p.product_category_name IS NOT NULL AND t.product_category_name IS NULL) AS no_translation
FROM products p
LEFT JOIN category_translation t ON p.product_category_name = t.product_category_name;

SELECT DISTINCT p.product_category_name
FROM products p
LEFT JOIN category_translation t ON p.product_category_name = t.product_category_name
WHERE p.product_category_name IS NOT NULL
  AND t.product_category_name IS NULL;
-- [결과] 카테고리 없는 상품 610개 / 번역 없는 상품 13개 (2개 카테고리: pc_gamer, portateis_cozinha_e_preparadores_de_alimentos)
-- [결정] 영어 이름이 없으면 포르투갈어, 카테고리가 없으면 'unknown'
--        → COALESCE(t.product_category_name_english, p.product_category_name, 'unknown')


-- ---------------------------------------------------------------------
-- Q10. 리뷰 중복
-- ---------------------------------------------------------------------
SELECT (SELECT COUNT(*) - COUNT(DISTINCT review_id) FROM order_reviews) AS dup_review_id,
       (SELECT COUNT(*) FROM (SELECT order_id FROM order_reviews
                              GROUP BY order_id HAVING COUNT(*) > 1) t) AS orders_multi_review;
-- [결과] 중복 review_id 814개, 리뷰가 2개 이상인 주문 547건
-- [결정] 주문별 리뷰 점수 = AVG(review_score) 로 주문당 1행으로 만든 뒤 사용


-- ---------------------------------------------------------------------
-- Q11. geolocation 중복
-- ---------------------------------------------------------------------
SELECT COUNT(*)                                    AS n_rows,
       COUNT(DISTINCT geolocation_zip_code_prefix) AS n_zip
FROM geolocation;
-- [결과] 1,000,163행인데 우편번호는 19,015개 → 우편번호당 평균 50행
-- [결정] 지역 분석은 customers.customer_state 사용. 좌표가 필요하면 우편번호별 평균 좌표로 1행 만든 뒤 JOIN
