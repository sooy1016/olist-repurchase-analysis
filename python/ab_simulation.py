# =====================================================================
# A/B 테스트 검정력 시뮬레이션 (1,000번 반복)   → docs/05_ab_test_design.md
#
# 입력: SQL에서 저장한 CSV (컬럼: customer_unique_id, rep30, rep14)
#   - outputs/ab_base.csv      ← 30_ab_simulation_37211.sql ① ab_base      (37,211명)
#   - outputs/ab_base_ext.csv  ← 32_ab_simulation_58071.sql ① ab_base_ext  (58,071명)
#
# 방법
#   매 반복마다 ① A/B를 새로 무작위 배정 ② B의 비재구매 고객을 확률적으로 재구매로 바꿈
#   ③ 단측 두 비율 검정(B > A). 1,000번 중 p < 0.05 비율 = 검정력 (효과 1.0이면 1종 오류율)
# =====================================================================
import numpy as np
import pandas as pd
from statsmodels.stats.proportion import proportions_ztest


def simulate(file, col='rep30', lift=1.33, n_sim=1000, seed=42, verbose=True):
    """file: CSV 경로, col: 'rep30' 또는 'rep14', lift: 1.0(효과 없음) / 1.33(33%) / 1.37(37%) ..."""
    y = pd.read_csv(file)[col].values
    n = len(y)
    p_a = y.mean()                              # 기준 재구매율
    p_b = p_a * lift                            # B 목표 재구매율
    change_prob = (p_b - p_a) / (1 - p_a)       # B 비재구매 고객을 바꿀 확률

    rng = np.random.default_rng(seed)
    rate_a, rate_b, signif = [], [], 0
    for _ in range(n_sim):
        is_b = rng.permutation(n) < n // 2                      # ① 매번 새로 배정 (B = n//2명)
        a = y[~is_b]
        b = y[is_b].copy()
        b[(b == 0) & (rng.random(len(b)) < change_prob)] = 1    # ② 쿠폰 효과 주입
        z, p = proportions_ztest([b.sum(), a.sum()], [len(b), len(a)],
                                 alternative='larger')         # ③ 단측 검정
        signif += p < 0.05
        rate_a.append(a.mean())
        rate_b.append(b.mean())

    if verbose:
        print(f'[{file} | {col} | 효과 {lift}]')
        print(f'  대상 {n:,}명, 재구매 {y.sum():,}명, 기준 재구매율 {100*p_a:.3f}%, 바꿀 확률 {change_prob:.5f}')
        print(f'  A 평균 {100*np.mean(rate_a):.3f}%, B 평균 {100*np.mean(rate_b):.3f}%, '
              f'B ÷ A {np.mean(rate_b)/np.mean(rate_a):.2f}')
        print(f'  유의하게 나온 횟수 {signif} / {n_sim} → '
              f'{"1종 오류율" if lift == 1 else "검정력"} {100*signif/n_sim:.1f}%')
    return signif / n_sim


if __name__ == '__main__':
    # ---- 처음 설계: 37,211명 ------------------------------------------
    simulate('outputs/ab_base.csv', 'rep30', 1.0)    # 효과 없음 점검
    simulate('outputs/ab_base.csv', 'rep30', 1.33)   # 33% → 검정력 72.4%
    simulate('outputs/ab_base.csv', 'rep30', 1.37)   # 37%
    simulate('outputs/ab_base.csv', 'rep14', 1.33)   # 14일 쿠폰 → 53.9%

    # ---- 최종 설계: 58,071명 ------------------------------------------
    simulate('outputs/ab_base_ext.csv', 'rep30', 1.0)
    simulate('outputs/ab_base_ext.csv', 'rep30', 1.33)   # 88.7%
    simulate('outputs/ab_base_ext.csv', 'rep14', 1.33)   # 68.5%

    # ---- 최소 효과별 검정력 표 (저장: chart_data/10_power_curve.csv) ----
    rows = []
    for file in ['outputs/ab_base.csv', 'outputs/ab_base_ext.csv']:
        for lift in [1.20, 1.25, 1.28, 1.30, 1.33, 1.35, 1.37, 1.40, 1.50]:
            rows.append({'file': file, 'lift': lift,
                         'power': simulate(file, 'rep30', lift, verbose=False)})
    curve = pd.DataFrame(rows)
    print(curve.pivot(index='lift', columns='file', values='power'))
    curve.to_csv('chart_data/10_power_curve.csv', index=False)   # g13 그래프 데이터
