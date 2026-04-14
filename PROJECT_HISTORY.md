# 쇼핑몰 이미지 자동 편집 도구 — 프로젝트 히스토리

## 프로젝트 개요
쇼핑몰 판매용 상품 이미지를 자동으로 편집하는 Windows 데스크탑 앱.
원본 사진 → 배경 제거/그림자 → AI 분석 → 색보정 → 1000×1000 표준 출력.

**기술 스택:** Python 3, tkinter GUI, PySide6 GUI, Photoroom API, remove.bg API, Claid.ai API, OpenCV, Claude/ChatGPT/Gemini/Grok Vision API

---

## 아키텍처 (현재: 멀티 프로바이더 파이프라인)

```
원본 이미지 (다중 파일 선택 가능)
  ↓
[병렬 처리: ThreadPoolExecutor, 동시 1/2/4/8개]
  ↓ (각 파일별 독립 파이프라인 인스턴스)
Vision API [선택: Claude / ChatGPT / Gemini / Grok]
  → 유형/배경/카테고리/그림자 방향/그림자 파라미터 판별
  → ★ 디테일컷 + has_human_hand 감지 (흰 장갑 포함)
  → ★ shooting_angle, floor_visible 판별 (그림자 스마트 판단용)
  ↓
[디테일컷 + 손 감지 시] 손 크롭 (edge crop, 4% 마진) → 그림자 절대 비활성화
  ↓
배경 제거 [선택: Photoroom / remove.bg / 복합] (재시도 3회, exponential backoff)
  - Photoroom: removeBackground + shadow 옵션 (API 그림자 선택 시)
  - remove.bg: 배경 제거 전용 (그림자 옵션 없음)
  - ★ 복합(hybrid): Photoroom 1차 → Vision API 품질 검증 → 불합격 시 remove.bg 폴백
  ↓
그림자 처리 [선택: API 그림자 / 누끼 합성 / Gemini 생성형 / 없음]
  - ★ 디테일컷/손 감지 → _no_shadow_override로 절대 차단
  - API 그림자: Photoroom shadow.mode/opacity (배경제거와 동시)
  - 누끼 합성: 원본에서 그림자 추출 → 누끼 위에 합성 (7개 파라미터 조절)
  - Gemini 생성형: 마네킹 모드 시 원본→Gemini 직접 전송
  - 없음: 그림자 없이 진행
  ↓
후처리 (pipeline.py)
  - BFS 연결 컴포넌트 분석으로 아티팩트 제거
  - 제품 본체 기준 스케일링 (그림자 제외)
  - 카테고리별 여백 적용 + 큰 임시 캔버스 방식 정확한 중앙 배치
  - ★ 디테일컷은 여백 스킵
  ↓
이미지 보정 [선택: Claid.ai / OpenCV] (재시도 3회, exponential backoff)
  - Claid.ai: AI 기반 HDR/선명도 (유료 API)
  - OpenCV: CLAHE HDR + Unsharp Mask + LAB/HSV 조정 (로컬 무료)
  ↓
JPEG 최적화 (용량 제한 2024KB)
  ↓
출력 (1000×1000)
```

**프로바이더 선택:** GUI 메인화면에서 라디오 버튼으로 즉시 전환 가능

### 핵심 파일 구조
```
shop-image-editor/
├── gui.py                    # tkinter GUI (5탭: 실행/프롬프트편집/평가프롬프트/그림자힌트/설정) — 라이트 테마
├── main.py                   # CLI 진입점
├── gui_pyside.py             # PySide6 GUI 진입점 (프로토타입, 보류)
├── gui_pyside/               # PySide6 모듈 (12개, 보류)
├── crash.log                 # 크래시 로그 (자동 생성)
├── config/
│   ├── settings.yaml         # 출력 설정, 프로바이더 파라미터, Gemini/Grok 그림자 프롬프트
│   ├── categories.yaml       # 카테고리별 여백 규칙 (padding_860)
│   ├── prompts.yaml          # Vision 분석 + 검증 + 독립평가 + 자동수정 프롬프트
│   └── shadow_hints.yaml     # 카테고리/촬영방향별 그림자 보충 힌트 (55개 프리셋)
├── models/                   # SAM 체크포인트 (삭제됨, 필요 시 재다운로드)
├── src/
│   ├── pipeline.py           # ★ 메인 파이프라인 오케스트레이터
│   │                         #   process_single/batch/with_refinement
│   │                         #   _evaluate_independent(): 원본+결과 2장 비교 독립평가
│   │                         #   _gemini_add_shadow/_grok_add_shadow: AI 그림자 생성
│   │                         #   preview_prompt_fix/preview_shadow_only/apply_prompt_and_regenerate
│   ├── analyzer/
│   │   ├── vision_client.py      # Claude Vision API
│   │   ├── openai_vision_client.py  # OpenAI GPT-4o Vision
│   │   ├── gemini_vision_client.py  # Gemini Vision (재시도+부분응답복구)
│   │   ├── grok_vision_client.py    # Grok (xAI) Vision API
│   │   ├── result_parser.py  # EditInstruction 데이터클래스 + JSON 파싱
│   │   └── prompt_builder.py # 프롬프트 조립
│   ├── photoroom/
│   │   └── client.py         # Photoroom API v2/edit (배경제거+그림자)
│   ├── claid/
│   │   └── client.py         # Claid.ai API (HDR/선명도 보정)
│   ├── removebg/
│   │   └── client.py         # remove.bg API (배경 제거 전용)
│   ├── opencv_enhance/
│   │   └── enhancer.py       # OpenCV 로컬 보정 (CLAHE/Unsharp Mask/LAB/HSV)
│   ├── sam/
│   │   └── client.py         # SAM/MobileSAM 그림자 추출 (모델 삭제됨)
│   ├── exporter/
│   │   ├── optimizer.py      # JPEG 최적화
│   │   └── namer.py          # 파일명 생성
│   └── utils/
│       ├── category.py       # 카테고리 관리
│       ├── image_io.py       # 이미지 I/O
│       └── logger.py         # 로깅
├── requirements.txt          # 의존성 (PySide6 포함)
└── .env                      # API 키 (7개: PHOTOROOM, CLAID, ANTHROPIC, OPENAI, GEMINI, REMOVEBG, XAI)
```

---

## 개발 히스토리 (시간순)

### Phase 1: 기본 파이프라인 구축
- tkinter GUI 3탭 구조 (실행 / 프롬프트 편집 / 설정)
- RemoveBG API 연동 → 배경 제거
- Claude Vision API 연동 → 이미지 분석 및 보정값 도출
- OpenCV 기반 밝기/대비/선명도 보정
- 860×860 캔버스 피팅 + JPEG 최적화
- 카테고리별 여백(padding) 시스템

### Phase 2: 그림자 추출 시스템 (8회+ 반복 수정)
**문제:** 배경 제거 후 상품이 공중에 뜬 느낌 → 원본 그림자를 보존해야 함

1. **초기 구현** — 원본 이미지에서 어두운 영역을 그림자로 추출
2. **이격 문제** (전경-그림자 사이 흰 틈)
   - erode/dilate 마스크 조합 시도 → 실패
   - blend_mask 조정 시도 → 실패
   - **해결: shadow-under, foreground-on-top 알파 합성** → 마스크 기반 로직 제거
3. **밝은 상품 오탐지** (가방 자체를 그림자로 인식)
   - **해결: 배경 밝기 자동 측정** → `bg_level - 30` 이상 어두운 것만 그림자
4. **비네팅/가장자리 아티팩트**
   - edge_mask 시도 → 부족
   - **해결: 수직 방향 제한** → 피사체 하단 65% 아래만 그림자 허용
5. **경계 윤곽 그림자** (누끼 테두리에 얇은 그림자)
   - dilation 시도 → 흰 틈 발생
   - **해결: distanceTransform + min_shadow_dist=3px 데드존**
6. **그림자 강도 조절**
   - 사람 편집 참고로 약하게 조정 (multiplier 1.5, cap 0.6) → 너무 연함
   - multiplier 2.2, cap 0.85 → 아직 부족
   - **현재: multiplier 3.0, cap 0.9** ← 테스트 중

**최종 그림자 알고리즘:**
```
1. 배경 밝기 추정 (bg_level = median of bright bg pixels)
2. shadow_threshold = bg_level - 30
3. shadow_raw = clip((threshold - gray) / 60, 0, 1)
4. distanceTransform으로 피사체와의 거리 계산
5. 3px 이내 데드존 제거 (경계 아티팩트 방지)
6. 피사체 하단 65% 아래만 그림자 허용
7. morphology 노이즈 제거 + 가우시안 블러
8. 그림자 레이어 아래, 전경 레이어 위로 알파 합성
```

### Phase 3: 품질 보정 강화
**문제:** 프로그램 결과물이 사람 편집보다 평면적이고 밋밋함

원본 ↔ 사람편집 이미지 5쌍을 비교 분석하여 차이점 도출:
- **Clarity (질감강화)**: 대형 반경 unsharp mask로 로컬 콘트라스트 향상
- **Tone Curve (톤커브)**: LAB L채널에 sigmoid S커브 적용
  - shadow_lift: 어두운 부분 밝힘
  - highlight_compress: 밝은 부분 억제
  - midtone_contrast: 중간톤 대비 강화

**기본 보정값 (settings.yaml):**
| 항목 | 값 | 설명 |
|------|-----|------|
| brightness | 8 | 약간 밝게 |
| contrast | 13 | 대비 강화 |
| sharpness | 135 | 선명도 35% 증가 |
| clarity | 0.45 | 질감 강화 |
| tone_shadow_lift | 10 | 그림자 밝힘 |
| tone_highlight_compress | 8 | 하이라이트 억제 |
| tone_midtone_contrast | 0.35 | 중간톤 대비 |

### Phase 4: 다중 이미지 카테고리 감지
- 1장 → 3장 → **5장** 동시 전송으로 카테고리 인식률 향상
- `_collect_sibling_images()`: 같은 폴더에서 최대 5장 수집, 1024px로 리사이즈
- 배치 처리 시 첫 이미지에서만 카테고리 감지 → 나머지에 적용

### Phase 5: 디테일컷 자동 인식
- Claude Vision API가 `is_detail_cut` 필드 반환
- 전체 상품이 아닌 부분 촬영 → 디테일컷으로 판별
- 디테일컷: 정사각 중앙 크롭 + 5px 여백

### Phase 6: 다중 피사체 분리
**문제:** RemoveBG가 주변 오브젝트도 함께 남김 → 메인 상품이 작게 나옴

**해결:** `_isolate_main_subject()`
- alpha 채널에서 `cv2.findContours`로 연결 컴포넌트 분리
- 면적 최대 컨투어만 유지, 나머지 알파 0으로
- 결과: 메인 상품만 적절한 크기로 중앙 배치

### Phase 7: GUI 개선
- **폴더 열기** 버튼: 입력/출력 폴더 옆에 `os.startfile()` 호출
- **그림자 슬라이더** 초기값 버그 수정: `ttk.Scale`에 `.set()` 명시 호출
- **기본 보정값 UI**: 설정탭에 7개 항목 2열 레이아웃 + settings.yaml 저장/로드
- **분석 로그**: 디테일컷 여부 표시

### Phase 8: Photoroom + Claid.ai 파이프라인 마이그레이션
**동기:** RemoveBG+OpenCV 대비 더 나은 배경 제거, 자동 그림자 생성, AI 색보정

1. **RemoveBG → Photoroom API** 교체
   - 배경 제거 + AI 그림자 합성을 단일 API로 처리
   - `shadow.mode: ai.soft`로 자연스러운 접지 그림자 자동 생성
   - `outputSize: originalImage`로 원본 해상도 유지 (품질 보존 핵심)
2. **OpenCV 보정 → Claid.ai API** 교체
   - HDR + 선명도 AI 보정 (수동 톤커브/Clarity 불필요)
   - 유형별 설정: full(hdr20/sharp15), detail(hdr15/sharp10), worn(hdr10/sharp5)
3. **후처리 시스템 개발** (pipeline.py `_clean_and_recenter_bytes`)
   - 불투명 모드 (그림자 있음): BFS 컴포넌트 분석 + 제품 기준 스케일링
   - 투명 모드 (그림자 없음): alpha 기반 아티팩트 제거 + 중앙 배치
   - RGBA이지만 투명 픽셀 없으면 자동으로 불투명 모드 전환
4. **settings.yaml 통합**: Photoroom/Claid 파라미터를 설정 파일에서 관리
5. **GUI 개선**: 단일 이미지 파일 선택 기능 추가
6. **10MB 제한 대응**: Claid.ai 전달 시 PNG→JPEG 자동 변환

**해결한 주요 이슈:**
- Photoroom 402 → 유료 API 키 (Basic $0.02/img)
- 상단 아티팩트 → BFS 연결 컴포넌트로 가장 큰 그룹만 제품 인식
- 제품 크기 작음 → 제품 본체 기준 스케일링 (그림자 영역 제외)
- 그림자 노이즈 → 투명 PNG 대신 흰배경 합성 (`background.color: FFFFFF`)

---

## 환경 설정 (다른 컴퓨터에서 시작하기)

### 1. 필수 소프트웨어
- Python 3.10+ (Windows)
- Git

### 2. 프로젝트 클론 및 의존성 설치
```bash
cd D:\CLAUDE_CODE_WORK
git clone <repo-url> shop-image-editor
cd shop-image-editor
pip install -r requirements.txt
```

### 3. API 키 설정
`.env` 파일을 프로젝트 루트에 생성:
```
PHOTOROOM_API_KEY=여기에_포토룸_API_키
CLAID_API_KEY=여기에_클레이드_API_키
ANTHROPIC_API_KEY=여기에_앤트로픽_키
REMOVEBG_API_KEY=여기에_리무브BG_API_키
OPENAI_API_KEY=여기에_오픈AI_API_키
GEMINI_API_KEY=여기에_제미니_API_키
```
또는 GUI 설정탭에서 API 키 입력 가능.

**Photoroom API**: https://www.photoroom.com/api — Basic $0.02/img, Plus $0.10/img
**Claid.ai API**: https://www.claid.ai — 별도 요금제
**remove.bg API**: https://www.remove.bg/api — 무료 50장/월, 유료 요금제
**OpenAI API**: https://platform.openai.com — GPT-4o Vision
**Google Gemini API**: https://ai.google.dev — Gemini Vision

### 4. 실행
```bash
# GUI 실행
python gui.py

# CLI 실행
python main.py process <이미지경로>
python main.py batch <폴더경로>
```

---

### Phase 9: 그림자 개선 + API 옵션 GUI + 중앙 정렬
**동기:** 그림자 자연스러움 개선, API 옵션을 코드 수정 없이 GUI에서 직접 조절

1. **그림자 시스템 개선 시도**
   - Photoroom `ai.soft` → `ai.hard` → `ai.floating` 등 다양한 모드 테스트
   - `shadow.opacity` 파라미터 추가로 강도 제어
   - 프로그래밍 방식 그림자(`_add_ground_shadow`) 개발 (탑다운 실루엣 기반)
   - 최종: Photoroom `ai.soft` + `shadow.opacity: 0.01`로 복귀 (GUI에서 조절 가능)

2. **중앙 정렬 완전 수정**
   - 기존: product-center + clamp → 그림자 비대칭 시 한쪽으로 편향
   - 최종: 큰 임시 캔버스에 제품 중심 배치 → 최종 크기로 크롭
   - 음수 좌표 문제 해결, 클램프 없이 정확한 중앙 배치

3. **API 옵션 GUI 추가** (Phase의 핵심)
   - 설정탭에 **Photoroom API 옵션** 섹션 추가
     - shadow.mode (none/ai.soft/ai.hard/ai.floating)
     - shadow.opacity (0~1)
     - padding, outputSize
   - 설정탭에 **Claid.ai API 옵션** 섹션 추가
     - 유형별(full/detail/worn/package) 4열 그리드
     - hdr, sharpness, exposure, saturation, contrast
   - 모든 옵션에 **한글 툴팁** 표시 (마우스 호버)
   - 각 섹션별 "설정 저장" 버튼 → settings.yaml에 즉시 반영

4. **GUI 개선**
   - 단일 파일 선택 시 "폴더 열기" → 파일의 부모 폴더 열림
   - ToolTip 클래스 추가 (마우스 호버 → 옵션 설명 표시)

5. **Photoroom 클라이언트 개선**
   - `shadow.opacity` 파라미터 지원 추가
   - settings.yaml에서 값 읽어 API에 전달

**해결한 주요 이슈:**
- 제품 오른쪽 치우침 → 임시 큰 캔버스 방식으로 정확한 중앙 배치
- 그림자 반사 효과 → shadow_limit 축소 (10%) + opacity 제어
- API 옵션 변경마다 코드 수정 필요 → GUI 설정 메뉴로 해결
- Claid HDR이 프로그래밍 그림자를 날림 → 순서 변경 (Claid 이후 그림자)

**현재 settings.yaml 설정값 (사용자 조정):**
```yaml
photoroom.full:
  shadow.mode: ai.soft
  shadow.opacity: 0.01
  padding: 0.01
claid.full:
  hdr: 20, sharpness: 10, exposure: 20, saturation: 5, contrast: 5
```

### Phase 10: 멀티 프로바이더 파이프라인 + 누끼 합성 그림자
**동기:** Photoroom vs remove.bg, Claid vs OpenCV 품질/비용 비교 테스트 필요. 그림자도 API 의존 대신 원본 그림자 추출 방식 도입.

1. **remove.bg 클라이언트 추가** (`src/removebg/client.py`)
   - `https://api.remove.bg/v1.0/removebg` REST API 연동
   - `X-Api-Key` 헤더 인증, `REMOVEBG_API_KEY` 환경변수
   - size(auto/preview/full), type(product/person/car) 옵션 GUI 설정
   - Photoroom과 동일한 인터페이스: `process()`, `should_process()`, `_call_api()`

2. **OpenCV 로컬 보정 엔진** (`src/opencv_enhance/enhancer.py`)
   - Claid.ai API 대체용 로컬 무료 보정
   - 5단계 처리: HDR(CLAHE) → 노출(LAB L-channel) → 대비(PIL Contrast) → 채도(HSV S-channel) → 선명도(Unsharp Mask)
   - exposure/saturation/contrast: 0=변화 없음 (-100~100 범위)
   - hdr/sharpness: 0-100 범위
   - 유형별(full/detail/worn/package) 개별 설정 가능

3. **프로바이더 전환 시스템**
   - `settings.yaml` `providers` 섹션: background_removal, enhancement, shadow 각각 선택
   - `pipeline.py`: `_bg_provider`, `_enhance_provider`, `_shadow_provider`로 분기
   - `_call_bg_removal()` 헬퍼: Photoroom/removebg 라우팅
   - GUI **메인 실행 화면**에 라디오 버튼으로 즉시 전환 (설정탭에도 동일 표시)
   - StringVar 공유: 메인탭과 설정탭이 동일 변수 참조

4. **누끼 합성 그림자 방식** (`_preserve_natural_shadow`)
   - 기존 마스크 확장 방식 → 어색한 결과 → OpenCV 추출+합성으로 전면 교체
   - 알고리즘:
     1. 배경제거 결과(투명 PNG)에서 alpha 마스크 추출
     2. 원본 이미지 가장자리에서 배경색 추정
     3. 제품 마스크 dilate → 제품 영역 제외
     4. 배경색보다 threshold만큼 어두운 픽셀 = 그림자 후보
     5. search_top/bottom/sides로 탐색 영역 제한
     6. 그림자 강도 계산 + gaussian blur 적용
     7. 흰 배경 + 그림자 레이어(multiply) + 누끼 제품 합성
   - 7개 파라미터 GUI 조절 가능 (`shadow_extract` 섹션)

5. **그림자 3방식 선택 (GUI)**
   - **API 그림자** (`api_shadow`): Photoroom shadow.mode/opacity 사용
   - **누끼 합성** (`opencv_extract`): 원본에서 그림자 추출 → 합성
   - **없음** (`none`): 그림자 처리 안 함
   - API 그림자 + removebg 조합 시 GUI 경고 표시

6. **누끼 합성 그림자 파라미터** (설정탭, 7개 항목 + 한글 툴팁)
   | 파라미터 | 기본값 | 설명 |
   |---------|--------|------|
   | opacity | 70% | 그림자 진하기 |
   | threshold | 5 | 그림자 감지 임계값 |
   | blur | 3.0 | 가우시안 블러 |
   | search_top | 5% | 상단 탐색 범위 |
   | search_bottom | 60% | 하단 탐색 범위 |
   | search_sides | 30% | 좌우 탐색 범위 |
   | mask_expand | 2.5% | 누끼 경계 확장 |

7. **Claude Vision 분석 확장**
   - `shadow_direction` 필드 추가 (bottom, bottom-left, bottom-right, left, right)
   - `needs_shadow` 필드 추가 (탑다운 촬영 시 false)
   - `result_parser.py` EditInstruction에 `shadow_direction: Optional[str]` 추가

**해결한 주요 이슈:**
- 마스크 확장 그림자 어색함 → OpenCV 추출+합성으로 전면 교체
- removebg 누끼가 photoroom보다 우수한 경우 있음 → 프로바이더 선택으로 해결
- OpenCV 보정 값 매핑 오류 (기본값 50=변화) → 0-based 매핑으로 수정
- 프로바이더 StringVar 중복 생성 → 공유 변수로 통합
- 그림자 추출 기본값 과공격적 → GPT 분석 기반 최적값 적용

### Phase 11: Vision 멀티 프로바이더 + 그림자 레벨 보정 알고리즘
**동기:** Vision API를 Claude 외 ChatGPT/Gemini로도 전환 가능하게. 그림자 추출 알고리즘이 부드러운 그라데이션 그림자를 놓치는 문제 근본 해결.

1. **Vision API 프로바이더 시스템** (Claude / ChatGPT / Gemini)
   - `src/analyzer/openai_vision_client.py` — OpenAI GPT-4o Vision 클라이언트
   - `src/analyzer/gemini_vision_client.py` — Google Gemini Vision 클라이언트
   - `pipeline.py`: `_vision_provider` 추가, `_get_vision_client()` 메서드로 claude/chatgpt/gemini 분기
   - 프로바이더별 설정: `api`(claude), `openai`(chatgpt), `gemini` 섹션 in settings.yaml
   - `max_tokens` 1024 → 2048 증가 (shadow_params로 응답 길어짐)
   - 로그 메시지에 정확한 프로바이더명 표시 (e.g., "Gemini Vision API 호출 중")

2. **GUI 변경**
   - 메인 실행탭: Vision 프로바이더 라디오 버튼 (Claude / ChatGPT / Gemini) 추가
   - 설정탭: OPENAI_API_KEY 입력 + OpenAI 모델 선택 (gpt-4o 등)
   - 설정탭: GEMINI_API_KEY 입력 + Gemini 모델 선택 (gemini-2.5-flash 등)
   - API 키 저장/토글 메서드 (OpenAI, Gemini용)
   - `_run()` 메서드에서 선택된 Vision 프로바이더의 API 키 유무 검증

3. **그림자 추출 알고리즘 — 레벨 보정 방식으로 완전 재작성**
   - OLD: threshold 기반 이진 감지 (배경보다 threshold만큼 어두운 픽셀 = 그림자)
     - 문제점: 부드러운 그라데이션 그림자를 완전히 놓침
   - NEW: 레벨 보정 방식 (Gemini 추천)
     1. 원본에서 제품 제거 (soft mask로 배경색 채움)
     2. 레벨 보정: `pixel / bg_color * 255` (배경→흰색, 그림자→그라데이션 보존)
     3. search region 제한 + edge fadeout
     4. opacity 블렌딩 (순백색과 혼합)
     5. threshold는 노이즈 정리용만 (거의 흰색 → 순백색)
     6. 제품을 위에 알파 합성
   - **핵심 인사이트:** 그림자를 "감지"하지 말고, 그림자가 아닌 것을 제거하고 나머지 보존

4. **Vision API 그림자 파라미터 추천**
   - `prompts.yaml`에 `shadow_params` 필드 추가
   - Vision API가 이미지별 최적 그림자 추출 파라미터 추천
   - `result_parser.py` EditInstruction에 `shadow_params: Optional[dict]` 추가
   - 파이프라인에서 AI 추천값과 GUI 설정값 머지 (AI 값 우선)

5. **Truncated JSON Recovery**
   - `result_parser.py`에 방법 4 추가: 잘린 JSON 복구 (닫히지 않은 중괄호 자동 닫기)

6. **의존성 추가** (`requirements.txt`)
   - `openai>=1.0.0` (OpenAI GPT-4o Vision)
   - `google-genai>=1.0.0` (Google Gemini Vision)

**settings.yaml 새 섹션:**
```yaml
providers:
  vision: claude  # claude / chatgpt / gemini

openai:
  model: gpt-4o
  max_tokens: 2048
  temperature: 0.1

gemini:
  model: gemini-2.5-flash
  max_tokens: 2048
  temperature: 0.1
```

**해결한 주요 이슈:**
- 부드러운 그림자 놓침 → 레벨 보정 방식으로 근본 해결
- Vision API 단일 프로바이더 의존 → 3개 프로바이더 전환 가능
- max_tokens 부족으로 JSON 잘림 → 2048 증가 + truncated JSON recovery
- 프로바이더별 API 키 검증 → GUI _run()에서 사전 체크

### Phase 12: 애니메이션 기능 제거 + SAM 그림자 + Gemini 생성형 그림자
**동기:** 불필요한 기능(타이핑 애니메이션, 비디오 내보내기, 아바타) 제거. SAM 기반 그림자 추출과 Gemini 이미지 편집 API 그림자 생성 추가.

1. **애니메이션 기능 완전 제거**
   - 타이핑 애니메이션, 비디오 내보내기, 아바타 설정 UI 삭제
   - `src/video/` 디렉토리 삭제 (avatars.py, exporter.py, __init__.py)
   - settings.yaml에서 `deliberation_effects` 섹션 제거
   - `✓` 문자 → `(OK)` 변경 (cp949 인코딩 오류 해결)

2. **SAM 그림자 추출 클라이언트** (`src/sam/client.py`)
   - MobileSAM (40.7MB, CPU 3~5초)
   - SAM VIT-B (375MB, CPU 10~30초 / GPU 2~5초)
   - GPU 자동 감지 (CUDA + VRAM 체크)
   - 그림자 프로바이더 선택지: sam_mobile / sam_cpu / sam_gpu

3. **Gemini 생성형 그림자** (`pipeline.py → _gemini_add_shadow()`)
   - Gemini 이미지 편집 API (gemini-3.1-flash-image-preview)로 그림자 생성
   - 원본 이미지를 참고하여 그림자 방향/농도 재현
   - 보정 전/후 생성 순서 선택 가능 (GUI 라디오 버튼)
   - 프롬프트 3개: 원본 참고, 그림자 생성(메인), 원본 삽입문
   - `{has_original}` 치환자로 원본 유무에 따라 프롬프트 동적 구성

### Phase 13: 의류 처리 개선 + 크롭 완료 모드 + API 비용 절감
**동기:** 의류(마네킹/행거) 이미지의 배경제거 스킵 버그와 그림자 오판 수정. 이미 크롭된 이미지 처리 모드 추가. Vision API 참고 이미지 수 축소.

1. **배경제거 스킵 버그 수정** (`photoroom/client.py`, `removebg/client.py`)
   - `should_process()` 메서드가 `worn` 유형을 처리 대상에서 누락
   - 의류 착용샷도 배경제거가 필요하므로 `worn` → True 반환으로 수정

2. **의류 그림자 fallback 수정** (`pipeline.py`)
   - OpenCV가 마네킹 밝기 차이를 그림자로 오감지 → 강제 그림자 처리
   - `_is_clothing_no_shadow` 조건 추가: worn 유형 + AI 판단 그림자 불필요 시 OpenCV 감지 무시
   - AI 분석 프롬프트에 의류 그림자 판단 기준 상세 추가

3. **크롭 완료 이미지 모드** (`var_pre_cropped` 체크박스)
   - 이미 외부에서 크롭한 이미지를 입력할 때 사용
   - 크롭/여백/중앙정렬 건너뛰고 누끼 + 보정 + 그림자만 수행
   - `process_single()`, `process_batch()`, `analyze_only()` 등에 `pre_cropped` 파라미터 추가
   - 디테일컷 크롭도 pre_cropped 모드에서 스킵

4. **Vision API 참고 이미지 축소** (5장 → 2장)
   - `_ref_count = 1 if pre_cropped else 2`
   - 크롭 완료 모드는 1장만 사용하여 API 비용 추가 절감

### Phase 14: 마네킹 잔여물 자동 감지 + Gemini 그림자에서 제거 (2026-04-01)
**동기:** remove.bg 배경제거 후 의류 하단에 마네킹/스탠드 잔여물이 남는 문제. Gemini 그림자 생성 시 마네킹 제거를 함께 수행하도록 조건부 프롬프트 시스템 구축.

1. **AI 비전 분석에 마네킹 감지 필드 추가**
   - `has_mannequin: bool` — 마네킹/토르소/스탠드가 보이면 true
   - `mannequin_position: str` — "bottom" | "full" | "none"
   - `EditInstruction` 데이터클래스에 필드 추가 (`result_parser.py`)
   - `prompts.yaml` 분석 프롬프트에 JSON 필드 정의 추가

2. **Gemini 그림자 — 마네킹 모드 (원본 이미지 직접 전송)**
   - **핵심 설계:** 마네킹 감지 시 remove.bg 누끼 대신 **원본 이미지를 Gemini에 직접 전송**
   - Gemini가 원본에서 배경제거 + 마네킹 제거 + 그림자 생성을 한 번에 처리
   - 이유: remove.bg 누끼에 남은 마네킹 잔여물을 우회하기 위함
   - 일반 상품: 기존처럼 누끼 이미지 + `{mannequin_removal}` 빈 문자열
   - `_gemini_add_shadow()` 시그니처에 `has_mannequin: bool` 파라미터 추가

3. **마네킹 전용 풀 프롬프트** (`mannequin_full_prompt`)
   - 원본 이미지를 받아서 배경제거+마네킹 제거+그림자를 한 번에 지시
   - GUI 설정탭에서 편집 가능 ("마네킹 전용:" 필드)
   - 기본값: 배경→흰색, 마네킹→완전 제거, 마감선→자연스럽게 복원, 그림자→접지 그림자

4. **의류 no-shadow 예외 vs 마네킹 강제 활성화 버그 수정**
   - **버그:** AI가 의류(worn)를 `needs_shadow=false`로 판단 → 의류 예외 로직에서 존중
     → Gemini 그림자 블록이 아예 실행되지 않음 → 마네킹 제거 불가
   - **수정:** `_mannequin_force` 조건 추가 — `has_mannequin + gemini_shadow` 조합 시
     의류 no-shadow 예외보다 **마네킹 제거가 우선**하여 `needs_shadow=true` 강제 활성화
   - 우선순위: 마네킹 강제 > 의류 예외 > OpenCV fallback > 생성형 그림자 기본

5. **GUI 프롬프트 필드 구성** (설정 → Gemini AI 그림자 프롬프트)
   | # | 필드명 | 용도 |
   |---|--------|------|
   | 1 | 원본 참고 | 원본 이미지 전송 시 그림자 방향/농도 참고 지시 |
   | 2 | 그림자 생성 | 일반 상품 누끼 → 그림자 추가 메인 프롬프트 (`{has_original}`, `{mannequin_removal}` 치환) |
   | 3 | 원본 삽입문 | `{has_original}` 위치에 삽입되는 문구 |
   | 4 | 마네킹 삽입문 | `{mannequin_removal}` 위치에 삽입 (경미한 잔여물용) |
   | 5 | 마네킹 전용 | ★ 원본 이미지 직접 전송용 풀 프롬프트 (배경제거+마네킹 제거+그림자 한 번에) |

6. **settings.yaml 프롬프트 키 구조**
   ```yaml
   gemini_shadow:
     ref_prompt: 원본 참고 프롬프트
     main_prompt: 일반 그림자 생성 프롬프트 ({mannequin_removal}, {has_original} 치환자 포함)
     orig_insert: 원본 있을 때 삽입문
     mannequin_prompt: 마네킹 삽입문 (경미한 잔여물)
     mannequin_full_prompt: ★ 마네킹 전용 풀 프롬프트 (원본→Gemini 직접 전송)
     order: after_enhance
   ```

**동작 흐름 (마네킹 의류):**
```
1. Vision AI 분석 → image_type=worn, has_mannequin=true, needs_shadow=false
2. Pipeline 그림자 판정:
   - _is_clothing_no_shadow=true (의류+AI 판단 그림자 불필요)
   - _mannequin_force=true (마네킹 감지+생성형 그림자)
   - → 마네킹 강제 활성화가 우선 → needs_shadow=true
3. remove.bg 배경제거 실행 (마네킹 잔여물 남을 수 있음)
4. Gemini 호출 시 마네킹 모드 활성화:
   - 누끼 이미지 대신 ★원본 이미지를 메인으로 전송
   - mannequin_full_prompt 사용 (배경제거+마네킹 제거+그림자 한 번에)
5. Gemini 결과 → 마네킹 없이 깔끔한 의류 + 자연스러운 그림자
```

**동작 흐름 (일반 상품 — 가방, 신발 등):**
```
1. Vision AI 분석 → has_mannequin=false, needs_shadow=true
2. 기존 로직 그대로 동작
3. Gemini에 누끼 이미지 전송 + main_prompt (치환자 빈 문자열)
```

**수정된 파일:**
| 파일 | 변경 내용 | 열어야 할 위치 |
|------|----------|---------------|
| `src/analyzer/result_parser.py` | `has_mannequin`, `mannequin_position` 필드 + 파싱 | L27-28 (dataclass), L144-145 (_to_instruction) |
| `config/prompts.yaml` | 분석 프롬프트에 마네킹 감지 JSON 필드 추가 | L28 부근 (`has_mannequin` 필드 정의) |
| `src/pipeline.py` | ★ 핵심 — 마네킹 강제 활성화 + 원본 전송 모드 | L1235-1260 (그림자 판정), L1536-1650 (_gemini_add_shadow) |
| `gui.py` | 프롬프트 필드 6개 (ref/main/orig/mannequin/mannequin_full) | L1264-1310 (prompt_items), L2134-2195 (save/reset) |
| `config/settings.yaml` | `mannequin_prompt` + `mannequin_full_prompt` 키 | L128-148 (gemini_shadow 섹션) |

**해결한 주요 이슈:**
- remove.bg 누끼에 마네킹 잔여물 → 원본 이미지를 Gemini에 직접 전송하여 우회
- 의류 no-shadow 예외가 Gemini 호출 자체를 차단 → 마네킹 강제 활성화 조건 추가
- 하드코딩된 프롬프트(파타고니아 재킷) → 범용 치환자 + 마네킹 전용 프롬프트 분리

---

## 다른 PC에서 작업 이어가기

### 열어야 할 핵심 파일 (우선순위순)

1. **`src/pipeline.py`** — 메인 파이프라인 오케스트레이터 (~1500줄)
   - `process_single()` (L1192~): 단일 이미지 전체 처리 흐름
   - 그림자 판정 로직 (L1225~1260): `_mannequin_force`, `_is_clothing_no_shadow`
   - `_gemini_add_shadow()` (L1536~): 마네킹 모드 원본 전송 / 일반 모드 누끼 전송
   - `_preserve_natural_shadow()`: OpenCV 그림자 추출

2. **`gui.py`** — tkinter GUI (~2200줄, 라이트 테마)
   - Gemini 그림자 프롬프트 UI (L1238~1310): 6개 텍스트 필드
   - save/load/reset (L2134~2195): settings.yaml 연동

3. **`src/analyzer/result_parser.py`** — AI 분석 결과 파싱
   - `EditInstruction` 데이터클래스: `has_mannequin`, `mannequin_position` 등 20+ 필드

4. **`config/settings.yaml`** — 모든 설정값
   - `providers`: vision/background_removal/enhancement/shadow 프로바이더
   - `gemini_shadow`: 프롬프트 6개 키 (ref/main/orig/mannequin/mannequin_full/order)

5. **`config/prompts.yaml`** — AI 비전 분석 프롬프트
   - `analysis.user_template`: JSON 스키마 정의 (has_mannequin 등)

### 현재 설정 상태
```yaml
providers:
  vision: gemini
  background_removal: removebg
  enhancement: claid
  shadow: gemini_shadow        # ★ 마네킹 제거 기능은 이 모드에서만 동작
```

### 테스트 필요 사항
- [ ] 마네킹 의류 이미지로 Gemini 마네킹 모드 테스트 (원본 전송 확인)
- [ ] 일반 상품(가방/신발)은 기존 동작 유지되는지 확인
- [ ] GUI에서 "마네킹 전용" 프롬프트 수정 → 저장 → 반영 확인
- [ ] 병렬 배치 처리 (미구현, 논의됨)

### Phase 15: 병렬 처리 + API 재시도 로직 (2026-04-02)
**동기:** 다수 파일(20장+) 처리 시 순차 처리는 너무 느림. 또한 병렬 호출 시 API 429 Rate Limit 오류가 빈번 발생.

1. **멀티파일 병렬 처리 (ThreadPoolExecutor)**
   - GUI 동시처리 갯수 선택: `[1, 2, 4, 8]` (콤보박스, 툴팁: "2~4 권장")
   - 파일 모드(`single`): 다중 파일 선택 → ThreadPoolExecutor로 병렬 실행
   - 배치 모드(`batch`): 폴더 내 파일 → 같은 병렬 패턴
   - **스레드 안전성**: 각 스레드마다 별도 `ImageEditPipeline` 인스턴스 생성
   - `threading.Lock`으로 성공/실패 카운터 보호
   - 취소 버튼으로 진행 중 작업 중단 가능
   - **성공 판정**: `result.get("files", [])` 체크 (`"success"` 키 없음 주의)

2. **API 재시도 로직 (Exponential Backoff + Jitter)**
   - **Claid.ai** (`src/claid/client.py`): max 3회, 429/500/502/503에서 재시도
   - **remove.bg** (`src/removebg/client.py`): 동일 패턴
   - **Photoroom** (`src/photoroom/client.py`): 동일 패턴
   - 대기: `(2^attempt) + random.uniform(0, 1)` (Thundering Herd 방지)
   - `files` dict를 매 시도마다 재생성 (requests.post가 파일 객체를 소비하므로)

**수정된 파일:**
| 파일 | 변경 내용 |
|------|----------|
| `gui.py` | 동시처리 콤보박스 [1,2,4,8], `_run_worker` ThreadPoolExecutor 패턴, Lock 기반 카운터 |
| `src/claid/client.py` | `_call_api` 재시도 루프 (3회, exponential backoff) |
| `src/removebg/client.py` | 동일 재시도 패턴 |
| `src/photoroom/client.py` | 동일 재시도 패턴 |

---

### Phase 16: 디테일컷 + 손/장갑 감지 핸들링 (2026-04-02)
**동기:** 럭셔리 상품 촬영에서 흰 장갑을 끼고 가방 내부를 보여주는 디테일 사진 처리. 손이 피사체로 인식되어 여백이 잘못 잡히고, 불필요한 그림자가 생성되는 문제.

**핵심 규칙:**
- 손/장갑으로 상품을 잡고 있으면 → `detail` + `has_human_hand=true`
- 디테일컷은 **항상** 그림자 비활성화
- 손 감지 시 → 손 크롭 수행, 여백(padding) 스킵, 그림자 비활성화
- 배경 제거 + 보정(Claid.ai)은 정상 수행

1. **AI 프롬프트 강화** (`config/prompts.yaml`)
   - `detail` 정의에 ★★★ 강조: "사람 손이나 흰 장갑으로 상품을 잡고 있는 사진은 반드시 detail + has_human_hand=true"
   - `has_human_hand`: "★흰 장갑(면장갑)을 낀 손도 반드시 true로 판단"
   - `needs_shadow`: "손/장갑으로 잡고 있으면 반드시 false", "디테일컷(detail) → needs_shadow: false (항상)"

2. **그림자 절대 차단 (`_no_shadow_override` 플래그)** (`src/pipeline.py` ~L1356-1414)
   ```python
   # ★ 사람 손이 감지된 경우 → 그림자 강제 비활성화
   if instruction.has_human_hand:
       needs_shadow = False

   # ★ 디테일컷은 항상 그림자 비활성화
   if is_detail_cut:
       needs_shadow = False

   # ★ 절대 재활성화 방지 플래그
   _no_shadow_override = is_detail_cut or instruction.has_human_hand

   # 마네킹 강제, 실제 그림자, 생성형 그림자 등 모든 재활성화 조건에서 차단
   if _mannequin_force and not needs_shadow and not _no_shadow_override:
       needs_shadow = True
   elif not needs_shadow and has_real_shadow and not _is_clothing_no_shadow and not _no_shadow_override:
       needs_shadow = True
   elif not needs_shadow and _is_generative_shadow and not _no_shadow_override:
       needs_shadow = True
   ```

3. **손 크롭 처리** (`src/pipeline.py`)
   - `_crop_out_hand()`: 손 영역 감지 → 4% 마진으로 크롭 (`hand_margin = int(max(w, h) * 0.04)`)
   - **디테일컷은 Method 2(edge crop)만 사용**: `product_only_region=None if is_detail_cut`
     - 이유: AI의 `product_only_region`이 디테일 사진에서는 너무 타이트함 (내부 로고만 잡아서 가방 본체가 잘림)
   - `_adjust_crop_away_from_hand()`: 손 방향 반대로 4% push (손이 오른쪽이면 왼쪽으로 밀기)
   - `_crop_detail_cut()`: 알파 마스킹으로 손 영역 제외 후 오브젝트 바운드 계산

4. **디테일컷 여백 스킵** (`src/pipeline.py` ~L1567)
   ```python
   elif is_detail_cut:
       _log(f"  디테일컷 → 여백 적용 스킵 (디테일 크롭에서 처리)")
       edit_actions.append(f"{self._bg_provider}: 배경 제거 (디테일컷)")
   ```

**동작 흐름 (손으로 잡은 디테일 사진):**
```
1. Vision AI 분석 → image_type=detail, has_human_hand=true, needs_shadow=false
2. Pipeline:
   - is_detail_cut=true, _no_shadow_override=true
   - → 그림자 절대 비활성화 (어떤 조건에서도 재활성화 불가)
3. 배경 제거 (Photoroom/remove.bg) — 정상 실행
4. 손 크롭 (_crop_out_hand) — edge crop method, 4% 마진
5. 보정 (Claid.ai) — 정상 실행
6. 여백 적용 — 스킵
7. 그림자 — 스킵
8. 결과: 손 제거 + 배경 흰색 + 보정된 상품 디테일
```

**수정된 파일:**
| 파일 | 변경 내용 | 열어야 할 위치 |
|------|----------|---------------|
| `config/prompts.yaml` | detail/has_human_hand/needs_shadow 프롬프트 강화 | `detail` 정의, `has_human_hand` 정의 |
| `src/pipeline.py` | ★ 핵심 — `_no_shadow_override`, 손 크롭, 디테일 여백 스킵 | L1356-1414 (그림자 판정), L1430 (손 크롭 호출), L1567 (여백 스킵) |

**해결한 주요 이슈:**
- 손이 피사체로 인식 → 손 영역 제외 후 오브젝트 바운드 계산
- 디테일컷에 그림자가 계속 생성 → `_no_shadow_override` 플래그로 모든 재활성화 차단
- `product_only_region`이 디테일컷에서 너무 타이트 → 디테일컷은 edge crop만 사용
- 손 크롭 마진 과다/과소 → 4%로 안정화 (10% → 5% → 2% → 4%)
- 흰 장갑을 손으로 인식 못함 → 프롬프트에 "흰 장갑=손" 명시

---

## 다른 PC에서 작업 이어가기

### 열어야 할 핵심 파일 (우선순위순)

1. **`src/pipeline.py`** — 메인 파이프라인 오케스트레이터 (~1700줄)
   - `process_single()` (L1192~): 단일 이미지 전체 처리 흐름
   - 그림자 판정 로직 (L1356~1414): `_no_shadow_override`, `_mannequin_force`, `_is_clothing_no_shadow`
   - 손 크롭 호출 (L1430): `_crop_out_hand()` — 디테일컷은 `product_only_region=None`
   - 디테일컷 여백 스킵 (L1567)
   - `_gemini_add_shadow()` (L1536~): 마네킹 모드 원본 전송 / 일반 모드 누끼 전송
   - `_crop_out_hand()`: hand_margin 4%, edge crop method
   - `_crop_detail_cut()`: 알파 마스킹 손 제외
   - `_adjust_crop_away_from_hand()`: 4% push
   - `_preserve_natural_shadow()`: OpenCV 그림자 추출

2. **`gui.py`** — tkinter GUI (~2700줄, 라이트 테마)
   - 동시처리 콤보박스 (L726 부근): `[1, 2, 4, 8]`
   - `_run_worker` (single/batch): ThreadPoolExecutor 병렬 처리
   - Gemini 그림자 프롬프트 UI (L1238~1310): 6개 텍스트 필드
   - save/load/reset (L2134~2195): settings.yaml 연동

3. **`src/analyzer/result_parser.py`** — AI 분석 결과 파싱
   - `EditInstruction` 데이터클래스: `has_mannequin`, `has_human_hand`, `hand_region`, `product_only_region` 등 20+ 필드

4. **`config/prompts.yaml`** — AI 비전 분석 프롬프트
   - `detail` 정의 (★★★ 강조), `has_human_hand` (흰 장갑 포함), `needs_shadow` (디테일컷/손 규칙)

5. **API 클라이언트 (재시도 로직)**
   - `src/claid/client.py`: `_call_api` 3회 재시도, exponential backoff
   - `src/removebg/client.py`: 동일 패턴
   - `src/photoroom/client.py`: 동일 패턴

6. **`config/settings.yaml`** — 모든 설정값

### 현재 설정 상태
```yaml
providers:
  vision: gemini
  background_removal: removebg
  enhancement: claid
  shadow: gemini_shadow        # ★ 마네킹 제거 기능은 이 모드에서만 동작

# 병렬 처리: GUI에서 1/2/4/8 선택 가능 (2~4 권장)
# API 재시도: 모든 API 클라이언트 3회 재시도 + exponential backoff
```

### 테스트 필요 사항
- [ ] 디테일컷(손/장갑) 이미지 → 그림자 비활성화 + 손 크롭 확인
- [ ] Gemini Vision이 흰 장갑을 `has_human_hand=true`로 분류하는지 확인 (★ 불안정할 수 있음)
- [ ] 병렬 처리 8개 동시 → API 429 오류 재시도 동작 확인
- [ ] 마네킹 의류 이미지로 Gemini 마네킹 모드 테스트
- [ ] 일반 상품(가방/신발)은 기존 동작 유지되는지 확인

---

## 알려진 이슈 / 남은 작업

1. **★ Gemini Vision AI 분류 신뢰성** — 흰 장갑으로 가방을 잡은 사진을 `full`(confidence 0.00)로 분류하는 경우 있음. 프롬프트 강화했지만 AI 분류 실패 가능성 상존. 필요 시 파이프라인 레벨 fallback 감지 로직 고려
2. **마네킹 제거 품질 테스트** — Gemini 원본 전송 모드 실제 의류 이미지로 검증 필요
3. **프로바이더 품질 비교** — Photoroom vs removebg, Claid vs OpenCV, Claude vs ChatGPT vs Gemini A/B 테스트
4. **Vision 프로바이더 응답 차이** — has_mannequin, has_human_hand 필드가 각 프로바이더에서 정확히 반환되는지 모니터링

---

## 핵심 알고리즘 레퍼런스

### 후처리: 불투명 모드 (pipeline.py — Photoroom 그림자 있는 경우)
```python
# Photoroom이 background.color=FFFFFF + shadow.mode로 합성한 결과 처리
# 1. BFS 연결 컴포넌트 분석 (1/4 축소, threshold 240)으로 제품 본체 감지
# 2. 가장 큰 컴포넌트 = 제품, 나머지 아티팩트 무시
# 3. 제품 상단 위: 흰색, 좌우 마진(20%) 밖: 흰색
# 4. 그림자 보호: 제품 아래 10%까지만, 나머지 흰색
# 5. 근백색(>245) 클린업 (그림자 영역 보호)
# 6. 비백색 크롭 → 제품 본체 기준 스케일링
# 7. 큰 임시 캔버스에 제품 중심 배치 → 최종 크기 크롭 (정확한 중앙)
```

### 프로그래밍 접지 그림자 (`_add_ground_shadow` — 현재 비활성)
```python
# Photoroom 그림자 대신 사용 가능한 대안 (코드는 유지, 호출은 비활성)
# 1. 가장자리 10px 중앙값으로 배경색 추정
# 2. 배경색과 30+ 차이나는 픽셀 = 제품
# 3. 제품 하단 30% 실루엣을 시드로 그림자 마스크 생성
# 4. 가우시안 블러로 탑다운 방식 확산
# 5. 제품 위 마스킹 + 강도 15% 적용
# 주의: Claid.ai HDR 이후에 적용해야 HDR이 그림자를 날리지 않음
```

### 후처리: 투명 모드 (pipeline.py — 그림자 없는 경우)
```python
# Photoroom이 투명 PNG로 반환한 결과 처리
# 1. alpha>=128 BFS 컴포넌트 분석으로 제품 감지
# 2. bbox 확장 (상하 25%, 좌우 20%)
# 3. 확장 영역 밖 alpha=0 (아티팩트 제거)
# 4. 노이즈 제거 (alpha < 10 → 0)
# 5. 크롭 전체 기준 스케일링 + 중앙 배치
```

### Photoroom API 설정 (settings.yaml — GUI에서 조절 가능)
```yaml
photoroom:
  full:
    shadow.mode: ai.soft        # GUI: none/ai.soft/ai.hard/ai.floating
    shadow.opacity: 0.01        # GUI: 0~1 (0.01=거의 투명)
    padding: 0.01               # GUI: 여백 비율
    outputSize: originalImage   # GUI: 원본/1000x1000/2000x2000
    export.format: png
  detail_complex:
    padding: 0                  # 디테일컷은 그림자/여백 없음 (고정)
  package:
    shadow.mode/opacity는 full과 동기화
```

### Claid.ai API 설정 (settings.yaml — GUI에서 유형별 조절 가능)
```yaml
claid:
  full:    { hdr: 20, sharpness: 10, exposure: 20, saturation: 5, contrast: 5 }
  detail:  { hdr: 15, sharpness: 10, fit: canvas, background_color: '#FFFFFF' }
  worn:    { hdr: 10, sharpness: 5, fit: bounds }
  package: { hdr: 20, sharpness: 15 }
# exposure, saturation, contrast가 0이 아닐 때만 adjustments에 포함
```

### 누끼 합성 그림자 알고리즘 (`_preserve_natural_shadow` — 레벨 보정 방식)
```python
# Phase 11에서 완전 재작성 — 레벨 보정(Level Correction) 방식
# OLD: threshold 기반 이진 감지 → 부드러운 그라데이션 그림자를 놓침
# NEW: 그림자가 아닌 것을 제거하고 나머지를 보존
#
# 1. 배경제거 결과(투명 PNG)에서 alpha 마스크 → 제품 영역
# 2. 원본에서 제품 제거: soft mask로 배경색 채움 (제품 없는 이미지 생성)
# 3. 레벨 보정: pixel / bg_color * 255
#    - 배경색 픽셀 → 255 (순백색)
#    - 그림자 픽셀 → 원래 그라데이션 비율 보존
# 4. search_top/bottom/sides로 탐색 영역 제한 + edge fadeout
# 5. opacity 블렌딩: 결과를 순백색과 혼합 (그림자 강도 조절)
# 6. threshold: 노이즈 정리용만 (거의 흰색 → 순백색으로 클린업)
# 7. 합성: 레벨 보정된 배경 위에 누끼 제품 alpha composite
#
# Vision API shadow_params: AI가 이미지별 최적 파라미터 추천 → GUI 설정과 머지
```

### OpenCV 보정 알고리즘 (`opencv_enhance/enhancer.py`)
```python
# Claid.ai API 대체 로컬 보정 (5단계 순차 처리)
# 1. HDR: CLAHE (clipLimit=hdr/10, tileGrid=8x8) on LAB L-channel
# 2. Exposure: LAB L-channel offset (value * 0.3)
# 3. Contrast: PIL ImageEnhance.Contrast (1.0 + value/100 * 0.5)
# 4. Saturation: HSV S-channel scale (1.0 + value/100 * 0.5)
# 5. Sharpness: Unsharp Mask (radius=2, amount=value/100*1.5, threshold=0)
# 0 = 변화 없음 (exposure, saturation, contrast)
# alpha 채널 보존
```

### 프로바이더 설정 (settings.yaml)
```yaml
providers:
  background_removal: removebg  # photoroom / removebg
  enhancement: claid             # claid / opencv
  shadow: opencv_extract         # api_shadow / opencv_extract / none
  vision: claude                 # claude / chatgpt / gemini

openai:
  model: gpt-4o
  max_tokens: 2048
  temperature: 0.1

gemini:
  model: gemini-2.5-flash
  max_tokens: 2048
  temperature: 0.1

shadow_extract:  # 누끼 합성 그림자 파라미터 (레벨 보정 방식)
  opacity: 70
  threshold: 8       # 노이즈 정리용 (거의 흰색 → 순백색)
  blur: 3.0
  search_top: 5
  search_bottom: 60
  search_sides: 30
  mask_expand: 2.5

removebg:
  size: auto      # auto / preview / full
  type: product   # product / person / car

opencv_enhance:  # 유형별 보정값
  full:    { hdr: 20, sharpness: 15, exposure: 0, saturation: 0, contrast: 0 }
  detail:  { hdr: 15, sharpness: 10, ... }
  worn:    { hdr: 10, sharpness: 5, ... }
  package: { hdr: 20, sharpness: 15, ... }
```

### GUI API 옵션 메뉴
- **메인 실행탭**: 프로바이더 라디오 버튼 (Vision/배경제거/보정/그림자 각각 선택)
  - Vision: Claude / ChatGPT / Gemini
  - 배경제거: Photoroom / remove.bg
  - 보정: Claid.ai / OpenCV
  - 그림자: API 그림자 / 누끼 합성 / 없음
- 설정탭 → "Photoroom API 옵션" 섹션: 그림자/여백/해상도 직접 조절
- 설정탭 → "Claid.ai API 옵션" 섹션: 유형별 HDR/선명도/노출/채도/대비
- 설정탭 → "OpenCV 보정 옵션" 섹션: 유형별 HDR/선명도/노출/채도/대비
- 설정탭 → "remove.bg 옵션" 섹션: size/type
- 설정탭 → "누끼 합성 그림자 옵션" 섹션: 7개 파라미터 + 한글 툴팁
- 설정탭 → "OpenAI 설정" 섹션: API 키 입력 + 모델 선택 (gpt-4o 등)
- 설정탭 → "Gemini 설정" 섹션: API 키 입력 + 모델 선택 (gemini-2.5-flash 등)
- 모든 옵션에 마우스 호버 시 한글 툴팁 표시
- "설정 저장" 버튼으로 settings.yaml에 즉시 반영 → 다음 처리부터 적용

---

## 2026-04-03 작업 내역

### 1. 디테일컷 배경 제거 수정
**문제:** 디테일 유형 이미지(지갑 펼침 등)에서 배경 제거가 스킵됨
**원인 (3중):**
1. `gui_state.json`에 `pre_cropped: true`가 저장되어 디테일컷 분기 진입 실패
2. `PhotoroomClient.should_process("detail", "clean")` → False 반환 (complex만 허용)
3. `RemoveBgClient.should_process("detail", "clean")` → False 반환 (실제 사용 프로바이더)

**수정:**
- `src/photoroom/client.py:93` — `image_type == "detail"` 이면 background 무관하게 True
- `src/removebg/client.py:76` — 동일하게 수정

### 2. 디테일컷 그림자 AI 판단 존중
**변경:** 상품 전체가 보이는 디테일샷(지갑 펼침)은 그림자 생성 유지
- `pipeline.py:1430-1434` — `is_detail_cut`일 때 무조건 `needs_shadow=False` → AI 판단 존중
- `pipeline.py:1460` — `_no_shadow_override`에서 `is_detail_cut` 제거, `has_human_hand`만 유지

### 3. Gemini 그림자 제품 원형 보호
**문제:** Gemini 이미지 편집 API가 그림자 생성 시 제품 형태/색상을 변형
**해결:** `_protect_product_pixels()` 정적 메서드 추가 (`pipeline.py:1772-1814`)
- 누끼 PNG의 알파 채널을 마스크로 사용
- Gemini 결과 위에 원본 제품 픽셀을 paste → 제품 100% 보존
- 투명/배경 영역만 Gemini의 그림자 출력 사용
- `_gemini_add_shadow()` 내에서 Gemini 응답 수신 직후 호출

### 4. 품질 검증 시스템 (Vision API)
**신규:** 처리 완료 후 자동 품질 검증 — 3항목 체크
- `pipeline.py` — `_validate_result()` 메서드 추가
  - **배경**: 흰색 배경으로 깨끗하게 제거되었는지
  - **그림자**: 자연스러운지 (과도/인공적 여부)
  - **원형보존**: 상품 형태/색상/디테일 변형 없는지
- Vision API(설정된 프로바이더)로 원본 vs 결과 이미지를 비교 분석
- JSON 응답 파싱하여 항목별 pass/fail + 상세 설명 반환
- `process_single()` 완료 후 자동 호출, `validation` 키로 결과 반환
- 스테이지: 7단계 (분석→누끼→보정→그림자→크롭→저장→**검증**)

### 5. 뷰파인더 팝업 다이얼로그
**신규:** 처리 결과를 원본과 1:1 비교하는 팝업 뷰어

**구조:**
```
┌─────────────────────────────────────────────────┐
│ 🔍 뷰파인더 — 처리 결과 비교          ESC로 닫기 │  ← 다크 타이틀바
├──────────┬──────────────────────────────────────┤
│ 처리 현황 │  📷 원본         │  ✨ 처리 결과      │
│          │                  │                   │
│ ✅ file1 │   [Canvas]       │   [Canvas]        │
│ ████████ │                  │                   │
│ ✅배경...│                  │                   │
│          │                  │                   │
│ ⏳ file2 │                  │                   │
│ ████░░░░ │                  │                   │
│ 보정 중..│                  │                   │
│          ├──────────────────┴───────────────────┤
│ ◀이전 1/5│  file1.jpg · 3024×4032 · 2.4MB      │
│   다음▶ │  ✅배경  ✅그림자  ✅원형              │
│          │  ↑↓ 파일이동  ←→ 출력전환  ESC 닫기   │
└──────────┴──────────────────────────────────────┘
```

**기능:**
- 다크 테마 (시안 반영): `#1e1e2e` 배경, 보라색 악센트
- 좌측: 파일 리스트 + 7단계 pip 바 (녹/파/빨/회) + 검증 아이콘
  - 선택 시 좌측 파란 바 표시 (`border-left` 효과)
  - 처리 중: "보정 중..." 텍스트, 대기: 반투명
  - 완료: `✅배경 ✅그림자 ✅원형` 또는 `❌배경` 빨간색
  - 검증 불합격: 파일 아이콘 ⚠️
- 우측: 원본/결과 좌우 비교 (Canvas), 보라색 구분선
- 네비게이션: 키보드(↑↓←→ ESC), 버튼, 마우스 클릭
- 실시간 업데이트: 500ms 폴링으로 처리 중 파일 진행 반영
- 리사이즈 디바운스 150ms
- `status_val_frame` 고정 높이(16px) — 처리 중/완료 전환 시 행 크기 변동 방지

**데이터 흐름:**
1. `_run_worker()` 시작 시 `_viewfinder_pairs=[]`, `_vf_file_stages={}` 초기화
2. 파일 처리 전 `_vf_register_file()` → pair 등록
3. 로그 래퍼 `_vf_make_log()` → 로그 메시지 패턴으로 단계 감지 (`_vf_detect_stage()`)
4. 처리 완료 시 `_vf_complete_file()` → output_files + validation 저장
5. 뷰파인더 팝업에서 500ms마다 `_refresh()` → 새 행 추가 + pip 색상 업데이트

### 6. GUI 상태 영속화
- `gui_state.json`에 체크박스 상태 저장/복원: `skip_analysis`, `pre_cropped`, `auto_refine`, `max_iterations`

### 7. GUI 버튼 스타일
- **재시작** 버튼: 녹색 (`#16a34a`, `Restart.TButton`)
- **뷰파인더** 버튼: 보라색 (`#7c3aed`, `Viewfinder.TButton`)
- 뷰파인더 버튼은 처리 시작 시 활성화 (`state="normal"`)

### 8. 품질 검증 프롬프트 강화 (2026-04-03)
**변경:** 그림자 검증 기준을 대폭 강화하고 재시도 로직 추가

**검증 프롬프트 강화 (`_validate_result`):**
- 기존: "그림자가 자연스러운가?" → 약한 그림자도 합격 처리되는 문제
- 변경 (needs_shadow=True 시):
  - 원본에 그림자가 있었다면 결과물에도 비슷한 강도의 접지 그림자가 있어야 PASS
  - 그림자가 없거나 육안으로 식별 불가능할 정도로 약하면 FAIL
  - 그림자가 원본 대비 과도하게 짙거나 인위적이면 FAIL
  - 그림자의 방향이 원본과 현저히 다르면 FAIL
  - **정면 촬영 규칙**: 피사체를 정면에서 바라보고 촬영된 이미지면 그림자는 피사체 하단에만 있어야 PASS

**그림자 재시도 로직 (`process_single`):**
- 검증 불합격 시 Gemini 그림자만 1회 재시도
- `_pre_shadow_bytes`: 그림자 적용 전 상태를 백업 (before_enhance / after_enhance 양쪽)
- 재시도 후에도 불합격이면 그대로 확정 + 뷰파인더에 불합격 표시
- 재시도는 최대 1회 (무한루프 방지), 그림자 불합격인 경우만

### 9. 검증 프롬프트 YAML 외부화 + GUI 편집기 (2026-04-03)
**변경:** 하드코딩된 검증 프롬프트를 `config/prompts.yaml`로 이동, GUI에서 편집 가능

**`config/prompts.yaml` — validation 섹션 추가:**
```yaml
validation:
  system: |          # AI 역할 정의 (품질 검수 전문가)
  shadow_needed: |   # 그림자 필요 시 판정 기준 (엄격)
  shadow_not_needed: | # 그림자 불필요 시 판정 기준
  user_template: |   # 검증 요청 템플릿 ({image_type}, {shadow_context} 변수)
```

**`gui.py` — 프롬프트 편집 탭에 검증 프롬프트 섹션 추가:**
- `_build_prompt_tab()`: "검증 프롬프트" LabelFrame 추가
  - 시스템 (txt_val_system, 분홍 배경 #fef2f2)
  - 그림자 필요 시 판정 기준 (txt_val_shadow_needed)
  - 그림자 불필요 시 (txt_val_shadow_not_needed)
  - 검증 요청 템플릿 (txt_val_user)
- `_load_prompts()`: validation 섹션 4개 필드 로드
- `_save_prompts()`: validation 섹션 4개 필드 저장
- `_reset_prompts()`: 검증 프롬프트 한글 기본값 복원

**`src/pipeline.py` — `_validate_result()` YAML 연동:**
- 하드코딩된 프롬프트 제거
- 매 검증 호출마다 `config/prompts.yaml` 최신 내용 리로드
- GUI에서 프롬프트 수정 → 저장하면 다음 검증부터 즉시 반영
- fallback: YAML 로드 실패 시 `_prompt_builder._prompts`에서 읽기

---

## Phase 17: Grok (xAI) API 통합 (2026-04-03)

**목적**: xAI Grok API를 Vision 분석 + AI 그림자 생성 두 가지 용도로 추가

### xAI 모델 구조 (테스트 검증 완료)

| 용도 | 모델 | 가격 | 비고 |
|------|------|------|------|
| Vision 분석 | `grok-4-fast-non-reasoning` | - | grok-3 이하는 Vision 미지원 |
| Vision 분석 (대안) | `grok-4-fast-reasoning`, `grok-4-0709` | - | grok-4 계열만 이미지 입력 가능 |
| 그림자 생성 | `grok-imagine-image` | $0.02/장 (~28원) | `/v1/images/edits` JSON 엔드포인트 |
| 그림자 생성 (고품질) | `grok-imagine-image-pro` | $0.07/장 (~98원) | 더 사실적이고 세밀 |

### API 포맷 (자동 테스트로 확인)

**Vision**: OpenAI 호환 `chat.completions.create()` (openai SDK)
**Shadow**: `/v1/images/edits` — JSON (`Content-Type: application/json`), multipart 아님
```json
{
  "model": "grok-imagine-image",
  "prompt": "그림자 프롬프트",
  "image": {"url": "data:image/jpeg;base64,...", "type": "image_url"},
  "n": 1,
  "response_format": "b64_json"
}
```

### 변경 파일

**`src/analyzer/grok_vision_client.py` (신규)**
- OpenAI 호환 형식 (`base_url="https://api.x.ai/v1"`)
- 환경변수: `XAI_API_KEY`, 기본 모델: `grok-4-fast-non-reasoning`
- `analyze_image()` / `analyze_images()` 인터페이스

**`src/pipeline.py`**
- Vision 팩토리에 `grok` 분기 추가 (`_create_vision_client`, `_get_vision_client`, `_get_vision_config`)
- `_is_generative_shadow`에 `grok_shadow` 추가
- Shadow 디스패치에 `grok_shadow` 분기 (before/after enhance 모두)
- `_grok_add_shadow()` — `requests.post()` 직접 HTTP 호출 (OpenAI SDK 미지원)
  - `/v1/images/edits` JSON 엔드포인트, `response_format: b64_json`
  - 마네킹 모드 / 일반 모드 / 원본 참고 분기
- `_call_all_vision_apis()`에 grok 추가
- `_validate_result()` 품질 검증 개선:
  - `max_tokens` 512→8192 (Gemini 2.5 Flash thinking 토큰 소비 문제 해결)
  - 빈 응답 방어 코드 추가
  - 불완전 JSON 복구 로직 (닫는 괄호 보충)
  - `finish_reason` 로깅 추가 (gemini_vision_client.py)

**`gui.py`**
- Tab 1: Vision 라디오에 "Grok", Shadow 라디오에 "Grok" 추가
- 설정 탭: xAI API 키 입력란 + `_save_xai_key()` / `_toggle_xai_key_visibility()`
- 설정 탭: Grok Vision 모델 콤보박스 (`grok-4-fast-non-reasoning` 등)
- 설정 탭: Vision/Shadow 라디오에 Grok 추가
- Grok AI 그림자 프롬프트 편집 UI (모델, 순서, 5개 프롬프트)
  - Shadow 모델: `grok-imagine-image` / `grok-imagine-image-pro`
  - `_save_grok_shadow_settings()` / `_reset_grok_shadow_prompts()`
- API 키 검증 (grok vision + grok_shadow)
- 심의 토론 색상 (보라색 계열: `#a855f7`, `#c084fc`, `#1e1028`)
- 설정 로드/저장에 grok 모델 + grok_shadow 설정 포함

**`config/settings.yaml`**
- `grok` 섹션 (model: `grok-4-fast-non-reasoning`)
- `grok_shadow` 섹션 (model: `grok-imagine-image`, prompts, order)

**`src/analyzer/gemini_vision_client.py`**
- `finish_reason` 로깅 추가 (MAX_TOKENS 디버깅용)

### 트러블슈팅 이력

1. **Shadow API 포맷**: 자동 테스트 스크립트로 10가지 형식 시도 → `{"url","type"}` JSON 객체 확인
2. **Vision 모델**: `grok-2-vision-latest` 존재 안함 → API 모델 목록 조회 + 자동 테스트 → grok-4 계열만 Vision 지원
3. **품질 검증 실패**: Gemini 2.5 Flash의 thinking 토큰이 `max_output_tokens`에 포함 → 512토큰에서 21토큰만 출력 후 `MAX_TOKENS`로 잘림 → 8192로 증가 해결

---

### Phase 18: 그림자 힌트 관리 탭 + Gemini 폴백 + 뷰파인더 전체화면
**날짜:** 2026-04-06

1. **그림자 힌트 전용 탭** (`config/shadow_hints.yaml` 관리)
   - 프롬프트 편집 탭에서 분리 → 별도 "그림자 힌트" 탭 생성
   - 계층형 트리뷰: default → 촬영방향별 → 카테고리별 → Provider별
   - 카테고리+촬영각도 조합 키 지원 (예: `bag/detail`, `shoes/front/full`)
   - 55개 프리셋 추가 (bag, shoes, hat, clothing, watch, jewelry 등 × 각도별)
   - 추가/수정/삭제/내보내기 기능 + 도움말 가이드

2. **Gemini 503 자동 폴백**
   - 기본 모델 3회 연속 실패 → 폴백 모델로 자동 전환
   - `_gemini_add_shadow()`: 2단계 폴백 체인 (primary 3회 → fallback 3회)
   - GUI 설정: 기본 모델 + 폴백 모델 각각 콤보박스 선택
   - `config/settings.yaml`에 `fallback_model` 필드 추가

3. **뷰파인더 전체화면**
   - Windows 작업 영역 API (`ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA)`) 사용
   - 작업표시줄 제외한 정확한 세로 100% 활용

### Phase 19: 자동수정 3단계 + 결과 미리보기 플로우
**날짜:** 2026-04-06

1. **자동수정 3단계 플로우** (기존 직접 호출 → 미리보기+확인 방식으로 변경)
   ```
   [🔄 자동수정] 클릭
     → 1단계: AI에게 프롬프트 추천 요청 (백그라운드)
     → 2단계: 추천 프롬프트 미리보기 팝업 (편집 가능)
       → [👁 결과 미리보기] — 프롬프트 저장 없이 그림자만 임시 생성 → 이미지 표시
       → [✅ 적용 (프롬프트 저장)] — 미리보기 만족 시 프롬프트 저장 + 결과 확정
       → [취소] — 아무것도 저장 안 함
   ```
   - `pipeline.py`에 `preview_prompt_fix()`: AI에게 프롬프트 추천만 받기 (재생성 X)
   - `pipeline.py`에 `apply_prompt_and_regenerate()`: 확정 프롬프트로 그림자 재생성
   - `pipeline.py`에 `preview_shadow_only()`: 프롬프트 저장 없이 임시 그림자 생성
     - `_shadow_hints`에 임시 저장 → 생성 → 복원 (YAML 파일 미변경)
   - 미리보기 결과가 있으면 재생성 없이 바로 적용 (API 비용 절약)

2. **왼쪽 파일 목록에 재생성 상태 표시**
   - 재생성 시작: `그림자 재생성 중...` (파란색) + 그림자 pip 파란색
   - 재생성 성공: `🔄재생성 {점수}/10` (초록색)
   - 재생성 실패: `🔄재생성 실패` (빨간색)

3. **자동수정 버튼 항상 활성화**
   - 기존: 독립평가 점수 7점 미만 항목이 있을 때만 활성
   - 변경: 독립평가 데이터가 있으면 항상 활성 (검수 통과해도 의견 입력 후 수정 가능)

### Phase 20: 검증 프롬프트 피드백 시스템
**날짜:** 2026-04-06

1. **독립평가 항상 실행**
   - 기존: 검증(validation) 합격일 때만 `_evaluate_independent()` 실행
   - 변경: 검증 결과와 무관하게 항상 실행 → 불합격이어도 자동수정 버튼 활성

2. **📝 검증수정 버튼** (뷰파인더 하단)
   - 검증 불합격(❌그림자 등)에 이의 제기할 때 사용
   - 플로우:
     ```
     의견 입력 (예: "이 그림자는 합격이다")
       → [📝 검증수정] 클릭
       → AI가 원본+결과 이미지를 보고 사용자 의견 타당성 판단
       → 수정된 검증 프롬프트 미리보기 팝업 (편집 가능)
       → [프롬프트 저장 + 강제 합격] — prompts.yaml 수정 + 현재 이미지 즉시 합격
       → [프롬프트만 저장] — 다음 처리부터 적용
       → [강제 합격 처리] — AI 동의 안 해도 사용자가 합격 처리
     ```
   - `config/prompts.yaml`의 `validation.shadow_needed`, `validation.user_template` 자동 업데이트
   - 강제 합격 시 파일 목록 검증 아이콘도 즉시 갱신

### Phase 21: MAX_TOKENS 오류 대응
**날짜:** 2026-04-06

1. **Gemini Vision max_tokens 증가**
   - `config/settings.yaml`: gemini.max_tokens 2048 → 4096
   - pipeline.py 기본값: 1024 → 2048

2. **부분 응답 복구** (`gemini_vision_client.py`)
   - `response.text`가 `None`이어도 `candidates[0].content.parts`에서 부분 텍스트 추출
   - `FinishReason.MAX_TOKENS`일 때 부분 응답으로 계속 진행

3. **잘림 감지 자동 재시도** (`pipeline.py`)
   - 분석 응답이 `,` `"` `:` `{`로 끝나면 (JSON 잘림 감지)
   - 토큰 수를 2배로 늘려 자동 재시도 (최대 8192)

### Phase 22: 독립평가 원본 비교 + 평가 프롬프트 탭 + 검증수정 확장 (2026-04-07)

**목적**: 독립평가 시 원본 이미지를 함께 전달하여 원본 고유 결함을 편집 결함으로 오인하는 문제 해결 + 평가 프롬프트를 GUI에서 직접 편집 가능하게

#### 1. 독립평가에 원본 이미지 함께 전달
- **문제**: 기존 `_evaluate_independent()`는 결과 이미지 1장만 Vision API에 전달 → 원본에 이미 있는 얼룩/자국을 편집 결함으로 평가
- **해결**: `original_bytes` 파라미터 추가, 원본+결과 2장을 함께 전달
- `src/pipeline.py` — `_evaluate_independent()` 시그니처 변경 + 3개 호출부 수정
- `config/prompts.yaml` — 독립평가 시스템/사용자 프롬프트에 "원본 결함 감점 금지" 지시 추가

#### 2. 평가 프롬프트 전용 탭 신설 (탭 3)
- **기존**: 검증 프롬프트는 탭 2(프롬프트 편집)에 혼재, 독립평가 프롬프트는 GUI 편집 불가
- **변경**: 새 탭 "평가 프롬프트" 생성 (실행 → 프롬프트 편집 → **평가 프롬프트** → 그림자 힌트 → 설정)
- **섹션 1 — 개별 검증 (PASS/FAIL)**: 시스템, 그림자 필요/불필요 판정 기준, 검증 요청 템플릿 (배경색 `#fef2f2`)
- **섹션 2 — 독립평가 (점수제)**: 시스템, 평가 요청 프롬프트 (배경색 `#eef2ff`)
- 전용 저장/로드/기본값 복원 버튼 (`_save_eval_prompts`, `_load_eval_prompts`, `_reset_eval_prompts`)

#### 3. 검증수정 버튼 확장 (독립평가+개별검증 선택)
- **기존**: 검증 불합격 시에만 활성화, validation 프롬프트만 수정
- **변경**: 독립평가 또는 검증 결과가 있으면 활성화
- 수정 대상 선택 팝업: 🟣 독립평가 프롬프트 수정 / 🔵 개별 검증 프롬프트 수정
- AI에게 전달: 원본/결과 이미지 + 기존 평가 결과 전문 + 현재 프롬프트 + 사용자 의견
- 독립평가 수정 시: `independent_evaluation.system` / `independent_evaluation.prompt` 업데이트
- 개별검증 수정 시: `validation.shadow_needed` / `validation.user_template` 업데이트 (기존)

#### 4. 크래시 로그 시스템 추가
- `gui.py` — 글로벌 예외 핸들러 3종 추가:
  - `sys.excepthook` (메인 스레드)
  - `threading.excepthook` (워커 스레드)
  - `app.report_callback_exception` (tkinter 콜백)
- 크래시 발생 시 `crash.log` 파일에 타임스탬프 + 트레이스백 기록

#### 5. PySide6 GUI 프로토타입 (보류)
- `gui_pyside/` 폴더에 12개 모듈 생성 (app, tabs×4, dialogs×3, workers, styles, utils)
- 진입점 `gui_pyside.py` — 정상 실행 확인 (4탭 로드 성공)
- **디자인 미흡으로 보류** — 기존 tkinter `gui.py` 계속 사용

#### 변경 파일 요약

| 파일 | 변경 내용 |
|------|-----------|
| `src/pipeline.py` | `_evaluate_independent()`: `original_bytes` 파라미터 추가, 원본+결과 2장 전달, 3개 호출부 수정 |
| `config/prompts.yaml` | `independent_evaluation.system/prompt`: 원본 비교 지시 + 원본 결함 감점 금지 추가 |
| `gui.py` | 새 탭 "평가 프롬프트" (`_build_eval_tab`), 검증수정 확장 (대상 선택 팝업, 독립평가 수정 로직), 크래시 로그 핸들러 |
| `gui_pyside/` | PySide6 프로토타입 12개 파일 (보류, 삭제하지 않음) |
| `gui_pyside.py` | PySide6 진입점 (보류) |
| `requirements.txt` | `PySide6>=6.5.0` 추가 |
| `CLAUDE.md` | PySide6 구조 문서화 추가 |

### Phase 23: 복합 배경제거 + 카테고리별 검증 프롬프트 + 크래시 수정 (2026-04-09)

**목적**: 배경 제거 비용 최적화 (복합 모드), 카테고리별 품질 검증 기준 도입, 유휴 상태 자동 종료 크래시 수정

#### 1. 복합(Hybrid) 배경 제거 모드
- **목적**: Photoroom(28원/건) 우선 사용 → Vision API 품질 검증 → 불합격 시 remove.bg(125원/건) 폴백
- **비용 절감**: 5000건 기준 약 66% 절감 (625,000원 → ~212,500원, 불합격률 10% 가정)
- `src/pipeline.py`:
  - `_check_nukki_quality()` — Vision API로 원본+누끼 결과 비교 품질 판정 (상품 보존/배경 제거/엣지 품질)
  - `_call_photoroom()` — Photoroom 로직 헬퍼 메서드로 분리
  - `_call_bg_removal()` — `hybrid` 분기 추가: Photoroom → 검증 → remove.bg 폴백
  - `_last_bg_provider` — 실제 사용된 프로바이더 추적 (로그/edit_actions 정확성)
  - Vision API 오류/파싱 실패 시 Photoroom 결과 채택 (비용 절약 우선)
- `config/settings.yaml`: `hybrid_bg.verify_method: vision_api` 추가
- `gui.py`: 배경 라디오 버튼에 `("복합", "hybrid")` 추가, 설정 탭 복합 모드 경고 메시지
- `gui_pyside/tabs/main_tab.py`: 배경 라디오 버튼에 `("복합", "hybrid")` 추가
- `gui_pyside/tabs/settings_tab.py`: 배경 라디오 버튼 + 복합 모드 경고 메시지

#### 2. 카테고리별 검증 프롬프트 시스템
- **목적**: 그림자 프롬프트 탭에서 카테고리별 합격/불합격 판정 기준을 관리
- `shadow_hints.yaml` 형식 확장:
  - 기존: `key: "그림자 프롬프트 문자열"` (하위 호환)
  - 신규: `key: {shadow_hint: "...", validation: "..."}`
- `gui.py` — 그림자 프롬프트 탭 UI 변경:
  - 탭 이름: "그림자 힌트" → "그림자 프롬프트"
  - 우측 편집 영역을 2분할: 그림자 프롬프트(보라색) + 검증 기준(청색)
  - `_shadow_hints_data` + `_validation_hints_data` 병렬 딕셔너리
  - 로드/저장/선택/추가/삭제 모두 양쪽 데이터 동기화
- `src/pipeline.py`:
  - `_get_shadow_hint()` — 새 dict 형식 호환 (`val.get("shadow_hint")`)
  - `_get_validation_hint()` — 신규 메서드. 카테고리별 검증 기준 우선순위 조회
  - `_validate_result()` — `category`, `shooting_angle` 파라미터 추가, 카테고리별 검증 기준을 Vision API 프롬프트에 `[카테고리별 추가 검증 기준]` 블록으로 삽입
  - 호출부 2곳에 `category`, `shooting_angle` 전달

#### 3. 유휴 상태 자동 종료 크래시 수정
- **원인**: 뷰파인더의 `_refresh()` 타이머(500ms)가 앱 종료/유휴 시 이미 소멸된 위젯/데이터에 접근하여 크래시
  - 타이머가 dialog 닫힘 후에도 계속 실행 (tkinter `after()` 미취소)
  - 워커 스레드와 메인 스레드 간 공유 데이터 경쟁 조건
  - 소멸된 위젯에 `.configure()` 호출 → TclError / RuntimeError
- **수정 (tkinter — gui.py)**:
  - `_refresh()`: 전체 본문 `try/except (RuntimeError, TclError, AttributeError, KeyError)` 래핑, 예외 시 타이머 재등록 중단
  - `_on_dlg_close()`: `dlg.after_cancel(_refresh_id[0])`로 타이머 명시적 취소 후 dialog 파괴
- **수정 (PySide6 — gui_pyside/)**:
  - `dialogs/viewfinder.py` `_refresh()`: `try/except (RuntimeError, AttributeError)` 래핑, 예외 시 `_refresh_timer.stop()`
  - `app.py` `closeEvent()`: 뷰파인더 `_refresh_timer` 명시적 정지 + dialog close 처리 후 워커 정리

#### 4. API 사용법 스킬 파일 생성
- `.claude/skills/api-ai.md` — AI API 가이드 (Vision 분석 + 그림자 생성: Claude/ChatGPT/Gemini/Grok)
- `.claude/skills/api-image.md` — 이미지 처리 API 가이드 (Photoroom/remove.bg/Claid.ai/OpenCV)
- 두 파일 모두 `D:\CLAUDE_CODE_WORK\.claude\skills\`(전역) + `shop-image-editor/.claude/skills/`(프로젝트) 양쪽에 배치

#### 변경 파일 요약

| 파일 | 변경 내용 |
|------|-----------|
| `src/pipeline.py` | `_check_nukki_quality()`, `_call_photoroom()`, hybrid 분기, `_get_validation_hint()`, `_validate_result()` 확장 |
| `config/settings.yaml` | `hybrid_bg.verify_method: vision_api` 추가 |
| `config/shadow_hints.yaml` | dict 형식 지원 (`{shadow_hint, validation}`) — 기존 string 형식 하위 호환 |
| `gui.py` | 그림자 프롬프트 탭 2분할 UI, 복합 배경 라디오, 뷰파인더 크래시 수정 |
| `gui_pyside/tabs/main_tab.py` | 복합 배경 라디오 추가 |
| `gui_pyside/tabs/settings_tab.py` | 복합 배경 라디오 + 경고 메시지 |
| `gui_pyside/dialogs/viewfinder.py` | `_refresh()` 예외 처리 추가 |
| `gui_pyside/app.py` | `closeEvent()` 뷰파인더 타이머 정리 추가 |
| `.claude/skills/api-ai.md` | AI API 사용법 스킬 (신규) |
| `.claude/skills/api-image.md` | 이미지 처리 API 사용법 스킬 (신규) |

### Phase 24: Git 레포지토리 초기화 + GitHub 연동 (2026-04-14)

**목적**: 프로젝트 버전 관리 시작, 다중 PC 협업을 위한 GitHub 원격 저장소 연결

#### 1. Git 레포지토리 초기화
- `git init` → Initial commit (ba57232)
- 전체 프로젝트 파일 최초 커밋 (Phase 1~23 작업물 일괄 포함)

#### 2. .gitignore 설정
- Python 관련: `__pycache__/`, `*.pyc`, `.venv/`, `venv/`, `*.egg-info/`
- 설정/시크릿: `.env`, `config/secrets.yaml`
- 이미지/결과물: `output/`, `temp/`, `*.jpg`, `*.jpeg`, `*.png`, `*.webp`
- 용량 큰 바이너리 파일 제외로 레포 경량화

#### 3. GitHub 원격 저장소 연결
- Remote: `https://github.com/kimyoungho0505/shop-image-editor.git`
- Branch: `main`

#### 변경 파일 요약

| 파일 | 변경 내용 |
|------|-----------|
| `.gitignore` | Python/시크릿/이미지 제외 규칙 추가 |

---

## SAM 모델 파일 (삭제됨)
models/ 디렉토리의 SAM 체크포인트 파일이 삭제되었습니다 (총 4GB):
- `sam_vit_b_01ec64.pth` (358MB)
- `sam_vit_h_4b8939.pth` (2.4GB)
- `sam_vit_l_0b3195.pth` (1.2GB)
- `mobile_sam.pt` (39MB)

SAM 기능 사용 시 재설치 방법:
```bash
# MobileSAM (경량, 권장)
pip install git+https://github.com/ChaoningZhang/MobileSAM.git
# 체크포인트는 src/sam/client.py 실행 시 자동 다운로드

# 또는 수동 다운로드
# https://github.com/facebookresearch/segment-anything#model-checkpoints
# models/ 폴더에 저장
```
소스코드(`src/sam/client.py`, `src/sam/__init__.py`)는 그대로 유지됨.

---

## 현재 상태 & 이어서 할 작업

### 최근 변경 (Phase 24, 2026-04-14)
1. **Git 레포지토리 초기화** — 전체 프로젝트 최초 커밋 (Phase 1~23 일괄)
2. **GitHub 원격 저장소 연결** — `kimyoungho0505/shop-image-editor`
3. **.gitignore 설정** — Python/시크릿/이미지 파일 제외 규칙

### 확인 필요
1. **복합 배경 제거 테스트** — Photoroom → Vision 검증 → remove.bg 폴백 플로우 실제 이미지로 확인
2. **카테고리별 검증 기준 작성** — shadow_hints.yaml에 주요 카테고리별 validation 문구 실제 작성 필요
3. **크래시 재발 모니터링** — 타이머 수정 후에도 자동 종료 재발 시 crash.log 확인 (외부 요인 가능성)
4. **독립평가 원본 비교** — 원본+결과 2장 전달 후 평가 정확도 개선 확인

### 향후 고려 사항
- **Gemini 그림자 근본 한계**: 동일 이미지에 대해 결과 편차가 큼 (너무 약하거나 과함)
- **대안 검토**: 복잡한 구도(중첩 상품)는 누끼 합성 그림자로 fallback 고려
- **PySide6 GUI**: 프로토타입 완성 (gui_pyside/) — 디자인 개선 후 전환 가능
- **그림자 스마트 판단 시스템**: 촬영 각도/바닥 가시성 기반 자동 판단 기획 완료 (plan 파일 참조), 구현 대기

### 탭 구조 (gui.py)
```
탭 1: 실행         — 폴더 선택, 프로바이더 라디오(복합 배경 포함), 옵션, 로그, 뷰파인더
탭 2: 프롬프트 편집  — 시스템 프롬프트, 분석 요청 프롬프트 (Vision API)
탭 3: 평가 프롬프트  — 개별 검증(PASS/FAIL) + 독립평가(점수제) 프롬프트
탭 4: 그림자 프롬프트 — 카테고리/촬영방향별 그림자 프롬프트 + ★검증 기준★ 동시 편집
탭 5: 설정         — API 키, 모델 선택, 출력 설정, Gemini/Grok 그림자 설정, TTS 등
```

### 아키텍처 업데이트 (파이프라인 흐름)
```
원본 이미지 → Vision API 분석 → 배경 제거 [Photoroom/remove.bg/★복합★] → 후처리(크롭/센터링)
  → 이미지 보정 → [그림자 생성 (Gemini/Grok)] → JPEG 최적화 → 저장
  → ★ 품질 검증 (Vision API, prompts.yaml + ★카테고리별 검증 기준★)
  → validation: {background, shadow, integrity} → 합격/불합격
  → 그림자 불합격 시: _pre_shadow_bytes에서 Gemini 그림자 1회 재시도 → 재검증
  → ★ 독립 품질 평가 (항상 실행, 원본+결과 2장 비교, 5항목 10점제)
  → 뷰파인더에서 결과 확인:
    → [🔄 자동수정] — AI 추천 프롬프트 → 미리보기 → 적용
    → [📝 검증수정] — 독립평가 또는 개별검증 프롬프트 수정 (대상 선택)
    → [📋 클로드 복사] — 분석 리포트 클립보드 복사
```

### 주요 파일 현황
| 파일 | 역할 | 최근 변경 (Phase 24) |
|------|------|-----------|
| `.gitignore` | Git 제외 규칙 | Python/시크릿/이미지 제외 규칙 추가 |
| `gui.py` | tkinter GUI 전체 | 그림자 프롬프트 탭 2분할, 복합 배경 라디오, 크래시 수정 |
| `src/pipeline.py` | 처리 파이프라인 | hybrid 배경, `_check_nukki_quality()`, `_get_validation_hint()`, `_validate_result()` 확장 |
| `config/prompts.yaml` | AI 프롬프트 | 변경 없음 |
| `config/settings.yaml` | 설정값 | `hybrid_bg.verify_method: vision_api` 추가 |
| `config/shadow_hints.yaml` | 그림자 프롬프트 + 검증 기준 | dict 형식 지원 (`{shadow_hint, validation}`), 기존 string 하위 호환 |
| `config/categories.yaml` | 카테고리 여백 | 변경 없음 |
| `gui_pyside/` | PySide6 GUI | 복합 배경 라디오, 뷰파인더 크래시 수정, closeEvent 타이머 정리 |
| `.claude/skills/` | API 사용법 스킬 | `api-ai.md` (AI API), `api-image.md` (이미지 API) 신규 |
