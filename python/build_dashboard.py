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
출력 : dashboard/index.html        (GitHub Pages로 게시, 화면 구성은 dashboard_page.py)
       dashboard/analysis.json     (지표별 판정 결과 요약 + 해석 문장)
해석 : python/ai_comment.py        (Gemini로 해석 문장 작성 후 검증, 실패 시 규칙 기반 요약)
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

import ai_comment
from dashboard_page import build_html

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
    })
    num = ["n", "late_n", "n_prev", "late_n_prev"]
    st[num] = st[num].fillna(0)
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
    reg_label = (f"최근 {len(recent)}개월 ({pl(recent[0])}~{pl(recent[-1])})",
                 f"그 전 {len(before)}개월 ({pl(before[0])}~{pl(before[-1])})" if len(before) else "그 전 기간 (데이터 없음)")

    # 예상 도착일 대비 도착 시점별 1~2점 리뷰 비율: 이번 달 배송 vs 직전 12개월 배송
    d = oo[oo["deliv"] & oo["review_score"].notna()].copy()
    d["band"] = d["delay_days"].apply(delay_band)
    in_cur = d["deliv_month"] == month
    in_prev = (d["deliv_month"] < month) & (d["deliv_month"] >= month - 12)

    def band_rate(x):
        return x.groupby("band")["review_score"].agg(n="size", low=lambda v: (v <= 2).mean()).reindex(BANDS)

    bc, bp = band_rate(d[in_cur]), band_rate(d[in_prev])
    band = pd.DataFrame({"cur": bc["low"], "cur_n": bc["n"], "prev": bp["low"], "prev_n": bp["n"]})
    b_start = max(month - 12, d["deliv_month"].min())
    band_prev_label = f"직전 {(month - b_start).n}개월 ({pl(b_start)}~{pl(month - 1)})"

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


# ================================================================== 해석 (규칙 기반 요약)
NAMES = {"repurchase": "첫 구매 고객 재구매율", "late": "예상일 초과 도착 비율",
         "low_review": "1~2점 리뷰 비율"}


def analysis_payload(r):
    """지표별 값, 평소 범위, 판정, 주별 기여를 정리한 요약 (dashboard/analysis.json)"""
    m = r["metrics"]
    top = [dict(state=s, region=row["region"], orders=int(row["n"]),
                rate=round(row["rate"] * 100, 1), rate_prev=None if pd.isna(row["rate_prev"]) else round(row["rate_prev"] * 100, 1),
                contribution_pp=round(row["contrib"] * 100, 2))
           for s, row in r["states"].iterrows()]
    pct = lambda v, d=2: None if v is None or pd.isna(v) else round(v * 100, d)
    return dict(
        month=str(r["month"]),
        metrics={k: dict(name=NAMES[k], value_pct=pct(m[k]["value"]), prev_pct=pct(m[k]["prev"]),
                         change_pp=pct(m[k]["value"] - m[k]["prev"]),
                         normal_range_pct=[pct(m[k]["lo"]), pct(m[k]["hi"])], status=m[k]["status"],
                         position=m[k]["position"])
                 for k in NAMES},
        repurchase_detail=dict(cohort=m["repurchase"]["cohort"], customers=m["repurchase"]["n"],
                               southeast_pct=pct(m["repurchase"]["se"]),
                               southeast_prev_pct=pct(m["repurchase"]["se_prev"])),
        late_change_total_pp=pct(r["total_late_change"]),
        late_change_by_state=top,
        orders=dict(name="주문 수", value=m["orders"]["value"], prev=m["orders"]["prev"],
                    change_pct=round((m["orders"]["value"] / m["orders"]["prev"] - 1) * 100, 1)),
        sales=dict(name="거래액 (만 헤알)", value=round(m["gmv"]["value"] / 10000, 1),
                   prev=round(m["gmv"]["prev"] / 10000, 1),
                   change_pct=round((m["gmv"]["value"] / m["gmv"]["prev"] - 1) * 100, 1)),
    )


def rule_comment(r):
    """규칙 기반 요약 (개조식): (결론 1줄, 상세 목록)"""
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


# ================================================================== 차트 데이터
# 화면 구성은 python/dashboard_page.py
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
    ap.add_argument("--no-ai", action="store_true", help="AI 해석 없이 규칙 기반 요약만 사용")
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
    payload = analysis_payload(r)
    headline, details = rule_comment(r)
    source = ""
    ai = None if args.no_ai else ai_comment.generate(payload)
    if ai:
        headline, details, source = ai
    payload["comment"] = dict(headline=headline, details=details,
                              source=source or "규칙 기반 요약")

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as fp:
        fp.write(build_html(r, headline, details, source, chart_data(r), ECHARTS))
    with open(os.path.join(OUT_DIR, "analysis.json"), "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    with open(STATE, "w", encoding="utf-8") as fp:
        json.dump({"current_month": str(month)}, fp, ensure_ascii=False)
    print(f"대시보드 생성 완료: 기준월 {month} → dashboard/index.html")


if __name__ == "__main__":
    main()
