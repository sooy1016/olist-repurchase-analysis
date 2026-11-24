"""
대시보드 갱신 후 분석가에게 Slack으로 검토 요청 보내기
------------------------------------------------------------
흐름: 자동 생성(AI 해석 초안 포함) → 분석가에게 검토 요청 → 분석가가 확인 후 팀에 공유
입력: dashboard/analysis.json
환경 변수
  SLACK_WEBHOOK_URL : Slack Incoming Webhook 주소 (GitHub Secrets). 없으면 보내지 않고 종료
  DASHBOARD_URL     : 게시된 대시보드 주소
"""
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYSIS = os.path.join(ROOT, "dashboard", "analysis.json")


def build_message(a, url):
    m = a["metrics"]
    rp = a["repurchase_detail"]
    c = a["comment"]
    is_ai = c["source"].startswith("AI")

    def line(key, digits=2, extra=""):
        x = m[key]
        mark = ":warning: *주의*" if x["status"] == "주의" else "정상"
        return f"• {x['name']} *{x['value_pct']:.{digits}f}%*{extra} · {mark}"

    metrics = "\n".join([
        line("repurchase", 2, f" ({rp['cohort']} 배송 고객)"),
        line("late", 1),
        line("low_review", 1),
        f"• 주문 수 *{a['orders']['value']:,}건* (전월 대비 {a['orders']['change_pct']:+.1f}%) · "
        f"거래액 *{a['sales']['value']:,.1f}만 헤알* ({a['sales']['change_pct']:+.1f}%)",
    ])
    details = "\n".join(f"• {d}" for d in c["details"])
    review = ("AI가 작성한 해석 초안입니다. 수치는 자동 검증을 통과했습니다. 내용 확인 후 팀 채널에 공유해 주세요."
              if is_ai else
              "AI 해석을 만들지 못해 규칙 기반 요약이 들어갔습니다. 내용 확인 후 팀 채널에 공유해 주세요.")

    text = f"[검토 요청] Olist 재구매 모니터링 · 기준월 {a['month']}"
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": text}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{c['headline']}*"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": metrics}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*해석*\n{details}"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"{c['source']} · {review}"}]},
    ]
    if url:
        blocks.append({"type": "actions", "elements": [{
            "type": "button", "text": {"type": "plain_text", "text": "대시보드 열기"}, "url": url}]})
    return {"text": text, "blocks": blocks}


def main():
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        print("[Slack] SLACK_WEBHOOK_URL 없음 → 알림 생략")
        return
    with open(ANALYSIS, encoding="utf-8") as fp:
        a = json.load(fp)
    msg = build_message(a, os.environ.get("DASHBOARD_URL", ""))
    req = urllib.request.Request(webhook, data=json.dumps(msg).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            print(f"[Slack] 검토 요청 전송 완료 ({res.status})")
    except Exception as e:                      # 알림이 실패해도 대시보드 게시는 이미 끝난 상태
        print(f"[Slack] 전송 실패: {e}")


if __name__ == "__main__":
    main()
