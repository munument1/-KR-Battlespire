# 배틀스파이어 한국어 패처 0.1.0

Steam판 *An Elder Scrolls Legend: Battlespire* 1.5용 한국어 패치입니다. Preview 표기를 제거한 일반 릴리스로 배포합니다.

## 변경 내용

- **Steam 전체화면 표시 개선**: DOSBox 0.73의 `output=surface` 강제 설정을 제거하고 원래 Steam 설정의 `output=ddraw`를 유지하도록 변경했습니다. `fullresolution=desktop`, `windowresolution`, `scaler`, 화면 비율은 기존 Steam 설정을 보존합니다.
- Steam **플레이** 버튼에서 그대로 한국어판이 실행되도록 원래 `Battlespire (Full Screen).bat` 및 `Battlespire (Windowed).bat` 구조를 유지했습니다.
- `core=dynamic`, `cycles=max`, `memsize=63` 등 게임 실행에 필요한 구성은 유지했습니다.
- 이전 Preview 2의 한글 엔진·번역 내용과 RSC 특수 제어 바이트 수정은 그대로 보존합니다.
- **0.1.0-preview1 및 0.1.0-preview2** 설치본에서 원본 복원 없이 업데이트할 수 있습니다. 이전 릴리스의 설치 파일 및 원본 백업을 검증한 뒤 업그레이드합니다.

## 설치

1. 실행 중인 배틀스파이어와 DOSBox를 종료합니다.
2. `BattlespireKoreanPatcher-0.1.0-Windows-x64.zip`을 내려받아 압축을 해제합니다.
3. `BattlespireKoreanPatcher.exe` 실행 후 `GAME.EXE`가 들어 있는 Steam 게임 폴더를 선택합니다.
4. **원본 검사 → 한국어 패치 적용**을 누릅니다.
5. Steam의 **플레이** 버튼에서 원하는 화면 모드로 실행합니다. 별도의 `START_KOREAN.bat` 실행은 필요 없습니다.

## 제한 및 안전

원본 파일의 SHA-256 검사, 자동 백업, 손상 탐지, 원본 복원 기능을 제공합니다. 게임 원본 파일 전체 대신 차분 패치만 배포합니다.

변경된 구성과 설치·복원 자동 테스트는 통과했지만, 모든 모니터에서의 실제 Steam 전체화면 동작 및 게임 텍스트의 전수 인게임 검증까지 완료한 것은 아닙니다. 이전에 보고된 본문 중 남은 물음표 1개도 별도 확인이 필요합니다.
