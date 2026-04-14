# LUXBOY 쇼핑몰 이미지 자동 편집 도구 - 개발 기획서

> **문서 작성일:** 2026-03-31
> **프로젝트 경로:** `D:\CLAUDE_CODE_WORK\shop-image-editor`
> **플랫폼:** Windows 데스크톱 (Python 3.10+ / tkinter)

---

## 1. 프로젝트 개요

### 1.1 목적
럭셔리 쇼핑몰(LUXBOY) 상품 사진을 자동으로 편집하는 Windows 데스크톱 앱.
원본 상품 사진 → **AI 분석 → 배경 제거 → 그림자 합성 → 색보정 → 1000x1000 JPEG 출력**을 자동화한다.

### 1.2 핵심 가치
- 사람이 수작업으로 30분 이상 걸리는 상품 이미지 편집을 **30~120초**로 단축
- AI가 이미지 유형/카테고리를 자동 판별하여 최적 파라미터 적용
- 원본 그림자의 자연스러운 그라데이션을 보존하는 그림자 추출 기술
- 6가지 프로바이더를 조합 가능한 모듈형 파이프라인 설계

---

## 2. 시스템 아키텍처

### 2.1 전체 처리 흐름

```
원본 이미지
    │
    ▼
┌──────────────────┐
│ 1. AI 비전 분석   │  Claude / ChatGPT / Gemini
│   (이미지 분류)    │  → image_type, category, shadow, hand 감지
└────────┬─────────┘
         │
    ▼
┌──────────────────┐
│ 2. 손 크롭        │  product_only_region 기반 상품 최대화 크롭
│   (선택적)        │  → 손 제외, 상품만 최대한 크게
└────────┬─────────┘
         │
    ▼
┌──────────────────┐
│ 3. 배경 제거      │  Photoroom API / remove.bg API
│                  │  → 투명 PNG (알파 채널)
└────────┬─────────┘
         │
    ▼
┌──────────────────┐
│ 4. 그림자 처리     │  API Shadow / OpenCV 추출 / SAM 추출 / 없음
│                  │  → 원본 그림자 보존 + 거리 기반 그라데이션
└────────┬─────────┘
         │
    ▼
┌──────────────────┐
│ 5. 정리 & 센터링  │  아티팩트 제거 (BFS) → 상품 중앙 배치
│                  │  → 카테고리별 여백 적용
└────────┬─────────┘
         │
    ▼
┌──────────────────┐
│ 6. 색상 보정      │  Claid.ai API / OpenCV 로컬
│                  │  → HDR, 샤프니스, 노출, 채도, 대비
└────────┬─────────┘
         │
    ▼
┌──────────────────┐
│ 7. JPEG 최적화    │  품질 자동 조절 (95→60)
│   & 출력         │  → 1000x1000px, ≤2024KB
└──────────────────┘
```

### 2.2 프로바이더 구조

| 기능 | 프로바이더 옵션 | 기본값 |
|------|----------------|--------|
| **AI 비전 분석** | Claude / ChatGPT / Gemini | gemini |
| **배경 제거** | Photoroom / remove.bg | removebg |
| **색상 보정** | Claid.ai / OpenCV | claid |
| **그림자** | API Shadow / OpenCV 추출 / SAM Mobile / SAM CPU / SAM GPU / 없음 | sam_mobile |

각 프로바이더는 독립 모듈로 동일 인터페이스를 구현하여 **드롭인 교체** 가능.

---

## 3. 디렉토리 구조

```
shop-image-editor/
├── gui.py                          # GUI 메인 (tkinter, 3탭, ~1750줄)
├── main.py                         # CLI 진입점 (Click)
├── requirements.txt                # Python 의존성
├── .env                            # API 키 (6개)
├── run_gui.bat                     # Windows 실행 배치파일
├── PROJECT_HISTORY.md              # 개발 이력
│
├── config/
│   ├── settings.yaml               # 출력 설정, 프로바이더 설정, 파라미터
│   ├── prompts.yaml                # AI 비전 분석 프롬프트 (시스템 + 유저)
│   └── categories.yaml             # 13개 카테고리 여백 규칙
│
├── models/                         # SAM 체크포인트 (자동 다운로드)
│   ├── mobile_sam.pt               # MobileSAM (40.7MB)
│   └── sam_vit_b_01ec64.pth        # SAM VIT-B (375MB)
│
├── src/
│   ├── pipeline.py                 # ★ 핵심 오케스트레이터 (~1200줄)
│   │
│   ├── analyzer/                   # AI 비전 분석
│   │   ├── vision_client.py        #   Claude API 클라이언트
│   │   ├── openai_vision_client.py #   ChatGPT API 클라이언트
│   │   ├── gemini_vision_client.py #   Gemini API (재시도 로직 포함)
│   │   ├── prompt_builder.py       #   프롬프트 동적 생성
│   │   └── result_parser.py        #   JSON 파싱 (4단계 폴백)
│   │
│   ├── photoroom/
│   │   └── client.py               # Photoroom v2/edit API
│   │
│   ├── removebg/
│   │   └── client.py               # remove.bg API
│   │
│   ├── claid/
│   │   └── client.py               # Claid.ai 보정 API
│   │
│   ├── opencv_enhance/
│   │   └── enhancer.py             # OpenCV 로컬 보정 (CLAHE, Unsharp Mask)
│   │
│   ├── sam/
│   │   ├── __init__.py
│   │   └── client.py               # SAM/MobileSAM 그림자 추출
│   │
│   ├── exporter/
│   │   ├── optimizer.py            # JPEG 품질 최적화 (이진 탐색)
│   │   ├── resizer.py              # 리사이즈 헬퍼
│   │   └── namer.py                # 출력 파일명 생성
│   │
│   ├── utils/
│   │   ├── category.py             # 카테고리 관리 + 여백 계산
│   │   ├── image_io.py             # 이미지 I/O (로드, 저장, base64)
│   │   └── logger.py               # loguru 설정
│   │
│   ├── background/                 # [DEPRECATED] API로 대체됨
│   └── editor/                     # [DEPRECATED] pipeline.py로 통합됨
│
├── logs/
│   └── editor.log                  # 런타임 로그
│
└── tests/
    └── test_modules.py             # 모듈 임포트 테스트
```

---

## 4. 핵심 모듈 상세

### 4.1 AI 비전 분석 (`src/analyzer/`)

#### 역할
원본 이미지를 AI에게 보내 **이미지 유형, 카테고리, 그림자 방향, 손 감지, 최적 보정 파라미터**를 분석.

#### 입력
- 이미지 1~5장 (같은 폴더의 형제 이미지 함께 전송, 1024px 리사이즈)
- 시스템 프롬프트 + 유저 프롬프트 (config/prompts.yaml)

#### 출력 (EditInstruction)
```python
@dataclass
class EditInstruction:
    image_type: str          # "full" | "detail" | "worn" | "package"
    background: str          # "clean" | "complex" | "none"
    detected_category: str   # "bag" | "shoes" | "clothing" 등 13개
    subject_position: str    # "center" | "left" | "right" | "top" | "bottom"
    is_detail_cut: bool      # 디테일컷 여부
    detail_focus_area: dict  # {x, y, width, height} 정규화 좌표
    needs_shadow: bool       # 그림자 필요 여부
    shadow_direction: str    # "bottom" | "bottom-left" 등
    shadow_params: dict      # AI 추천 그림자 파라미터
    has_human_hand: bool     # 손 감지 여부
    hand_region: dict        # 손 바운딩 박스
    product_only_region: dict # 상품만의 바운딩 박스 (손 제외)
    enhance_params: dict     # AI 추천 보정 파라미터
    photoroom_params: dict   # AI 추천 Photoroom 파라미터
    confidence: float        # 분석 확신도 (0~1)
    notes: str               # 비고
```

#### 프로바이더별 특성

| 프로바이더 | SDK | 모델 | 특이사항 |
|-----------|-----|------|---------|
| Claude | anthropic | claude-opus-4-20250514 | 정확도 최고, 비용 높음 |
| ChatGPT | openai | gpt-4o | data URL 형식 |
| Gemini | google-genai | gemini-2.5-flash | 저비용, 503 재시도 로직 (5회, 지수 백오프) |

#### JSON 파싱 전략 (result_parser.py)
1. 전체 텍스트 `json.loads()` 시도
2. ` ```json ... ``` ` 코드 블록 추출
3. 정규식 `{...}` 블록 추출
4. 잘린 JSON 복구 (닫히지 않은 `{` 개수만큼 `}` 추가)

---

### 4.2 배경 제거 (`src/photoroom/`, `src/removebg/`)

#### Photoroom API
- **엔드포인트:** `https://image-api.photoroom.com/v2/edit`
- **처리 조건:** image_type이 full/package이거나, detail이면서 background=complex
- **주요 파라미터:**
  - `removeBackground: "true"`
  - `shadow.mode: "ai.soft"` (API 그림자 사용 시)
  - `shadow.opacity: 0.0~1.0`
  - `outputSize: "originalImage"` (원본 크기 유지)
- **출력:** 투명 PNG 또는 흰 배경+그림자 PNG

#### remove.bg API
- **엔드포인트:** `https://api.remove.bg/v1.0/removebg`
- **파라미터:** `size: "auto"`, `type: "product"`
- **출력:** 투명 PNG

---

### 4.3 그림자 처리 (pipeline.py + src/sam/)

#### 6가지 그림자 모드

| 모드 | 설명 | 소요 시간 |
|------|------|-----------|
| `api_shadow` | Photoroom API의 AI 그림자 | 0초 (배경제거와 동시) |
| `opencv_extract` | 원본에서 OpenCV로 그림자 추출 | 1~2초 |
| `sam_mobile` | MobileSAM 마스크 기반 추출 | 3~5초 (CPU) |
| `sam_cpu` | SAM VIT-B CPU 추출 | 10~30초 |
| `sam_gpu` | SAM VIT-B GPU 추출 | 2~5초 (CUDA) |
| `none` | 그림자 없음 | 0초 |

#### 그림자 추출 알고리즘 (`_preserve_natural_shadow`)

```
1. 누끼 결과에서 알파 채널 → 제품 마스크 추출
2. 원본 이미지 로드, 크기 맞춤
3. 이미지 테두리(10px)에서 배경색 추정 (중앙값)
4. 제품 마스크 팽창 (mask_expand %) → 제품 영역 배경색으로 채움
5. 레벨 보정: 배경 → 순백, 그림자 → 자연 그라데이션 유지
6. 탐색 범위 제한 (search_top/bottom/sides %)
7. 경계 페이드아웃 (가우시안 블러)
8. 거리 기반 감쇠 (distanceTransform + sqrt 커브)
   - distance_falloff (30~100%): 제품 크기 대비 그라데이션 범위
9. opacity 적용 (0~100%)
10. threshold 노이즈 제거
11. 제품 알파 합성
```

#### 핵심 파라미터 (settings.yaml → shadow_extract)

| 파라미터 | 범위 | 기본값 | 설명 |
|---------|------|--------|------|
| opacity | 0~100 | 40 | 그림자 진하기 (%) |
| threshold | 0~30 | 15 | 배경 판정 허용 오차 |
| blur | 0~25 | 18.0 | 그림자 블러 (제품 크기 대비 %) |
| search_top | 0~50 | 10 | 상단 탐색 범위 (%) |
| search_bottom | 0~200 | 150 | 하단 탐색 범위 (%) |
| search_sides | 0~100 | 80 | 좌우 탐색 범위 (%) |
| mask_expand | 1~5 | 3.0 | 제품 마스크 확장 (%) |
| distance_falloff | 30~100 | 60 | 그라데이션 범위 (제품 크기 대비 %) |

#### SAM (Segment Anything Model)

- **MobileSAM:** 경량 모델, CPU 전용, 3~5초
- **SAM VIT-B:** 중형 모델, CPU 10~30초 / GPU(CUDA) 2~5초
- **GPU 자동 감지:** CUDA + VRAM 크기 체크 → GPU 옵션 활성화/비활성화
- **자동 프롬프트:** 중앙 3점(positive) + 모서리 4점(negative) → 최고 점수 마스크 선택
- **체크포인트 자동 다운로드:** Facebook AI 저장소에서 models/ 폴더로

---

### 4.4 정리 & 센터링 (`_clean_and_recenter_bytes`)

#### 아티팩트 제거 (BFS 연결 성분 분석)
1. 이미지를 4배 축소하여 BFS 탐색
2. 가장 큰 연결 성분 = 상품 본체
3. 작은 노이즈 덩어리 제거
4. 상품 위쪽 아티팩트 클리어
5. 하단 10%는 그림자 영역으로 보존

#### 센터링 & 여백
- 상품 바운딩 박스 계산
- 카테고리별 여백 적용 (categories.yaml)
- 여백 기준: 860px 베이스 → 출력 크기에 비례 스케일링
- 상품을 여백 내 최대 크기로 스케일 + 중앙 배치

---

### 4.5 색상 보정 (`src/claid/`, `src/opencv_enhance/`)

#### Claid.ai API
- **엔드포인트:** `https://api.claid.ai/v1-beta1/image/edit/upload`
- **파라미터:** hdr (0~50), sharpness (0~30), exposure, saturation, contrast
- **이미지 유형별 다른 설정** (full/detail/worn/package)

#### OpenCV 로컬 보정
- **CLAHE:** 적응형 히스토그램 균일화 (LAB L채널)
- **Unsharp Mask:** 커널 크기, 시그마, 강도
- **LAB 톤 커브:** 그림자/하이라이트/미드톤
- **HSV 채도 조절**
- API 호출 없이 로컬 처리, 속도 빠름

#### AI 자동 vs 수동 모드
- **수동(manual):** GUI에서 설정한 고정값 사용
- **AI 자동(ai_auto):** 비전 API가 추천한 값으로 자동 오버라이드
  - AI 실패 시 GUI 값을 기본값으로 사용
  - Claid, OpenCV, Photoroom, Shadow 각각 독립 토글

---

### 4.6 손 감지 & 크롭 (`_crop_out_hand`)

#### 동작 원리
1. AI 비전 분석에서 `has_human_hand=true` 감지
2. `product_only_region` (상품만의 바운딩 박스) 우선 사용
   - 3% 마진 추가하여 상품이 잘리지 않도록
   - 손 위치와 무관하게 상품 영역만 크롭
3. `product_only_region` 없으면 `hand_region` 기반 가장자리 크롭
   - 손이 이미지 가장자리(5% 이내)에 닿아 있을 때만
   - 크롭 후 70% 미만이면 원본 유지
4. 크롭된 이미지가 Photoroom에도 전달됨

---

### 4.7 JPEG 최적화 (`src/exporter/optimizer.py`)

- 품질 95에서 시작, 5씩 감소하며 목표 용량(≤2024KB) 달성
- 최소 품질 60에서 중단
- 이진 탐색으로 최적 품질 결정

---

## 5. GUI 구성

### 5.1 3탭 구조 (1100x850px)

#### 탭 1: 실행 (메인)
- **입력/출력 폴더** 선택 + "폴더 열기" 버튼
- **프로바이더 선택** (라디오 버튼 4그룹)
- **실행 버튼:** 단일 이미지 / 배치 처리 / 분석만
- **진행 표시:** 프로그레스바 + 퍼센트 + 상태바
- **로그 창:** 색상 코딩 (파랑/초록/빨강/주황), 다크 테마

#### 탭 2: 프롬프트 편집
- **시스템 프롬프트** 에디터 (노란 배경)
- **유저 프롬프트 템플릿** 에디터 (초록 배경)
- 저장 / 초기화 / 리로드 버튼

#### 탭 3: 설정
- **출력 이미지 설정** (크기, 용량, 배경색, JPEG 품질)
- **API 키 관리** (6개, 눈 아이콘 표시/숨김 토글)
- **Photoroom 옵션** (수동/AI 자동 토글, shadow.mode, opacity, padding)
- **Claid.ai 옵션** (수동/AI 자동, 4유형 × 5파라미터 그리드)
- **OpenCV 보정 옵션** (수동/AI 자동, 동일 그리드)
- **remove.bg 옵션** (size, type)
- **그림자 추출 옵션** (수동/AI 자동, 8개 파라미터 슬라이더)
- **카테고리별 여백** (편집 가능한 트리뷰 테이블)

### 5.2 상태 영속화
- `gui_state.json`: 입출력 폴더, skip 플래그
- `settings.yaml`: 모든 프로바이더 설정
- `.env`: API 키

---

## 6. 설정 파일 명세

### 6.1 settings.yaml

```yaml
output:
  width: 1000                    # 출력 이미지 가로 (px)
  height: 1000                   # 출력 이미지 세로 (px)
  max_file_size_kb: 2024         # JPEG 최대 용량
  background_color: [255,255,255] # 배경 흰색
  default_jpeg_quality: 95       # 기본 JPEG 품질

providers:
  vision: gemini                 # AI 분석: claude | chatgpt | gemini
  background_removal: removebg   # 배경 제거: photoroom | removebg
  enhancement: claid             # 보정: claid | opencv
  shadow: sam_mobile             # 그림자: api_shadow | opencv_extract | sam_mobile | sam_cpu | sam_gpu | none

auto_options:
  claid: manual                  # manual | ai_auto
  opencv: manual
  photoroom: manual
  shadow: ai_auto

shadow_extract:
  opacity: 40
  threshold: 15
  blur: 18.0
  search_top: 10
  search_bottom: 150
  search_sides: 80
  mask_expand: 3.0
  distance_falloff: 60
```

### 6.2 prompts.yaml
- `analysis.system`: AI 역할 정의 (럭셔리 이커머스 전문 분류기)
- `analysis.user_template`: 이미지 분석 요청 + JSON 스키마 정의
  - 20개 이상 필드 (image_type, category, shadow, hand, enhance 등)
  - 각 필드에 상세한 가이드라인과 범위 명시

### 6.3 categories.yaml
- 13개 카테고리 (bag, shoes, clothing, wallet, belt, scarf 등)
- `padding_860`: 860px 기준 상하좌우 여백
- `thumbnail_padding`: 썸네일용 여백
- `default`: 미분류 상품용 기본 여백

---

## 7. API 키 & 외부 서비스

| 서비스 | 환경변수 | 용도 | 필수 여부 |
|--------|---------|------|-----------|
| Anthropic (Claude) | ANTHROPIC_API_KEY | AI 비전 분석 | 비전=claude일 때 |
| OpenAI (ChatGPT) | OPENAI_API_KEY | AI 비전 분석 | 비전=chatgpt일 때 |
| Google (Gemini) | GEMINI_API_KEY | AI 비전 분석 | 비전=gemini일 때 |
| Photoroom | PHOTOROOM_API_KEY | 배경 제거 | BG=photoroom일 때 |
| remove.bg | REMOVEBG_API_KEY | 배경 제거 | BG=removebg일 때 |
| Claid.ai | CLAID_API_KEY | 색상 보정 | 보정=claid일 때 |

---

## 8. 의존성 & 설치

### 8.1 requirements.txt

```
requests>=2.31.0
anthropic>=0.39.0
openai>=1.0.0
google-genai>=1.0.0
Pillow>=10.0.0
numpy>=1.24.0
click>=8.1.0
python-dotenv>=1.0.0
pyyaml>=6.0
loguru>=0.7.0
pytest>=8.0.0
opencv-python>=4.8.0
timm>=0.9.0
tenacity>=8.0.0
```

### 8.2 선택 설치 (SAM)
```bash
# PyTorch (CPU)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# PyTorch (CUDA 11.8 - GPU)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118

# MobileSAM
pip install git+https://github.com/ChaoningZhang/MobileSAM.git

# SAM
pip install segment-anything
```

### 8.3 자동 의존성 설치
- `gui.py` 시작 시 `_check_and_install_deps()` 실행
- 필수 패키지 누락 시 자동 `pip install`
- 선택 패키지(SAM, torch) 누락 시 경고 메시지

---

## 9. 에러 처리 & 복구 전략

| 상황 | 처리 방식 |
|------|----------|
| Gemini 503 UNAVAILABLE | 5회 재시도, 지수 백오프 (2~60초) |
| JSON 파싱 실패 | 4단계 폴백 (직접 파싱 → 코드 블록 → 정규식 → 잘린 JSON 복구) |
| 배경 제거 실패 | 예외 로그 후 원본 이미지 사용 |
| SAM 모델 없음 | FileNotFoundError + 다운로드 URL 안내 |
| JPEG 용량 초과 | 품질 감소 (95→60) 반복 |
| 배치 중 개별 이미지 오류 | 해당 이미지 실패 기록, 나머지 계속 처리 |
| 손 크롭 영역 부족 | 크롭 생략, 원본 유지 |
| API 키 누락 | 실행 전 검증, 경고 다이얼로그 |

---

## 10. 성능 특성

| 단계 | 소요 시간 |
|------|-----------|
| AI 비전 분석 | 3~10초 |
| 배경 제거 (Photoroom) | 5~15초 |
| 그림자 추출 (SAM Mobile) | 3~5초 |
| 그림자 추출 (SAM CPU vit_b) | 10~30초 |
| 그림자 추출 (SAM GPU) | 2~5초 |
| 색상 보정 (Claid) | 10~20초 |
| 색상 보정 (OpenCV) | 1~2초 |
| JPEG 최적화 | 1~2초 |
| **총 단일 이미지** | **30~120초** |
| 메모리 사용량 | ~500MB (SAM GPU 모드) |

---

## 11. 배치 처리 흐름

```
1. 입력 폴더 스캔 (jpg, jpeg, png, bmp, tiff, webp)
2. 첫 번째 이미지로 카테고리 감지
3. 이미지별 순차 처리 (1초 간격 API 호출)
4. on_progress 콜백으로 진행률 업데이트
5. is_cancelled 콜백으로 중지 지원
6. 결과 집계: 성공/실패 개수, 생성된 파일 수
```

---

## 12. 신규 개발 시 환경 셋업

```bash
# 1. Python 3.10+ 설치
# 2. 프로젝트 클론/복사
cd D:\CLAUDE_CODE_WORK\shop-image-editor

# 3. 의존성 설치
pip install -r requirements.txt

# 4. PyTorch + SAM (선택)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install git+https://github.com/ChaoningZhang/MobileSAM.git
pip install segment-anything

# 5. API 키 설정 (.env 파일 생성)
# ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...
# GEMINI_API_KEY=AIza...
# PHOTOROOM_API_KEY=...
# CLAID_API_KEY=...
# REMOVEBG_API_KEY=...

# 6. SAM 체크포인트 다운로드 (models/ 폴더)
# mobile_sam.pt (40.7MB) - MobileSAM
# sam_vit_b_01ec64.pth (375MB) - SAM VIT-B

# 7. 실행
python gui.py
# 또는
run_gui.bat
```

---

## 13. 주요 알고리즘 참고

### 13.1 거리 기반 그림자 감쇠
```python
dist = cv2.distanceTransform(255 - product_mask, cv2.DIST_L2, 5)
falloff_pct = config.get("distance_falloff", 60) / 100.0
max_range = max(30, int(max(prod_w, prod_h) * falloff_pct))
dist_falloff = np.clip(1.0 - (dist / max_range), 0, 1)
dist_falloff = np.sqrt(dist_falloff)  # sqrt 커브 → 자연스러운 감쇠
```

### 13.2 BFS 아티팩트 제거
- 4배 축소 이미지에서 비-백색 픽셀 BFS
- 최대 연결 성분 = 상품 본체
- 나머지 작은 성분 = 노이즈 → 흰색으로 채움

### 13.3 JPEG 품질 이진 탐색
- 목표: 지정 KB 이하에서 최대 품질
- 시작 95, 5씩 감소, 최소 60

---

## 14. 향후 확장 고려사항

- [ ] 다중 스레드 배치 처리 (현재 순차)
- [ ] 추가 배경 제거 API 연동 (예: Clipdrop)
- [ ] 워터마크 자동 추가
- [ ] 이미지 비교 뷰 (원본 vs 결과)
- [ ] 웹 UI 버전 (Flask/Streamlit)
- [ ] 프리셋 저장/불러오기 (카테고리별 최적 설정 묶음)
