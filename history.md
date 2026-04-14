# LUXBOY Shop Image Editor - 개발 히스토리

> 마지막 업데이트: 2026-04-01 (2차)
> 다른 PC에서 이어서 개발할 때 이 문서를 참고하세요.

---

## 프로젝트 개요

럭셔리 이커머스(LUXBOY) 제품 이미지 자동 편집 데스크톱 앱 (Windows, tkinter GUI).
원본 제품 사진 → 배경 제거 → 그림자 처리 → HDR/보정 → 센터링 → 최적 출력.

## 프로젝트 구조

```
shop-image-editor/
├── gui.py                          # 메인 GUI (tkinter, ~2450줄)
├── config/
│   ├── settings.yaml               # 전체 설정 (프로바이더, 파라미터)
│   └── prompts.yaml                # Vision API 프롬프트 템플릿 (분석 + 6단계 회의)
├── src/
│   ├── pipeline.py                 # 핵심 오케스트레이터 (~2400줄)
│   ├── analyzer/
│   │   ├── vision_client.py        # Claude Vision API
│   │   ├── openai_vision_client.py # ChatGPT Vision API
│   │   ├── gemini_vision_client.py # Gemini Vision API
│   │   ├── prompt_builder.py       # 프롬프트 동적 생성 (6단계 회의 포함)
│   │   └── result_parser.py        # JSON 파싱 + 잘린 JSON 복구
│   ├── photoroom/client.py         # Photoroom API (배경제거)
│   ├── removebg/client.py          # remove.bg API (배경제거)
│   ├── claid/client.py             # Claid.ai API (HDR 보정)
│   ├── opencv_enhance/enhancer.py  # OpenCV 로컬 보정
│   ├── sam/client.py               # SAM 그림자 추출 (Mobile/VIT-B/L/H)
│   ├── exporter/                   # 파일 저장, 네이밍, 최적화
│   └── utils/
│       ├── image_io.py             # 이미지 I/O + base64 변환 (max 1568px 리사이즈)
│       └── category.py             # 카테고리 관리
├── backups/                        # 자동수정 롤백 스냅샷
└── .env                            # API 키 (ANTHROPIC, OPENAI, GEMINI, PHOTOROOM, REMOVEBG, CLAID)
```

---

## 멀티 프로바이더 시스템

### 배경 제거
- **Photoroom** (기본): shadow.mode 옵션 포함
- **remove.bg**: 대안

### 이미지 보정
- **Claid.ai**: HDR, sharpness, exposure 등 API 보정
- **OpenCV**: 로컬 보정 (동일 파라미터)

### Vision 분석 (이미지 분류 + 품질 평가)
- **Claude** (Anthropic)
- **ChatGPT** (OpenAI GPT-4o)
- **Gemini** (Google)
- 3개 동시 병렬 호출 (`ThreadPoolExecutor`)

### 그림자 처리 (7가지 옵션)
| 옵션 | 설명 |
|------|------|
| `api_shadow` | Photoroom API의 그림자 옵션 |
| `gemini_shadow` | **Gemini 이미지 편집 API** (`gemini-3.1-flash-image-preview`) |
| `opencv_extract` | 원본에서 그림자 추출 (원본이식/레벨보정) |
| `sam_mobile` | MobileSAM 경량 (3~5초) |
| `sam_cpu` | SAM VIT-B CPU (10~30초) |
| `sam_gpu_b/l/h` | SAM GPU (VIT-B/L/H) |
| `none` | 그림자 없음 |

---

## 6단계 AI 회의 시스템 (자동 수정)

자동 수정(`process_with_refinement`) 실행 시, 3개 Vision API가 6단계 구조화된 회의를 진행:

### 회의 흐름
```
1단계: 의견 발의     → 3 API 병렬 독립 평가
2단계: 상호 검토     → 3 API 병렬 (동의/반박, 상대방 이름 언급)
3단계: 문제점 인식   → 메인 프로바이더 1개 (공통 문제 정리)
4단계: 해결방법 제시  → 3 API 병렬 (파라미터/코드 수정 제안)
5단계: 해결방법 토론  → 3 API 병렬 반복 (최대 3라운드, 합의까지)
6단계: 최종 결정     → 메인 프로바이더 1개 (adjusted_params 포함)
```

### 핵심 구현 위치
- **프롬프트**: `config/prompts.yaml` > `deliberation` 섹션
- **프롬프트 빌더**: `src/analyzer/prompt_builder.py` > `build_phase1~6_*()` 메서드
- **회의 실행**: `src/pipeline.py` > `evaluate_result()` 메서드 (1583줄~)
- **자동수정 루프**: `src/pipeline.py` > `process_with_refinement()` (2108줄~)
- **GUI 채팅 윈도우**: `gui.py` > `_open_deliberation_window()`, `_on_deliberation()`, `_on_deliberation_inner()`

### 주요 기능
- **실시간 채팅 윈도우**: Toplevel 윈도우에 대화체로 회의 과정 표시
- **발언자별 색상 구분**: Claude(초록), ChatGPT(파랑), Gemini(주황), 사회자(크림), 나(하늘)
- **사용자 참여**: 하단 입력창에서 메시지 입력 → 다음 API 호출 프롬프트에 주입
- **단계 진행 바**: 6단계 색상 표시 (완료=초록, 진행중=핑크, 대기=회색)
- **심화 탐색 모드**: 5회차 이상 반복 시 다른 분야 기법 탐색 프롬프트 주입
- **중지 버튼**: `is_cancelled` 콜백으로 매 단계 사이에서 체크
- **롤백 스냅샷**: 자동수정 시작 전 src/ + config/ 백업, 실패 시 복원

### 사용자 채팅 참여 구현
- `gui.py` > `_on_delib_user_send()`: 입력 → 채팅 표시 + `_user_messages` 큐 추가
- `gui.py` > `_get_user_messages()`: 큐에서 꺼내서 pipeline에 전달
- `pipeline.py` > `_inject_user_input()`: 각 단계 API 호출 전 프롬프트에 주입
  - `"[회의 참석자(사용자) 의견 — 반드시 고려하세요]: {messages}"`

---

## 최근 해결한 주요 이슈들

### 1. 채팅 입력 커서 멈춤 (IME 문제) ✅
- **원인**: `chat.config(state="normal/disabled")` 토글이 Windows 한글 IME 조합을 깨뜨림
- **해결**: ScrolledText를 **항상 normal 상태**로 유지, `<Key>` 바인딩으로 키 입력만 차단
- **위치**: `gui.py` 2052줄~ (`_open_deliberation_window`)

### 2. 자동수정 시 동일 파라미터 반복 ✅
- **원인**: AI가 `adjusted_params`를 비워서 반환 → 매번 같은 값으로 처리
- **해결 1**: 6단계 프롬프트에 `{current_params}` 추가 + 구체적 수치 요구 강조
- **해결 2**: `_force_param_change()` — AI가 동일 값 반환 시 점수 기반 강제 조정
- **위치**: `pipeline.py` > `_force_param_change()` (1925줄~)

### 3. 그림자 유무 오판 ✅
- **해결**: `_detect_shadow_in_original()` — 원본 상단(배경) vs 하단(바닥) 밝기 차이 분석
- **로직**: 배경 밝기 180+ 일 때, 차이 > 10이면 그림자 있음
- **위치**: `pipeline.py` > `_detect_shadow_in_original()` (1925줄~)

### 4. Gemini 이미지 편집 그림자 ✅ (신규)
- **모델**: `gemini-3.1-flash-image-preview`
- **방식**: 배경 제거된 이미지 + 프롬프트 → 그림자가 추가된 이미지 반환
- **소요시간**: ~30~45초
- **위치**: `pipeline.py` > `_gemini_add_shadow()` (1499줄~)

### 5. Gemini 그림자 미생성 버그 수정 ✅ (신규)
- **원인 1**: `_detect_shadow_in_original()`이 원본에 그림자가 없으면 `needs_shadow = False`로 덮어씀
  - Gemini/API 그림자는 **새로 생성**하는 방식이므로 원본 그림자 유무와 무관해야 함
  - **수정**: 생성형 그림자(`gemini_shadow`, `api_shadow`)일 때는 감지 결과와 무관하게 `needs_shadow = True` 유지
- **원인 2**: 배경 제거된 누끼(PNG)를 `image/jpeg` mime type으로 Gemini에 전송
  - **수정**: 이미지 헤더(PNG magic bytes)를 확인하여 자동 mime type 감지
- **위치**: `pipeline.py` > `process_single()` 1220줄~, `_gemini_add_shadow()` 1520줄~

### 6. Gemini 그림자 프롬프트 GUI 설정 ✅ (신규)
- 설정 패널에 **"Gemini AI 그림자 프롬프트"** 섹션 추가
- 3개 편집 가능한 텍스트 필드:
  - **원본 참고 프롬프트**: 원본 이미지 전송 시 안내 프롬프트
  - **그림자 생성 프롬프트**: 메인 프롬프트 (`{has_original}` 자리에 원본 참고 문구 자동 삽입)
  - **원본 참고 삽입문**: 원본이 있을 때 `{has_original}` 위치에 들어가는 문구
- **설정 저장** / **기본값 복원** 버튼
- `settings.yaml`의 `gemini_shadow` 섹션에서 로드/저장
- **위치**: `gui.py` 설정 패널 (누끼 합성 그림자 옵션 아래), `pipeline.py` > `_gemini_add_shadow()`

### 7. Gemini 그림자 생성 순서 옵션 ✅ (신규)
- **문제**: 기존에는 누끼 → 그림자 → 보정 순서 고정 → 그림자에 HDR 등 보정이 적용되어 부자연스러울 수 있음
- **해결**: 설정에서 순서 선택 가능
  - **보정 후 그림자 (권장, 기본값)**: 누끼 → Claid/OpenCV 보정 → Gemini 그림자
    - 최종 톤에 맞는 자연스러운 그림자 생성
  - **보정 전 그림자**: 누끼 → Gemini 그림자 → Claid/OpenCV 보정
    - 그림자에도 HDR/샤프니스 보정 적용됨
- **구현**: `pipeline.py`에서 `after_enhance` 모드일 때 배경제거 후 그림자 스킵 → 보정 완료 후(4.5단계) 실행
- **설정키**: `settings.yaml` > `gemini_shadow.order` (`after_enhance` / `before_enhance`)
- **위치**: `gui.py` Gemini 그림자 설정 내 라디오 버튼, `pipeline.py` > `process_single()` 1342줄~ + 1432줄~

### 8. 소스 코드 자동 수정 — 미구현
- AI가 `code_issues`로 코드 수정을 **제안**은 하지만, **실제 소스 파일 수정은 미구현**
- 롤백 스냅샷 시스템은 준비되어 있음 (`create_rollback_snapshot`, `rollback_from_snapshot`)
- 향후 구현 시: `code_issues`의 `suggested_fix`를 파싱 → 소스 파일에 적용 → 실패 시 롤백

---

## 설정 (settings.yaml) 주요 항목

```yaml
providers:
  vision: gemini          # 메인 Vision (claude/chatgpt/gemini)
  background_removal: removebg  # 배경제거 (photoroom/removebg)
  enhancement: claid      # 보정 (claid/opencv)
  shadow: gemini_shadow   # 그림자 (api_shadow/gemini_shadow/opencv_extract/sam_*/none)

shadow_extract:
  method: transplant      # 원본이식(transplant) / 레벨보정(level)
  opacity: 70
  threshold: 15
  blur: 10.0
  # ... search_top, search_bottom, search_sides, mask_expand, distance_falloff

auto_options:
  claid: ai_auto          # AI 자동 파라미터 추천 사용
  opencv: ai_auto
  photoroom: ai_auto
  shadow: ai_auto

gemini_shadow:
  order: after_enhance    # 그림자 생성 순서 (after_enhance / before_enhance)
  ref_prompt: "..."       # 원본 참고 프롬프트 (GUI에서 편집)
  main_prompt: "..."      # 그림자 생성 메인 프롬프트 ({has_original} 치환)
  orig_insert: "..."      # 원본 있을 때 {has_original}에 삽입되는 문구
```

---

## API 키 (.env)

```
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
GEMINI_API_KEY=...
PHOTOROOM_API_KEY=...
REMOVEBG_API_KEY=...
CLAID_API_KEY=...
```

---

## 개발 환경

- **OS**: Windows 11
- **Python**: 3.x
- **GUI**: tkinter
- **주요 패키지**: opencv-python, Pillow, numpy, requests, loguru, pyyaml, python-dotenv, anthropic, openai, google-genai, tenacity
- **선택 패키지**: torch, segment-anything, mobile_sam, timm (SAM용)

---

## 다음 개발 과제

1. **소스 코드 자동 수정 구현**: AI `code_issues` → 실제 파일 수정 + 롤백
2. **Gemini 그림자 프롬프트 최적화**: 제품 유형별(신발/가방/시계 등) 맞춤 프롬프트
3. **이미지 캐싱**: 동일 이미지의 base64 인코딩 캐싱으로 반복 인코딩 방지
4. **배치 자동수정**: 현재 단건만 자동수정 가능 → 배치에도 적용
5. **회의 결과 내보내기**: 채팅 윈도우 내용을 파일로 저장하는 기능

---

## 주의사항

- **그림자 처리 순서**: Gemini 그림자는 `gemini_shadow.order` 설정으로 보정 전/후 선택 가능 (기본: 보정 후)
- **센터링**: 큰 임시 캔버스에 배치 후 크롭하는 방식 (정확한 중앙 정렬)
- **이미지 전송 크기**: API 전송 시 max 1568px로 리사이즈 + JPEG 90% (12MB 원본 → ~300KB)
- **Gemini 이미지 편집**: 30~45초 소요, SynthID 워터마크 자동 포함
- **Gemini 그림자 + 생성형 그림자**: `_detect_shadow_in_original()` 결과와 무관하게 항상 `needs_shadow = True` (생성형은 새로 만드는 것)
- **누끼 이미지 mime type**: removebg/photoroom 결과는 PNG → Gemini 전송 시 자동 감지 필요 (jpeg로 보내면 안 됨)
- **IME 이슈**: ScrolledText에 state 토글 절대 사용 금지 (한글 입력 깨짐)
