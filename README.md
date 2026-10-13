# 배틀스파이어 한국어 패처

**[Windows 패처 다운로드](https://github.com/munument1/-KR-Battlespire/releases)**

An Elder Scrolls Legend: Battlespire **Steam 1.5 원본**에 한국어 번역과 한글 출력 패치를 적용합니다. Python 설치 없이 실행하는 Windows 프로그램을 제공합니다. 대사·서적·이미지 UI와 함께 **GAME.EXE 내부 직업/기술 화면, 능력치, 상단 메시지와 도움말**을 포함합니다.

현재 버전은 **0.1.0-preview1 시험 배포판**입니다. 파일 형식·CPU 코드·설치/복원을 검사했으며 실제 게임의 모든 화면과 분기를 전수 확인한 정식 완성판은 아닙니다. GOG 등 다른 버전은 해시가 다르면 적용하지 않습니다.

## 사용법

1. 실행 중인 게임을 종료합니다.
2. Releases에서 ZIP을 받아 풀고 `BattlespireKoreanPatcher.exe`를 실행합니다.
3. `GAME.EXE`가 있는 배틀스파이어 설치 폴더를 선택합니다.
4. **원본 검사 → 한국어 패치 적용**을 누릅니다.
5. 게임 폴더에 만들어진 **START_KOREAN.bat**로 실행합니다.

원본은 게임 폴더의 `_Battlespire_Korean_Backup/0.1.0-preview1/`에 보관합니다. 되돌릴 때는 패처에서 같은 게임 폴더를 선택하고 **원본 복원**을 누릅니다. 저장 파일과 사용자가 새로 만든 직업은 대상에 포함하지 않습니다. 기존 저장에 들어 있는 영문 이름이 그대로 남을 수 있습니다.

패치 후 사용자가 다른 모드로 바꾼 파일은 복원 과정에서 덮어쓰지 않습니다. 지원하지 않는 버전·부분 적용·손상된 패치/백업도 검사하여 중단합니다. 적용 도중 일반적인 쓰기 오류가 발생하면 이미 바꾼 게임 파일을 되돌립니다. 강제 종료 뒤에는 백업 복원을 실행할 수 있습니다.

## 적용 범위

| 대상 | 범위 |
|---|---:|
| 대사 | 76표 / 2,275필드 + 원문 줄바꿈 누락 구절 보완 |
| 서적·편지 | 59개 / 1,135필드 |
| RSC 설명 | 본문 204개 + 빈 슬롯 표시 68개 |
| 아이템 이름 수식어·고유명 | 463개 |
| SPIRE 설명 | 143줄 |
| EXE 메시지·도움말·기술·능력치·재질명 | 628개 |
| EXE 기본 주문·장비·괴물명 | 90개 |
| 직업 이름 | 18종 |
| 지역·지도 이름 | 17개 |
| 이미지 UI | 승인된 UI 14 번역본 |
| 동적 글꼴 | 갈무리11/7, 필요한 한글 1,126자 |

아이템의 32바이트 고정 이름 칸에는 짧은 식별자를 저장하고 표시할 때 전체 한국어 이름을 불러옵니다. EXE 메시지 포인터도 외부 한국어 문자열로 연결합니다. 퍼즐 영문 입력값·진명, 실행 명령, 자원 파일명은 보존합니다. 드라이버 진단문·개발 로그·일부 영상에 들어 있는 영어는 위 수치에 포함하지 않습니다.

게임 원본 EXE/BSA/RSC/FNT, 영상, 사운드는 배포하지 않습니다. `assets/korean-patch.zip`에는 원본을 요구하는 **차분**과 새 한국어 문자열·설정만 들어 있습니다. 특히 BSA는 항목별 압축 해제 원본에 차분을 적용해 다시 조립하므로 바뀌지 않은 그림 전체를 배포 데이터에 넣지 않습니다.

## 검증

[검증 범위와 결과](docs/VERIFICATION.md)를 참조하세요. 원본이 없는 CI는 설치기 합성 테스트를 수행하며, 실제 게임 데이터의 검증과 구분합니다.

## 소스로 실행

Python 3.11 이상과 Tk를 사용합니다.

```powershell
python -m pip install -r requirements.txt
python patcher.py
# 명령행
python patcher.py --game "C:\Games\Battlespire" --check
python patcher.py --game "C:\Games\Battlespire" --apply
python patcher.py --game "C:\Games\Battlespire" --restore
python -m unittest discover -s tests -v
```

Windows 실행 파일 빌드:

```powershell
python -m pip install -r requirements-build.txt
python -m PyInstaller --clean --noconfirm --onefile --windowed --name BattlespireKoreanPatcher --add-data "assets;assets" --add-data "licenses;licenses" patcher.py
```

개발용 차분 재생성에는 본인이 보유한 호환 원본과 검수된 번역 게임 폴더가 필요합니다. 기존 출력은 덮어쓰지 않습니다.

```powershell
python build_payload.py --original-game "C:\Games\Battlespire-original" --translated-game "C:\Work\translation\game" --output assets/korean-patch-new.zip
```

## 출처

- 서적 참고 번역: [BGS_Translation_Archive](https://github.com/munument1/BGS_Translation_Archive), 원문과 대응해 사용하고 게임 전용 구절은 추가 번역했습니다.
- 동적 글꼴: [Galmuri](https://github.com/quiple/galmuri), SIL Open Font License. 글꼴 비트맵의 원형을 사용합니다.
- 이미지 UI: 솔뫼 김대건 글꼴을 이용해 제작한 한국어 이미지. 원본 TTF/OTF는 이 저장소에 포함하지 않습니다.
- 차분 라이브러리: bsdiff4, BSD 라이선스. Windows 패키징: PyInstaller의 배포 예외 조항을 적용합니다.

설치기 자체 소스는 [MIT](LICENSE)이며 게임 저작물·번역·글꼴의 권리를 바꾸지 않습니다. 게임 원본은 Bethesda/ZeniMax의 저작물입니다.
