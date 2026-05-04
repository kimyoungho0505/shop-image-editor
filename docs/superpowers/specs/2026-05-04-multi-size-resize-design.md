# 멀티 사이즈 리사이징 기능 설계

**작성일:** 2026-05-04
**대상 모듈:** `src/exporter/resizer.py`, `src/pipeline.py`, `gui3.py`, `config/settings.yaml`

---

## 1. 배경 & 목표

쇼핑몰 업로드용 이미지를 편집 완료 후 자동으로 3가지 사이즈로 변환하고, 편집 원본을 보존하여 이후 재리사이징이 가능하도록 한다.

**입력:** 편집 완료된 2250×2250 이미지 (PIL bytes 또는 파일)
**출력:** 4개 결과물 (배치 단위)

| 결과물 | 사이즈 | 명명 규칙 | 위치 | 생성 조건 |
|--------|--------|----------|------|----------|
| 편집 원본 보존 | 2250×2250 | `{원본명}_1.jpg` | `output/original/` | 항상 |
| 메인 사이즈 | 1500×1500 | `{n}.jpg` (1, 2, 3...) | `output/1500/` | 항상 |
| 리스트용 | 860×860 | `100_{n}.jpg` | `output/860/` | 항상 |
| 세로 크롭 | 1500×2250 | `main.jpg` | `output/crop/` | 배치 첫 이미지만 |

`{n}`은 **배치 전체 통합 순번** (한 번의 처리 실행에서 1부터 증가).

---

## 2. 아키텍처

### 2.1 모듈 구성

```
src/exporter/
  resizer.py          ← 신규 (또는 기존 비어있는 파일 확장)
    ├─ class BatchCounter     : thread-safe 순번 발급기
    └─ class MultiSizeResizer : 4개 출력물 저장
```

### 2.2 BatchCounter

```python
class BatchCounter:
    """배치 단위 thread-safe 순번 카운터.

    GUI에서 배치 시작 시 1개 생성, 모든 워커 스레드에 공유.
    """
    def __init__(self):
        self._n = 0
        self._first_consumed = False
        self._lock = threading.Lock()

    def next(self) -> int:
        """다음 순번 반환 (1부터 시작). thread-safe."""
        with self._lock:
            self._n += 1
            return self._n

    def is_first(self) -> bool:
        """이번 호출자가 배치의 첫 번째인지 — True 1회만 반환.

        호출 즉시 소비되므로 동시성 안전하게 '딱 1회만' True.
        """
        with self._lock:
            if self._first_consumed:
                return False
            self._first_consumed = True
            return True
```

### 2.3 MultiSizeResizer

```python
class MultiSizeResizer:
    """편집 완료 이미지 → 4개 출력물 저장.

    설정은 settings.yaml의 `resize:` 섹션에서 로드.
    """
    def __init__(self, output_dir: Path, settings: dict, optimizer: ImageOptimizer):
        self.output_dir = Path(output_dir)
        self.cfg = settings.get("resize", {})
        self.optimizer = optimizer

    def save_original(self, img_bytes: bytes, original_stem: str) -> Path:
        """output/original/{stem}_1.jpg 로 저장 (2250×2250 보존)."""

    def make_resized_set(
        self,
        img_bytes: bytes,
        seq_n: int,
        is_first: bool,
        on_log: Callable[[str], None] = None,
    ) -> dict:
        """3가지 리사이즈 사이즈 생성.

        Returns: {
            "size_1500": Path | None,
            "size_860":  Path | None,
            "crop":      Path | None,  # is_first일 때만
        }
        """

    def resize_from_file(
        self,
        source_path: Path,
        seq_n: int,
        variants: dict[str, bool],   # {"size_1500": True, "size_860": True, "crop": False}
        overwrite: bool = True,
    ) -> dict:
        """기존 파일에서 재리사이징 (리사이징 전용 탭 / 뷰파인더 재실행용).

        Returns: 같은 dict 형태.
        """
```

### 2.4 리사이즈 알고리즘

- **1500×1500, 860×860**: `Image.resize((W, H), Image.LANCZOS)` — 입력이 정사각형이라 비율 유지됨
- **1500×2250 크롭**: `img.crop((375, 0, 1875, 2250))` — 좌측 375, 우측 375 제거. 별도 리사이즈 없음 (이미 2250 높이)
- **저장**: `ImageOptimizer.save_from_bytes()` 재사용 (max 2024KB JPEG)
- **입력 사이즈 검증**: 입력이 `base_size`(2250)와 다르면 경고 로그 + 자동으로 `(2250, 2250)`로 먼저 리사이즈 후 진행. 크롭은 항상 base_size 기준 좌우 375 제거.

---

## 3. 파이프라인 통합

### 3.1 흐름

```
GUI._start_unified_processing()
  ├─ batch_counter = BatchCounter()
  ├─ resizer = MultiSizeResizer(output_dir, settings, optimizer)
  └─ for 이미지 in 이미지목록 (병렬):
       └─ GUI._process_one(이미지, batch_counter, resizer)
            ├─ pipeline.process_single_unified_photoroom(...) → final_bytes 반환
            ├─ resizer.save_original(final_bytes, stem)
            ├─ n = batch_counter.next()
            ├─ first = batch_counter.is_first()
            └─ resizer.make_resized_set(final_bytes, n, first)
```

### 3.2 pipeline 변경

`process_single_unified_photoroom()` 반환값에 `final_bytes` 추가:

```python
return {
    "success": True,
    "final_bytes": current_bytes,    # 신규 — 최종 편집 bytes
    "original_stem": Path(image_path).stem,
    "files": [info],                  # 기존 (호환성, original/ 저장본)
    "path": image_path,
    "image_type": image_type,
    "background": background,
    "shooting_angle": shooting_angle,
    "is_label_cut": is_label_cut,
}
```

기존 `FileNamer` 저장 로직은 **`save_original()` 안으로 이동** — pipeline은 더 이상 직접 저장하지 않음. 관심사 분리.

### 3.3 실패 처리

- pipeline 자체 실패 → resizer 호출 안 함, 순번 소비 안 함
- 크레딧 부족(402) → 즉시 전체 중단 (기존 동작 유지)
- resizer 단독 실패 → 로그만 남기고 다음 이미지 진행 (편집 결과는 `original/`에 보존됨)

### 3.4 뷰파인더 연동

`_vf_complete_file()`에 4개 결과 경로 모두 등록:

```python
result["resized"] = {
    "original": Path(...),
    "size_1500": Path(...),
    "size_860": Path(...),
    "crop": Path(...) or None,
}
```

뷰파인더 카드는 `size_1500` 결과를 썸네일로 표시.

---

## 4. 리사이징 전용 탭 (재실행)

메인 윈도우에 신규 탭 "리사이징" 추가.

### 4.1 UI 구성

```
┌─ 탭: 리사이징 ────────────────────────────────────┐
│ [폴더 선택] [output/original 폴더 경로...........]│
│                                                    │
│ 발견된 이미지: 12장                                │
│ (정렬: 자연순 — 상품명_1, 상품명_2, ...)            │
│                                                    │
│ 출력 사이즈:                                       │
│   ☑ 1500×1500   (output/1500/)                     │
│   ☑ 860×860     (output/860/)                      │
│   ☑ 1500×2250 크롭 (output/crop/, 첫 이미지만)      │
│                                                    │
│ 출력 폴더: ☐ 같은 위치  ☑ 별도 지정 [경로...]       │
│                                                    │
│ 덮어쓰기: ☑ 기존 파일 덮어쓰기                      │
│                                                    │
│ [리사이징 시작]                                    │
│                                                    │
│ 진행: ████████░░░░  8/12                           │
│ 로그 영역                                          │
└────────────────────────────────────────────────────┘
```

### 4.2 동작

1. 사용자가 폴더 선택 → `Path.glob("*.jpg")` + 자연순 정렬로 이미지 목록 구성
2. "리사이징 시작" 클릭 → 새 `BatchCounter` + `MultiSizeResizer`로 순회
3. 출력 폴더가 입력 폴더와 같고 결과 파일이 이미 있으면 **덮어쓰기 확인 다이얼로그** 1회만 표시 (전체 적용)
4. 진행률 바 + 로그로 상태 표시
5. 동일 `MultiSizeResizer.resize_from_file()` 메서드 사용 → 코드 중복 0

---

## 5. 뷰파인더 리사이즈 옵션

뷰파인더의 각 완료 이미지 카드에 "리사이즈" 버튼 추가.

### 5.1 카드 UI

```
┌─ 이미지 카드 ──────────────────┐
│  [편집된 이미지 썸네일 표시]    │
│  상품명_1.jpg                    │
│  ✓ 편집 완료 | 1500×1500 ✓      │
│  [원본보기] [리사이즈] [폴더열기]│
└──────────────────────────────────┘
```

### 5.2 리사이즈 다이얼로그

```
┌─ 리사이즈 옵션 ─────────────────┐
│ 대상: 상품명_1.jpg                │
│                                   │
│ ☑ 1500×1500                       │
│ ☑ 860×860                         │
│ ☐ 1500×2250 크롭                   │
│                                   │
│ ☑ 기존 파일 덮어쓰기                │
│                                   │
│ [실행] [취소]                     │
└───────────────────────────────────┘
```

### 5.3 동작

- 원본은 `output/original/{stem}_1.jpg` 에서 로드
- 순번은 카드의 현재 인덱스(`vf_idx + 1`) 사용
- 1500×2250 크롭은 자동 첫 이미지 제한 무시하고 수동 생성 가능

---

## 6. 설정 (config/settings.yaml)

```yaml
output:
  width: 1000          # deprecated (보존만)
  height: 1000
  max_file_size_kb: 2024
  background_color: [255, 255, 255]
  default_jpeg_quality: 95

# ── 신규 ──
resize:
  enabled: true
  base_size: 2250      # 편집 결과물 기준

  variants:
    size_1500:
      enabled: true
      size: 1500
      subfolder: "1500"
      naming: "{n}.jpg"

    size_860:
      enabled: true
      size: 860
      subfolder: "860"
      naming: "100_{n}.jpg"

    crop_vertical:
      enabled: true
      width: 1500
      height: 2250
      crop_left: 375
      crop_right: 375
      subfolder: "crop"
      filename: "main.jpg"
      first_only: true

  preserve_original:
    enabled: true
    subfolder: "original"
    naming: "{stem}_1.jpg"

  jpeg_max_size_kb: 2024
  jpeg_quality: 95
```

---

## 7. 테스트 계획

### 7.1 단위 테스트

| 항목 | 검증 |
|------|------|
| `BatchCounter.next()` | 1, 2, 3 순서 보장 (단일 스레드) |
| `BatchCounter.next()` 동시성 | 100스레드 동시 호출 시 1~100 정확히 1회씩 |
| `BatchCounter.is_first()` | 첫 호출만 True, 이후 모두 False |
| `MultiSizeResizer.save_original()` | 2250 그대로 저장됨 |
| `MultiSizeResizer.make_resized_set()` | 1500×1500, 860×860 정확한 사이즈 |
| 1500×2250 크롭 좌우 375 절단 | 픽셀 검증 |
| `is_first=False`이면 crop 결과 없음 | None 반환 |

### 7.2 통합 테스트

- 5장 이미지 배치 처리 → `output/1500/`, `output/860/`, `output/original/`에 정확히 5장씩, `output/crop/`에 1장
- 리사이징 전용 탭으로 같은 폴더 재실행 → 결과 동일
- 뷰파인더에서 개별 이미지 리사이즈 → 해당 인덱스 파일만 갱신

### 7.3 실제 구동 테스트 (CLAUDE.md 규칙)

`gui3.py` 실행 → 실제 이미지 5장으로 배치 처리 → 4개 폴더에 결과물 생성 확인 → 음성 "완료되었습니다" 출력.

---

## 8. 구현 순서

1. `src/exporter/resizer.py` 작성 (`BatchCounter`, `MultiSizeResizer`)
2. `config/settings.yaml`에 `resize:` 섹션 추가
3. `src/pipeline.py` `process_single_unified_photoroom()` 반환값 수정 (`final_bytes` 추가)
4. `gui3.py` `_start_unified_processing()` / `_process_one()`에 카운터+리사이저 통합
5. 단위 테스트 작성 & 실행
6. 메인 윈도우에 "리사이징" 탭 추가 + 재실행 워커
7. 뷰파인더 카드에 리사이즈 버튼 + 다이얼로그 추가
8. 실 이미지 통합 테스트 + 음성 알림
