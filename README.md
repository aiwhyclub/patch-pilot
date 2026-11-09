# PatchPilot

PatchPilot은 API 제공사가 릴리스 전에 고객 Python 코드의 영향을 점검하는 CLI입니다. 이 저장소의 현재 코드는 사전 릴리스이며 mode A의 입력 검사, OpenAPI 분류, 정적 AST 탐색, 패치 검증, 안전 gate, 읽기 전용 표시만 구현합니다.

난이도: Mid  
학습 키워드: OpenAPI, AST, Unified Diff, Fail Closed, Manifest, Exit Code

## 지금 할 수 있는 일

- OpenAPI **3.0.3 JSON** 문서 두 개와 provider mapping을 읽어, 같은 부모 객체의 마지막 키 개명(`field_renamed`)만 지원으로 분류합니다.
- allowlist 안의 `.py` 파일을 실행하지 않고 AST로 읽어, 함수 파라미터에 직접 붙은 문자열 키 접근만 찾습니다.
- 사람이 만든 unified diff가 그 마지막 문자열 키만 바꾸는지 AST와 토큰으로 검사합니다.
- 비밀 후보를 찾고, 출력에서는 `[REDACTED]`로 가립니다. 비밀이 diff 안에 있으면 마스킹만으로 통과시키지 않습니다.
- manifest와 사람용 report를 만들고, stdout에는 계약의 영문 안내를 그대로 냅니다.
- mode `B`와 `C`는 요청 값을 보존한 채 `E_MODE_UNSUPPORTED`로 거부합니다.

## 지금 하지 않는 일

다음 경로는 코드에 상수가 `False`로 고정되어 있습니다. 환경 변수로 켤 수 없습니다.

- 제품 LLM, provider, model endpoint 호출
- 고객 코드 실행. 합성 fixture를 worker로 실행하는 것도 포함합니다.
- 고객 API 호출
- 고객 저장소의 draft PR 생성
- 배포, 자동 머지, fork 생성

이 빌드의 CLI는 지원 변경과 직접 키 접근을 찾은 뒤 `test_baseline_v1`을 `blocked`로 두고 멈춥니다. 테스트 결과는 `not_run`입니다. `not_run`은 pass도 fail도 아닙니다. 고객 프로세스는 시작하지 않습니다.

`draft_pr_opened`와 `patch_only`는 능력이 증명되기 전에 나오면 `error`로 내립니다. 이 결과를 제품 PASS나 고객 PR 성공으로 읽으면 안 됩니다.

PP-AC-001부터 PP-AC-024까지 24개 수용 기준은 모두 **NOT_RUN**입니다. `python3 -m unittest`가 통과해도 수용 기준 통과가 아닙니다. 단위 검사는 schema, AST 비교, 렌더러, gate 순수 함수만 다룹니다.

## 아직 필요한 별도 승인

아래가 생기기 전에는 고객 실행, 모델 호출, 고객 PR을 열 수 없습니다.

1. 별도로 승인된 Linux 일회성 비특권 컨테이너, trusted supervisor, broker, PR 주체의 분리. cgroup과 rlimit 강제가 실제로 증명되어야 합니다. 이 개발 환경은 그 컨테이너가 아닙니다.
2. 고객 저장소와 PR 대상 저장소가 같고, base SHA와 승인 binding이 정해져야 합니다.
3. 모델로 보낼 최소 발췌, 비밀 검사, `model_send_consent=true`, 승인된 endpoint와 예산.
4. durable lock과 append-only ledger의 재시작 복구 증명. 증명 전에는 PR 단계가 막혀 있습니다.
5. 원본 test, expected, fixture는 읽기 전용이어야 하고, 판정은 trusted supervisor의 독립 assertion이어야 합니다. 고객 프로세스의 exit 0만으로 통과시키지 않습니다.

`base_sha`는 git을 실행하지 않으므로 획득하지 않습니다. 고객 hook을 피하기 위한 결정입니다. 값이 없으면 `acquisition.base_sha`는 `not_attempted`이고 inputs의 `base_sha`는 null입니다.

## 데모 변경의 의미

고지 문장은 계약 C13 원문입니다. `current_weather.temperature`를 `current_weather.temperature_2m`으로 바꾸는 예는 팀이 만든 synthetic 변경입니다. Open-Meteo의 실제 변경이 아니고, `current_weather.temperature_2m` 경로는 Open-Meteo에 없습니다. 이름만 신형 `current` 블록에서 빌렸습니다.

실행 전에는 "Validated on"이라고 말하지 않습니다. 이 빌드에는 성공 run이 없으므로 완료형 고지로 바꾸지 않습니다.

## 설치와 실행

Python 3.11 이상이 필요합니다. 외부 패키지는 쓰지 않습니다.

```bash
export PYTHONPATH=src:.
python3 -m patchpilot run \
  --specs-root specs \
  --spec-old v1.json \
  --spec-new v2.json \
  --change-mapping map.json \
  --customer-repo owner/name \
  --customer-base-ref main \
  --customer-checkout checkout \
  --lock-root locks \
  --test-lock tests.lock \
  --allowlist 'client.py' \
  --pr-target-repo owner/name \
  --pr-target-base-branch main \
  --model-send-consent true \
  --open-pr false \
  --out-dir patchpilot-run
```

경로 입력은 모두 상대 경로입니다. 절대 경로, `..`, symlink, hardlink는 거부합니다. `out-dir`은 spec, checkout, lock 디렉터리와 겹치면 안 됩니다. 위험하면 manifest를 만들지 않고 exit 30, `E_OUTPUT_ROOT`입니다.

`--customer-repo`와 `--pr-target-repo`는 정규화 없이 같은 문자열이어야 합니다. 다르면 exit 30, `E_INPUT`이고 PR 호출은 없습니다.

필수 인자가 없거나 mode가 A/B/C가 아니면 exit 2이고 manifest와 report를 만들지 않습니다.

### exit

| 상황 | exit |
|---|---|
| 사용법 오류 | 2 |
| `draft_pr_opened` | 0. 이 빌드에서는 능력 미증명으로 도달하지 않습니다. |
| `patch_only` | 10. 마찬가지로 도달하지 않습니다. |
| `pr_gate_blocked` | 11 |
| `hold` | 20 |
| `error` | 30 |

지원 변경을 찾고 직접 접근까지 확인한 정상 차단은 exit 30, `E_INTERNAL`입니다. stdout의 짧은 문장은 계약 C14의 "Internal error. See report."입니다. stderr와 stage `test_baseline_v1=blocked`가 실제 이유입니다. 계약에 "런타임 미검증" 전용 reason 코드가 없어서 새 코드를 만들지 않았습니다. 이것은 baseline 실패가 아닙니다.

## 입력 형식

- spec은 OpenAPI 3.0.3 JSON입니다. YAML, 다른 버전, operation이 0개 또는 2개 이상, 200이 아닌 응답, `application/json`이 아닌 media, inline object가 아닌 schema, `$ref`는 `H_UNSUPPORTED_SPEC`입니다.
- 루트 키는 `openapi`, `info`, `paths`, `servers`만 허용합니다.
- pointer는 `current_weather.temperature`처럼 점으로 구분합니다. JSON Pointer(`/a/b`)는 받지 않습니다.
- mapping 객체는 `old_pointer`, `new_pointer`, `type_same`, `unit_same`, `semantic_same`만 가집니다. 추가 키는 `H_METADATA_MISSING`입니다.
- 이름만 비슷한 삭제와 추가를 rename으로 추론하지 않습니다. mapping이 있어야 합니다.
- 부모가 다르면 `field_moved`로 기록하고 `supported=false`, `H_UNSUPPORTED_KIND`입니다. `field_moved`는 구현하지 않습니다.
- allowlist glob은 전체 상대 경로에 맞춥니다. `*`는 `/`를 넘지 않고 `**`만 넘습니다. `.py`가 아니면 읽지 않습니다.
- 직접 접근은 `payload["current_weather"]["temperature"]` 또는 `payload.get("current_weather").get("temperature")`처럼 파라미터에서 바로 이어진 체인만 인정합니다. 별칭, 재대입, 동적 키는 `H_UNRESOLVED`이고 일부 사이트만 패치하지 않습니다.
- 정적 탐색 상한은 200개 파일, 파일당 1,000,000바이트입니다. 넘으면 부분 성공으로 보지 않습니다.

## 출력

`<out-dir>/manifest.json`이 기계가 읽는 원본입니다. `<out-dir>/report.md`는 렌더러가 만든 문자열을 core가 저장합니다. 렌더러는 파일을 쓰지 않고 outcome을 다시 계산하지 않습니다.

PR을 만들지 않았으면 문장은 `PR creation not attempted.`입니다. URL이 없으면 URL을 만들지 않습니다.

## 개발 검사

```bash
PYTHONPATH=src:. python3 -m unittest discover -s tests -v
```

이 명령은 네트워크, 고객 코드 실행, 고객 PR publisher를 호출하지 않습니다. `ObviousFakeModel`은 이름이 말하듯 가짜이며 diff를 만들지 않습니다. 규칙으로 `temperature`를 `temperature_2m`으로 바꿔 성공이라고 말하지 않습니다.

## 구현에서 정한 것

계약이 값을 적지 않은 부분은 아래처럼 두었습니다.

- `idem_key`는 여섯 문자열을 NUL 바이트로 이어 sha256합니다.
- 고객 실행을 막을 때 stage는 `blocked`, 테스트는 `not_run`, outcome은 `error`, reason은 `E_INTERNAL`입니다.
- mode B/C는 다른 입력 오류보다 먼저 거부합니다.
- 분류는 단일 operation 객체를 키 이름만 되돌린 뒤 비교합니다. `info`와 `servers` 차이는 그 비교에 넣지 않습니다.
- 직접 사이트가 0개이면 `H_UNRESOLVED`로 멈춥니다.
- 렌더러 경로는 `presentation/renderers/`와 `tests/presentation/`입니다. 공용 schema와 CLI가 표시 결과를 계산하지 않습니다.

## 제품 개발 PR과 고객 PR

이 저장소의 branch와 pull request는 제품 코드 개발용입니다. 고객 저장소에 수정안을 올리는 draft PR이 아닙니다. 고객 PR은 별도 승인 전에는 만들지 않습니다.
