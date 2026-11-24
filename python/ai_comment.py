"""
대시보드 해석 문장 생성 (Gemini API) + 검증
------------------------------------------------------------
역할 분담
  - 계산·판정 : build_dashboard.py (지표, 평소 범위, 정상/주의, 주별 기여)
  - 문장 작성 : Gemini (판정 결과를 읽고 결론 1줄 + 상세 해석 작성)
  - 검증     : 이 파일 (숫자, 표현, 판정과의 일치 여부)
검증을 통과하지 못하거나 API 키가 없으면 규칙 기반 요약을 그대로 사용한다.

API 키는 환경 변수 GEMINI_API_KEY에서 읽는다 (GitHub Actions에서는 저장소 Secrets).
"""
import json
import os
import re
import time
import urllib.request

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
FALLBACK_MODEL = "gemini-3.1-flash-lite"                            # 가볍고 빠른 무료 모델 (기본 모델이 느리거나 혼잡할 때)
TIMEOUT = 120                                                       # 응답 대기 최대 시간(초)
# 시도 계획: (모델, 시도 전 대기 초). 503(서버 혼잡)·시간 초과는 시간을 두고 다시 시도하거나 가벼운 모델로 바꾸면 대부분 해결됨
# 대기 시간을 점점 늘림 (최대 약 4분)
ATTEMPTS = [(MODEL, 0), (FALLBACK_MODEL, 20), (MODEL, 60), (FALLBACK_MODEL, 120)]
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
BANNED = ["때문", "원인", "탓", "인해", "덕분", "초래", "야기"]      # 인과 단정 표현
BANNED_TERMS = ["GMV", "gmv", "AOV", "aov"]                          # 한눈에 안 들어오는 약어 (거래액, 객단가로 표기)
ALWAYS_OK = {1, 2, 3, 4, 6, 12, 30}                                # 지표 정의에 쓰이는 숫자 (1~2점, 30일, 6개월 등)

DEFINITIONS = """\
- 첫 구매 고객 재구매율: 첫 구매 배송 완료 후 30일 이내에 처음 다시 구매한 고객 비율 (첫 구매와 같은 날 주문 제외).
  30일을 지켜봐야 알 수 있어서 기준월(month)이 아니라 repurchase_detail.cohort 달에 배송받은 고객의 값임
- 예상일 초과 도착 비율: 해당 월 배송 완료 주문 중 예상 도착일보다 늦게 도착한 비율
- 1~2점 리뷰 비율: 해당 월 배송 완료 주문 중 리뷰가 1~2점인 비율
- 평소 범위: 최근 6개월 평균 ± 2 × 표준편차. 나쁜 쪽으로 벗어나면 '주의', 그 외는 '정상'
- late_change_by_state.contribution_pp: 전체 예상일 초과 도착 비율 변화를 주별로 나눈 값 (합하면 전체 변화)
- 주문 수: 해당 월 주문 건수 / 거래액: 해당 월 상품 가격 합계 (배송비 제외, 단위 만 헤알)"""

PAST_FINDINGS = """\
- 예상 도착일보다 늦게 도착하면 1~2점 리뷰 비율이 크게 높아졌다
- 첫 구매 배송 기간이 길수록 재구매율이 낮았다
- 1~2점 리뷰를 준 고객은 재구매율이 낮았다
- 위 결과는 관측 데이터 분석이라 인과관계로 단정할 수 없다"""


def build_prompt(payload):
    return f"""당신은 이커머스 회사의 데이터 분석가다. 아래 월간 지표 판정 결과를 읽고,
경영진과 협업 부서가 볼 대시보드의 해석 문장을 작성하라.

[지표 정의]
{DEFINITIONS}

[과거 분석에서 확인된 관련성]
{PAST_FINDINGS}

[이번 달 판정 결과 (JSON)]
{json.dumps(payload, ensure_ascii=False, indent=2)}

[작성 규칙]
1. headline: 이번 달 상태를 개조식 한 줄(60자 이내)로 쓴다. status가 '주의'인 지표가 있으면 반드시 '주의'라는 단어로 시작하고, 없으면 '주의'라는 단어를 쓰지 않는다.
2. details: 개조식 2~4개. 순서는 (1) 무엇이 변했나 (2) 어디서 변했나 (3) 재구매와의 관련성. 평소 범위 안의 작은 변화에는 의미를 부여하지 않는다.
3. 숫자는 JSON에 있는 값만 그대로 쓴다. 새로 계산하거나 반올림을 바꾸지 않는다. 퍼센트는 % 또는 %p를 붙인다.
4. 원인을 단정하지 않는다. '때문', '원인', '탓', '인해' 같은 표현 대신 '관련', '함께 나타남'을 쓴다.
5. 문장은 '~임', '~함', '~필요' 같은 개조식으로 끝낸다. 담당 부서나 담당자는 지정하지 않는다.
6. '첫 구매 고객 재구매율'을 말할 때는 '2017년 12월 배송 고객 기준'처럼 repurchase_detail.cohort 달을 함께 쓴다. 기준월의 재구매율처럼 쓰지 않는다.
7. 지표는 JSON의 name에 적힌 한국어 이름 그대로 부른다 (예: 거래액). GMV, AOV처럼 한눈에 이해하기 어려운 약어는 쓰지 않는다.

[출력 형식]
JSON 하나만 출력한다: {{"headline": "...", "details": ["...", "..."]}}"""


def call_gemini(prompt, api_key, model=MODEL, timeout=TIMEOUT):
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT.format(model=model), data=body, method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        data = json.loads(res.read().decode("utf-8"))
    text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    return json.loads(text)


# ------------------------------------------------------------------ 검증
def _numbers_in(obj):
    """JSON 안의 모든 숫자 (문자열 속 숫자 포함, 예: '2018-08' → 2018, 8)"""
    if isinstance(obj, bool):
        return []
    if isinstance(obj, (int, float)):
        return [float(obj)]
    if isinstance(obj, str):
        return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", obj)]
    if isinstance(obj, dict):
        return [n for v in obj.values() for n in _numbers_in(v)]
    if isinstance(obj, list):
        return [n for v in obj for n in _numbers_in(v)]
    return []


def allowed_numbers(payload):
    allowed = set(ALWAYS_OK)
    for n in _numbers_in(payload):
        allowed.add(round(abs(n), 2))
        allowed.add(round(abs(n), 1))
        allowed.add(round(abs(n)))
    return allowed


def mentions_month(text, ym):
    """'2017-12'를 2017년 12월, 2017.12, 2017-12, 17년 12월 등 어떤 형태로든 언급했는지"""
    y, m = ym.split("-")
    m1 = str(int(m))
    pats = [rf"{y}\s*년\s*0?{m1}\s*월", rf"{y}[.\-/]\s*0?{m1}(?!\d)", rf"{y[2:]}\s*년\s*0?{m1}\s*월"]
    return any(re.search(p, text) for p in pats)


def validate(result, payload):
    """(통과 여부, 실패 이유)"""
    if not isinstance(result, dict) or not isinstance(result.get("headline"), str) \
            or not isinstance(result.get("details"), list) or not result["details"]:
        return False, "출력 형식이 맞지 않음"
    headline, details = result["headline"].strip(), [str(d).strip() for d in result["details"]]
    if len(headline) > 80 or not 1 <= len(details) <= 4:
        return False, "길이 또는 항목 수 초과"

    text = headline + " " + " ".join(details)
    for w in BANNED:
        if w in text:
            return False, f"인과 단정 표현 사용: '{w}'"

    for w in BANNED_TERMS:
        if re.search(rf"(?<![A-Za-z]){w}(?![A-Za-z])", text):
            return False, f"대시보드에 없는 용어 사용: '{w}'"

    if "첫 구매 고객 재구매율" in text and not mentions_month(text, payload["repurchase_detail"]["cohort"]):
        return False, f"재구매율의 배송 완료월({payload['repurchase_detail']['cohort']})을 밝히지 않음"

    has_warn = any(m["status"] == "주의" for m in payload["metrics"].values())
    if has_warn != ("주의" in headline):
        return False, "결론 줄의 '주의' 표시가 판정 결과와 다름"

    allowed = allowed_numbers(payload)
    for n in re.findall(r"\d+(?:\.\d+)?", text.replace(",", "")):
        v = float(n)
        if not any(abs(v - a) < 0.005 for a in allowed):
            return False, f"입력에 없는 숫자 사용: {n}"
    return True, ""


def generate(payload):
    """(headline, details, 표시 문구) 또는 None (키 없음·모든 시도 실패)
    - 호출 실패(서버 혼잡 등): 잠시 기다렸다가 다시 시도, 마지막에는 다른 모델로 시도
    - 검증 실패: 실패 이유를 알려주고 다시 작성하게 함"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[AI 해석] GEMINI_API_KEY 없음 → 규칙 기반 요약 사용")
        return None
    prompt = build_prompt(payload)
    for i, (model, wait) in enumerate(ATTEMPTS, start=1):
        if wait:
            time.sleep(wait)
        try:
            result = call_gemini(prompt, api_key, model)
        except Exception as e:                  # 어떤 오류든 대시보드 생성은 계속
            print(f"[AI 해석] 호출 실패 ({i}회차, {model}): {e}")
            continue
        ok, reason = validate(result, payload)
        if ok:
            print(f"[AI 해석] 검증 통과 ({i}회차, {model})")
            return (result["headline"].strip(), [str(d).strip() for d in result["details"]],
                    f"AI 요약 · 수치 검증 완료 ({model})")
        print(f"[AI 해석] 검증 실패 ({i}회차, {model}): {reason}")
        print(json.dumps(result, ensure_ascii=False))
        prompt = (build_prompt(payload)
                  + f"\n\n[재작성 요청]\n이전 답변이 검증에 실패했다: {reason}\n작성 규칙을 지켜 다시 작성하라.")
    print("[AI 해석] 모든 시도 실패 → 규칙 기반 요약 사용")
    return None
