# 작업 큐 & 진행 추적 시스템 설계

**날짜:** 2026-04-17  
**상태:** 승인됨  
**대상 파일:** `gui.py`, `src/pipeline.py`, `gui_pyside/` (선택적)

---

## 배경 및 목적

배치 처리 중 프로그램이 예기치 않게 종료(충돌, KeyboardInterrupt 등)될 경우,
어떤 파일이 완료되었고 어떤 파일이 미처리로 남았는지 파악할 방법이 없었다.
이 시스템은 파일별 처리 상태를 영속적으로 저장하고, 중단 후 미완료 파일만
선택적으로 재처리할 수 있게 한다.

---

## 데이터 구조

### 세션 파일 위치

```
app_dir/sessions/{md5(입력폴더절대경로)}.json
```

`app_dir`는 `gui.py`의 `APP_DIR` (실행 파일 기준 디렉터리).

### 세션 JSON 스키마

```json
{
  "input_folder": "D:/images/product",
  "created_at": "2026-04-17T10:00:00",
  "updated_at": "2026-04-17T10:45:00",
  "total": 24,
  "files": {
    "061.jpg": {
      "status": "done",
      "output": ["001_1.jpg", "001_2.jpg"],
      "finished_at": "2026-04-17T10:10:00"
    },
    "062.jpg": {
      "status": "failed",
      "error": "Remove.bg API 오류: 402 - insufficient_credits",
      "finished_at": "2026-04-17T10:15:00"
    },
    "063.jpg": {
      "status": "pending"
    }
  }
}
```

**status 값:**
| 값 | 의미 |
|----|------|
| `pending` | 아직 처리 안 됨 |
| `processing` | 현재 처리 중 (비정상 종료 시 이 상태로 남음 → 재시작 시 `pending`으로 간주) |
| `done` | 완료 |
| `failed` | 오류로 실패 |

> 시작 시 `processing` 상태인 파일은 모두 `pending`으로 재설정 (충돌 감지).

---

## 신규 모듈: `src/session_manager.py`

단일 책임: 세션 파일 읽기/쓰기/초기화.

```python
class SessionManager:
    def __init__(self, app_dir: Path): ...

    def get_session_path(self, input_folder: str) -> Path:
        """입력 폴더 경로를 MD5 해시하여 세션 파일 경로 반환."""

    def load(self, input_folder: str) -> dict | None:
        """세션 로드. 없으면 None. processing 상태를 pending으로 정정."""

    def create(self, input_folder: str, file_list: list[str]) -> dict:
        """새 세션 생성 (전체 파일 pending으로 초기화)."""

    def update_file(self, input_folder: str, filename: str,
                    status: str, output: list[str] = None, error: str = None):
        """단일 파일 상태 즉시 저장 (처리 중 충돌 대비)."""

    def reset(self, input_folder: str) -> dict:
        """세션 초기화 (전체 다시 실행용)."""

    def get_pending_files(self, session: dict) -> list[str]:
        """pending + failed 파일 목록 반환."""
```

---

## GUI 변경: `gui.py`

### 작업 현황 패널 추가

메인 탭 내 기존 로그 영역 아래(또는 우측)에 `Treeview` 기반 파일 상태 패널 추가.

```
┌─ 작업 현황 (마지막: 2026-04-17 10:45) ───────────────────┐
│ 파일명          상태      출력파일          완료시각       │
│ ✓ 061.jpg      완료      001_1.jpg         10:10          │
│ ✗ 062.jpg      실패      크레딧 부족        10:15          │
│ ─ 063.jpg      대기      -                  -              │
│ ─ 064.jpg      대기      -                  -              │
├───────────────────────────────────────────────────────────┤
│  [전체 다시 실행]            [미완료만 이어서 처리]         │
└───────────────────────────────────────────────────────────┘
```

**색상 코딩:**
- 완료(done): 초록 텍스트
- 실패(failed): 빨강 텍스트
- 대기(pending): 기본 회색
- 처리중(processing): 파랑 텍스트

### 버튼 동작

| 버튼 | 동작 |
|------|------|
| 미완료만 이어서 처리 | `pending + failed` 파일만 큐에 넣고 배치 시작 |
| 전체 다시 실행 | 세션 초기화 후 전체 파일 처리 |

### 자동 로드 시점

1. **프로그램 시작 시**: 마지막 세션(`gui_state.json`의 `input_folder` 기준) 자동 복원
2. **폴더 선택 시**: 해당 폴더의 세션 파일 탐색 → 있으면 패널 갱신, 없으면 빈 상태

---

## Pipeline 변경: `src/pipeline.py`

`process_batch()` 및 병렬 `_batch_one()`에 세션 업데이트 훅 추가.

```python
def process_batch(
    self,
    ...,
    session_manager: SessionManager = None,   # 신규
    input_folder: str = None,                  # 신규
    file_list: list[str] = None,               # 신규 (미완료 파일만 처리 시)
):
```

처리 흐름:
1. 파일 처리 시작 전 → `session_manager.update_file(..., status="processing")`
2. 처리 완료 → `session_manager.update_file(..., status="done", output=[...])`
3. 처리 실패 → `session_manager.update_file(..., status="failed", error=str(e))`

`file_list`가 주어지면 해당 파일만 처리 (이어서 처리 모드).

---

## 오류 처리

- 세션 파일 읽기/쓰기 실패 → 로그 경고만, 처리는 계속 진행 (세션 기능은 부가 기능)
- `processing` 상태 파일 재시작 시 `pending`으로 자동 복구
- 출력 폴더가 바뀐 경우 세션은 유지되나 출력 파일 경로가 달라짐 → 표시만 하고 재처리 허용

---

## 구현 범위 (이번 스프린트)

- [x] `src/session_manager.py` 신규 생성
- [x] `gui.py` 작업 현황 패널 UI 추가
- [x] `gui.py` 폴더 선택 / 시작 시 세션 자동 로드
- [x] `src/pipeline.py` 세션 업데이트 훅 연결
- [x] "미완료만 이어서 처리" / "전체 다시 실행" 버튼 구현

**범위 외 (이번 구현 제외):**
- PySide6 GUI (`gui_pyside/`) 동일 기능 이식 — 별도 작업
- 세션 내역 내보내기(CSV/JSON export)
- 세션 자동 만료(오래된 기록 삭제)
