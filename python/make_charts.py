# =====================================================================
# 그래프 (g01~g13)
#   입력: chart_data/ 의 CSV (SQL 결과, 10번은 python/ab_simulation.py 결과)
#   11~13번은 포트폴리오 슬라이드용 데이터
#   출력: images/ 의 PNG
# =====================================================================
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mt
from matplotlib import font_manager as fm
from matplotlib.patches import Patch

# ---- 한글 글꼴: 윈도우는 맑은 고딕, 없으면 Noto Sans CJK ----
names = {f.name for f in fm.fontManager.ttflist}
plt.rcParams['font.family'] = 'Malgun Gothic' if 'Malgun Gothic' in names else 'Noto Sans CJK JP'
plt.rcParams['axes.unicode_minus'] = False

DATA, OUT = 'chart_data', 'images'
os.makedirs(OUT, exist_ok=True)
BLUE, ORANGE, GREEN, GRAY, GRID, K = '#2a78d6', '#eb6834', '#1baf7a', '#b5b5b0', '#e6e5e0', '#000000'
SUB = '취소, 상품없음 주문 제외'
read = lambda f: pd.read_csv(os.path.join(DATA, f), encoding='utf-8-sig')


def head(ax, title, sub=SUB):
    ax.set_title(title, loc='left', fontsize=15, color=K, pad=26, fontweight='bold')
    # 부제는 그래프 높이와 상관없이 축 위 8pt에 고정 (제목 pad 26pt와 겹치지 않게)
    ax.annotate(sub, xy=(0, 1), xycoords='axes fraction', xytext=(0, 8),
                textcoords='offset points', fontsize=10, color=K)


def clean(ax, axis='y'):
    for s in ['top', 'right', 'left']:
        ax.spines[s].set_visible(False)
    ax.spines['bottom'].set_color(GRID)
    ax.tick_params(length=0, colors=K)
    ax.grid(axis=axis, color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def save(fig, name):
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, name), facecolor='white')
    plt.close(fig)


def hbar(df, label_col, val_col, text, title, xlabel, xmax, h, sub=SUB):
    fig, ax = plt.subplots(figsize=(9, h), dpi=150)
    y = np.arange(len(df))[::-1]
    ax.barh(y, df[val_col], color=BLUE, height=0.65)
    for yi, (_, r) in zip(y, df.iterrows()):
        ax.text(r[val_col] + xmax * 0.01, yi, text(r), va='center', fontsize=9, color=K)
    ax.set_yticks(y)
    ax.set_yticklabels(df[label_col], color=K)
    ax.set_xlim(0, xmax)
    ax.set_xlabel(xlabel, color=K)
    ax.xaxis.set_major_formatter(mt.FuncFormatter(lambda v, p: f'{int(v):,}'))
    clean(ax, 'x')
    head(ax, title, sub)
    return fig


# ---- 그래프 1, 2: 월별 거래액 ------------------------------------------
m = read('01_monthly_gmv.csv')
color = {2016: GREEN, 2017: BLUE, 2018: ORANGE}
for name, title, years, end in [('g01_monthly_gmv_2017_2018.png', '월별 거래액(2017.01~2018.08)', [2017, 2018], (2018, 8)),
                                ('g02_monthly_gmv_all.png', '월별 거래액(2016.09~2018.09)', [2016, 2017, 2018], (2018, 9))]:
    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=150)
    for yr in years:
        d = m[(m.yr == yr) & ((m.yr < end[0]) | (m.mon <= end[1]))].set_index('mon')
        d = d.reindex(range(d.index.min(), d.index.max() + 1))   # 빈 달(2016-11)은 선을 끊음
        ax.plot(d.index, d.gmv, color=color[yr], lw=2, marker='o', ms=5, mec='white', mew=1.2, label=str(yr))
    ax.set_xticks(range(1, 13))
    ax.set_xticklabels([f'{i}월' for i in range(1, 13)])
    ax.set_ylim(0, 1.15e6)
    ax.set_yticks([0, 2e5, 4e5, 6e5, 8e5, 1e6])
    ax.set_yticklabels(['0', '20만', '40만', '60만', '80만', '100만'])
    ax.set_ylabel('거래액 (헤알)')
    ax.legend(frameon=False, loc='upper left', ncol=3)
    clean(ax)
    head(ax, title)
    save(fig, name)

# ---- 그래프 3, 4, 5: 주별 ------------------------------------------------
st = read('02_state_summary.csv')
TOTAL = 94703   # 전체 고객 수 (11_state_customers_gmv.sql ②)
c = st.sort_values('n_customers', ascending=False)
save(hbar(c, 'customer_state', 'n_customers',
          lambda r: f"{r.n_customers:,}명 ({100*r.n_customers/TOTAL:.1f}%)" if 100*r.n_customers/TOTAL >= 0.05 else f"{r.n_customers:,}명 (<0.1%)",
          '주별 고객 수(2017.01~2018.08)', '고객 수 (명)', 47000, 9), 'g03_state_customers.png')
g = st.sort_values('gmv', ascending=False).assign(gmv_man=lambda d: d.gmv / 1e4)
save(hbar(g, 'customer_state', 'gmv_man', lambda r: f"{r.gmv_man:,.0f}만 ({r.gmv_pct}%)",
          '주별 거래액(2017.01~2018.08)', '거래액 (만 헤알)', 620, 9), 'g04_state_gmv.png')

fig, ax = plt.subplots(figsize=(9, 6), dpi=150)
ax.scatter(st.freight_pct, st.avg_order_value, s=[max(25, o / 60) for o in st.n_orders],
           color=BLUE, alpha=0.75, edgecolors='white', linewidths=1.2)
OFF = {'SP': (0.35, -1, 'left'), 'RJ': (-0.1, 4.5, 'right'), 'DF': (-0.35, 0, 'right'), 'MG': (-0.25, -3, 'right'),
       'PR': (0, -3.5, 'center'), 'ES': (0, -3.2, 'center'), 'RS': (0.2, -1, 'left'), 'SC': (0.05, 3, 'left'),
       'GO': (0.15, 1, 'left'), 'MS': (0.15, 1, 'left'), 'BA': (0.15, 1, 'left')}   # 겹치는 이름표 위치 조정
for _, r in st.iterrows():
    dx, dy, ha = OFF.get(r.customer_state, (0.12, 2, 'left'))
    ax.text(r.freight_pct + dx, r.avg_order_value + dy, r.customer_state, fontsize=9, color=K, ha=ha, va='center')
ax.set_xlabel('배송비 비중 (%)')
ax.set_ylabel('객단가 (헤알)')
for s in ['top', 'right']:
    ax.spines[s].set_visible(False)
ax.grid(color=GRID, lw=0.8)
ax.set_axisbelow(True)
ax.tick_params(length=0)
head(ax, '주별 배송비 비중과 객단가(2017.01~2018.08)', SUB + ' | 점 크기 = 주문 수')
save(fig, 'g05_state_freight_aov.png')

# ---- 그래프 6: 구매 횟수별 1명당 거래액 ---------------------------------
p = read('03_purchase_count.csv')
fig, ax = plt.subplots(figsize=(8, 4.8), dpi=150)
b = ax.bar(p.purchase_cnt, p.gmv_per_customer, color=BLUE, width=0.5)
for r, (_, row) in zip(b, p.iterrows()):
    ax.text(r.get_x() + r.get_width() / 2, row.gmv_per_customer + 8,
            f'{row.gmv_per_customer:,.0f}헤알\n(고객 {row.customer_pct}%)', ha='center', fontsize=10)
ax.set_ylim(0, 520)
ax.set_ylabel('고객 1명당 거래액 (헤알)')
ax.set_xlabel('구매 횟수')
clean(ax)
head(ax, '구매 횟수별 고객 1명당 거래액(2017.01~2018.08)')
save(fig, 'g06_purchase_count.png')

# ---- 그래프 7: 카테고리 상위 10 -----------------------------------------
KO = {'bed_bath_table': '침구·욕실', 'health_beauty': '건강·미용', 'sports_leisure': '스포츠·레저',
      'computers_accessories': '컴퓨터 액세서리', 'furniture_decor': '가구·인테리어', 'housewares': '생활용품',
      'watches_gifts': '시계·선물', 'telephony': '휴대폰·통신', 'auto': '자동차용품', 'toys': '장난감'}
cat = read('04_category_top10.csv').assign(name=lambda d: d.category.map(KO).fillna(d.category))
save(hbar(cat, 'name', 'n_orders', lambda r: f"{r.n_orders:,}건 ({r.order_pct}%)",
          '카테고리별 주문 수 상위 10개(2017.01~2018.08)', '주문 수 (건)', 11500, 6.2), 'g07_category_top10.png')

# ---- 그래프 8: 주문 금액 구간 구성 (100% 누적 막대) ------------------------
v = read('05_order_value_band.csv')
bands = [s.split(') ')[1] for s in v.value_band]
cols = ['#b7d3f6', '#6da7ec', '#2a78d6', '#1c5cab', '#0d366b']
fig, ax = plt.subplots(figsize=(10, 4.2), dpi=150)
for row, col in enumerate(['gmv_pct', 'order_pct']):
    left = 0
    for val, cl, i in zip(v[col], cols, range(5)):
        ax.barh(row, val, left=left, color=cl, height=0.55, edgecolor='white', linewidth=2)
        if val >= 6:
            ax.text(left + val / 2, row, f'{val}%', ha='center', va='center', fontsize=10, color=K if i < 2 else 'white')
        else:
            ax.text(left + val / 2, row + 0.36, f'{val}%', ha='center', va='bottom', fontsize=10)
        left += val
ax.set_yticks([0, 1])
ax.set_yticklabels(['거래액', '주문 수'], fontsize=11)
ax.set_xlim(0, 100)
ax.xaxis.set_major_formatter(mt.FuncFormatter(lambda x, p: f'{int(x)}%'))
for s in ['top', 'right', 'left', 'bottom']:
    ax.spines[s].set_visible(False)
ax.tick_params(length=0)
ax.legend(handles=[Patch(color=c_, label=b_) for c_, b_ in zip(cols, bands)], title='주문 금액 (헤알)',
          frameon=False, ncol=5, loc='upper center', bbox_to_anchor=(0.5, -0.12), fontsize=9)
head(ax, '주문 금액 구간별 주문 수와 거래액 구성(2017.01~2018.08)')
save(fig, 'g08_order_value_band.png')

# ---- 그래프 9: 두 번째 주문까지 걸린 기간 ---------------------------------
gp = read('06_repurchase_gap.csv')
labels = [s.split(') ')[1] for s in gp.gap_band]
fig, ax = plt.subplots(figsize=(10, 4.8), dpi=150)
ax.bar(range(len(gp)), gp.n_customers, color=[GRAY] + [BLUE] * (len(gp) - 1), width=0.62)
for i, (n_, p_) in enumerate(zip(gp.n_customers, gp.pct)):
    ax.text(i, n_ + 15, f'{n_:,}명\n({p_}%)', ha='center', va='bottom', fontsize=9.5)
ax.set_xticks(range(len(gp)))
ax.set_xticklabels(labels)
ax.set_ylim(0, 1050)
ax.set_ylabel('고객 수 (명)')
ax.set_xlabel('첫 주문 → 두 번째 주문까지 걸린 기간')
real = gp.n_customers[1:].sum()
ax.legend(handles=[Patch(color=GRAY, label='같은 날 (재구매에서 제외)'), Patch(color=BLUE, label=f'진짜 재구매 {real:,}명')],
          frameon=False, loc='upper right', fontsize=9.5)
clean(ax)
head(ax, '두 번째 주문까지 걸린 기간(2017.01~2018.08)', f'{SUB} · 2번 이상 구매한 고객 {gp.n_customers.sum():,}명')
save(fig, 'g09_repurchase_gap.png')

# ---- 그래프 10: 확장 퍼널 ------------------------------------------------
f = read('07_funnel_experience.csv').iloc[0]
n = [f.s1_ordered, f.s2_delivered, f.s3_on_time, f.s4_satisfied]
st_ = ['1. 주문', '2. 배송 완료', '3. 예상일 안에 도착', '4. 리뷰 4점 이상']
fig, ax = plt.subplots(figsize=(10, 5.2), dpi=150)
y = list(range(4))[::-1]
ax.barh(y, n, color=BLUE, height=0.6)
for i, (yi, v_) in enumerate(zip(y, n)):
    t = f'{v_:,}건 ({100*v_/n[0]:.1f}%)'.replace('(100.0%)', '(100%)') + (f'  ← 이전 단계의 {100*v_/n[i-1]:.1f}%' if i else '')
    ax.text(v_ + 800, yi, t, va='center', fontsize=10)
ax.set_yticks(y)
ax.set_yticklabels(st_, fontsize=11)
ax.set_xlim(0, 135000)
ax.xaxis.set_major_formatter(mt.FuncFormatter(lambda x, p: f'{int(x):,}'))
ax.set_xlabel('주문 수 (건)')
clean(ax, 'x')
head(ax, '주문부터 고객 만족까지 퍼널(2017.01~2018.08)', 'delivered인데 날짜가 빈 주문 23건 제외')
fig.text(0.01, 0.01, f'* 제때 도착한 주문의 {100*f.reviewed_on_time/f.s3_on_time:.1f}%({f.reviewed_on_time:,}건)가 리뷰를 작성해, '
         '4단계 감소는 대부분 1~3점 리뷰에 의한 것임', fontsize=9)
fig.tight_layout(rect=(0, 0.04, 1, 1))
fig.savefig(os.path.join(OUT, 'g10_funnel_experience.png'), facecolor='white')
plt.close(fig)

# ---- 그래프 11: 예상일 대비 도착 시점별 1~2점 비율 -------------------------
dl = read('08_delay_band_review.csv')
lab = ['15일 이상\n일찍', '8~14일\n일찍', '1~7일\n일찍', '예상일\n당일', '1~3일\n지연', '4~7일\n지연', '8~14일\n지연', '15일 이상\n지연']
fig, ax = plt.subplots(figsize=(10, 5.2), dpi=150)
b = ax.bar(range(8), dl.low_review_pct, color=[BLUE] * 4 + [ORANGE] * 4, width=0.62)
for r, v_ in zip(b, dl.low_review_pct):
    ax.text(r.get_x() + r.get_width() / 2, v_ + 1.5, f'{v_}%', ha='center', fontsize=10)
ax.set_xticks(range(8))
ax.set_xticklabels(lab, fontsize=9.5)
ax.set_ylim(0, 95)
ax.set_ylabel('리뷰 1~2점 비율 (%)')
ax.set_xlabel('예상 배송일 대비 실제 도착')
ax.legend(handles=[Patch(color=BLUE, label='예상일 안에 도착'), Patch(color=ORANGE, label='예상일보다 늦게 도착')],
          frameon=False, loc='upper left', fontsize=9)
clean(ax)
head(ax, '예상 배송일 대비 도착 시점별 1~2점 리뷰 비율(2017.01~2018.08)', '배송 완료 주문 기준')
save(fig, 'g11_delay_band_review.png')

# ---- 그래프 12: 주별 지연 주문 상위 10 -----------------------------------
sd = read('09_state_delay.csv').head(10)
total_late = 6530   # 전체 지연 주문 (15_region_delay.sql ① n_late 합계)
save(hbar(sd, 'state', 'n_late',
          lambda r: f"{r.n_late:,}건 ({r.late_share}%)  · 지연율 {r.late_pct}% (배송 완료 {r.n_orders:,}건 중)",
          '주별 지연 주문 수 상위 10개 주(2017.01~2018.08)', '지연 주문 수 (건)', 3000, 5.4,
          f'배송 완료 주문 기준, delivered인데 날짜가 빈 주문 23건 제외 · 괄호는 전체 지연 주문 {total_late:,}건 중 비중'),
     'g12_state_delay.png')

# ---- 그래프 13: 최소 효과별 검정력 (python/ab_simulation.py 실행 후) --------
if os.path.exists(os.path.join(DATA, '10_power_curve.csv')):
    pc = read('10_power_curve.csv')
    fig, ax = plt.subplots(figsize=(9, 5), dpi=150)
    for file, lab, cl in [('outputs/ab_base.csv', '37,211명 (처음 설계)', GRAY),
                          ('outputs/ab_base_ext.csv', '58,071명 (최종 설계)', BLUE)]:
        d = pc[pc.file == file]
        ax.plot((d.lift - 1) * 100, d.power * 100, color=cl, lw=2.2, marker='o', ms=5, mec='white', label=lab)
    ax.axhline(80, color=ORANGE, lw=1.2, ls='--')
    ax.text(20.3, 81.5, '목표 검정력 80%', color=ORANGE, fontsize=9)
    ax.axvline(33, color=K, lw=0.8, ls=':')
    ax.text(33.4, 32, '최소 효과 33%', fontsize=9)
    ax.set_xlabel('가정한 쿠폰 효과 (재구매율 증가, %)')
    ax.set_ylabel('검정력 (%)')
    ax.set_ylim(30, 102)
    ax.legend(frameon=False, loc='lower right')
    clean(ax)
    head(ax, '쿠폰 효과 크기별 검정력 (1,000번 시뮬레이션)', '배송 후 30일 재구매율, 단측 5% · 시드 42')
    save(fig, 'g13_power_curve.png')

print('images/ 폴더에 저장')
