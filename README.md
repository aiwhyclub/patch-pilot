# PatchPilot

PatchPilot은 API 제공사가 릴리스 전에 고객 Python 코드의 영향을 점검하는 CLI입니다. 이 저장소의 현재 코드는 사전 릴리스이며 mode A의 입력 검사, OpenAPI 분류, 정적 AST 탐색, 패치 검증, 안전 gate, 읽기 전용 표시만 구현합니다.

난이도: Mid  
학습 키워드: OpenAPI, AST, Unified Diff, Fail Closed, Manifest, Exit Code

## 지금 할 수 있는 일

- OpenAPI **3.0.3 JSON** 문서 두 개와 provider mapping을 읽어, 같은 부모 객체의 마지막 키 개명(`field_renamed`)만 지원으로 분류합니다.
- allowlist 안의 `.py` 파일을 실행하지 않고 AST로 읽어, 승인된 operation의 JSON 응답 변수에 직접 붙은 문자열 키 접근만 찾습니다. 함수 파라미터라는 이유만으로 응답으로 보지 않습니다.
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

`base_sha`의 읽기 전용 adapter는 연결되어 있지 않습니다. git을 실행하지 않고, `git -c`나 고객 hook 명령을 만들지 않습니다. 1차 SHA는 시작 시 trusted supervisor가 고정하고, 2차 SHA는 `approval_gate` 다음 `base_sha_check`에서 다시 읽어 승인 binding과 비교하는 계약입니다. 둘 다 이 빌드에서는 하지 않습니다. 그래서 초기 중단의 `acquisition.base_sha`는 `not_attempted`이고 inputs의 `base_sha`는 null입니다. 이 조합은 `draft_pr_opened`와 `patch_only`에서 manifest 검사가 거부합니다. 주입된 두 SHA가 다르면 순수 함수가 `H_BASE_MOVED`를 돌려주지만, 그 함수는 고객 repo를 보지 않습니다.

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

지원 변경과 직접 JSON 바인딩을 찾은 뒤의 정상 차단은 exit 30, `error` / `E_RUNTIME_NOT_READY`입니다. stage `test_baseline_v1`은 `blocked`, attempts 1, 시각이 있고 reason도 같습니다. attempts는 supervisor가 사전조건을 평가한 횟수입니다. 고객 프로세스, pytest, 모델, PR 호출 횟수가 아닙니다. 테스트 결과 `baseline_v1`은 `not_run`입니다. `not_run`은 pass도 fail도 아니고 `E_BASELINE_FAIL`도 아닙니다. 이후 stage는 skipped, attempts 0, 시각 null입니다. stage는 11개입니다. `open_pr=true`여도 이 지점에서는 `pr_gate_blocked`로 바꾸지 않습니다. 그 outcome은 검증 시퀀스가 끝난 뒤의 PR 전 gate 전용입니다.

stdout의 짧은 문장은 `Runtime prerequisites are not verified. No customer tests were executed.`입니다. `E_INTERNAL`은 예상 밖 bug의 "Internal error. See report."에만 씁니다. `not_run`은 제품이 테스트를 시작하지 않았다는 기록입니다. 운영체제 프로세스 0건을 암호학적으로 증명하지는 않습니다.

## 입력 형식

- spec은 OpenAPI 3.0.3 JSON입니다. YAML, 다른 버전, operation이 0개 또는 2개 이상, 200이 아닌 응답, `application/json`이 아닌 media, inline object가 아닌 schema, `$ref`는 `H_UNSUPPORTED_SPEC`입니다.
- 루트 키는 `openapi`, `info`, `paths`, `servers`만 허용합니다.
- pointer는 `current_weather.temperature`처럼 점으로 구분합니다. JSON Pointer(`/a/b`)는 받지 않습니다.
- mapping 객체는 `old_pointer`, `new_pointer`, `type_same`, `unit_same`, `semantic_same`만 가집니다. 추가 키는 `H_METADATA_MISSING`입니다.
- 이름만 비슷한 삭제와 추가를 rename으로 추론하지 않습니다. mapping이 있어야 합니다.
- 부모가 다르면 `field_moved`로 기록하고 `supported=false`, `H_UNSUPPORTED_KIND`입니다. `field_moved`는 구현하지 않습니다.
- allowlist glob은 전체 상대 경로에 맞춥니다. `*`는 `/`를 넘지 않고 `**`만 넘습니다. `.py`가 아니면 읽지 않습니다.
- 직접 접근은 승인 operation과 같은 method, path가 URL 칸에 있는 호출의 JSON 응답을 한 변수에 한 번만 대입한 뒤, 그 변수에서 `body["current_weather"]["temperature"]` 또는 `body.get("current_weather").get("temperature")`로 이어진 체인만 인정합니다. method는 `requests.get`처럼 호출 속성 이름이거나 `client.request`의 method 칸입니다. `note="/v1/weather"`처럼 다른 칸에만 path가 있으면 인정하지 않습니다. `body = response.json()`처럼 고정 호출 결과에 바로 붙인 `.json()`도 포함합니다.
- 계약은 callee 라이브러리 이름을 정하지 않습니다. 그래서 `cache.get("/v1/weather")`는 기존 속성-method 모양으로 남고, 그 callee가 HTTP 클라이언트라는 뜻은 아닙니다.
- 함수 파라미터, 다른 path, 다른 method, 변수로 만든 URL, 이름 별칭, 응답 객체를 속성·컨테이너에 저장하는 alias, 재대입, comprehension·except·with·async for·import·match가 같은 이름을 묶는 경우, 동적 키, 변수에 담지 않은 `.json()` 호출은 `H_UNRESOLVED`입니다. comprehension의 다른 반복 이름이나 match의 다른 capture는 응답 변수를 묶지 않습니다. 그 경우 baseline stage는 blocked가 아니라 skipped입니다.
- 응답 체인의 앞부분만 다른 이름에 나누면, 같은 함수에 전체 체인이 있어도 `H_UNRESOLVED`입니다. `saved = body["current_weather"]` 뒤에 `body["current_weather"]["temperature"]`가 있는 경우가 그렇습니다. `body["current_weather"]["windspeed"]`처럼 길이가 같고 마지막 키가 다른 형제 접근은 그 이유로 버리지 않습니다.
- path item의 `parameters`, `summary`, `description`, `servers`, `x-*`가 옛 문서와 다르면 rename만으로 `supported`가 되지 않고 `H_UNSUPPORTED_KIND`입니다. 문서 루트의 `info`와 `servers`는 이 비교에 넣지 않습니다.
- 패치 경로는 `tests/`, `test/`, `fixtures/`, `fixture/`, `.github/`와 `test.py`, `tests.py`, `fixture.py`, `fixtures.py`를 대소문자 구분 없이 거부합니다. `client.py`, `contest.py`, `latest.py`처럼 이름 일부만 비슷한 일반 코드는 그 이유만으로 거부하지 않습니다.
- 비밀 검사는 후보 패턴입니다. 따옴표 없는 `password` / `secret` / `token` / `api_key` 대입도 `H_PATCH_REJECTED`와 `H_MODEL_SEND_BLOCKED`에 포함합니다. 모든 비밀 형태를 찾는다고 보지 않습니다.
- 응답 변수가 아닌 다른 리스트 첨자는 동적 키로 보지 않습니다. 호스트 이름은 계약 operation 식별자에 없습니다. 판정은 method와 path입니다.
- method와 path만으로 provider identity, API identity, 고객 repo, 대상 branch, 전송 동의를 증명하지 않습니다. 그 결합은 실행 승인 기록의 별도 필드이며 CLI 필수 입력이나 manifest 필드로 추가하지 않았습니다. 기록이 없거나 고객 repo·branch와 다르면 네트워크를 열지 않습니다.
- 정적 탐색 상한은 200개 파일, 파일당 1,000,000바이트입니다. 넘으면 부분 성공으로 보지 않습니다.

## 출력

`<out-dir>/manifest.json`이 기계가 읽는 원본입니다. `<out-dir>/report.md`는 렌더러가 만든 문자열을 core가 저장합니다. 렌더러는 파일을 쓰지 않고 outcome을 다시 계산하지 않습니다.

PR을 만들지 않았으면 문장은 `PR creation not attempted.`입니다. URL이 없으면 URL을 만들지 않습니다.

## 개발 검사

CLI만 볼 때는 아래면 됩니다. 웹 경로 검사까지 포함한 전체 발견은 FastAPI가 설치된 인터프리터가 필요합니다.

```bash
PYTHONPATH=src:. python3 -m unittest discover -s tests -t . -v
```

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
PYTHONPATH=src:. .venv/bin/python -m unittest discover -s tests -t . -v
```

`-t .`가 필요합니다. `tests/presentation/`은 제품 패키지 `presentation`과 디렉터리 이름이 같습니다. top을 저장소 루트로 두지 않으면 테스트 디렉터리가 `presentation`을 가립니다.

이 명령은 네트워크, 고객 코드 실행, 고객 PR publisher를 호출하지 않습니다. `ObviousFakeModel`은 이름이 말하듯 가짜이며 diff를 만들지 않습니다. 규칙으로 `temperature`를 `temperature_2m`으로 바꿔 성공이라고 말하지 않습니다.

## 웹 정적 분석 화면

브라우저에서 팀이 만든 샘플만 고릅니다. `GET /api/v1/samples`가 목록과 읽기 전용 미리보기를 주고, `POST /api/v1/analyze`는 `{"sample_id": "..."}`만 받습니다. 본문은 4 KiB 이하입니다. 고객 URL, 업로드, 자유 코드, 원격 저장소는 받지 않습니다. 브라우저가 이 사이트의 API를 호출하는 것은 같은 origin 분석이며, 외부 모델이나 고객 저장소 호출이 아닙니다.

응답 `envelope_kind`는 `pp-web-static-analysis/1`입니다. CLI manifest가 아니므로 `cli_manifest_claim`은 false입니다. runtime은 `not_run` / `E_RUNTIME_NOT_READY`, PR은 `not_attempted`, AC24는 `NOT_RUN`입니다. `diff`는 classify, scan, patch_preview가 모두 ok이고 `validate_patch`를 통과한 결정적 미리보기일 때만 문자열이 됩니다. 그 미리보기는 모델이 만든 수정이나 고객 테스트 성공이 아닙니다. 부모 조각을 나눈 `split_parent_alias` 샘플은 `H_UNRESOLVED`이고 `diff`는 null입니다. 샘플을 바꾸거나 다시 분석하거나 오류가 나면 화면의 이전 결과와 다운로드는 지워집니다.

로컬에서 보려면 웹 의존성을 설치한 뒤 다음을 실행하고 `http://127.0.0.1:8000/`을 엽니다.

```bash
PYTHONPATH=src:. .venv/bin/python -m patchpilot.web.local
```

### 배포 설정

이 저장소는 Vercel 프로젝트를 만들거나 배포하지 않습니다. 배포는 별도의 프로젝트 설정으로 합니다. 추가 환경 변수, 데이터베이스, Blob, 모델 키는 필요 없습니다.

- Framework: FastAPI
- Root Directory: 저장소 루트. 하위 디렉터리로 두지 않습니다.
- Output Directory: 비웁니다. `public`으로 두면 Function이 빠집니다.
- Entrypoint: `pyproject.toml`의 `[tool.vercel] entrypoint = "src.app:app"`. 빌더는 모듈 경로의 점을 슬래시로 바꿔 저장소 루트의 `src/app.py` 또는 `src/app/__init__.py`만 찾습니다. `src/` 아래 패키지 경로를 자동으로 앞에 붙이지 않으므로 `patchpilot.web.app:app`은 `patchpilot/web/app.py`가 없어 `PYTHON_ENTRYPOINT_NOT_FOUND`가 됩니다. `src/app.py`는 `src`를 경로에 넣은 뒤 `patchpilot.web.app`의 `app`을 내보냅니다.
- `vercel.json`의 functions 키는 그 해석 결과와 같은 `src/app.py`이고 maxDuration 30입니다. `includeFiles`는 `src/patchpilot/**`입니다. `runtime`은 넣지 않습니다. 그 값은 `vercel-php@0.5.2`처럼 버전을 포함한 커뮤니티 런타임 패키지 이름이고, `python3.12`를 넣으면 빌드가 `invalid_function_runtime`으로 바로 실패합니다.
- 웹 배포의 Python은 루트 `.python-version`의 `3.12`입니다. 지정하지 않아도 공식 기본값은 3.12입니다. CLI `requires-python`은 `>=3.11` 그대로입니다.
- Install: `pyproject.toml`이 있으면 빌더는 `requirements.txt`를 읽지 않고 `[project.dependencies]`만 설치합니다. 함수 import에 필요한 항목은 `fastapi==0.117.1`입니다. `requirements.txt`의 `uvicorn`과 `httpx`는 로컬 서버와 테스트용입니다.
- `public/**`는 CDN이 루트 경로로 제공합니다. FastAPI 앱은 그 디렉터리를 mount하지 않습니다. `src/patchpilot/web/local.py`의 mount는 로컬 확인용입니다.

공식 설명은 Python 런타임과 FastAPI 문서, 그리고 public 정적 파일을 CDN에서 제공한다는 changelog를 따릅니다. https://vercel.com/docs/functions/runtimes/python https://vercel.com/docs/functions/runtimes/python/python-version https://vercel.com/docs/frameworks/backend/fastapi https://vercel.com/changelog/fastapi-frontends-and-static-files-served-from-the-cdn

## 구현에서 정한 것

계약이 값을 적지 않은 부분은 아래처럼 두었습니다.

- `idem_key`는 여섯 문자열을 NUL 바이트로 이어 sha256합니다.
- 고객 실행을 막을 때 stage는 `blocked`, 테스트는 `not_run`, outcome은 `error`, reason은 `E_RUNTIME_NOT_READY`입니다. 이 reason을 baseline 실패나 PR gate 차단으로 읽지 않습니다.
- 응답 변수의 AST 모양은 인자 없는 `.json()` 직접 대입입니다. `json.loads` 같은 다른 파서 모양은 계약이 문장을 주지 않아 추측하지 않고 `H_UNRESOLVED`입니다.
- mode B/C는 다른 입력 오류보다 먼저 거부합니다.
- 분류는 단일 operation 객체를 키 이름만 되돌린 뒤 비교합니다. `info`와 `servers` 차이는 그 비교에 넣지 않습니다.
- 직접 사이트가 0개이면 `H_UNRESOLVED`로 멈춥니다.
- 렌더러 경로는 `presentation/renderers/`와 `tests/presentation/`입니다. 공용 schema와 CLI가 표시 결과를 계산하지 않습니다.

## 비활성 경계

`E_RUNTIME_NOT_READY`는 확정된 단일 코드입니다. outcome은 `error`, exit는 30입니다. 새 reason을 더 만들지 않았습니다. `capability=False`는 그 능력이 이 환경에서 증명되지 않았다는 뜻입니다. 아래 순수 함수가 있어도 고객 실행, 모델 전송, 고객 PR은 시작되지 않습니다. mock이나 fixture의 pass를 제품 성공으로 기록하지 않습니다.

| 영역 | 상태 | 근거 |
|---|---|---|
| 직접 바인딩 AST, OpenAPI 분류, 패치 AST equality, manifest 검사 | 구현, 정적 단위 검사 | `scan/ast_scan.py`, `diff_spec/classify.py`, `patch/validate.py`, `schema/manifest.py` |
| 런타임 미준비 stage·문구·not_run 정합 | 구현, 정적 단위 검사 | `schema/codes.py`, `schema/manifest.py`의 `_runtime_block_problems` |
| supervisor 평가와 fixture 기대값 판정 | 구현, 순수 함수. worker 미호출 | `runner/supervisor.py`의 `decide_dispatch`, `classify_worker_fixture` |
| 고객 worker 시작 | stub. 호출 시 예외. 테스트에서 호출하지 않음 | `runner/guard.py` |
| lock 계획 index | 구현. `executed=false`라 완료 baseline이 아님 | `collector/evidence.py`의 `plan_lock_snapshots` |
| ledger append와 중단 지점 순수 판정 | 구현, 정적 단위 검사. 재시작 내구성은 미검증 | `pr/ledger.py`의 `crash_view`, `replay_lines` |
| 실행 승인 기록 모양 | 구현, 순수 함수. 네트워크는 항상 꺼짐 | `core/approval.py` |
| base SHA adapter | 미연결. 주입값과 차단 원인만 | `core/base_sha.py`의 `adapter_block_cause` |
| 고객 PR publisher | 미연결. 호출 판정은 False이고 성공을 기록하지 않음 | `pr/publisher.py`의 `publisher_decision` |
| 모델 전송 | 미연결. provider identity가 없으면 차단 | `broker/adapter.py`의 `send_gate` |
| 웹 샘플 정적 분석 | 구현. 샘플 식별자만 받고 CLI manifest를 만들지 않음 | `web/analyze.py`, `web/app.py`, `public/` |
| 컨테이너, cgroup, 모델 endpoint, 고객 PR 권한 | runtime 미검증. 상수 False | `core/capability.py` |

## 제품 개발 PR과 고객 PR

이 저장소의 branch와 pull request는 제품 코드 개발용입니다. 고객 저장소에 수정안을 올리는 draft PR이 아닙니다. 고객 PR은 별도 승인 전에는 만들지 않습니다.
