# 소스 복원 및 현재 네트워크 검증

확인일: 2026-11-07 UTC. 3단계는 승인되지 않았으며 진행하지 않았다.

## 소스 복원

첨부 `youtube-analyzer-stage2-source.zip`의 7개 파일을 기존 `/workspace/video-analyze` 저장소에 복원했다. 복원 직후 각 파일이 ZIP 원본과 바이트 단위로 일치함을 확인했다. 기존 `.git`과 `access-check` 기록은 보존했다. 아래 현재 진단을 반영하기 위해 README와 2단계 보고서는 복원 후 갱신했다. 프로그램 코드와 테스트는 변경하지 않았다.

ZIP SHA256: `d7b26a93171a5a4d96ca541b3a20a3abb81f7d9fba07f9485e57373ae1fd3cf7`

ZIP에는 가상환경, 설치된 도구 및 과거 downloads 실행 결과가 포함되지 않았다. 복원 문서의 과거 설치·시험 기록은 현재 환경에서 재현한 결과를 뜻하지 않는다.

## 현재 environment_status

새 연결 전후 조회에서 아래 값이 동일했다.

| 항목 | 값 |
| --- | --- |
| environment_id | `ccarenv_b64_Y2NhcmVudl83MGNiMzkyNDBiMTQ4MTkxOTRlNjExZTAwOTY4ZGNiYg` |
| network_policy.mode | `unrestricted` |
| network_policy.state | `enforced` |
| spec_revision (설정 버전) | `1` |
| observed_spec_revision (적용 버전) | `1` |
| observations_current | `true` |
| source_config_version_id | `b875f24b2518719593a16bf4fb74cffa0484bcc222e979b379d98a27bd5fb844~cecfgver_6aef1eeb46f8819db540c2ba6e648041` |

현재 환경은 **전체 공용 인터넷 허용 모드**이며 제한 허용 목록 모드가 아니다. 설정 버전과 적용 버전이 일치한다. 전체 허용 모드에서도 플랫폼 자체의 목적지 접근 제한은 적용될 수 있다.

## 새 연결 검증

환경이 제공한 프록시와 TLS 검증 설정을 유지하고, 새 curl 프로세스로 각각 요청했다. 앞선 샌드박스의 프록시 연결 실패와 구분하기 위해 승인된 샌드박스 외부 실행 경로를 사용했다.

| URL | http_connect | http_code | curl 종료 코드 |
| --- | --- | --- | --- |
| `https://youtu.be/Z0aXJeC4HiE` | 403 | 0 | 56 |
| `https://www.youtube.com/watch?v=Z0aXJeC4HiE` | 403 | 0 | 56 |

두 요청 모두 `CONNECT tunnel failed, response 403`으로 실패했다. **403은 프록시 CONNECT 단계에서 발생했으며 YouTube 원본 서버의 영상 응답은 수신하지 못했다.** 영상 존재·공개 여부나 로그인 요구 여부를 판정할 수 없다.

정책이 이미 unrestricted/enforced이므로 도메인 추가를 요청하거나 반복하지 않았다. 이번 차단은 **환경 서비스의 프록시/목적지 접근 제한 문제**로 기록한다. 서비스 내부의 구체적인 거부 규칙은 현재 증거만으로 확정하지 못했다. 과거 문서의 제한 모드 및 도메인 추가 안내를 현재 상태에 적용해서는 안 된다.

원시 결과와 CONNECT 응답 헤더: `../access-check/current-policy/results.json`, 같은 디렉터리의 `*.headers.txt`.

이번 작업에서는 영상 다운로드, 전사, 프레임 추출, 3단계 구현, 환경 정책 변경, 패키지 설치, Git 커밋·push를 수행하지 않았다.
