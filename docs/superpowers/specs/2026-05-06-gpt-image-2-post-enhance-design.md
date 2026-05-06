# gpt-image-2 사후 보정 + 검증 기능 설계

**작성일:** 2026-05-06
**대상 모듈:** `src/openai_image/client.py`, `config/image2_prompts.yaml`, `gui3.py`
**관련 사양:** `docs/superpowers/specs/2026-05-04-multi-size-resize-design.md` (멀티사이즈 출력)

---

## 1. 목적 & 범위

기존 편집 파이프라인 완료 후, 뷰파인더에서 **선택적으로** OpenAI `gpt-image-2`로 사후 보정을 수행하고, 같은 OpenAI 계정의 `gpt-4o-mini`로 변형 여부(로고/문자/제품 디테일 왜곡)를 자동 검증한다. 사용자는 보정 결과 중 하나를 선택해 최종 저장본으로 사용한다.

**주요 특징:**
- **선택적**: 모든 이미지가 자동으로 보정되지 않음. 뷰파인더에서 사용자가 카드별로 트리거.
- **반복 가능**: 같은 카드에서 여러 번 시도(품질/프롬프트 조합) → 결과가 토글로 누적.
- **자동 검증**: 보정 후 즉시 변형 여부 검사. 변형 감지 시 토글에 경고 배지.
- **최종 저장 시 멀티사이즈 자동 재생성**: 선택된 결과로 `OUTPUT/original/`을 덮어쓰고 1500/860/crop을 같은 `MultiSizeResizer`로 갱신.

---

## 2. 아키텍처

### 2.1 모듈 구성

```
src/openai_image/                # 신규 패키지
├── __init__.py
└── client.py                    # GPTImage2Client + 데이터클래스 + 에러
config/
└── image2_prompts.yaml          # 신규 — 카테고리별 프롬프트 + 모델 설정
tests/
└── test_openai_image.py         # 신규 — 단위 테스트 (mock 기반)
gui3.py                          # 수정 — 조건 탭 확장 + 카드 UI + 다이얼로그
```

### 2.2 클라이언트 인터페이스

```python
# src/openai_image/client.py

@dataclass
class GPTImage2Result:
    enhanced_bytes: bytes
    quality: str                 # "low" | "medium" | "hd"
    prompt_used: str
    cost_estimate_usd: float
    elapsed_sec: float

@dataclass
class VerificationResult:
    safe: bool
    issues: list[str]
    raw_response: str
    elapsed_sec: float

class GPTImage2NoCreditError(RuntimeError):
    """OpenAI 크레딧 부족 (402)."""

class GPTImage2Client:
    def __init__(
        self,
        api_key: str = None,                    # None이면 OPENAI_API_KEY env
        verification_model: str = "gpt-4o-mini",
        timeout: int = 120,
    ): ...

    def enhance(
        self,
        image_bytes: bytes,
        prompt: str,
        quality: str = "medium",
        size: str = "1024x1024",
    ) -> GPTImage2Result:
        """gpt-image-2로 보정. POST /v1/images/edits."""

    def verify(
        self,
        original_bytes: bytes,
        enhanced_bytes: bytes,
        prompt: str,
    ) -> VerificationResult:
        """gpt-4o-mini로 변형 검증. POST /v1/chat/completions, JSON 응답."""

    def enhance_and_verify(
        self,
        image_bytes: bytes,
        enhance_prompt: str,
        verify_prompt: str,
        quality: str = "medium",
    ) -> tuple[GPTImage2Result, VerificationResult | None]:
        """편의 메서드: 보정 후 검증."""
```

### 2.3 OpenAI API 호출 형태

**보정 (`enhance`):**
```python
# openai SDK 사용
import io
from openai import OpenAI
client = OpenAI(api_key=self._api_key)
img_file = io.BytesIO(image_bytes); img_file.name = "input.png"
resp = client.images.edit(
    model="gpt-image-2",
    image=img_file,
    prompt=prompt,
    size=size,
    quality=quality,           # "low" | "medium" | "hd"
)
b64 = resp.data[0].b64_json
enhanced_bytes = base64.b64decode(b64)
```

**검증 (`verify`):**
```python
import base64
o_b64 = base64.b64encode(original_bytes).decode()
e_b64 = base64.b64encode(enhanced_bytes).decode()
resp = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{o_b64}"}},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{e_b64}"}},
        ],
    }],
    response_format={"type": "json_object"},
)
text = resp.choices[0].message.content   # '{"safe": true, "issues": []}'
parsed = json.loads(text)
```

### 2.4 에러 처리

| HTTP | 처리 |
|------|------|
| 402 | `GPTImage2NoCreditError` raise → GUI에서 한글 팝업 + OpenAI 충전 링크 |
| 429 | 지수 백오프 자동 재시도 (최대 3회: 2s/4s/8s) |
| 5xx | 1회 재시도 |
| 타임아웃 (120초) | 즉시 실패, 카드에 `❌ 타임아웃 — 재시도하세요` |
| `verify` JSON 파싱 실패 | `safe=False, issues=["검증 응답 파싱 실패"]`로 폴백 |

---

## 3. 설정 (`config/image2_prompts.yaml`)

```yaml
image2:
  default_quality: medium        # low | medium | hd
  default_size: "1024x1024"

  verification:
    model: "gpt-4o-mini"
    block_on_unsafe: false       # true면 변형 감지 결과는 토글 비활성화
                                 # false면 경고 배지만 달고 최종 저장은 가능

  prompts:
    default:
      enhance: |
        Enhance this product photo for an e-commerce listing.
        Improve sharpness, color accuracy, and lighting.
        Keep the product, pose, and composition exactly the same.
        Pure white background. No text, no watermarks.
      verify: |
        Compare the original (first image) and enhanced (second image).
        Check if logos, text, brand marks, or distinctive product features
        have been altered, distorted, or blurred.
        Respond ONLY in JSON: {"safe": true|false, "issues": ["short Korean strings"]}.

    jewelry:
      enhance: |
        Enhance details and reflective highlights on this jewelry product photo.
        Keep engravings, gemstones, metal texture, and brand marks sharp and accurate.
        Do not alter shape, color, or proportions of stones and metalwork.
        Pure white background.
      verify: |
        Compare the original and enhanced jewelry images.
        Check for changes in engravings, gemstones, settings, or brand marks.
        Respond ONLY in JSON: {"safe": true|false, "issues": ["..."]}.

    mannequin:
      enhance: |
        Enhance fabric texture, folds, and color accuracy of this clothing on mannequin.
        Smooth mannequin contours but keep clothing exactly as is.
        Do not change garment shape or details.
      verify: |
        Compare original and enhanced mannequin clothing photos.
        Check if logos, prints, embroidery, buttons, or seams were altered.
        Respond ONLY in JSON: {"safe": true|false, "issues": ["..."]}.

    model:
      enhance: |
        Enhance natural skin tones and clothing details on this fashion model photo.
        Keep the model's pose, face, body shape exactly as is.
      verify: |
        Compare original and enhanced fashion photos.
        Check if face, body, garment logos, or prints were altered.
        Respond ONLY in JSON: {"safe": true|false, "issues": ["..."]}.

    full:
      enhance: |
        Enhance overall product photo for clarity and color accuracy.
      verify: |
        Compare original and enhanced full-shot images. Check for any visible alteration.
        Respond ONLY in JSON: {"safe": true|false, "issues": ["..."]}.

    detail:
      enhance: |
        Enhance fine detail, texture, and color of this close-up product shot.
        Keep all features intact.
      verify: |
        Compare original and enhanced detail shots.
        Check if textures, materials, or stitching were altered.
        Respond ONLY in JSON: {"safe": true|false, "issues": ["..."]}.

    package:
      enhance: |
        Enhance package photo for clarity. Keep all printed text and logos sharp and unchanged.
      verify: |
        Compare original and enhanced package images.
        Check carefully if any printed text, barcode, or logo was altered. Even minor blur counts.
        Respond ONLY in JSON: {"safe": true|false, "issues": ["..."]}.
```

---

## 4. 조건 탭 UI 확장

기존 라우팅 규칙 아래에 새 섹션 추가.

```
┌─ 조건 탭 ─────────────────────────────────────────────────┐
│ [기존 라우팅 규칙 영역 — 변경 없음]                          │
│                                                             │
│ ───────────────────────────────────────────────────         │
│                                                             │
│ ✨ image-2.0 카테고리별 프롬프트                             │
│                                                             │
│ 기본 품질: [medium ▼]   검증 모델: [gpt-4o-mini ▼]          │
│ ☐ 변형 감지 시 저장 차단 (off면 경고만)                       │
│                                                             │
│ 카테고리: [기본] [주얼리] [의류(마네킹)] [의류(모델)]         │
│            [전체컷] [디테일] [패키지]                         │
│                                                             │
│ ▼ 선택된 카테고리: 주얼리                                     │
│                                                             │
│ 보정 프롬프트:                                               │
│ ┌─────────────────────────────────────────────────────┐   │
│ │ (텍스트 영역)                                        │   │
│ └─────────────────────────────────────────────────────┘   │
│                                                             │
│ 검증 프롬프트:                                               │
│ ┌─────────────────────────────────────────────────────┐   │
│ │ (텍스트 영역)                                        │   │
│ └─────────────────────────────────────────────────────┘   │
│                                                             │
│ [기본값으로 복원]  [저장]                                    │
└─────────────────────────────────────────────────────────────┘
```

**카테고리 매핑** (Vision 분석 결과 → 프롬프트 키):

| Vision 결과 | 프롬프트 키 |
|----------|----------|
| `detected_category == "jewelry"` | `jewelry` |
| `image_type == "worn"` && `has_mannequin` | `mannequin` |
| `image_type == "worn"` && !`has_mannequin` | `model` |
| `image_type == "full"` | `full` |
| `image_type == "detail"` | `detail` |
| `image_type == "package"` | `package` |
| (그 외) | `default` |

---

## 5. 뷰파인더 카드 UI

### 5.1 카드 레이아웃 (확장)

```
┌─ 상품명_1.jpg ──────────────────────────────────────┐
│  [썸네일]                                             │
│                                                        │
│  단계: 분석 → 누끼 → 보정 → 그림자 → 크롭 → 저장 → 검증 │
│        → image-2.0 (medium) → image-2.0 (high)        │
│                                                        │
│  ─── 결과 선택 (현재: 편집본) ───                      │
│  ◉ 편집본 (기본)                                       │
│  ○ image-2.0 medium (1차)  ✅ 검증 통과               │
│  ○ image-2.0 high   (2차)  ⚠️ 변형 감지 [상세]        │
│                                                        │
│  [원본보기] [폴더열기] [리사이즈]                      │
│  [✨ image-2.0 보정] [💾 최종 저장]                     │
└────────────────────────────────────────────────────────┘
```

### 5.2 보정 다이얼로그

```
┌─ image-2.0 보정 ─ 상품명_1.jpg ───────────────────────┐
│  카테고리: [의류(마네킹) (자동 감지) ▼]                   │
│                                                         │
│  보정 프롬프트:                                         │
│  ┌────────────────────────────────────────────────┐   │
│  │ (카테고리 기본값 prefill, 1회 한정 수정 가능)     │   │
│  └────────────────────────────────────────────────┘   │
│                                                         │
│  품질:  ◉ medium (~$0.05)  ○ high (~$0.21)  ○ low      │
│                                                         │
│  ☑ 자동 검증 (gpt-4o-mini, ~$0.001)                     │
│                                                         │
│  [취소]  [✨ 보정 시작]                                  │
└─────────────────────────────────────────────────────────┘
```

### 5.3 스테이지 표시 (B안 — 동적 추가)

기존 `_VF_STAGE_PATTERNS` (분석/누끼/보정/그림자/크롭/저장/검증) 뒤에 image-2.0 호출 시점에 동적으로 추가:

```python
# 보정 시작 시
self._vf_add_stage(card_idx, label=f"image-2.0 ({quality})", state="active")

# 검증 통과 시
self._vf_update_stage(card_idx, label=f"image-2.0 ({quality})", state="done", icon="✅")

# 변형 감지 시
self._vf_update_stage(card_idx, label=f"image-2.0 ({quality})", state="warning", icon="⚠️")
```

여러 번 시도하면 스테이지가 순서대로 추가됨.

---

## 6. 데이터 플로우

### 6.1 카드별 메모리 상태

```python
# self._viewfinder_pairs[idx]에 추가되는 필드
{
    # 기존 필드들...
    "image2_results": [
        {
            "bytes": b"...",
            "quality": "medium",
            "prompt": "Enhance...",
            "verification": {"safe": True, "issues": []},
            "elapsed_sec": 12.4,
            "cost_estimate": 0.053,
        },
        # 사용자가 여러 번 시도하면 누적
    ],
    "image2_selected_idx": -1,   # -1=편집본, 0+=image2_results 인덱스
    "final_saved": False,
}
```

### 6.2 보정 트리거 흐름

```
[✨ image-2.0 보정] 클릭
    ↓
다이얼로그 열림 (카테고리 자동 감지 + 프롬프트 prefill)
    ↓
[보정 시작]
    ↓
워커 스레드:
  1. 입력 bytes 확보:
     - card.image2_selected_idx == -1이면 OUTPUT/original/{stem}_1.jpg에서 로드
     - card.image2_selected_idx >= 0이면 해당 결과를 입력으로 사용 (이전 결과 위에 추가 보정)
     - 단순화 옵션: 항상 OUTPUT/original/{stem}_1.jpg에서 로드 (← 채택)
  2. GPTImage2Client.enhance(...)
  3. GPTImage2Client.verify(...)
  4. card.image2_results.append({...})
    ↓
메인 스레드 (after(0)):
  - 카드 라디오 영역에 새 항목 추가
  - 스테이지에 "image-2.0 (quality)" 추가
  - 비용 누적 표시
```

### 6.3 최종 저장 흐름

```
사용자: ◉ image-2.0 high 선택 → [💾 최종 저장]
    ↓
1. 변형 감지 항목이면 확인 다이얼로그
    ↓
2. 백업: OUTPUT/original/{stem}_1.jpg → {stem}_1_v0.jpg
    (이미 _v0.jpg가 있으면 _v0_1, _v0_2 ... 자동 증분)
    ↓
3. 선택된 image2_result.bytes → OUTPUT/original/{stem}_1.jpg 덮어쓰기
    ↓
4. 멀티사이즈 재생성 (기존 MultiSizeResizer 재사용):
   resizer.resize_from_file(
       new_original_path,
       seq_n=card.seq_n,             # 기존 순번 그대로
       variants={"size_1500": True, "size_860": True, "crop": is_first},
       overwrite=True,
   )
    ↓
5. 카드에 "✓ 최종 저장됨" 배지, 라디오 잠금
```

**입력 사이즈 처리:**
- gpt-image-2는 1024×1024 입력 권장. 우리 편집본은 2250×2250.
- → 보정 전 1024×1024로 다운스케일 → API 호출 → 결과 1024×1024
- → 결과를 2250×2250로 LANCZOS 업스케일하여 `OUTPUT/original/`에 저장
- → 멀티사이즈는 이 2250 기반으로 다시 1500/860/crop 생성

(품질 손실은 디테일 보강 효과로 상쇄됨. high 품질 시 1024 출력은 medium 대비 노이즈 적음.)

---

## 7. 테스트 계획

### 7.1 단위 테스트 (`tests/test_openai_image.py`)

| 테스트 | 검증 |
|------|------|
| `test_enhance_returns_jpeg_bytes` | mock 응답 → bytes 반환 |
| `test_enhance_402_raises_no_credit_error` | 402 → `GPTImage2NoCreditError` |
| `test_enhance_passes_quality_param` | `quality="hd"`가 API 호출에 포함 |
| `test_verify_parses_safe_json` | `{"safe": true}` → `safe=True` |
| `test_verify_parses_unsafe_json` | `{"safe": false, "issues": [...]}` → 정확히 파싱 |
| `test_verify_invalid_json_falls_back_to_unsafe` | 잘못된 JSON → safe=False, issues=["파싱 실패"] |
| `test_enhance_and_verify_combined` | 두 호출 순차 실행, 튜플 반환 |
| `test_429_retries_with_backoff` | 429 → 재시도 |
| `test_timeout_raises_clean_error` | 타임아웃 → 명확한 메시지 |

### 7.2 통합 테스트

- 실 이미지 1장으로 GUI 실행
- 카드에서 image-2.0 보정 → 다이얼로그 → medium 보정 → 토글 추가 확인
- 같은 카드에서 high 보정 → 토글 2개 확인
- 라디오로 high 선택 → 최종 저장 → `OUTPUT/original/{stem}_1.jpg` 변경 + `_v0.jpg` 백업 + 1500/860/crop 갱신 확인
- 음성 알림 "image-2.0 보정 기능 완료되었습니다"

### 7.3 회귀 테스트

- 기존 14개 resizer 테스트 전부 통과
- 멀티사이즈 자동 재생성 흐름 확인 (Task A 통합 테스트 시나리오)
- 크레딧 부족 (Photoroom/Claid) 즉시 중단 동작 유지 확인

---

## 8. 의존성 & 환경

- `openai` Python SDK (이미 설치됨, `requirements.txt`에 존재)
- 환경변수: `OPENAI_API_KEY` (이미 사용 중)
- 신규 의존성 없음 — `base64`, `json`, `io` 표준 라이브러리만

---

## 9. 구현 순서 요약

1. `src/openai_image/client.py` 작성 (TDD, 9개 단위 테스트)
2. `config/image2_prompts.yaml` 작성 + `config_loader` 호환 확인
3. 조건 탭에 image-2.0 프롬프트 섹션 추가 (`_build_conditions_tab` 확장)
4. 뷰파인더 카드에 라디오 토글 영역 + "image-2.0 보정" / "최종 저장" 버튼 추가
5. 보정 다이얼로그 (`_vf_open_image2_dialog`) 구현
6. 백그라운드 워커 + 스테이지 동적 추가 (`_vf_add_stage`)
7. 최종 저장 워크플로우 (백업 + 덮어쓰기 + 멀티사이즈 재생성)
8. 실 이미지 통합 테스트 + 음성 알림
9. `history.md` 업데이트 + 커밋 + 푸시
