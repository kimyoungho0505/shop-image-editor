---
name: ai-api
description: "AI API 사용법 — Vision 분석(Claude/OpenAI/Gemini/Grok) + AI 그림자 생성(Gemini Image Edit/Grok Image Edit). 모델, 엔드포인트, 인증, 요청/응답 형식, 재시도 로직, 그림자 힌트 시스템 참조."
user_invocable: true
---

# AI API 통합 가이드 (Vision + Shadow Generation)

이 프로젝트에서 사용하는 AI API들의 사용법, 인증, 요청/응답 형식, 에러 처리 패턴을 정리한 스킬입니다.

---

## 1. Vision API (이미지 분석)

4개 프로바이더가 동일한 인터페이스(`analyze_image`/`analyze_images`)를 공유합니다.
`config/settings.yaml`의 `providers.vision`으로 선택합니다.

### 1.1 Claude Vision
- **파일:** `src/analyzer/vision_client.py`
- **SDK:** `anthropic`
- **인증:** `ANTHROPIC_API_KEY` 환경변수
- **모델:** `claude-haiku-4-5-20251001` (settings.yaml `api.model`)
- **호출:** `client.messages.create()`
- **이미지 전송:** base64 JPEG (`to_base64(img, fmt=".jpg")`)
- **응답:** `message.content[0].text`
- **토큰:** `message.usage.input_tokens`, `message.usage.output_tokens`
- **에러:** `anthropic.APIError`

```python
response = client.messages.create(
    model=model,
    max_tokens=max_tokens,  # 기본 1024
    temperature=0.1,
    system=system_prompt,
    messages=[{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
        {"type": "text", "text": prompt}
    ]}]
)
```

### 1.2 OpenAI Vision (ChatGPT)
- **파일:** `src/analyzer/openai_vision_client.py`
- **SDK:** `openai`
- **인증:** `OPENAI_API_KEY` 환경변수
- **모델:** `gpt-4o` (settings.yaml `openai.model`)
- **호출:** `client.chat.completions.create()`
- **이미지 전송:** data URI (`data:image/jpeg;base64,{b64}`, detail: "high")
- **응답:** `response.choices[0].message.content`
- **에러:** `openai.APIError`

### 1.3 Gemini Vision
- **파일:** `src/analyzer/gemini_vision_client.py`
- **SDK:** `google.genai`
- **인증:** `GEMINI_API_KEY` 환경변수
- **모델:** `gemini-2.5-pro` (settings.yaml `gemini.model`)
- **호출:** `client.models.generate_content()`
- **이미지 전송:** `types.Part.from_bytes()` (JPEG, max 1568px, quality 90)
- **응답:** `response.text`
- **토큰:** `response.usage_metadata.prompt_token_count`, `candidates_token_count`
- **에러:** 모든 Exception (@retry 데코레이터)

**특수 처리:**
- **부분 응답 복구:** `response.text`가 None이면 `candidates[0].content.parts`에서 추출
- **MAX_TOKENS 대응:** `FinishReason.MAX_TOKENS` 시 부분 응답으로 계속 진행
- **자동 재시도:** @retry 5회, exponential backoff (4~60초)
- **잘림 감지:** JSON이 `,` `"` `:` `{`로 끝나면 토큰 2배로 재시도 (최대 8192)

### 1.4 Grok Vision (xAI)
- **파일:** `src/analyzer/grok_vision_client.py`
- **SDK:** `openai` (호환 모드)
- **인증:** `XAI_API_KEY` 환경변수
- **Base URL:** `https://api.x.ai/v1`
- **모델:** `grok-4-fast-non-reasoning` (settings.yaml `grok.model`)
- **호출:** OpenAI SDK `chat.completions.create()`
- **이미지 전송:** OpenAI와 동일 형식 (data URI)
- **응답:** `response.choices[0].message.content`
- **주의:** grok-4 계열만 Vision 지원 (grok-3 이하 불가)

### 1.5 Vision 통합 (pipeline.py)
- **클라이언트 생성:** `_get_vision_client()` — provider별 분기
- **설정 조회:** `_get_vision_config(provider)` — settings.yaml에서 model/max_tokens/temperature
- **병렬 호출:** `_call_all_vision_apis()` — ThreadPoolExecutor(max_workers=3)으로 전 프로바이더 동시 호출
- **응답 파싱:** `result_parser.py`의 `EditInstruction` 데이터클래스로 변환

### 1.6 settings.yaml Vision 설정
```yaml
providers:
  vision: gemini  # claude / chatgpt / gemini / grok

api:                              # Claude
  model: claude-haiku-4-5-20251001
  max_tokens: 2048
  temperature: 0.1

openai:                           # ChatGPT
  model: gpt-4o
  max_tokens: 2048
  temperature: 0.1

gemini:                           # Gemini
  model: gemini-2.5-pro
  max_tokens: 4096
  temperature: 0.1

grok:                             # Grok
  model: grok-4-fast-non-reasoning
  max_tokens: 2048
  temperature: 0.1
```

---

## 2. AI 그림자 생성 API

### 2.1 Gemini Image Edit (그림자 생성)
- **파일:** `src/pipeline.py` → `_gemini_add_shadow()`
- **SDK:** `google.genai` (Client)
- **인증:** `GEMINI_API_KEY`
- **모델:** `gemini-3-pro-image-preview` (settings.yaml `gemini_shadow.model`)
- **폴백 모델:** `gemini-3-pro-image-preview` (`gemini_shadow.fallback_model`)
- **이미지 전송:** `types.Part.from_bytes()` (MIME 자동 감지: PNG/JPEG)

**요청 구성:**
```python
contents = [
    types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
    types.Part.from_text(text=prompt)
]
response = client.models.generate_content(model=model, contents=contents)
```

**2가지 모드:**
1. **일반 모드:** 누끼 이미지 + main_prompt (+ 원본 참고 이미지 선택적)
2. **마네킹 모드:** 원본 이미지 직접 전송 + mannequin_full_prompt (배경제거+마네킹 제거+그림자)

**프롬프트 치환자:**
- `{has_original}` → 원본 이미지가 있으면 orig_insert 삽입
- `{mannequin_removal}` → 마네킹 감지 시 mannequin_prompt 삽입
- `{shadow_hint}` → 카테고리/촬영방향별 보충 힌트

**폴백 체인:**
- Primary 모델 3회 시도 → 실패 시 fallback 모델 3회 시도
- 503 Service Unavailable 시 자동 전환

**제품 보호:** `_protect_product_pixels()` — 누끼 알파 마스크로 제품 영역 원본 보존

### 2.2 Grok Image Edit (그림자 생성)
- **파일:** `src/pipeline.py` → `_grok_add_shadow()`
- **엔드포인트:** `https://api.x.ai/v1/images/edits` (REST)
- **인증:** Bearer token (`XAI_API_KEY`)
- **모델:** `grok-imagine-image` ($0.02/장) 또는 `grok-imagine-image-pro` ($0.07/장)
- **Content-Type:** `application/json` (multipart 아님)

**요청 형식:**
```json
{
  "model": "grok-imagine-image",
  "prompt": "그림자 프롬프트",
  "image": {
    "url": "data:image/jpeg;base64,{base64_data}",
    "type": "image_url"
  },
  "n": 1,
  "response_format": "b64_json"
}
```

**응답 파싱:**
```python
resp = requests.post(url, headers=headers, json=payload, timeout=120)
result = resp.json()
image_bytes = base64.b64decode(result["data"][0]["b64_json"])
```

**주의:** OpenAI SDK의 images.edit()가 아니라 requests.post() 직접 호출 (SDK 미지원 형식)

### 2.3 settings.yaml 그림자 설정
```yaml
providers:
  shadow: gemini_shadow  # api_shadow / opencv_extract / gemini_shadow / grok_shadow / none

gemini_shadow:
  model: gemini-3-pro-image-preview
  fallback_model: gemini-3-pro-image-preview
  order: after_enhance  # before_enhance / after_enhance
  main_prompt: |
    ...그림자 생성 프롬프트...
  mannequin_prompt: |
    ...마네킹 삽입문...
  original_prompt: |
    ...원본 참고 삽입문...
  mannequin_full_prompt: |
    ...마네킹 전용 풀 프롬프트...

grok_shadow:
  model: grok-imagine-image
  order: after_enhance
  main_prompt: |
    ...
  mannequin_prompt: |
    ...
  original_prompt: |
    ...
```

---

## 3. 그림자 힌트 시스템

### 3.1 힌트 조회 우선순위 (`_get_shadow_hint()`)
12단계 계층적 탐색 (가장 구체적 → 가장 일반적):
1. `{provider}/{category}/{angle}/{type}`
2. `{provider}/{category}/{angle}`
3. `{provider}/{category}/{type}`
4. `{provider}/{category}`
5. `{category}/{angle}/{type}`
6. `{category}/{angle}`
7. `{category}/{type}`
8. `{category}`
9. `{provider}/default`
10. `{angle}/{type}`
11. `{angle}`
12. `default`

### 3.2 힌트 저장/미리보기
- **저장:** `_save_shadow_hint()` → `config/shadow_hints.yaml`에 append
- **미리보기:** `preview_shadow_only()` → `_shadow_hints` dict에 임시 저장 → 생성 → 복원 (YAML 미변경)
- **적용:** `apply_prompt_and_regenerate()` → 힌트 저장 + 그림자 재생성 + 재평가

---

## 4. 품질 검증/평가 (Vision API 활용)

### 4.1 개별 검증 (`_validate_result()`)
- 원본 + 결과 이미지 2장을 Vision API에 전달
- 3항목 PASS/FAIL: 배경, 그림자, 원형보존
- 프롬프트: `config/prompts.yaml` → `validation` 섹션
- 그림자 불합격 시 1회 자동 재시도 (`_pre_shadow_bytes`에서 복원)

### 4.2 독립 품질 평가 (`_evaluate_independent()`)
- 원본 + 결과 이미지 2장 비교
- 5항목 10점제 평가
- 검증 결과와 무관하게 항상 실행
- 프롬프트: `config/prompts.yaml` → `independent_evaluation` 섹션

### 4.3 자동수정 플로우
1. `preview_prompt_fix()` — AI에게 프롬프트 추천만 받기
2. `preview_shadow_only()` — 임시 힌트로 그림자 생성 (저장 X)
3. `apply_prompt_and_regenerate()` — 확정 시 힌트 저장 + 재생성

---

## 5. 공통 에러 처리 패턴

| 패턴 | 적용 대상 |
|------|----------|
| Exponential backoff (2^attempt + jitter) | 모든 외부 API |
| 재시도 대상 HTTP: 429, 500, 502, 503 | Photoroom, remove.bg, Claid |
| @retry 데코레이터 (5회, 4~60초) | Gemini Vision |
| 부분 응답 복구 (MAX_TOKENS) | Gemini Vision |
| JSON 잘림 감지 + 토큰 2배 재시도 | pipeline.py 분석 호출 |
| 폴백 모델 체인 (primary → fallback) | Gemini 그림자 |
| 불완전 JSON 복구 (닫는 괄호 보충) | result_parser.py |

---

## 6. 환경변수 (.env)

```
ANTHROPIC_API_KEY=...    # Claude Vision
OPENAI_API_KEY=...       # ChatGPT Vision
GEMINI_API_KEY=...       # Gemini Vision + Gemini 그림자
XAI_API_KEY=...          # Grok Vision + Grok 그림자
```

Gemini와 Grok은 Vision + 그림자 생성에 동일한 API 키를 공유합니다.
