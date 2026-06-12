# image-2.0 프롬프트 자동 공유 설정 가이드 (관리자 1회 설정)

한 명이 조건 탭에서 프롬프트를 **저장**하면 GitHub의 공유 파일에 자동 푸시되고,
다른 사용자는 **프로그램 시작 시 자동으로 받아 적용**됩니다 (마지막 저장자 우선).

`.env`에 설정이 없으면 이 기능은 완전히 꺼져 있으며 기존과 동일하게 동작합니다.

---

## 1. 프롬프트 전용 저장소 만들기 (권장: 새 private 저장소)

> 코드 저장소(shop-image-editor)와 분리하는 이유: 토큰이 유출돼도
> 프로그램 코드/자동업데이트는 절대 건드릴 수 없게 하기 위함입니다.

1. https://github.com/new 접속
2. Repository name: `shop-editor-shared`
3. **Private** 선택 → Create repository
   (빈 저장소면 됩니다. README 추가 체크해도 무방)

## 2. 토큰(PAT) 만들기 — 이 저장소만 쓸 수 있는 열쇠

1. https://github.com/settings/personal-access-tokens/new 접속
2. Token name: `shop-editor-prompts`
3. Expiration: 1년 (만료되면 같은 방법으로 재발급)
4. Repository access: **Only select repositories** → `shop-editor-shared` 선택
5. Permissions → Repository permissions → **Contents: Read and write**
   (다른 권한은 모두 No access 유지)
6. Generate token → `github_pat_...` 로 시작하는 토큰 복사 (한 번만 보임!)

## 3. 사용자 3명의 PC에 .env 두 줄 추가

각 PC의 EXE 옆 `.env` 파일에 아래 두 줄을 추가:

```
SHARED_PROMPTS_REPO=kimyoungho0505/shop-editor-shared
SHARED_PROMPTS_TOKEN=github_pat_여기에_복사한_토큰
```

(선택) 브랜치가 main이 아니면: `SHARED_PROMPTS_BRANCH=브랜치명`

## 4. 끝 — 동작 방식

| 상황 | 동작 |
|---|---|
| 누군가 조건 탭에서 [저장] | 로컬 저장 + 공유 저장소에 자동 푸시 (로그: "전체 사용자에게 공유됨") |
| 다른 사용자가 프로그램 시작 | 공유본을 받아 자동 적용 (로그: "공유본 자동 적용됨") |
| 인터넷 안 될 때 저장 | 보류 표시 후 다음 실행 때 자동 재푸시 |
| 동시에 두 명이 저장 | 마지막 저장자의 내용으로 통일 (last-writer-wins) |

## 문제 해결

- 공유가 안 되면: `.env`의 REPO/TOKEN 오타 확인, 토큰 만료 확인
- 특정 PC만 공유 끄기: 그 PC의 `.env`에서 두 줄 삭제
- 잘못된 프롬프트가 퍼졌을 때: 아무나 올바른 내용으로 다시 저장하면 됨
