---
name: image-processing-api
description: "이미지처리 API 사용법 — 배경 제거(Photoroom/remove.bg), 색보정(Claid.ai/OpenCV), 누끼 그림자 추출. 엔드포인트, 파라미터, 재시도 로직, 유형별 설정 참조."
user_invocable: true
---

# 이미지처리 API 가이드 (배경 제거 + 보정 + 그림자 추출)

이 프로젝트에서 사용하는 이미지 처리 API들의 사용법, 인증, 요청/응답 형식, 에러 처리 패턴을 정리한 스킬입니다.

---

## 1. 배경 제거 API

`config/settings.yaml`의 `providers.background_removal`로 선택합니다.

### 1.1 Photoroom API
- **파일:** `src/photoroom/client.py`
- **엔드포인트:** `https://image-api.photoroom.com/v2/edit`
- **인증:** 헤더 `x-api-key` (환경변수 `PHOTOROOM_API_KEY`)
- **가격:** Basic $0.02/img, Plus $0.10/img
- **요청:** Multipart form-data
- **타임아웃:** 60초

**요청 파라미터:**
```python
{
    "removeBackground": "true",
    "outputSize": "originalImage",    # originalImage / 1000x1000 / 2000x2000
    "padding": "0.01",               # 여백 비율 (0~1)
    "scaling": "fit",
    "referenceBox": "originalImage",
    "export.format": "png",
    "shadow.mode": "ai.soft",        # none / ai.soft / ai.hard / ai.floating
    "shadow.opacity": "0.01",        # 0~1 (0.01 = 거의 투명)
    "background.color": "FFFFFF"     # 흰 배경 (그림자 있을 때)
}
```

**사용 조건 (`should_process()`):**
- `full`, `worn`, `package`, `detail` 유형 → True
- 배경이 이미 투명/흰색이어도 처리 (그림자 합성 필요)

**그림자 모드 설명:**
| 모드 | 설명 | 방향 제어 |
|------|------|----------|
| `ai.soft` | 부드러운 접지 그림자 | 불가 |
| `ai.hard` | 선명한 접지 그림자 | 불가 |
| `ai.floating` | 떠있는 느낌 그림자 | 불가 |
| `none` | 그림자 없음 (투명 PNG) | - |

**주의:** shadow.mode 사용 시 background.color 필수 (그림자가 불투명 배경에 합성됨)

### 1.2 remove.bg API
- **파일:** `src/removebg/client.py`
- **엔드포인트:** `https://api.remove.bg/v1.0/removebg`
- **인증:** 헤더 `X-Api-Key` (환경변수 `REMOVEBG_API_KEY`)
- **가격:** 무료 50장/월, 유료 요금제
- **요청:** Multipart form-data
- **타임아웃:** 60초

**요청 파라미터:**
```python
{
    "size": "auto",       # auto / preview / full
    "type": "product",    # product / person / car
    "format": "png"
}
```

**응답:** 투명 PNG bytes (그림자 옵션 없음)

**그림자 주의:** remove.bg는 그림자 생성 기능이 없으므로 `api_shadow` 프로바이더와 조합 불가. Gemini/Grok 그림자 또는 누끼 합성 그림자와 조합해야 함.

### 1.3 공통 재시도 로직 (Photoroom, remove.bg 동일)
```python
max_retries = 3
for attempt in range(max_retries):
    response = requests.post(url, headers=headers, files=files, timeout=60)
    if response.status_code == 200:
        return response.content
    if response.status_code in (429, 500, 502, 503) and attempt < max_retries - 1:
        wait = (2 ** attempt) + random.uniform(0, 1)
        time.sleep(wait)
        files = rebuild_files()  # requests.post가 파일 객체를 소비하므로 재생성
        continue
    response.raise_for_status()
```

### 1.4 settings.yaml 배경 제거 설정
```yaml
providers:
  background_removal: removebg  # photoroom / removebg

photoroom:
  full:
    shadow.mode: ai.soft
    shadow.opacity: 0.01
    padding: 0.01
    outputSize: originalImage
    export.format: png
  detail_complex:
    padding: 0
  package:
    # full과 동기화

removebg:
  size: auto      # auto / preview / full
  type: product   # product / person / car
```

---

## 2. 이미지 보정 API

`config/settings.yaml`의 `providers.enhancement`로 선택합니다.

### 2.1 Claid.ai API
- **파일:** `src/claid/client.py`
- **엔드포인트:** `https://api.claid.ai/v1-beta1/image/edit/upload`
- **인증:** 헤더 `Authorization: Bearer {CLAID_API_KEY}`
- **가격:** 별도 요금제
- **요청:** Multipart form-data (file + JSON operations)
- **타임아웃:** 120초

**요청 형식:**
```python
files = {"file": ("image.png", image_bytes, "image/png")}
data = {"data": json.dumps({"operations": operations})}
response = requests.post(url, headers=headers, files=files, data=data)
```

**operations 구조:**
```python
{
    "restorations": {"upscale": "2x"},          # 선택적
    "adjustments": {
        "hdr": 20,           # 0-100, HDR 효과
        "sharpness": 15,     # 0-100, 선명도
        "exposure": 20,      # -100~100, 노출 (0이면 생략)
        "saturation": 5,     # -100~100, 채도 (0이면 생략)
        "contrast": 5        # -100~100, 대비 (0이면 생략)
    },
    "resizing": {
        "width": 1000,
        "height": 1000,
        "fit": "canvas"      # canvas / bounds
    },
    "background": {"color": "#FFFFFF"}
}
```

**응답 처리:**
1. JSON 응답 → `data.output.tmp_url` 추출 → URL에서 이미지 다운로드
2. 바이너리 응답 → 직접 반환

**10MB 제한:** 입력이 10MB 초과 시 PNG→JPEG 자동 변환 후 전송

**재시도 로직:** Photoroom/remove.bg와 동일 패턴 (3회, exponential backoff)

### 2.2 OpenCV 로컬 보정 (API 불필요)
- **파일:** `src/opencv_enhance/enhancer.py`
- **의존성:** OpenCV, PIL (로컬 처리, API 비용 없음)

**5단계 순차 처리:**
```
1. HDR    → CLAHE (clipLimit = hdr/10, tileGrid 8x8) on LAB L-channel
2. Exposure → LAB L-channel offset (value * 0.3)
3. Contrast → PIL ImageEnhance.Contrast (1.0 + value/100 * 0.5)
4. Saturation → HSV S-channel scale (1.0 + value/100 * 0.5)
5. Sharpness → Unsharp Mask (radius=2, amount=value/100*1.5)
```

**값 범위:**
| 파라미터 | 범위 | 기본값(full) | 0의 의미 |
|---------|------|-------------|---------|
| hdr | 0-100 | 20 | 효과 없음 |
| sharpness | 0-100 | 15 | 효과 없음 |
| exposure | -100~100 | 0 | 변화 없음 |
| saturation | -100~100 | 0 | 변화 없음 |
| contrast | -100~100 | 0 | 변화 없음 |

**알파 채널:** RGBA 입력 시 알파 분리 → RGB만 보정 → 알파 재합성

### 2.3 유형별 보정 프로파일
```yaml
claid:
  full:    { hdr: 20, sharpness: 10, exposure: 20, saturation: 5, contrast: 5 }
  detail:  { hdr: 15, sharpness: 10, fit: canvas, background_color: '#FFFFFF' }
  worn:    { hdr: 10, sharpness: 5, fit: bounds }
  package: { hdr: 20, sharpness: 15 }

opencv_enhance:
  full:    { hdr: 20, sharpness: 15, exposure: 0, saturation: 0, contrast: 0 }
  detail:  { hdr: 15, sharpness: 10, exposure: 0, saturation: 0, contrast: 0 }
  worn:    { hdr: 10, sharpness: 5,  exposure: 0, saturation: 0, contrast: 0 }
  package: { hdr: 20, sharpness: 15, exposure: 0, saturation: 0, contrast: 0 }
```

---

## 3. 누끼 합성 그림자 (OpenCV, 로컬)

API가 아닌 로컬 OpenCV 처리. `providers.shadow: opencv_extract` 선택 시 사용.

### 3.1 레벨 보정 방식 (`_preserve_natural_shadow()`)
- **파일:** `src/pipeline.py`
- **핵심 원리:** 그림자를 "감지"하지 않고, 그림자가 아닌 것을 제거하고 나머지 보존

**알고리즘:**
```
1. 배경제거 결과(RGBA)에서 alpha 마스크 → 제품 영역
2. 원본에서 제품 제거 (soft mask로 배경색 채움)
3. 레벨 보정: pixel / bg_color * 255
   - 배경색 → 255 (순백색)
   - 그림자 → 원래 그라데이션 비율 보존
4. search_top/bottom/sides로 탐색 영역 제한 + edge fadeout
5. opacity 블렌딩 (순백색과 혼합 → 그림자 강도 조절)
6. threshold: 노이즈 정리 (거의 흰색 → 순백색)
7. 합성: 레벨 보정 배경 + 누끼 제품 alpha composite
```

### 3.2 7개 파라미터 (GUI 조절 가능)
```yaml
shadow_extract:
  opacity: 70         # 그림자 진하기 (0-100%)
  threshold: 8        # 노이즈 정리 임계값
  blur: 3.0           # 가우시안 블러 (%)
  search_top: 5       # 상단 탐색 범위 (%)
  search_bottom: 60   # 하단 탐색 범위 (%)
  search_sides: 30    # 좌우 탐색 범위 (%)
  mask_expand: 2.5    # 누끼 경계 확장 (%)
```

**Vision API 연동:** AI가 이미지별 최적 파라미터를 `shadow_params`로 추천 → GUI 설정값과 머지 (AI 값 우선)

---

## 4. 후처리 알고리즘 (pipeline.py)

### 4.1 불투명 모드 (그림자 있는 이미지)
```
1. BFS 연결 컴포넌트 분석 (1/4 축소, threshold 240)
2. 가장 큰 컴포넌트 = 제품, 나머지 아티팩트 제거
3. 제품 상단 위/좌우 마진 밖: 흰색
4. 그림자 보호: 제품 아래 10%까지
5. 근백색(>245) 클린업
6. 제품 본체 기준 스케일링 (그림자 영역 제외)
7. 큰 임시 캔버스 + 제품 중심 배치 → 최종 크기 크롭
```

### 4.2 투명 모드 (그림자 없는 이미지)
```
1. alpha>=128 BFS 컴포넌트로 제품 감지
2. bbox 확장 (상하 25%, 좌우 20%)
3. 확장 영역 밖 alpha=0
4. 노이즈 제거 (alpha < 10 → 0)
5. 크롭 → 스케일링 → 중앙 배치
```

---

## 5. JPEG 최적화 (exporter/optimizer.py)

- **용량 제한:** 2024KB
- **품질 조절:** 이진 탐색으로 목표 용량에 맞는 JPEG quality 결정
- **출력 크기:** 1000x1000 고정

---

## 6. 환경변수 (.env)

```
PHOTOROOM_API_KEY=...    # Photoroom 배경 제거 + API 그림자
REMOVEBG_API_KEY=...     # remove.bg 배경 제거
CLAID_API_KEY=...        # Claid.ai 보정
```

---

## 7. 프로바이더 조합 가이드

| 배경제거 | 그림자 | 보정 | 비고 |
|---------|--------|------|------|
| Photoroom | api_shadow | Claid | Photoroom이 배경제거+그림자 동시 처리 |
| Photoroom | gemini_shadow | Claid | Photoroom 누끼 → Gemini 그림자 |
| remove.bg | gemini_shadow | Claid | **현재 기본 설정** |
| remove.bg | grok_shadow | Claid | Grok 그림자 ($0.02/장) |
| remove.bg | opencv_extract | OpenCV | **완전 무료** (API 비용 0) — Vision API 비용만 |
| remove.bg | none | Claid | 그림자 없이 보정만 |

**주의:** `api_shadow` + `removebg` 조합은 불가 (remove.bg에 그림자 옵션 없음)
