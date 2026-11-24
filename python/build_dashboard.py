"""
Olist 재구매 모니터링 대시보드 생성
------------------------------------------------------------
재구매와 관련된 지표를 기준월마다 다시 계산하고, 평소 범위를 벗어났는지 판정해
HTML 대시보드(ECharts)로 만든다.

  핵심 지표 : 첫 구매 고객 재구매율 (배송 후 30일 이내)
              예상일 초과 도착 비율, 1~2점 리뷰 비율   (배송 경험)
              주문 수, 거래액                          (참고)

입력 : outputs/orders_mart.csv     (주문 1건 = 1행, sql/06_dashboard/40_dashboard_exports.sql ①)
       outputs/first_purchase.csv  (첫 구매 고객 1명 = 1행, 같은 파일 ②)
출력 : dashboard/index.html        (GitHub Pages로 게시)
       dashboard/analysis.json     (판정 결과. AI 해석의 입력으로 사용)
상태 : dashboard/state.json        (현재 기준월)

[운영 시뮬레이션]
기준월의 마지막 날을 '데이터 기준일'로 보고, 그날까지 일어난 일만 사용한다.
  - 주문      : 주문일 <= 기준일
  - 배송 완료  : 도착일 <= 기준일 (주문 상태값이 아니라 날짜로 판단)
  - 재구매율   : 배송 완료일 + 30일 <= 기준일인 첫 구매 고객만 계산

[평소 범위]
비율 지표마다 직전 6개월(최소 4개월)의 월별 값으로 평균 ± 2 × 표준편차를 계산한다.
이번 달 값이 이 범위를 나쁜 쪽으로 벗어나면 '주의', 그 밖에는 '정상'.

실행
  python python/build_dashboard.py              # state.json의 기준월로 생성
  python python/build_dashboard.py --advance    # 기준월을 한 달 넘기고 생성 (자동 실행용)
  python python/build_dashboard.py --month 2018-08
  python python/build_dashboard.py --validate   # 원본 분석 숫자와 대조
"""
import argparse
import json
import os
from datetime import datetime

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORDERS = os.path.join(ROOT, "outputs", "orders_mart.csv")
FIRST = os.path.join(ROOT, "outputs", "first_purchase.csv")
OUT_DIR = os.path.join(ROOT, "dashboard")
STATE = os.path.join(OUT_DIR, "state.json")

FIRST_MONTH = pd.Period("2017-06", "M")   # 평소 범위 판정에 필요한 직전 4개월이 쌓이는 첫 달
LAST_MONTH = pd.Period("2018-08", "M")    # 분석 기간 마지막 달
REGIONS = ["남동부", "남부", "중서부", "북동부", "북부"]
BASE_WINDOW, BASE_MIN, Z = 6, 4, 2.0      # 평소 범위: 직전 6개월(최소 4개월) 평균 ± 2 × 표준편차
ECHARTS = "https://cdn.jsdelivr.net/npm/echarts@5.6.0/dist/echarts.min.js"


# ================================================================== 데이터
def load():
    o = pd.read_csv(ORDERS, encoding="utf-8",
                    parse_dates=["purchase_date", "delivered_date", "estimated_date"])
    f = pd.read_csv(FIRST, encoding="utf-8", na_values=["NULL"],
                    parse_dates=["first_purchase_at", "delivered_at", "repurchase_at"])
    o["month"] = o["purchase_date"].dt.to_period("M")
    o["valid"] = ~o["order_status"].isin(["canceled", "unavailable"])   # 거래액 계산용
    f["deliv_month"] = f["delivered_at"].dt.to_period("M")
    return o, f


def pl(m):
    """화면 표시용 월 표기: 2018.07"""
    return f"{m.year}.{m.month:02d}"


def month_end(m):
    return m.to_timestamp(how="end").normalize()


def as_of(o, f, cutoff):
    """기준일(cutoff)까지 관찰 가능한 데이터만 남긴다."""
    oo = o[o["purchase_date"] <= cutoff].copy()
    oo["deliv"] = oo["delivered_date"].notna() & (oo["delivered_date"] <= cutoff)
    oo["late"] = oo["deliv"] & (oo["delivered_date"] > oo["estimated_date"])
    oo["on_time"] = oo["deliv"] & ~oo["late"]
    oo["deliv_month"] = oo["delivered_date"].dt.to_period("M")
    ff = f[f["delivered_at"] + pd.Timedelta(days=30) <= cutoff].copy()
    return oo, ff


def delay_band(d):
    if d <= -15: return "15일+ 일찍"
    if d <= -8:  return "8~14일 일찍"
    if d <= -1:  return "1~7일 일찍"
    if d == 0:   return "당일"
    if d <= 3:   return "1~3일 늦음"
    if d <= 7:   return "4~7일 늦음"
    if d <= 14:  return "8~14일 늦음"
    return "15일+ 늦음"


BANDS = ["15일+ 일찍", "8~14일 일찍", "1~7일 일찍", "당일",
         "1~3일 늦음", "4~7일 늦음", "8~14일 늦음", "15일+ 늦음"]


# ================================================================== 월별 지표
def experience_by_month(oo):
    """배송 완료월별 배송 경험: 예상일 초과 도착 비율, 1~2점 리뷰 비율"""
    d = oo[oo["deliv"]]
    late = d.groupby("deliv_month").agg(late=("late", "mean"), late_n=("late", "size"))
    rv = d[d["review_score"].notna()]
    low = rv.groupby("deliv_month")["review_score"].agg(
        low=lambda s: (s <= 2).mean(), low_n="size")
    return late.join(low)


def repurchase_by_cohort(ff, cutoff):
    """배송 완료월(코호트)별 30일 이내 재구매율. 30일 관찰이 모두 끝난 달만 포함."""
    done = [m for m in ff["deliv_month"].unique()
            if month_end(m) + pd.Timedelta(days=31) <= cutoff + pd.Timedelta(days=1)]
    g = ff[ff["deliv_month"].isin(done)]
    se = g[g["region"] == "남동부"]
    return pd.DataFrame({
        "all": g.groupby("deliv_month")["rep30"].mean(),
        "all_n": g.groupby("deliv_month").size(),
        "se": se.groupby("deliv_month")["rep30"].mean(),
        "se_n": se.groupby("deliv_month").size(),
    }).sort_index()


# ================================================================== 평소 범위 판정
def control_limits(p, n=None):
    """평소 범위: 각 달마다 직전 BASE_WINDOW개월(최소 BASE_MIN개월) 비율의 평균 ± Z × 표준편차.
    (n은 쓰지 않음. 매달 표본이 수천 건이라 달마다 표본 수 차이는 고려하지 않음)"""
    p = p.astype(float)
    lo, mid, hi = [], [], []
    for i in range(len(p)):
        w = p.iloc[max(0, i - BASE_WINDOW):i]
        if len(w) < BASE_MIN:
            lo.append(np.nan); mid.append(np.nan); hi.append(np.nan)
            continue
        m, sd = w.mean(), w.std(ddof=1)
        lo.append(max(m - Z * sd, 0)); mid.append(m); hi.append(m + Z * sd)
    return pd.DataFrame({"lo": lo, "mid": mid, "hi": hi}, index=p.index)


def judge(value, lim, higher_is_bad):
    """평소 범위 대비 (상태, 위치).
    상태: 정상 / 주의(나쁜 방향으로 벗어남) / 판정 보류
    위치: 범위 안 / 범위보다 높음 / 범위보다 낮음 (좋은 방향으로 벗어나도 상태는 정상)"""
    if lim is None or pd.isna(lim["lo"]):
        return "판정 보류", None
    if value > lim["hi"]:
        pos = "범위보다 높음"
    elif value < lim["lo"]:
        pos = "범위보다 낮음"
    else:
        return "정상", "범위 안"
    worse = value > lim["hi"] if higher_is_bad else value < lim["lo"]
    return ("주의" if worse else "정상"), pos


# ================================================================== 계산
def compute(o, f, month):
    cutoff = month_end(month)
    oo, ff = as_of(o, f, cutoff)

    exp = experience_by_month(oo)
    exp = exp[exp.index <= month]
    late_lim = control_limits(exp["late"], exp["late_n"])
    low_lim = control_limits(exp["low"], exp["low_n"])

    coh = repurchase_by_cohort(ff, cutoff)
    rep_lim = control_limits(coh["all"], coh["all_n"])

    cm, pm = coh.index[-1], coh.index[-2]          # 최근 코호트, 그 전 코호트

    def row(series, lim, key, higher_is_bad, prev_key):
        v, p = series.loc[key], series.loc[prev_key] if prev_key in series.index else np.nan
        l = lim.loc[key] if key in lim.index else None
        status, pos = judge(v, l, higher_is_bad)
        return dict(value=float(v), prev=float(p), status=status, position=pos,
                    lo=None if l is None or pd.isna(l["lo"]) else float(l["lo"]),
                    hi=None if l is None or pd.isna(l["hi"]) else float(l["hi"]))

    def ref(m):
        orders = oo[oo["month"] == m]
        return len(orders), float(orders.loc[orders["valid"], "item_price"].sum())

    orders, gmv = ref(month)
    orders_p, gmv_p = ref(month - 1)

    metrics = dict(
        repurchase=dict(row(coh["all"], rep_lim, cm, False, pm),
                        cohort=str(cm), n=int(coh.loc[cm, "all_n"]),
                        se=float(coh.loc[cm, "se"]), se_prev=float(coh.loc[pm, "se"]),
                        se_n=int(coh.loc[cm, "se_n"])),
        late=dict(row(exp["late"], late_lim, month, True, month - 1),
                  n=int(exp.loc[month, "late_n"])),
        low_review=dict(row(exp["low"], low_lim, month, True, month - 1),
                        n=int(exp.loc[month, "low_n"])),
        orders=dict(value=orders, prev=orders_p),
        gmv=dict(value=gmv, prev=gmv_p),
    )

    # 주별 분해: 예상일 초과 도착 비율 변화에 대한 기여도 (각 주 기여의 합 = 전체 변화)
    cur = oo[oo["deliv"] & (oo["deliv_month"] == month)]
    pre = oo[oo["deliv"] & (oo["deliv_month"] == month - 1)]
    st = pd.DataFrame({
        "region": cur.groupby("customer_state")["region"].first(),
        "n": cur.groupby("customer_state").size(),
        "late_n": cur.groupby("customer_state")["late"].sum(),
        "n_prev": pre.groupby("customer_state").size(),
        "late_n_prev": pre.groupby("customer_state")["late"].sum(),
    }).fillna(0)
    st["rate"] = st["late_n"] / st["n"].replace(0, np.nan)
    st["rate_prev"] = st["late_n_prev"] / st["n_prev"].replace(0, np.nan)
    st["contrib"] = st["late_n"] / len(cur) - st["late_n_prev"] / len(pre)
    total_change = metrics["late"]["value"] - metrics["late"]["prev"]
    st = st[st["n"] >= 50].sort_values("contrib", ascending=total_change < 0)
    states = st.head(5)

    # 권역별 재구매율: 최근 6개월 코호트 vs 그 전 6개월 코호트 (30일 관찰이 끝난 배송 완료월)
    done = coh.index
    recent, before = done[-6:], done[-12:-6]

    def region_rate(months):
        g = ff[ff["deliv_month"].isin(months)]
        return g.groupby("region")["rep30"].mean(), g.groupby("region").size()

    rr, rn = region_rate(recent)
    br, bn = region_rate(before)
    reg = pd.DataFrame({"recent": rr, "recent_n": rn, "before": br, "before_n": bn}).reindex(REGIONS)
    reg_label = (f"{pl(recent[0])}~{pl(recent[-1])}",
                 f"{pl(before[0])}~{pl(before[-1])}" if len(before) else None)

    # 예상 도착일 대비 도착 시점별 1~2점 리뷰 비율: 이번 달 배송 vs 직전 12개월 배송
    d = oo[oo["deliv"] & oo["review_score"].notna()].copy()
    d["band"] = d["delay_days"].apply(delay_band)
    in_cur = d["deliv_month"] == month
    in_prev = (d["deliv_month"] < month) & (d["deliv_month"] >= month - 12)

    def band_rate(x):
        return x.groupby("band")["review_score"].agg(n="size", low=lambda v: (v <= 2).mean()).reindex(BANDS)

    bc, bp = band_rate(d[in_cur]), band_rate(d[in_prev])
    band = pd.DataFrame({"cur": bc["low"], "cur_n": bc["n"], "prev": bp["low"], "prev_n": bp["n"]})
    band_prev_label = f"{pl(max(month - 12, d['deliv_month'].min()))}~{pl(month - 1)}"

    # 퍼널: 전월 주문 기준 (각 주문월은 다음 달 말일 시점으로 평가해 배송 시간을 같게 맞춤)
    def funnel_of(pm):
        cut = month_end(pm + 1)
        x = o[o["month"] == pm]
        deliv = x["delivered_date"].notna() & (x["delivered_date"] <= cut)
        on_time = deliv & (x["delivered_date"] <= x["estimated_date"])
        good = on_time & (x["review_score"] >= 4)
        return [len(x), int(deliv.sum()), int(on_time.sum()), int(good.sum())]

    fm = month - 1
    f_cur = funnel_of(fm)
    f_base = [funnel_of(fm - k) for k in (1, 2, 3) if fm - k >= pd.Period("2017-01", "M")]
    f_avg = [float(np.mean([b[i] / b[0] for b in f_base])) for i in range(4)] if f_base else [np.nan] * 4
    funnel = dict(steps=["주문", "배송 완료", "예상일 안에 도착", "리뷰 4점 이상"],
                  cur=f_cur, cur_pct=[v / f_cur[0] for v in f_cur], base_pct=f_avg,
                  cur_label=pl(fm),
                  base_label=f"{pl(fm - len(f_base))}~{pl(fm - 1)}" if f_base else None)

    monthly = (oo.groupby("month").agg(orders=("order_id", "size"))
                 .join(oo[oo["valid"]].groupby("month")["item_price"].sum().rename("gmv")))

    return dict(month=month, cutoff=cutoff, metrics=metrics, total_late_change=total_change,
                exp=exp, late_lim=late_lim, low_lim=low_lim, coh=coh, rep_lim=rep_lim,
                states=states, reg=reg, reg_label=reg_label, band=band, band_prev_label=band_prev_label,
                funnel=funnel, monthly=monthly)


# ================================================================== 해석 (규칙 기반, 4단계에서 AI로 교체)
NAMES = {"repurchase": "첫 구매 고객 재구매율", "late": "예상일 초과 도착 비율",
         "low_review": "1~2점 리뷰 비율"}


def analysis_payload(r):
    """AI 해석에 넘길 입력. 계산은 전부 여기서 끝내고 AI에는 결과만 준다."""
    m = r["metrics"]
    top = [dict(state=s, region=row["region"], orders=int(row["n"]),
                rate=round(row["rate"] * 100, 1), rate_prev=None if pd.isna(row["rate_prev"]) else round(row["rate_prev"] * 100, 1),
                contribution_pp=round(row["contrib"] * 100, 2))
           for s, row in r["states"].iterrows()]
    pct = lambda v, d=2: None if v is None or pd.isna(v) else round(v * 100, d)
    return dict(
        month=str(r["month"]),
        metrics={k: dict(name=NAMES[k], value_pct=pct(m[k]["value"]), prev_pct=pct(m[k]["prev"]),
                         normal_range_pct=[pct(m[k]["lo"]), pct(m[k]["hi"])], status=m[k]["status"],
                         position=m[k]["position"])
                 for k in NAMES},
        repurchase_detail=dict(cohort=m["repurchase"]["cohort"], customers=m["repurchase"]["n"],
                               southeast_pct=pct(m["repurchase"]["se"])),
        late_change_by_state=top,
        orders=dict(value=m["orders"]["value"], prev=m["orders"]["prev"]),
    )


def rule_comment(r):
    """규칙 기반 요약 (개조식): (결론 1줄, 상세 목록). AI 해석을 붙이면 AI 문장으로 교체, 검증 실패 시 대체용"""
    m = r["metrics"]
    warn = [k for k in NAMES if m[k]["status"] == "주의"]
    outside = [k for k in NAMES if m[k]["position"] in ("범위보다 높음", "범위보다 낮음")]

    if warn:
        headline = "주의: " + ", ".join(
            f"{NAMES[k]} 평소 범위 {'초과' if m[k]['position'] == '범위보다 높음' else '미달'} "
            f"({m[k]['value'] * 100:.{2 if k == 'repurchase' else 1}f}%)" for k in warn)
    else:
        headline = "주요 지표 모두 정상 범위"

    details = []
    for k in outside:
        x = m[k]
        details.append(f"{NAMES[k]} {x['value'] * 100:.2f}% (전월 {x['prev'] * 100:.2f}%), "
                       f"평소 범위 {x['lo'] * 100:.2f}~{x['hi'] * 100:.2f}% · {x['position']}")
    if not outside:
        details.append("평소 범위를 벗어난 지표 없음")
    if len(r["states"]):
        s = r["states"].iloc[0]
        details.append(f"예상일 초과 도착 비율 전월 대비 {r['total_late_change'] * 100:+.2f}%p, "
                       f"가장 큰 기여는 {r['states'].index[0]}({s['region']}) {s['contrib'] * 100:+.2f}%p")
    if "late" in warn or "low_review" in warn:
        details.append("예상일 초과 도착은 1~2점 리뷰 증가·낮은 재구매율과 관련 → 다음 달 재구매율 확인 필요")
    return headline, details


# ================================================================== HTML
def fmt_delta(cur, prev, kind):
    if prev is None or pd.isna(prev) or prev == 0:
        return '<span class="delta">전월 비교 없음</span>'
    v = round((cur / prev - 1) * 100, 1) if kind == "pct" else round((cur - prev) * 100, 2)
    txt = f"{abs(v):.1f}%" if kind == "pct" else f"{abs(v):.2f}%p"
    arrow = "▲" if v > 0 else "▼" if v < 0 else "–"
    return f'<span class="delta">{arrow} {txt} 전월 대비</span>'


def badge(status):
    cls = {"정상": "ok", "주의": "warn"}.get(status, "na")
    icon = {"정상": "●", "주의": "!"}.get(status, "○")
    return f'<span class="badge {cls}">{icon} {status}</span>'


def range_note(x, digits=2):
    if x.get("lo") is None:
        return "평소 범위 계산에 필요한 기간 부족"
    pos = f" · {x['position']}" if x.get("position") not in (None, "범위 안") else ""
    return f"평소 범위 {x['lo'] * 100:.{digits}f}~{x['hi'] * 100:.{digits}f}%{pos}"


def cards_html(r):
    m, mon = r["metrics"], r["month"]
    rp, lt, lw = m["repurchase"], m["late"], m["low_review"]
    return f"""
<div class="card">
  <div class="label">첫 구매 고객 재구매율 <span class="hint">배송 후 30일 이내</span></div>
  <div class="row"><div class="value">{rp['value'] * 100:.2f}%</div>{badge(rp['status'])}</div>
  {fmt_delta(rp['value'], rp['prev'], 'pp')}
  <div class="note">{rp['cohort']} 배송 고객 {rp['n']:,}명 · 남동부 {rp['se'] * 100:.2f}%<br>{range_note(rp)}</div>
</div>
<div class="card">
  <div class="label">예상일 초과 도착 비율</div>
  <div class="row"><div class="value">{lt['value'] * 100:.1f}%</div>{badge(lt['status'])}</div>
  {fmt_delta(lt['value'], lt['prev'], 'pp')}
  <div class="note">{mon} 배송 완료 {lt['n']:,}건<br>{range_note(lt, 1)}</div>
</div>
<div class="card">
  <div class="label">1~2점 리뷰 비율</div>
  <div class="row"><div class="value">{lw['value'] * 100:.1f}%</div>{badge(lw['status'])}</div>
  {fmt_delta(lw['value'], lw['prev'], 'pp')}
  <div class="note">{mon} 배송 완료 주문 중 리뷰 {lw['n']:,}건<br>{range_note(lw, 1)}</div>
</div>
<div class="card">
  <div class="label">주문 수 · 거래액</div>
  <div class="row"><div class="value">{m['orders']['value']:,}건</div></div>
  {fmt_delta(m['orders']['value'], m['orders']['prev'], 'pct')}
  <div class="row sub"><div class="value small">{m['gmv']['value'] / 10000:,.1f}만 헤알</div></div>
  {fmt_delta(m['gmv']['value'], m['gmv']['prev'], 'pct')}
  <div class="note">{mon} 주문 기준 · 거래액은 배송비 제외</div>
</div>"""


def states_table(r):
    st = r["states"]
    if not len(st):
        return "<p class='note'>비교할 주가 없음</p>"
    rows = "".join(
        f"<tr><td>{s}</td><td>{x['region']}</td><td class='num'>{int(x['n']):,}</td>"
        f"<td class='num'>{'' if pd.isna(x['rate_prev']) else f'{x.rate_prev * 100:.1f}%'}</td>"
        f"<td class='num'><b>{x['rate'] * 100:.1f}%</b></td>"
        f"<td class='num'>{x['contrib'] * 100:+.2f}%p</td></tr>"
        for s, x in st.iterrows())
    return f"""<table>
<thead><tr><th>주</th><th>권역</th><th class='num'>배송 완료</th><th class='num'>전월</th>
<th class='num'>이번 달</th><th class='num'>전체 변화 기여</th></tr></thead><tbody>{rows}</tbody></table>
<p class='note'>전체 예상일 초과 도착 비율 변화 {r['total_late_change'] * 100:+.2f}%p를 주별로 나눈 값 · 배송 완료 50건 이상인 주만 표시</p>"""


def chart_data(r):
    lab = lambda idx: [f"{p.year}.{p.month:02d}" for p in idx]
    nz = lambda s, d=3: [None if pd.isna(v) else round(float(v) * 100, d) for v in s]
    coh, exp = r["coh"], r["exp"]
    return dict(
        rep=dict(x=lab(coh.index), all=nz(coh["all"]), se=nz(coh["se"]),
                 lo=nz(r["rep_lim"]["lo"]), hi=nz(r["rep_lim"]["hi"])),
        late=dict(x=lab(exp.index), y=nz(exp["late"], 2),
                  lo=nz(r["late_lim"]["lo"], 2), hi=nz(r["late_lim"]["hi"], 2)),
        low=dict(x=lab(exp.index), y=nz(exp["low"], 2),
                 lo=nz(r["low_lim"]["lo"], 2), hi=nz(r["low_lim"]["hi"], 2)),
        region=dict(x=list(r["reg"].index), recent=nz(r["reg"]["recent"]), before=nz(r["reg"]["before"]),
                    recent_n=[0 if pd.isna(v) else int(v) for v in r["reg"]["recent_n"]],
                    before_n=[0 if pd.isna(v) else int(v) for v in r["reg"]["before_n"]],
                    recent_label=r["reg_label"][0], before_label=r["reg_label"][1]),
        band=dict(x=BANDS, cur=nz(r["band"]["cur"], 1), prev=nz(r["band"]["prev"], 1),
                  cur_n=[0 if pd.isna(v) else int(v) for v in r["band"]["cur_n"]],
                  prev_n=[0 if pd.isna(v) else int(v) for v in r["band"]["prev_n"]],
                  cur_label=pl(r["month"]), prev_label=r["band_prev_label"]),
        funnel=dict(x=r["funnel"]["steps"], cur=nz(r["funnel"]["cur_pct"], 1),
                    base=nz(r["funnel"]["base_pct"], 1), cur_n=r["funnel"]["cur"],
                    cur_label=r["funnel"]["cur_label"], base_label=r["funnel"]["base_label"]),
        monthly=dict(x=lab(r["monthly"].index), orders=[int(v) for v in r["monthly"]["orders"]],
                     gmv=[round(float(v) / 10000, 1) for v in r["monthly"]["gmv"]]),
    )


def build_html(r, headline, details, comment_source=""):
    built = datetime.now().strftime("%Y-%m-%d %H:%M")
    data = json.dumps(chart_data(r), ensure_ascii=False)
    detail_html = "".join(f"<li>{d}</li>" for d in details)
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Olist 재구매 모니터링 대시보드</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css">
<script src="{ECHARTS}"></script>
<style>
  :root {{
    --bg:#f5f5f3; --surface:#ffffff; --line:#e6e5e0;
    --ink:#0b0b0b; --ink2:#52514e; --ink3:#8a8984;
    --blue:#2a78d6; --orange:#eb6834;
    --ok-bg:#eef3ee; --ok:#2f6b3a; --warn-bg:#fdecea; --warn:#b42318; --good-bg:#e8f0fb; --good:#1f5fae;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
         font-family:Pretendard,'Malgun Gothic','Apple SD Gothic Neo',sans-serif; }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:32px 20px 56px; }}
  header {{ display:flex; justify-content:space-between; align-items:flex-end; gap:12px; flex-wrap:wrap; }}
  h1 {{ font-size:24px; margin:0; letter-spacing:-0.02em; }}
  .meta {{ color:var(--ink2); font-size:13px; line-height:1.6; text-align:right; }}
  .headline {{ margin:20px 0 16px; padding:18px 22px; background:var(--surface); border:1px solid var(--line);
               border-left:4px solid var(--blue); border-radius:12px; font-size:17px; font-weight:600; line-height:1.6; }}
  .headline small {{ display:block; font-size:12px; font-weight:400; color:var(--ink3); margin-top:4px; }}
  .cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }}
  .card {{ background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:16px 18px; }}
  .label {{ font-size:13px; color:var(--ink2); }}
  .hint {{ color:var(--ink3); font-size:12px; }}
  .row {{ display:flex; align-items:center; gap:10px; margin:8px 0 4px; }}
  .row.sub {{ margin-top:10px; }}
  .value {{ font-size:28px; font-weight:700; letter-spacing:-0.02em; }}
  .value.small {{ font-size:20px; }}
  .badge {{ font-size:12px; font-weight:600; padding:3px 8px; border-radius:999px; white-space:nowrap; }}
  .badge.ok {{ background:var(--ok-bg); color:var(--ok); }}
  .badge.warn {{ background:var(--warn-bg); color:var(--warn); }}
  .badge.good {{ background:var(--good-bg); color:var(--good); }}
  .badge.na {{ background:#f0f0ee; color:var(--ink3); }}
  .delta {{ font-size:13px; color:var(--ink2); }}
  .note {{ font-size:11.5px; color:var(--ink3); margin-top:8px; line-height:1.55; }}
  h2 {{ font-size:17px; margin:36px 0 12px; letter-spacing:-0.01em; }}
  h2 span {{ font-size:12.5px; font-weight:400; color:var(--ink3); margin-left:8px; }}
  .panel {{ background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:18px 18px 10px; min-width:0; }}
  .panel h3 {{ font-size:14.5px; margin:0 0 2px; }}
  .panel .desc {{ font-size:12px; color:var(--ink3); margin-bottom:4px; }}
  .chart {{ width:100%; height:300px; }}
  .chart.tall {{ height:330px; }}
  .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
  .stack {{ display:grid; gap:12px; }}
  .detail {{ margin:0; padding-left:18px; line-height:1.8; font-size:14px; }}
  .src {{ font-size:11.5px; color:var(--ink3); margin-top:8px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13.5px; margin-top:8px; }}
  th {{ text-align:left; font-weight:600; color:var(--ink2); border-bottom:1px solid var(--line); padding:8px 6px; font-size:12.5px; }}
  td {{ border-bottom:1px solid #f0efeb; padding:9px 6px; }}
  .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  footer {{ color:var(--ink3); font-size:12px; line-height:1.7; margin-top:32px; }}
  footer a {{ color:var(--ink2); }}
  @media (max-width:900px) {{ .cards {{ grid-template-columns:1fr 1fr; }} .grid2 {{ grid-template-columns:1fr; }} .meta {{ text-align:left; }} }}
</style></head>
<body><div class="wrap">

<header>
  <h1>Olist 재구매 모니터링</h1>
  <div class="meta">기준월 <b>{r['month']}</b> · 데이터 기준일 {r['cutoff']:%Y-%m-%d}<br>자동 생성 {built}</div>
</header>

<div class="headline">{headline}{f"<small>{comment_source}</small>" if comment_source else ""}</div>
<section class="cards">{cards_html(r)}</section>

<div class="panel" style="margin-top:12px">
  <h3>첫 구매 고객 재구매율 추이</h3>
  <div class="desc">배송 완료월별 · 배송 후 30일 이내 재구매 · 띠는 전국 기준 평소 범위</div>
  <div id="c-rep" class="chart tall"></div>
</div>

<h2>이번 달 변화 상세<span>무엇이 변했고, 어디서 변했나</span></h2>
<div class="grid2">
  <div class="panel"><h3>해석</h3><ul class="detail">{detail_html}</ul>{f'<div class="src">{comment_source}</div>' if comment_source else ""}</div>
  <div class="panel"><h3>예상일 초과 도착 비율 변화 기여 Top 5 (주)</h3>{states_table(r)}</div>
</div>

<h2>배송 경험 추이<span>배송 완료월별 · 띠는 평소 범위</span></h2>
<div class="grid2">
  <div class="panel"><h3>예상일 초과 도착 비율</h3><div id="c-late" class="chart"></div></div>
  <div class="panel"><h3>1~2점 리뷰 비율</h3><div id="c-low" class="chart"></div></div>
</div>

<h2>권역 비교<span>최근 6개월과 그 전 6개월 비교</span></h2>
<div class="panel"><h3>권역별 첫 구매 고객 재구매율</h3>
  <div class="desc">배송 완료월 기준 · 한 달씩 보면 권역별 고객 수가 적어 6개월씩 묶음</div>
  <div id="c-region" class="chart"></div></div>

<h2>참고<span>이번 달과 평소 비교</span></h2>
<div class="stack">
  <div class="panel"><h3>예상 도착일 대비 도착 시점별 1~2점 리뷰 비율</h3>
    <div class="desc">배송 완료월 기준 · 늦게 도착한 주문에 대한 불만이 평소보다 커졌는지 확인</div>
    <div id="c-band" class="chart"></div></div>
  <div class="panel"><h3>주문 이후 퍼널</h3>
    <div class="desc">전월 주문 기준 · 주문 대비 비율 · 이번 달 주문은 아직 배송 중인 주문이 많아 한 달 전 주문으로 비교</div>
    <div id="c-funnel" class="chart" style="height:280px"></div></div>
  <div class="grid2">
    <div class="panel"><h3>월별 주문 수</h3><div id="c-orders" class="chart"></div></div>
    <div class="panel"><h3>월별 거래액 (만 헤알)</h3><div id="c-gmv" class="chart"></div></div>
  </div>
</div>

<footer>
  <b>지표 정의</b> · 첫 구매 고객 재구매율: 첫 구매 배송 완료 후 30일 이내에 처음 다시 구매한 고객 비율(첫 구매와 같은 날 주문 제외),
  30일 관찰이 끝난 배송 완료월만 표시 · 예상일 초과 도착 비율: 해당 월 배송 완료 주문 중 예상 도착일보다 늦게 도착한 비율 ·
  거래액: 상품 가격 합계(배송비 제외, 취소·상품 없음 주문 제외)<br>
  <b>평소 범위</b> · 최근 6개월 평균 ± 2 × 표준편차. 이 범위를 나쁜 쪽으로 벗어나면 주의<br>
  <b>데이터</b> · Brazilian E-Commerce Public Dataset by Olist (Kaggle). 2017.01~2018.08 과거 데이터를 기준월 단위로 공급해 운영 환경을 시뮬레이션.
  배송 완료는 도착일이 기준일 이전인지로 판단. 리뷰 작성일 정보가 없어 기준일 이후 작성된 리뷰도 포함될 수 있음<br>
  분석 상세 · <a href="https://github.com/sooy1016/olist-repurchase-analysis">github.com/sooy1016/olist-repurchase-analysis</a>
</footer>
</div>

<script>
const D = {data};
const C = {{ blue:'#2a78d6', orange:'#eb6834', gray:'#c9c8c1', band:'rgba(42,120,214,0.12)',
            ink:'#0b0b0b', ink2:'#52514e', ink3:'#8a8984', grid:'#eeede9' }};
const FONT = "Pretendard, 'Malgun Gothic', sans-serif";
const charts = [];
function mk(id, opt) {{
  const c = echarts.init(document.getElementById(id), null, {{ renderer:'svg' }});
  c.setOption(Object.assign({{
    textStyle:{{ fontFamily:FONT, color:C.ink2 }}, animationDuration:600,
    grid:{{ left:8, right:16, top:36, bottom:8, containLabel:true }},
    tooltip:{{ trigger:'axis', backgroundColor:'#fff', borderColor:'#e6e5e0', textStyle:{{ color:C.ink, fontSize:12 }},
              axisPointer:{{ type:'line', lineStyle:{{ color:'#bbb' }} }} }},
  }}, opt));
  charts.push(c);
}}
const xCat = (data, extra={{}}) => Object.assign({{ type:'category', data, boundaryGap:true,
  axisLine:{{ show:false }}, axisTick:{{ show:false }}, axisLabel:{{ color:C.ink3, fontSize:11 }} }}, extra);
const yVal = (fmt) => ({{ type:'value', splitLine:{{ lineStyle:{{ color:C.grid }} }},
  axisLabel:{{ color:C.ink3, fontSize:11, formatter:fmt }} }});
const lineS = (name, data, color) => ({{ name, type:'line', data, symbol:'circle', symbolSize:7, connectNulls:false,
  lineStyle:{{ width:2.2, color }}, itemStyle:{{ color, borderColor:'#fff', borderWidth:2 }} }});
const bandS = (lo, hi) => ([
  {{ name:'_lo', type:'line', data:lo, stack:'band', symbol:'none', lineStyle:{{ opacity:0 }}, tooltip:{{ show:false }}, silent:true }},
  {{ name:'평소 범위', type:'line', data:hi.map((h,i)=> h==null||lo[i]==null ? null : +(h-lo[i]).toFixed(4)), stack:'band',
     symbol:'none', lineStyle:{{ opacity:0 }}, itemStyle:{{ color:'rgba(42,120,214,0.25)' }}, areaStyle:{{ color:C.band }}, tooltip:{{ show:false }}, silent:true }}
]);
const pctTip = (digits, extra) => (ps) => {{
  const rows = ps.filter(p => !p.seriesName.startsWith('_') && p.seriesName!=='평소 범위' && p.value!=null)
    .map(p => `${{p.marker}}${{p.seriesName}} <b>${{p.value.toFixed(digits)}}%</b>`);
  const i = ps[0].dataIndex; const ex = extra ? extra(i) : '';
  return `<b>${{ps[0].axisValue}}</b><br>` + rows.join('<br>') + ex;
}};

// 재구매율 추이
mk('c-rep', {{
  legend:{{ data:['전국','남동부','평소 범위'], right:0, top:0, icon:'roundRect', itemWidth:14, itemHeight:4,
           textStyle:{{ color:C.ink2, fontSize:12 }} }},
  xAxis:xCat(D.rep.x), yAxis:yVal('{{value}}%'),
  tooltip:{{ trigger:'axis', formatter:pctTip(2, i => (D.rep.lo[i]!=null ? `<br><span style="color:#8a8984">평소 범위 ${{D.rep.lo[i].toFixed(2)}}~${{D.rep.hi[i].toFixed(2)}}%</span>` : '')) }},
  series:[...bandS(D.rep.lo, D.rep.hi), lineS('전국', D.rep.all, C.blue), lineS('남동부', D.rep.se, C.orange)]
}});

// 배송 경험
for (const [id, key, name] of [['c-late','late','예상일 초과 도착 비율'], ['c-low','low','1~2점 리뷰 비율']]) {{
  const s = D[key];
  mk(id, {{
    xAxis:xCat(s.x), yAxis:yVal('{{value}}%'),
    tooltip:{{ trigger:'axis', formatter:pctTip(1, i => (s.lo[i]!=null ? `<br><span style="color:#8a8984">평소 범위 ${{s.lo[i].toFixed(1)}}~${{s.hi[i].toFixed(1)}}%</span>` : '')) }},
    series:[...bandS(s.lo, s.hi), lineS(name, s.y, C.blue)]
  }});
}}

// 묶음 막대 공통 (이번 vs 평소)
const pair = (id, x, cur, prev, curName, prevName, digits, curN, prevN, nUnit, labelColor) => mk(id, {{
  legend:{{ data:[curName, prevName], right:0, top:0, icon:'roundRect', itemWidth:12, itemHeight:8,
           textStyle:{{ color:C.ink2, fontSize:12 }} }},
  grid:{{ left:8, right:16, top:40, bottom:8, containLabel:true }},
  xAxis:xCat(x, {{ axisLabel:{{ color:C.ink2, fontSize:11.5 }} }}), yAxis:yVal('{{value}}%'),
  tooltip:{{ trigger:'axis', axisPointer:{{ type:'shadow' }}, formatter:ps => {{
    const i = ps[0].dataIndex;
    return `<b>${{ps[0].name}}</b><br>` + ps.filter(p=>p.value!=null).map(p => {{
      const n = p.seriesIndex===0 ? curN[i] : prevN[i];
      return `${{p.marker}}${{p.seriesName}} <b>${{p.value.toFixed(digits)}}%</b> <span style="color:#8a8984">(${{n.toLocaleString()}}${{nUnit}})</span>`;
    }}).join('<br>');
  }} }},
  series:[
    {{ name:curName, type:'bar', data:cur, barMaxWidth:30, barGap:'15%', itemStyle:{{ color:C.blue, borderRadius:[4,4,0,0] }},
       label:{{ show:true, position:'top', color:C.ink, fontSize:11.5, formatter:p => p.value==null ? '' : p.value.toFixed(digits)+'%' }} }},
    {{ name:prevName, type:'bar', data:prev, barMaxWidth:30, itemStyle:{{ color:C.gray, borderRadius:[4,4,0,0] }} }}
  ]
}});

// 권역별 재구매율: 최근 6개월 vs 그 전 6개월
pair('c-region', D.region.x, D.region.recent, D.region.before,
     `최근 6개월 (${{D.region.recent_label}})`, D.region.before_label ? `그 전 6개월 (${{D.region.before_label}})` : '그 전 6개월 (데이터 없음)',
     2, D.region.recent_n, D.region.before_n, '명');

// 예상 도착일 대비 1~2점 리뷰 비율: 이번 달 vs 직전 12개월
pair('c-band', D.band.x, D.band.cur, D.band.prev,
     `이번 달 (${{D.band.cur_label}})`, `직전 12개월 (${{D.band.prev_label}})`, 1, D.band.cur_n, D.band.prev_n, '건');

// 퍼널: 전월 주문 vs 직전 3개월 평균 (주문 대비 비율)
mk('c-funnel', {{
  legend:{{ data:[`${{D.funnel.cur_label}} 주문`, `직전 3개월 평균 (${{D.funnel.base_label}})`], right:0, top:0, icon:'roundRect',
           itemWidth:12, itemHeight:8, textStyle:{{ color:C.ink2, fontSize:12 }} }},
  grid:{{ left:8, right:70, top:36, bottom:8, containLabel:true }},
  xAxis:{{ type:'value', show:false, max:100 }},
  yAxis:{{ type:'category', data:D.funnel.x, inverse:true, axisLine:{{ show:false }}, axisTick:{{ show:false }},
          axisLabel:{{ color:C.ink2, fontSize:12.5 }} }},
  tooltip:{{ trigger:'axis', axisPointer:{{ type:'shadow' }}, formatter:ps => {{
    const i = ps[0].dataIndex;
    return `<b>${{ps[0].name}}</b><br>` + ps.filter(p=>p.value!=null).map(p =>
      `${{p.marker}}${{p.seriesName}} <b>${{p.value.toFixed(1)}}%</b>` + (p.seriesIndex===0 ? ` <span style="color:#8a8984">(${{D.funnel.cur_n[i].toLocaleString()}}건)</span>` : '')).join('<br>');
  }} }},
  series:[
    {{ name:`${{D.funnel.cur_label}} 주문`, type:'bar', data:D.funnel.cur, barWidth:16, itemStyle:{{ color:C.blue, borderRadius:[0,4,4,0] }},
       label:{{ show:true, position:'right', color:C.ink, fontSize:12, formatter:p => p.value.toFixed(1)+'%' }} }},
    {{ name:`직전 3개월 평균 (${{D.funnel.base_label}})`, type:'bar', data:D.funnel.base, barWidth:16, itemStyle:{{ color:C.gray, borderRadius:[0,4,4,0] }},
       label:{{ show:true, position:'right', color:C.ink3, fontSize:11.5, formatter:p => p.value==null ? '' : p.value.toFixed(1)+'%' }} }}
  ]
}});

// 월별 주문 수·거래액 (기준월 강조)
for (const [id, key, unit] of [['c-orders','orders','건'], ['c-gmv','gmv','만 헤알']]) {{
  const ys = D.monthly[key], last = ys.length - 1;
  mk(id, {{
    xAxis:xCat(D.monthly.x), yAxis:yVal(v => v.toLocaleString()),
    tooltip:{{ trigger:'axis', axisPointer:{{ type:'shadow' }}, formatter:ps => `<b>${{ps[0].name}}</b><br>${{ps[0].value.toLocaleString()}}${{unit}}` }},
    series:[{{ type:'bar', data:ys.map((v,i)=>({{ value:v, itemStyle:{{ color: i===last ? C.blue : C.gray }} }})),
              barMaxWidth:22, itemStyle:{{ borderRadius:[3,3,0,0] }} }}]
  }});
}}
window.addEventListener('resize', () => charts.forEach(c => c.resize()));
</script>
</body></html>"""


# ================================================================== 검증
def validate(o, f):
    print("[검증] 원본 분석 숫자와 대조")
    print(f"  주문 행 수            {len(o):,}  (기대 99,069)")
    print(f"  퍼널 (최종 상태 기준)  {int(o['is_ordered'].sum()):,} → {int(o['is_delivered'].sum()):,} → "
          f"{int(o['is_on_time'].sum()):,} → {int(((o['is_on_time'] == 1) & (o['review_score'] >= 4)).sum()):,}"
          "  (기대 99,069 → 96,189 → 89,658 → 73,703)")
    se = f[(f["region"] == "남동부") & (f["delivered_at"] + pd.Timedelta(days=30) <= pd.Timestamp("2018-08-31"))]
    print(f"  남동부 30일 대상       {len(se):,}명 / {int(se['rep30'].sum())}명 / {se['rep30'].mean() * 100:.3f}%"
          "  (기대 58,071 / 344 / 0.592%)")


# ================================================================== 실행
def read_state():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as fp:
            return pd.Period(json.load(fp)["current_month"], "M")
    return FIRST_MONTH


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--advance", action="store_true", help="기준월을 한 달 넘김")
    ap.add_argument("--month", help="기준월 지정 (예: 2018-08)")
    ap.add_argument("--validate", action="store_true", help="원본 분석 숫자와 대조만 함")
    args = ap.parse_args()

    o, f = load()
    if args.validate:
        validate(o, f)
        return

    month = pd.Period(args.month, "M") if args.month else read_state()
    if args.advance:
        month = month + 1
        if month > LAST_MONTH:          # 데이터 끝에 도달하면 처음으로
            month = FIRST_MONTH
    month = min(max(month, FIRST_MONTH), LAST_MONTH)

    r = compute(o, f, month)
    headline, details = rule_comment(r)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as fp:
        fp.write(build_html(r, headline, details))
    with open(os.path.join(OUT_DIR, "analysis.json"), "w", encoding="utf-8") as fp:
        json.dump(analysis_payload(r), fp, ensure_ascii=False, indent=2)
    with open(STATE, "w", encoding="utf-8") as fp:
        json.dump({"current_month": str(month)}, fp, ensure_ascii=False)
    print(f"대시보드 생성 완료: 기준월 {month} → dashboard/index.html")


if __name__ == "__main__":
    main()
