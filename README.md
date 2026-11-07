# YouTube Video Analyzer

## GitHub Actions 다운로드 시험

공개 저장소의 표준 실행기에서 단일 영상의 실제 다운로드를 수동 시험하는 워크플로를 추가했습니다. [사용 방법과 제한](docs/cloud-actions.md)을 참고하세요. 원본·아티팩트 업로드·자동 실행은 없으며 결과는 Actions 로그와 요약에서 확인합니다. 이는 기존 로컬 처리 기능과 별도로 실제 YouTube 접근을 검증하는 단계입니다.

유튜브 영상·자막·음성·주요 화면을 ChatGPT에서 분석할 수 있도록 정리하는 반자동 프로그램 개발 프로젝트입니다.

현재 **2단계 자료 확보 및 3단계 프레임 추출 코드를 구현**했습니다. 3단계는 합성 영상으로 검증했습니다. YouTube 접근은 환경 프록시 CONNECT 403으로 차단되어 실제 다운로드 및 통합 검증은 미완료입니다. 전사와 분석 패키지는 아직 구현하지 않았으며 4단계는 승인 후 진행합니다.

## 복원 소스의 이전 환경 기록

아래 도구 버전과 설치 상태는 첨부 소스의 과거 기록이며, 이번 복원에서 재설치하거나 재검증하지 않았습니다.

- 저장소: https://github.com/jkhjkh2754-maker/video-analyze
- 작업 경로: `/workspace/video-analyze`
- Python 3.12.14
- yt-dlp 2026.10.26: 프로젝트 `.venv`에 설치
- FFmpeg / ffprobe 7.1.5
- Debian 13.6, x86_64

## 환경 재구성

Python 및 FFmpeg/ffprobe가 설치된 환경에서 실행합니다. 아래 명령은 Python 도구만 설치하며 FFmpeg는 별도 시스템 설치가 필요합니다.

```bash
cd /workspace/video-analyze
python3 -m venv .venv
.venv/bin/python -m pip install --index-url https://pypi.org/simple -r requirements-tools.txt
.venv/bin/python -m yt_dlp --version
ffmpeg -version
ffprobe -version
```

현재 관리형 환경에서는 기본 샌드박스의 프록시 연결이 실패했습니다. 허용된 외부 실행 경로에서는 GitHub/PyPI 접속과 설치가 성공했습니다. 환경의 프록시 및 TLS 인증서 설정을 유지해야 합니다.

## 현재 제한

현재 환경 재확인 결과 `network_policy.mode=unrestricted`, `state=enforced`, 설정·적용 버전은 모두 `1`입니다. 전체 공용 인터넷 허용 모드에서도 시험 URL의 새 연결은 프록시 CONNECT 단계에서 HTTP 403으로 거부됐습니다. 도메인 추가를 반복할 상황이 아니며, 환경 서비스의 접근 제한 문제로 기록했습니다. 상세 값과 근거는 [현재 네트워크 검증](docs/current-network-verification.md)을 참고하세요.

시험 URL은 https://youtu.be/Z0aXJeC4HiE 입니다. 영상 서버 응답을 받지 못해 공개·재생 가능 여부는 미확인입니다. 로그인·지역·연령·멤버십 등 영상 자체의 접근 제한은 우회하지 않습니다.

자막이 없을 때 사용할 무료 로컬 음성 인식 모델은 아직 설치·검증하지 않았습니다. 유료 API, 유료 서버, 크레딧 구매, 자동 충전은 사용하지 않습니다. ChatGPT 자료 자동 전송 기능도 구현하지 않습니다.

원본 영상, 생성 자료, 모델 및 가상환경은 `.gitignore`로 제외합니다. 생성할 자료는 제외된 디렉터리에 보관하고, 커밋 전 파일 목록을 확인해야 합니다.

자세한 확인 결과와 미검증 항목은 [1단계 점검 보고서](docs/stage-1-environment.md)를 참고하세요.


## 2단계 사용법

이용 권한이 있는 공개 또는 일부 공개 단일 영상 URL을 지정합니다.

```bash
.venv/bin/python analyzer.py 'https://youtu.be/Z0aXJeC4HiE' --languages ko,en --output downloads --timeout 3600
```

- 실행마다 별도 디렉터리를 생성합니다. `metadata.json`에 제목·길이·출처·채널·자막 언어를, `result.json`에 상태·파일 목록·오류를 기록합니다.
- 영상은 `video.*`, 수동 또는 자동 자막은 `video.<언어>.vtt`에 저장합니다. 같은 언어에는 수동 자막을 우선합니다. 기본 요청 언어는 한국어와 영어입니다.
- 실제 영상 파일 존재·크기와 ffprobe의 영상 스트림 확인 후에만 `acquired`로 기록합니다. 이는 자료 확보 상태이며 전체 분석 완료를 뜻하지 않습니다.
- 자막이 없으면 `local_transcription_pending`으로 명시합니다. 무료 로컬 음성 인식은 아직 구현하지 않았습니다.
- `processing.log`는 진단용 로컬 파일입니다. 공유 전 내용을 확인하세요. 중단된 다운로드 파일이 남을 수 있습니다.
- 종료 코드: 0=영상 확보, 1=처리 실패, 2=입력·사전 조건 오류. 라이브와 재생목록 전체 처리는 지원하지 않습니다.
- 기본값은 가능한 최고 화질이므로 긴 영상은 디스크 사용량이 클 수 있습니다. 현재 여유 공간을 확인하고 실행하세요.

검증: `.venv/bin/python -m unittest discover -s tests -v`

실제 시험 결과와 제한은 [2단계 보고서](docs/stage-2-acquisition.md)를 참고하세요.


## 3단계 사용법

```bash
python frames.py downloads/<실행폴더>/video.mkv --interval 10 --max-images 120
```

로컬 영상도 입력할 수 있습니다. 기본 10초 간격과 장면 변화 후보를 결합하고, 유사·중복을 제거해 PNG와 타임스탬프를 `outputs/frames-…/frames.json`에 기록합니다. 기본 최대 120개이며 이미지가 모두 유사하면 주기 후보도 제거합니다. 자세한 설정, 검증 결과와 한계는 [3단계 보고서](docs/stage-3-frames.md)를 참고하세요. 실제 YouTube 다운로드와 통합 검증은 미완료이며 4단계는 시작하지 않았습니다.
