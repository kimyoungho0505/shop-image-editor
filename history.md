# LUXBOY Shop Image Editor - 개발 히스토리

> 마지막 업데이트: 2026-04-21 (7차)
> 다른 PC에서 이어서 개발할 때 이 문서를 참고하세요.

---

## 프로젝트 개요

럭셔리 이커머스(LUXBOY) 제품 이미지 자동 편집 데스크톱 앱 (Windows, tkinter GUI).
원본 제품 사진 → 배경 제거 → 그림자 처리 → HDR/보정 → 센터링 → 최적 출력.

## 프로젝트 구조

```
shop-image-editor/
├── gui.py                          # GUI v1 (tkinter, ~2450줄) - 기존
├── gui_pyside.py                   # GUI 기본 (PySide6) - 기존
├── gui2.py                         # GUI v2 (PySide6 향상판) ⭐ NEW
├── gui2_pyside/                    # GUI v2 모듈들
│   ├── app.py                      # 메인 윈도우 (사이드바 + 카드 레이아웃)
│   ├── styles.py                   # 스타일시트 (모던 라이트 테마)
│   ├── tabs/                       # 탭 모듈들
│   └── dialogs/                    # 다이얼로그 모듈들
├── design_samples/                 # PySide6 디자인 샘플들 ⭐ NEW
│   ├── sample1_sidebar_card.py    # 모던 라이트 (사이드바 + 카드)
│   ├── sample2_dark_glassmorphism.py # 다크 글래스모피즘 (프리미엄)
│   ├── sample3_minimal_clean.py    # 미니멀 클린 (Apple 스타일)
│   ├── sample_viewfinder.py        # 뷰파인더 다중탭 버전
│   └── sample_viewfinder_split.py  # 뷰파인더 좌우분할 버전
├── manual.html                     # 사용자 메뉴얼 (브라우저) ⭐ NEW
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

---

## 2026년 4월 17일 업데이트 (3차)

### 🎨 PySide6 기반 GUI v2 개발

#### 새로운 GUI 파일
- **gui2.py**: PySide6 향상된 버전 (독립 실행)
- **gui2_pyside/**: 모듈화된 구조
  - `app.py`: 사이드바 네비게이션 + 카드 레이아웃
  - `styles.py`: 모던 라이트 테마 스타일시트

#### 디자인 샘플 (design_samples/)
1. **sample1_sidebar_card.py** - 모던 라이트
   - 다크 네이비 사이드바 + 흰색 카드
   - 그래디언트 실행 버튼
   - 대시보드 느낌

2. **sample2_dark_glassmorphism.py** - 프리미엄 다크
   - 전체 다크 테마 + 보라색 포인트
   - 아이콘 사이드바 (64px)
   - 럭셔리 브랜드 이미지

3. **sample3_minimal_clean.py** - Apple 스타일
   - 상단 네비게이션 바
   - 여백 많은 미니멀 레이아웃
   - 가장 깔끔한 디자인

#### 뷰파인더 샘플 (이미지 비교 기능)
1. **sample_viewfinder.py** - 다중탭 버전
   - 슬라이더 비교 (상/하)
   - 좌우 분할 비교
   - 6단계 그리드 뷰
   - 평가 점수 + 세부 정보 패널

2. **sample_viewfinder_split.py** - 좌우분할 전문
   - 이전 단계 ↔ 현재 단계
   - 세로 분할선으로 명확히 구분
   - 각 영역별 상세 정보
   - 점수 및 액션 버튼

#### 사용자 메뉴얼
- **manual.html** - 브라우저 기반 완벽 설명서
  - 초등학생도 이해할 수 있는 쉬운 언어
  - 색상 코딩된 팁/주의/정보 박스
  - 3가지 디자인 스타일 스크린샷 포함
  - 목차 사이드바 + 검색 가능
  - 이미지 검증 상세 가이드 ⭐
  - 프롬프트 편집 완벽 가이드 ⭐

#### 실행 구성
- **.claude/launch.json** 추가
  - PySide6 GUI (gui_pyside.py)
  - tkinter GUI (gui.py)
  - CLI (main.py)

### 📊 주요 개선사항

| 항목 | GUI v1 (tkinter) | GUI v2 (PySide6) |
|------|-----------------|-----------------|
| 네비게이션 | 탭만 사용 | 사이드바 + 탭 |
| 시각적 품질 | 기본 | 모던 + 그래디언트 |
| 반응성 | 제한적 | 부드러운 호버/전환 |
| 디자인 자유도 | 낮음 | 높음 |
| 뷰파인더 | 기본 | 이미지 비교 전문화 |
| 문서화 | 없음 | 상세 HTML 매뉴얼 |

### 🚀 실행 방법

```bash
# GUI v1 (기존)
python gui.py

# GUI v2 (새로운)
python gui2.py

# 또는 CLI
python main.py --help
```

### 📝 다음 단계

1. **GUI v2 기능 완성**
   - 탭 구현 (프롬프트, 그림자, 설정)
   - 뷰파인더 통합
   - 실시간 이미지 처리

2. **PySide6 전환**
   - GUI v1 기능을 GUI v2로 이식
   - 테스트 및 최적화
   - GUI v2를 기본값으로 변경

3. **뷰파인더 기능**
   - 이미지 처리 단계별 시각화
   - 좌우분할 비교 UI 통합
   - 점수 기반 자동 평가

4. **사용자 메뉴얼 개선**
   - 실제 GUI 스크린샷으로 교체
   - 비디오 튜토리얼 추가
   - 다국어 지원

---

## 2026년 4월 17일 업데이트 (4차)

### 🗂️ 임시 옵션 탭 입출력 폴더 UI 추가

- `_build_temp_options_tab()`: 실행 탭과 동일한 입력/출력 폴더 선택 UI 추가
  - `var_unified_input` / `var_unified_output` StringVar (Entry + "..." 탐색 + "열기" 버튼)
  - 출력 폴더 기본값: `{입력폴더}/OUTPUT` (없으면 자동 생성)
- `_browse_unified_input()`: 입력 폴더 선택 시 출력 폴더를 `{선택폴더}/OUTPUT`으로 자동 지정 + 디렉터리 생성
- `_run_unified_photoroom()`: `var_unified_input` / `var_unified_output` 사용, 출력 폴더 없으면 자동 생성

### 💳 Photoroom 크레딧 확인 기능

- 설정 탭 API 키 입력 행(Photoroom 행) 옆에 "크레딧 확인" 버튼 + `lbl_photoroom_credits` 라벨 추가
- `_check_photoroom_credits()`: 백그라운드 스레드에서 `GET https://image-api.photoroom.com/v1/account` 호출
  - 응답: `{"credits":{"available":N,"subscription":M}}`
  - 성공 시: "남은 크레딧: N / M (사용: Z)" 초록색 표시
  - 실패 시: 빨간색 오류 메시지 표시

### 🔍 뷰파인더 라우팅 분류 결과 표시

- 뷰파인더 각 행에 라우팅 결과 텍스트 추가
  - `full_shadow` → "전체컷" (파란색)
  - `detail_bg_only` → "디테일(흰배경)" (주황색)
  - `claid_only` → "배경없는 디테일" (초록색)
  - 완료 상태: "성공" (초록) / "실패" (빨간)
- `routing_info`를 `_viewfinder_pairs`와 `_vf_file_stages` **양쪽** 모두에 저장하도록 수정
  - `_update_row_stages()`는 `_vf_file_stages`를 읽으므로 두 곳 모두 필요

### 🤖 Gemini 모델 업데이트

- `config/settings.yaml`: `gemini.model` `gemini-2.0-flash` → `gemini-2.5-flash` (구 모델 404 오류)
- GUI 콤보박스 목록에서 `gemini-2.0-flash` 제거, `gemini-2.5-flash-lite` 추가

### 🐛 버그 수정

#### result_parser.py — JSON 배열 응답 처리
- Gemini API가 `[{...}]` 배열 형태로 응답할 때 `_to_instruction()`에서 `.get()` 호출 → `AttributeError` 발생
- `_extract_json()`: `json.loads()` 결과가 list이면 첫 번째 dict 항목 반환하도록 수정

#### photoroom/client.py — background.color 파라미터 누락
- `_build_params()`: 그림자 모드 없을 때 `background.color` 설정이 무시되어 `export.format=jpg` + 투명 배경 충돌 → 400 오류
- `elif bg_color:` 분기 추가로 그림자 없는 경우에도 배경색 적용

#### pipeline.py — Vision 분류 실패 traceback 로깅
- Vision 분류 실패 시 예외 메시지만 출력되고 traceback 누락 → 원인 파악 어려움
- `except Exception as ve:` 블록에 `import traceback; _log(traceback.format_exc(), "warn")` 추가

### 🛡️ 디테일컷 누끼 품질 검증 (OpenCV flood fill)

배경 있는 디테일컷에서 Photoroom 누끼 결과 내부에 흰색 구멍이 생기는 문제 대응

#### 검증 로직 (`_check_detail_nukki_quality()`)
1. 결과 PNG에서 흰색 픽셀 마스크 생성 (R/G/B > 240)
2. 이미지 테두리에 1px 흰색 패딩 추가
3. 좌상단 (0,0)에서 flood fill → 외부 연결 흰색 픽셀을 128로 마킹
4. 패딩 제거 후 255로 남은 픽셀 = 외부에서 도달 불가 내부 구멍
5. 내부 구멍 면적 비율 > 0.05% 이면 품질 불량 판정

#### 롤백 처리
- 누끼 품질 불량 판정 시: 원본 이미지(`image_bytes`)로 대체 후 Claid 처리 진행
- 품질 양호 시: 정상적으로 Photoroom 결과로 Claid 처리

#### ConnectedComponents 방식 실패 이유
- 내부 구멍이 이미지 테두리의 흰 배경과 연결된 경우 "테두리 접촉" 판정 → 누락
- Flood fill 방식은 이런 경우에도 정확히 탐지 가능

---

## 2026년 4월 18일 업데이트 (5차)

### 🔧 폴더/파일 선택 대화상자 수정

#### 문제점
- tkinter `filedialog.askdirectory()` / `askopenfilenames()` 호출 시 `parent` 파라미터 누락
- 대화상자가 메인 윈도우 뒤에 나타나거나 표시되지 않는 현상 발생
- 특히 "임시옵션 탭"의 "파일 실행" 버튼 클릭 시 파일 선택 대화상자가 나타나지 않음

#### 수정 사항
**gui.py** 파일의 모든 `filedialog` 호출에 `parent=self` 파라미터 추가:

1. **_browse_input()** - 대시보드 탭 입력 폴더 선택
   ```python
   folder = filedialog.askdirectory(title="입력 이미지 폴더 선택", parent=self)
   ```

2. **_browse_output()** - 대시보드 탭 출력 폴더 선택
   ```python
   folder = filedialog.askdirectory(title="출력 폴더 선택", parent=self)
   ```

3. **_browse_unified_input()** - 임시옵션 탭 입력 폴더 선택
   ```python
   folder = filedialog.askdirectory(title="입력 이미지 폴더 선택", parent=self)
   ```

4. **_browse_unified_output()** - 임시옵션 탭 출력 폴더 선택
   ```python
   folder = filedialog.askdirectory(title="출력 폴더 선택", parent=self)
   ```

5. **_run_unified_photoroom("file")** - 파일 실행 모드 파일 선택
   ```python
   filepaths = filedialog.askopenfilenames(
       title="처리할 이미지 파일 선택 (여러 장 가능)",
       filetypes=filetypes, initialdir=initial_dir or None, parent=self)
   ```

#### 결과
- ✅ 모든 대화상자가 메인 윈도우 위에 정상적으로 표시됨
- ✅ 다중 모니터 환경에서도 올바른 화면에 표시됨
- ✅ 대화상자가 포커스를 받아 키보드/마우스 입력 즉시 가능

### 📝 API 키 설정 파일 생성

#### .env 파일 생성
프로젝트 루트에 `.env` 파일 생성 (API 키 설정용 템플릿)

```bash
GEMINI_API_KEY=your_gemini_api_key_here
PHOTOROOM_API_KEY=your_photoroom_api_key_here
# ANTHROPIC_API_KEY=your_anthropic_api_key_here (선택사항)
# OPENAI_API_KEY=your_openai_api_key_here (선택사항)
# XAI_API_KEY=your_xai_api_key_here (선택사항)
```

#### 필수 API 키
1. **Google Gemini Vision API** (이미지 분류용)
   - 설정: https://aistudio.google.com/app/apikeys
   - .env: `GEMINI_API_KEY=...`

2. **Photoroom API** (배경 제거용)
   - 설정: https://app.photoroom.com/api
   - .env: `PHOTOROOM_API_KEY=...`

#### API 키 등록 후
프로그램을 재시작하면 이미지 처리 기능이 정상 작동

### 📊 변경사항 요약
| 항목 | 수정 내용 |
|------|---------|
| gui.py | filedialog 호출 5곳에 parent=self 추가 |
| .env | 새로 생성 (API 키 설정 템플릿) |
| Commit | "Fix folder/file selection dialogs in tkinter GUI" |

---

## 2026년 4월 20일 업데이트 (6차)

### 🔄 수직촬영(탑다운) 누끼·그림자 스킵

- Vision API가 `shooting_angle == "top_down"` 감지 시 배경제거·그림자 없이 **Claid 보정만** 수행
- `pipeline.py`: `is_top_down` 분기 추가 (케이스 4)
- 결과 dict에 `shooting_angle` 반환
- `gui.py`: `top_down_only` 라우트 추가 (보라색 `#7c3aed`)
- 뷰파인더 파일 행: `수직촬영` 표시
- 뷰파인더 우측: `🟣 수직촬영(탑다운) → 보정만 (누끼·그림자 제외)`

### 🏷️ 수행 작업 배지 표시 (뷰파인더)

라우트별로 어떤 작업이 수행됐는지 파일 행에 표시:

| 라우트 | 파일 행 표시 |
|---|---|
| `full_shadow` | `전체컷  [누끼]  [그림자]` (파란색) |
| `detail_bg_only` | `디테일(흰배경)  [누끼]` (주황색) |
| `claid_only` | `배경없는 디테일` (초록색) |
| `top_down_only` | `수직촬영` (보라색) |
| `label_skip` | `라벨/바코드` (회색) |

- `routing_info`에 `performed` 리스트 추가 (`["누끼", "그림자"]` 등)
- 뷰파인더 우측 패널도 수행 내역 표시 (`▶ 누끼 · 그림자`)

### ✏️ 뷰파인더 수동 재처리 패널

결과가 마음에 들지 않을 때 원본에서 직접 재작업 가능

#### UI 구성 (뷰파인더 우측 하단)
- **누끼 방식**: 없음 / Photoroom / RemoveBG (라디오 버튼)
- **보정**: Claid 보정 on/off (체크박스)
- **▶ 재작업 실행**: 백그라운드 처리 → 뷰파인더 우측에 미리보기 (`✏️ 재처리 결과 (미확정)`)
- **✓ 수정완료 (파일 교체)**: 출력 파일을 재처리 결과로 덮어씌운 후 뷰파인더 자동 갱신
- 다른 이미지 선택 시 패널 자동 초기화

#### 구현 위치
- `gui.py`: eval_panel 하단에 `rp_panel` 프레임 추가
- `_on_rp_run()`: 백그라운드 스레드에서 선택된 작업 순차 실행
- `_on_rp_confirm()`: `out_files[0]["path"]`에 바이트 덮어쓰기
- `_show()`: 이미지 전환 시 `rp_result_bytes[0] = None` 초기화

### ⚪ 라벨/바코드컷 자동 스킵

모델명·바코드 확인용 클로즈업 이미지를 자동 감지하여 **모든 처리 없이 원본 저장**

#### 감지 대상
- 가방/신발 내부 브랜드 태그 클로즈업
- 제품 비닐 포장의 바코드 스티커
- 시리얼 번호, 모델명 라벨 확대컷

#### 구현
- `result_parser.py`: `EditInstruction`에 `is_label_cut: bool = False` 필드 추가
- `config/prompts.yaml`: 분류 JSON에 `is_label_cut` 판단 기준 추가
- `pipeline.py`: `is_label_cut` 감지 시 케이스 5 분기 → `original_bytes` 그대로 저장
  - `original_bytes` 변수 추가 (shrink 전 원본 보존)
- `gui.py`: `label_skip` 라우트 추가 + `_ROUTE_STYLES`에 `⚪ 라벨/바코드컷 → 처리 없음` 등록

### 🐛 버그 수정

#### result_parser.py — JSON 배열 처리 누락 (방법 2/3/4)
- **원인**: 방법 1에만 `isinstance(result, list)` 체크가 있었고 방법 2·3·4에는 없음
- Gemini가 코드블록(`\`\`\`json`)에 배열을 감싸서 응답하면 방법 2가 list를 그대로 반환
- `_to_instruction()`에서 `list.get()` 호출 → `AttributeError: 'list' object has no attribute 'get'`
- **수정**: 방법 2·3·4 모두 `isinstance` 체크 + 첫 번째 dict 추출 로직 추가


---

## 2026년 4월 21일 업데이트 (7차)

### 🆕 gui3.py — 설정·임시옵션 전용 분리 버전

`gui.py`에서 **설정 탭**과 **임시 옵션 탭**만 추출하여 `gui3.py` (4,961줄) 생성

#### 포함된 탭
- **설정 탭** (`_build_settings_tab`): API 키, 프로바이더, 파라미터 설정
- **임시 옵션 탭** (`_build_temp_options_tab`): Photoroom 단독 실행, 배경제거, 파일/폴더 처리

#### 제거된 탭 (실행·프롬프트 관련)
- 실행 탭 (`_build_main_tab`)
- 프롬프트 편집 (`_build_prompt_tab`)
- 평가 프롬프트 (`_build_eval_tab`)
- 그림자 프롬프트 (`_build_shadow_hints_tab`)

#### 주요 수정사항
| 항목 | 내용 |
|------|------|
| 창 제목 | `"LUXBOY 설정 및 임시옵션 - gui3"` |
| `__init__` | `self._unified_processing = False` 추가 (임시옵션 탭 상태) |
| `_save_state` | 실행탭 변수 저장 제거 (var_input, var_skip_bg, var_workers 등) |
| `_build_ui` | 설정 + 임시옵션 2개 탭만 생성 |
| `_save_settings` | `concurrent_workers` 저장 라인 제거 |
| `_load_configs` | `_load_prompts()` 호출 제거 |

#### 실행 방법
```bash
python gui3.py
```

### 📊 변경사항 요약
| 항목 | 수정 내용 |
|------|---------|
| gui3.py | 새로 생성 (4,961줄, 설정+임시옵션 전용) |
| history.md | 7차 업데이트 |
