@echo off
chcp 65001 > nul
echo ============================================================
echo  LUXBOY Shop Image Editor — EXE 빌드
echo ============================================================

:: Python 확인
python --version 2>nul || (echo [오류] Python이 설치되어 있지 않습니다. & pause & exit /b 1)

:: PyInstaller 설치 확인 / 설치
pip show pyinstaller >nul 2>&1 || (
    echo [설치] PyInstaller 설치 중...
    pip install pyinstaller
)

:: UPX 설치 확인 (선택 — 크기 압축용)
where upx >nul 2>&1 && echo [OK] UPX 발견 — 압축 적용 || echo [건너뜀] UPX 없음 (crackle-free 빌드)

:: 이전 빌드 정리
if exist "dist\LUXBOY_ShopEditor.exe" (
    echo [정리] 이전 빌드 삭제...
    del /f /q "dist\LUXBOY_ShopEditor.exe"
)
if exist "build" rmdir /s /q build

:: 빌드 실행
echo.
echo [빌드] PyInstaller 실행 중...
pyinstaller gui3.spec --clean --noconfirm

if errorlevel 1 (
    echo.
    echo [실패] 빌드 오류가 발생했습니다.
    pause
    exit /b 1
)

:: 결과 확인
if exist "dist\LUXBOY_ShopEditor.exe" (
    for %%F in ("dist\LUXBOY_ShopEditor.exe") do (
        set SIZE=%%~zF
    )
    echo.
    echo ============================================================
    echo  [완료] dist\LUXBOY_ShopEditor.exe 생성됨
    echo  크기: %SIZE% bytes
    echo ============================================================
    echo.
    echo 배포 전 .env 파일을 EXE와 같은 폴더에 복사하세요.
    echo (API 키가 .env에 저장됩니다)
) else (
    echo [실패] EXE 파일을 찾을 수 없습니다.
    pause
    exit /b 1
)

pause
