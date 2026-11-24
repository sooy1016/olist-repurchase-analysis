"""
Olist 재구매 모니터링 대시보드 · 화면 구성 (HTML)

입력 : build_dashboard.py의 compute() 결과, chart_data() 결과
출력 : HTML 문자열 → build_dashboard.py가 dashboard/index.html로 저장
"""
import json
from datetime import datetime

import pandas as pd

NAVY = "#003984"


# ------------------------------------------------------------------ 조각
def _delta(cur, prev, kind):
    if prev is None or pd.isna(prev) or prev == 0:
        return '<div class="k-delta">전월 비교 없음</div>'
    v = round((cur / prev - 1) * 100, 1) if kind == "pct" else round((cur - prev) * 100, 2)
    txt = f"{abs(v):.1f}%" if kind == "pct" else f"{abs(v):.2f}%p"
    arrow = "▲" if v > 0 else "▼" if v < 0 else "–"
    return f'<div class="k-delta">{arrow} {txt} <span>전월 대비</span></div>'


def _badge(status):
    cls = {"정상": "ok", "주의": "warn"}.get(status, "na")
    return f'<span class="tagbox {cls}">{status}</span>'


def _range(x, digits):
    if x.get("lo") is None:
        return "평소 범위 계산 기간 부족"
    pos = f" · {x['position']}" if x.get("position") not in (None, "범위 안") else ""
    return f"평소 범위 {x['lo'] * 100:.{digits}f}~{x['hi'] * 100:.{digits}f}%{pos}"


def _kpi(label, sub, value, unit, status, delta, note):
    warn = " warn" if status == "주의" else ""
    badge = _badge(status) if status else ""
    sub_html = f'<div class="k-sub">{sub}</div>' if sub else '<div class="k-sub">&nbsp;</div>'
    return f"""
<div class="kpi{warn}">
  <div class="k-head"><div class="k-label">{label}</div>{badge}</div>
  {sub_html}
  <div class="k-value">{value}<small>{unit}</small></div>
  {delta}
  <div class="k-note">{note}</div>
</div>"""


def _kpis(r):
    m, mon = r["metrics"], r["month"]
    rp, lt, lw = m["repurchase"], m["late"], m["low_review"]
    od, gm = m["orders"], m["gmv"]
    gm_chg = "전월 비교 없음" if not gm["prev"] else f"전월 대비 {(gm['value'] / gm['prev'] - 1) * 100:+.1f}%"
    return "".join([
        _kpi("첫 구매 고객 재구매율", f"{rp['cohort']} 배송 고객", f"{rp['value'] * 100:.2f}", "%",
             rp["status"], _delta(rp["value"], rp["prev"], "pp"),
             f"{rp['n']:,}명 · 남동부 {rp['se'] * 100:.2f}%<br>{_range(rp, 2)}"),
        _kpi("예상일 초과 도착 비율", f"{mon} 배송 완료", f"{lt['value'] * 100:.1f}", "%",
             lt["status"], _delta(lt["value"], lt["prev"], "pp"),
             f"배송 완료 {lt['n']:,}건<br>{_range(lt, 1)}"),
        _kpi("1~2점 리뷰 비율", f"{mon} 배송 완료", f"{lw['value'] * 100:.1f}", "%",
             lw["status"], _delta(lw["value"], lw["prev"], "pp"),
             f"리뷰 {lw['n']:,}건<br>{_range(lw, 1)}"),
        _kpi("주문 수", f"{mon} 주문", f"{od['value']:,}", "건", None,
             _delta(od["value"], od["prev"], "pct"),
             f"거래액 {gm['value'] / 10000:,.1f}만 헤알 ({gm_chg})<br>거래액은 배송비 제외"),
    ])


def _states(r):
    st = r["states"]
    if not len(st):
        return "<p class='k-note'>비교할 주가 없음</p>"
    rows = "".join(
        f"<tr><td><b>{s}</b></td><td>{x['region']}</td><td class='num'>{int(x['n']):,}</td>"
        f"<td class='num'>{'' if pd.isna(x['rate_prev']) else f'{x.rate_prev * 100:.1f}%'}</td>"
        f"<td class='num'>{x['rate'] * 100:.1f}%</td>"
        f"<td class='num em'>{x['contrib'] * 100:+.2f}%p</td></tr>"
        for s, x in st.iterrows())
    return f"""<table>
<thead><tr><th>주</th><th>권역</th><th class='num'>배송 완료</th><th class='num'>전월</th>
<th class='num'>이번 달</th><th class='num'>변화 기여</th></tr></thead><tbody>{rows}</tbody></table>
<p class='k-note'>전체 변화 {r['total_late_change'] * 100:+.2f}%p를 주별로 나눈 값 · 배송 완료 50건 이상인 주만 표시</p>"""


# ------------------------------------------------------------------ 페이지
def build_html(r, headline, details, source, data, echarts_url):
    built = datetime.now().strftime("%Y-%m-%d %H:%M")
    detail_html = "".join(f"<li>{d}</li>" for d in details)
    src_html = f'<div class="src">{source}</div>' if source else ""
    page = TEMPLATE
    for k, v in {
        "%%ECHARTS%%": echarts_url,
        "%%MONTH%%": str(r["month"]),
        "%%CUTOFF%%": f"{r['cutoff']:%Y-%m-%d}",
        "%%BUILT%%": built,
        "%%HEADLINE%%": headline,
        "%%SOURCE%%": src_html,
        "%%KPIS%%": _kpis(r),
        "%%DETAILS%%": detail_html,
        "%%STATES%%": _states(r),
        "%%DATA%%": json.dumps(data, ensure_ascii=False),
    }.items():
        page = page.replace(k, v)
    return page


TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Olist 재구매 모니터링</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css">
<script src="%%ECHARTS%%"></script>
<style>
  :root {
    --navy:#003984; --navy2:#2E5FA8; --sky:#8FB0DE; --tint:#EEF3FA;
    --ink:#121826; --ink2:#4A5568; --ink3:#8792A2; --rule:#D5DCE6; --rule2:#ECEFF4;
    --warn:#C8102E; --warn-tint:#FCEDEF;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:#fff; color:var(--ink);
         font-family:Pretendard,'Malgun Gothic','Apple SD Gothic Neo',sans-serif; }
  .wrap { max-width:1200px; margin:0 auto; padding:0 28px; }

  /* 상단 */
  .top { background:var(--navy); color:#fff; }
  .top .wrap { display:flex; justify-content:space-between; align-items:flex-end; gap:16px; flex-wrap:wrap;
               padding-top:26px; padding-bottom:22px; }
  .eyebrow { font-size:11.5px; letter-spacing:.14em; opacity:.7; font-weight:600; }
  .top h1 { font-size:26px; margin:6px 0 0; letter-spacing:-0.02em; font-weight:700; }
  .top .sub { font-size:13px; opacity:.78; margin-top:6px; }
  .asof { text-align:right; }
  .asof .m { font-size:30px; font-weight:700; letter-spacing:-0.02em; line-height:1; }
  .asof .m span { font-size:12px; font-weight:500; opacity:.7; margin-right:8px; letter-spacing:0; }
  .asof .d { font-size:12px; opacity:.7; margin-top:8px; line-height:1.6; }

  /* 이번 달 요약 */
  .summary { display:grid; grid-template-columns:150px 1fr; gap:24px; padding:26px 0 24px;
             border-bottom:1px solid var(--rule); }
  .summary .lbl { font-size:12.5px; font-weight:700; color:var(--navy); padding-top:3px; }
  .summary .txt { font-size:18px; font-weight:600; line-height:1.55; letter-spacing:-0.01em; }
  .src { font-size:11.5px; color:var(--ink3); margin-top:6px; font-weight:400; }

  /* KPI */
  .kpis { display:grid; grid-template-columns:repeat(4,1fr); border-bottom:1px solid var(--rule); }
  .kpi { padding:20px 22px 20px; border-top:3px solid var(--navy); border-right:1px solid var(--rule2); }
  .kpi:last-child { border-right:0; }
  .kpi.warn { border-top-color:var(--warn); background:linear-gradient(var(--warn-tint), #fff 70%); }
  .k-head { display:flex; justify-content:space-between; align-items:center; gap:8px; }
  .k-label { font-size:13.5px; font-weight:700; }
  .k-sub { font-size:11.5px; color:var(--ink3); margin-top:2px; }
  .k-value { font-size:38px; font-weight:700; letter-spacing:-0.03em; margin:12px 0 4px; color:var(--ink);
             font-variant-numeric:tabular-nums; }
  .k-value small { font-size:18px; font-weight:600; margin-left:2px; color:var(--ink2); }
  .kpi.warn .k-value { color:var(--warn); }
  .k-delta { font-size:13px; font-weight:600; color:var(--ink2); }
  .k-delta span { font-weight:400; color:var(--ink3); }
  .k-note { font-size:11.5px; color:var(--ink3); margin-top:10px; line-height:1.6; }
  .tagbox { font-size:11px; font-weight:700; padding:3px 8px; white-space:nowrap; letter-spacing:.02em; }
  .tagbox.ok { color:var(--navy); border:1px solid var(--navy); }
  .tagbox.warn { color:#fff; background:var(--warn); border:1px solid var(--warn); }

  /* 섹션 */
  .sec { margin-top:44px; }
  .sec-head { display:flex; align-items:center; gap:14px; margin-bottom:14px; }
  .ptag { display:inline-block; background:var(--navy); color:#fff; transform:skewX(-18deg); padding:5px 16px; }
  .ptag span { display:inline-block; transform:skewX(18deg); font-size:13px; font-weight:700; letter-spacing:-0.01em; }
  .sec-head .q { font-size:13px; color:var(--ink2); }
  .sec-head .line { flex:1; height:1px; background:var(--rule); }

  .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:28px; }
  .block { min-width:0; }
  .block h3 { font-size:14.5px; margin:0; font-weight:700; padding-bottom:8px; border-bottom:1px solid var(--ink); }
  .block .desc { font-size:12px; color:var(--ink3); margin:8px 0 2px; }
  .chart { width:100%; height:300px; }
  .chart.tall { height:340px; }

  .detail { list-style:none; margin:12px 0 0; padding:0; counter-reset:d; }
  .detail li { counter-increment:d; position:relative; padding:10px 0 10px 34px; border-bottom:1px solid var(--rule2);
               font-size:14px; line-height:1.65; }
  .detail li::before { content:counter(d, decimal-leading-zero); position:absolute; left:0; top:10px;
                       font-size:12px; font-weight:700; color:var(--navy); }

  table { width:100%; border-collapse:collapse; font-size:13.5px; margin-top:6px; }
  th { text-align:left; font-weight:600; color:var(--ink3); padding:10px 6px 8px; font-size:12px;
       border-bottom:1px solid var(--rule); }
  td { border-bottom:1px solid var(--rule2); padding:10px 6px; }
  td.em { color:var(--navy); font-weight:700; }
  .num { text-align:right; font-variant-numeric:tabular-nums; }

  /* 하단 */
  .defs { margin-top:52px; padding:22px 0; border-top:1px solid var(--rule); font-size:12px; color:var(--ink2);
          line-height:1.75; display:grid; grid-template-columns:150px 1fr; gap:6px 24px; }
  .defs dt { font-weight:700; color:var(--navy); }
  .defs dd { margin:0; }
  .bottom { background:var(--navy); color:#fff; margin-top:12px; }
  .bottom .wrap { display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; padding-top:14px;
                  padding-bottom:14px; font-size:12px; }
  .bottom a { color:#fff; opacity:.85; }

  @media (max-width:900px) {
    .kpis { grid-template-columns:1fr 1fr; } .kpi:nth-child(2) { border-right:0; }
    .grid2 { grid-template-columns:1fr; } .summary, .defs { grid-template-columns:1fr; }
    .asof { text-align:left; }
  }
</style></head>
<body>

<div class="top"><div class="wrap">
  <div>
    <div class="eyebrow">OLIST · MONTHLY MONITORING</div>
    <h1>첫 구매 고객 재구매 모니터링</h1>
    <div class="sub">재구매율과 배송 경험 지표를 매월 자동으로 계산하고 평소 범위와 비교</div>
  </div>
  <div class="asof">
    <div class="m"><span>기준월</span>%%MONTH%%</div>
    <div class="d">데이터 기준일 %%CUTOFF%% · 자동 생성 %%BUILT%%</div>
  </div>
</div></div>

<div class="wrap">

<section class="summary">
  <div class="lbl">이번 달 요약</div>
  <div class="txt">%%HEADLINE%%%%SOURCE%%</div>
</section>

<section class="kpis">%%KPIS%%</section>

<section class="block" style="margin-top:30px">
  <h3>첫 구매 고객 재구매율 추이</h3>
  <div class="desc">배송 완료월별 · 배송 후 30일 이내 재구매 · 음영은 전국 기준 평소 범위</div>
  <div id="c-rep" class="chart tall"></div>
</section>

<section class="sec">
  <div class="sec-head"><div class="ptag"><span>이번 달 변화</span></div><div class="q">무엇이 변했고, 어디서 변했나</div><div class="line"></div></div>
  <div class="grid2">
    <div class="block"><h3>해석</h3><ul class="detail">%%DETAILS%%</ul>%%SOURCE%%</div>
    <div class="block"><h3>예상일 초과 도착 비율 변화 기여 상위 5개 주</h3>%%STATES%%</div>
  </div>
</section>

<section class="sec">
  <div class="sec-head"><div class="ptag"><span>배송 경험</span></div><div class="q">배송 완료월별 · 음영은 평소 범위</div><div class="line"></div></div>
  <div class="grid2">
    <div class="block"><h3>예상일 초과 도착 비율</h3><div id="c-late" class="chart"></div></div>
    <div class="block"><h3>1~2점 리뷰 비율</h3><div id="c-low" class="chart"></div></div>
  </div>
</section>

<section class="sec">
  <div class="sec-head"><div class="ptag"><span>권역 비교</span></div><div class="q">최근 6개월과 그 전 기간 비교</div><div class="line"></div></div>
  <div class="block"><h3>권역별 첫 구매 고객 재구매율</h3>
    <div class="desc">배송 완료월 기준 · 한 달씩 보면 권역별 고객 수가 적어 6개월씩 묶음</div>
    <div id="c-region" class="chart"></div></div>
</section>

<section class="sec">
  <div class="sec-head"><div class="ptag"><span>참고</span></div><div class="q">이번 달과 평소 비교</div><div class="line"></div></div>
  <div class="grid2">
    <div class="block"><h3>예상 도착일 대비 도착 시점별 1~2점 리뷰 비율</h3>
      <div class="desc">늦게 도착한 주문에 대한 불만이 평소보다 커졌는지 확인</div>
      <div id="c-band" class="chart"></div></div>
    <div class="block"><h3>주문 이후 퍼널</h3>
      <div class="desc">전월 주문 기준 · 이번 달 주문은 아직 배송 중인 주문이 많아 한 달 전 주문으로 비교</div>
      <div id="c-funnel" class="chart"></div></div>
  </div>
  <div class="grid2" style="margin-top:28px">
    <div class="block"><h3>월별 주문 수</h3><div id="c-orders" class="chart"></div></div>
    <div class="block"><h3>월별 거래액 (만 헤알)</h3><div id="c-gmv" class="chart"></div></div>
  </div>
</section>

<dl class="defs">
  <dt>첫 구매 고객 재구매율</dt>
  <dd>첫 구매 배송 완료 후 30일 이내에 처음 다시 구매한 고객 비율(첫 구매와 같은 날 주문 제외). 배송 후 30일이 지나야 확정되므로 확정된 배송 달까지만 표시</dd>
  <dt>예상일 초과 도착 비율</dt>
  <dd>해당 월 배송 완료 주문 중 예상 도착일보다 늦게 도착한 비율</dd>
  <dt>1~2점 리뷰 비율</dt>
  <dd>해당 월 배송 완료 주문 중 리뷰가 있는 주문에서 1~2점(주문별 평균) 비율</dd>
  <dt>거래액</dt>
  <dd>상품 가격 합계(배송비 제외, 취소·상품 없음 주문 제외)</dd>
  <dt>평소 범위</dt>
  <dd>최근 6개월 평균 ± 2 × 표준편차. 이 범위를 나쁜 쪽으로 벗어나면 주의</dd>
  <dt>데이터</dt>
  <dd>Brazilian E-Commerce Public Dataset by Olist (Kaggle). 2017.01~2018.08 과거 데이터를 기준월 단위로 공급해 운영 환경을 시뮬레이션.
      배송 완료는 도착일이 기준일 이전인지로 판단. 리뷰 작성일 정보가 없어 기준일 이후 작성된 리뷰도 포함될 수 있음</dd>
</dl>
</div>

<div class="bottom"><div class="wrap">
  <div>Olist 재구매 분석 · 조수영</div>
  <a href="https://github.com/sooy1016/olist-repurchase-analysis">github.com/sooy1016/olist-repurchase-analysis</a>
</div></div>

<script>
const D = %%DATA%%;
const C = { navy:'#003984', sky:'#8FB0DE', gray:'#C9D1DC', band:'rgba(0,57,132,0.08)',
            ink:'#121826', ink2:'#4A5568', ink3:'#8792A2', grid:'#ECEFF4' };
const FONT = "Pretendard, 'Malgun Gothic', sans-serif";
const charts = [];
function mk(id, opt) {
  const c = echarts.init(document.getElementById(id), null, { renderer:'svg' });
  c.setOption(Object.assign({
    textStyle:{ fontFamily:FONT, color:C.ink2 }, animationDuration:500,
    grid:{ left:4, right:14, top:40, bottom:6, containLabel:true },
    tooltip:{ trigger:'axis', backgroundColor:'#fff', borderColor:C.navy, borderWidth:1, borderRadius:0,
              textStyle:{ color:C.ink, fontSize:12 }, axisPointer:{ type:'line', lineStyle:{ color:'#9AA6B8' } } },
  }, opt));
  charts.push(c);
}
const legend = (data) => ({ data, left:0, top:0, icon:'rect', itemWidth:12, itemHeight:4, itemGap:16,
                            textStyle:{ color:C.ink2, fontSize:12 } });
const xCat = (data, extra={}) => Object.assign({ type:'category', data, boundaryGap:true,
  axisLine:{ lineStyle:{ color:C.ink } }, axisTick:{ show:false }, axisLabel:{ color:C.ink3, fontSize:11 } }, extra);
const yVal = (fmt) => ({ type:'value', splitLine:{ lineStyle:{ color:C.grid } },
  axisLabel:{ color:C.ink3, fontSize:11, formatter:fmt } });
const lineS = (name, data, color, w=2) => ({ name, type:'line', data, symbol:'circle', symbolSize:6, connectNulls:false,
  lineStyle:{ width:w, color }, itemStyle:{ color, borderColor:'#fff', borderWidth:1.5 } });
const bandS = (lo, hi) => ([
  { name:'_lo', type:'line', data:lo, stack:'band', symbol:'none', lineStyle:{ opacity:0 }, tooltip:{ show:false }, silent:true },
  { name:'평소 범위', type:'line', data:hi.map((h,i)=> h==null||lo[i]==null ? null : +(h-lo[i]).toFixed(4)), stack:'band',
    symbol:'none', lineStyle:{ opacity:0 }, itemStyle:{ color:'rgba(0,57,132,0.18)' }, areaStyle:{ color:C.band }, tooltip:{ show:false }, silent:true }
]);
const pctTip = (digits, extra) => (ps) => {
  const rows = ps.filter(p => !p.seriesName.startsWith('_') && p.seriesName!=='평소 범위' && p.value!=null)
    .map(p => `${p.marker}${p.seriesName} <b>${p.value.toFixed(digits)}%</b>`);
  const i = ps[0].dataIndex; const ex = extra ? extra(i) : '';
  return `<b>${ps[0].axisValue}</b><br>` + rows.join('<br>') + ex;
};
const rangeTip = (s, d) => i => (s.lo[i]!=null ? `<br><span style="color:#8792A2">평소 범위 ${s.lo[i].toFixed(d)}~${s.hi[i].toFixed(d)}%</span>` : '');

mk('c-rep', {
  legend:legend(['전국','남동부','평소 범위']),
  xAxis:xCat(D.rep.x), yAxis:yVal('{value}%'),
  tooltip:{ trigger:'axis', formatter:pctTip(2, rangeTip(D.rep, 2)) },
  series:[...bandS(D.rep.lo, D.rep.hi), lineS('전국', D.rep.all, C.navy, 2.4), lineS('남동부', D.rep.se, C.sky)]
});

for (const [id, key, name] of [['c-late','late','예상일 초과 도착 비율'], ['c-low','low','1~2점 리뷰 비율']]) {
  const s = D[key];
  mk(id, {
    legend:legend([name,'평소 범위']),
    xAxis:xCat(s.x), yAxis:yVal('{value}%'),
    tooltip:{ trigger:'axis', formatter:pctTip(1, rangeTip(s, 1)) },
    series:[...bandS(s.lo, s.hi), lineS(name, s.y, C.navy, 2.4)]
  });
}

const pair = (id, x, cur, prev, curName, prevName, digits, curN, prevN, nUnit) => mk(id, {
  legend:Object.assign(legend([curName, prevName]), { itemHeight:8 }),
  xAxis:xCat(x, { axisLabel:{ color:C.ink2, fontSize:11.5, interval:0, lineHeight:15, formatter:v => v.replace(' ', '\n') } }),
  yAxis:yVal('{value}%'),
  tooltip:{ trigger:'axis', axisPointer:{ type:'shadow', shadowStyle:{ color:'rgba(0,57,132,0.05)' } }, formatter:ps => {
    const i = ps[0].dataIndex;
    return `<b>${ps[0].name}</b><br>` + ps.filter(p=>p.value!=null).map(p => {
      const n = p.seriesIndex===0 ? curN[i] : prevN[i];
      return `${p.marker}${p.seriesName} <b>${p.value.toFixed(digits)}%</b> <span style="color:#8792A2">(${n.toLocaleString()}${nUnit})</span>`;
    }).join('<br>');
  } },
  series:[
    { name:curName, type:'bar', data:cur, barMaxWidth:28, barGap:'12%', itemStyle:{ color:C.navy },
      label:{ show:true, position:'top', color:C.ink, fontSize:11.5, fontWeight:600, formatter:p => p.value==null ? '' : p.value.toFixed(digits)+'%' } },
    { name:prevName, type:'bar', data:prev, barMaxWidth:28, itemStyle:{ color:C.gray } }
  ]
});

pair('c-region', D.region.x, D.region.recent, D.region.before,
     D.region.recent_label, D.region.before_label, 2, D.region.recent_n, D.region.before_n, '명');
pair('c-band', D.band.x, D.band.cur, D.band.prev,
     `이번 달 (${D.band.cur_label})`, D.band.prev_label, 1, D.band.cur_n, D.band.prev_n, '건');

mk('c-funnel', {
  legend:Object.assign(legend([`${D.funnel.cur_label} 주문`, `직전 3개월 평균 (${D.funnel.base_label})`]), { itemHeight:8 }),
  grid:{ left:4, right:60, top:40, bottom:6, containLabel:true },
  xAxis:{ type:'value', show:false, max:100 },
  yAxis:{ type:'category', data:D.funnel.x, inverse:true, axisLine:{ lineStyle:{ color:C.ink } }, axisTick:{ show:false },
          axisLabel:{ color:C.ink2, fontSize:12 } },
  tooltip:{ trigger:'axis', axisPointer:{ type:'shadow', shadowStyle:{ color:'rgba(0,57,132,0.05)' } }, formatter:ps => {
    const i = ps[0].dataIndex;
    return `<b>${ps[0].name}</b><br>` + ps.filter(p=>p.value!=null).map(p =>
      `${p.marker}${p.seriesName} <b>${p.value.toFixed(1)}%</b>` + (p.seriesIndex===0 ? ` <span style="color:#8792A2">(${D.funnel.cur_n[i].toLocaleString()}건)</span>` : '')).join('<br>');
  } },
  series:[
    { name:`${D.funnel.cur_label} 주문`, type:'bar', data:D.funnel.cur, barWidth:14, itemStyle:{ color:C.navy },
      label:{ show:true, position:'right', color:C.ink, fontSize:11.5, fontWeight:600, formatter:p => p.value.toFixed(1)+'%' } },
    { name:`직전 3개월 평균 (${D.funnel.base_label})`, type:'bar', data:D.funnel.base, barWidth:14, itemStyle:{ color:C.gray },
      label:{ show:true, position:'right', color:C.ink3, fontSize:11, formatter:p => p.value==null ? '' : p.value.toFixed(1)+'%' } }
  ]
});

for (const [id, key, unit] of [['c-orders','orders','건'], ['c-gmv','gmv','만 헤알']]) {
  const ys = D.monthly[key], last = ys.length - 1;
  mk(id, {
    grid:{ left:4, right:14, top:16, bottom:6, containLabel:true },
    xAxis:xCat(D.monthly.x), yAxis:yVal(v => v.toLocaleString()),
    tooltip:{ trigger:'axis', axisPointer:{ type:'shadow', shadowStyle:{ color:'rgba(0,57,132,0.05)' } },
              formatter:ps => `<b>${ps[0].name}</b><br>${ps[0].value.toLocaleString()}${unit}` },
    series:[{ type:'bar', data:ys.map((v,i)=>({ value:v, itemStyle:{ color: i===last ? C.navy : C.gray } })), barMaxWidth:20 }]
  });
}
window.addEventListener('resize', () => charts.forEach(c => c.resize()));
</script>
</body></html>"""
