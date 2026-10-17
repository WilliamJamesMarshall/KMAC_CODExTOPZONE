# Cloud Run + 기존 Supabase 배포 안내

작성일: 2026-10-17 · Windows PowerShell 기준 · OSS AX 매칭 프로젝트 전용

## 먼저 확인할 점

목표 구성은 **Cloud Run 서울 + 현재 Supabase Free 서울**이다. Cloud Run의 무료 사용 한도를 활용해 작은 규모로 시작한다. 이미지 보관·파일 저장·AI API 등까지 포함한 월 0원을 보장하는 구성은 아니다.

현재 저장소는 로컬 개발 서버 상태다. `Dockerfile`, 운영용 HTTP 진입점, 클라우드용 진단 기록 처리는 아직 구현되지 않았다. **이 문서는 배포 방법 안내이며 아래 예시 파일이나 서버가 이미 만들어져 있다는 뜻이 아니다.** 1~3단계의 계정·도구 준비는 지금 진행할 수 있다. 4단계의 앱 준비를 마쳐야 9단계부터 이미지 빌드·배포가 가능하다.

이 문서의 명령은 안내용이며 실제 실행하지 않았다. 클라우드 리소스 생성·키 등록·유료 전환도 수행하지 않았다.

## 전체 구성

| 서비스 | 역할 |
| --- | --- |
| Cloud Run | 웹 화면, Python 분석 API, PDF 생성, 필요 시 Chromium 크롤링 |
| 현재 Supabase | 공급기업·원문 프로필 조회. 기존 데이터·권한 구조 유지 |
| Artifact Registry | 배포할 Docker 이미지 보관 |
| Secret Manager | AI API 키·Supabase 서버 키 보관 |
| Cloud Storage | Excel 지식베이스와 불완전 출력 진단 JSON 보관 |
| Cloud Logging | 처리시간·HTTP 상태·오류 로그 확인 |

사용자 브라우저는 Cloud Run의 HTTPS 주소에 접속한다. Cloud Run 서버가 키를 사용해 Supabase를 조회한다. Excel과 진단 파일은 공개 화면 디렉터리 밖에 둔다. 정상 분석 결과와 PDF는 기존처럼 메모리에서 전달하고 자동 보관하지 않는다.

## 1. Supabase 준비

### 1-1. 기존 프로젝트를 연다

[현재 프로젝트 대시보드](https://supabase.com/dashboard/project/viguohfdfaxscsebbuxw)를 연다. 2026-10-17 점검에서는 다음 상태였다.

- 프로젝트: `KMAC_CODExTOPZONE`
- 요금제: Free
- 리전: 서울, `ap-northeast-2`
- 가동 상태: `ACTIVE_HEALTHY`
- DB: 약 37MB
- 공급기업·2026 풀 원문: 각각 1,428건

동일 프로젝트를 사용하므로 새 DB 생성이나 데이터 재업로드는 필요하지 않다. [실제 점검 결과](supabase-deployment-readiness-2026-10-17.md)

### 1-2. 연결값을 준비한다

프로젝트의 Connect/연결 정보와 API Keys/키 화면에서 다음을 확인한다. 콘솔의 메뉴명은 업데이트에 따라 조금 다를 수 있다.

| 앱 설정 | 사용할 값 |
| --- | --- |
| `SUPABASE_URL` | `https://viguohfdfaxscsebbuxw.supabase.co` |
| `SUPABASE_SECRET_KEY` | 현재 앱에서 검증한 서버 전용 secret key |

`SUPABASE_URL`은 일반 환경변수, secret key는 Secret Manager에 넣는다. 현재 DB는 브라우저 역할의 테이블 접근을 차단하므로 publishable/anon 키로 바꾸면 같은 조회가 동작하지 않는다. RLS·테이블 권한은 현재 서버 전용 설계대로 유지한다. [Supabase 키의 구분](https://supabase.com/docs/guides/getting-started/api-keys)

### 1-3. 공개 전 백업과 무료 사용량을 확인한다

Free는 자동 백업이 포함되지 않는다. 현재 public 스키마·데이터·권한을 복구할 수 있는 외부 백업을 만들고 별도 환경에서 복구를 확인한다. Supabase CLI의 `db dump` 사용 방법은 공식 문서를 따른다. 백업에는 업무 연락처와 원문이 포함되므로 비공개로 보관한다. 기존 import SQL은 그 이후 변경까지 포함하는 백업이 아니다. [백업 안내](https://supabase.com/docs/guides/platform/backups)

[조직 Usage](https://supabase.com/dashboard/org/ewjenfgqfdcfdcqrqdjf/usage)에서 이번 달 egress 사용량을 확인한다. Free의 일반 외부 전송 한도는 5GB이며, 1주 비활성 시 일시중지 조건도 있다. 이번 점검에서는 월 누적 egress를 조회하지 못했다. [현재 무료 조건](https://supabase.com/pricing)

완료 기준: 기존 DB가 활성 상태이고, 서버 키와 URL을 확보했으며, 외부 백업·사용량을 확인했다.

## 2. Google Cloud 프로젝트와 결제 계정 준비

1. [Google Cloud Console](https://console.cloud.google.com/)에 로그인한다.
2. 상단 프로젝트 선택기에서 **새 프로젝트**를 만든다.
3. 표시 이름은 알아보기 쉽게 정하고, 실제 **프로젝트 ID**를 따로 기록한다.
4. 결제/Billing에서 사용할 결제 계정을 프로젝트에 연결한다.
5. 결제 계정의 **예산 및 알림**에서 이 프로젝트에 대한 예산을 설정한다. 시범 운영 예시로 월 USD $5와 50%·90%·100% 알림을 사용할 수 있다. 알림 수신자를 확인한다.

**프로젝트 이름과 프로젝트 ID는 다르다.** 이후 명령에는 실제 ID를 사용한다. 이 Google Cloud 프로젝트 ID는 Supabase 프로젝트 참조와도 다르다.

Cloud Run 무료 한도는 청구 계정이 필요하다. 유료 청구 계정에서는 무료 한도 밖의 사용량이 과금된다. 신규 계정의 기간 한정 체험 크레딧과 매월 갱신되는 무료 한도는 별개다. 예산 알림은 비용 발생을 자동 차단하는 상한이 아니다. [Google 무료 프로그램](https://docs.cloud.google.com/free/docs/free-cloud-features), [예산 알림](https://docs.cloud.google.com/billing/docs/how-to/budgets)

조직이 관리하는 Google 계정이라면 프로젝트 생성·결제 연결·IAM 설정 권한이 필요할 수 있다. 아래 절차는 본인이 프로젝트를 관리할 권한을 갖고 있다는 전제다.

## 3. Windows 도구 설치와 공통 설정

### 3-1. 도구를 설치한다

- [Google Cloud CLI Windows 설치](https://docs.cloud.google.com/sdk/docs/install-sdk#windows)
- [Docker Desktop Windows 설치](https://docs.docker.com/desktop/setup/install/windows-install/)

Docker Desktop이 요구하는 WSL 2·가상화 설정을 완료하고 Linux 컨테이너를 사용한다. 설치 후 PowerShell을 새로 열고 Docker Desktop을 실행한다.

```powershell
gcloud version
docker version
```

`docker version`에서 Client뿐 아니라 Server 정보도 나와야 한다. 현재 PC의 Google Cloud CLI·Docker 설치 여부는 이번 안내에서 확인하지 않았다.

### 3-2. 로그인하고 프로젝트를 지정한다

이후 코드 블록은 **같은 PowerShell 세션에서 순서대로** 실행한다. 새 창을 열면 아래 변수들을 다시 설정해야 한다. `REPLACE_WITH_YOUR_PROJECT_ID`는 콘솔에서 기록한 실제 ID로 바꾼다.

```powershell
Set-Location -LiteralPath 'C:\KMAC_CODExTOPZONE'

$GcpProjectId = 'REPLACE_WITH_YOUR_PROJECT_ID'
$GcpRegion = 'asia-northeast3'
$RunService = 'oss-ax'
$ArtifactRepo = 'oss-images'
$RuntimeSaName = 'oss-runtime'
$RuntimeSaEmail = "$RuntimeSaName@$GcpProjectId.iam.gserviceaccount.com"
$KnowledgeBucket = "$GcpProjectId-oss-kb"
$DiagnosticsBucket = "$GcpProjectId-oss-diag"
$WorkbookObject = 'kb-v03-20261017.xlsx'
$SupabaseUrl = 'https://viguohfdfaxscsebbuxw.supabase.co'

gcloud auth login
gcloud config set project $GcpProjectId
gcloud config set run/region $GcpRegion
gcloud config list
```

리전 표기는 사업자마다 다르다. Google Cloud 서울은 **`asia-northeast3`**, 기존 Supabase 서울은 **`ap-northeast-2`**다.

### 3-3. 필요한 API를 활성화한다

```powershell
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com storage.googleapis.com iam.googleapis.com logging.googleapis.com
```

이 안내는 PC에서 Docker 이미지를 빌드해 올리는 경로다. Cloud Build용 서비스 계정·빌드 저장소 설정을 추가할 필요가 없다. API 활성화가 끝난 뒤 다음으로 진행한다.

## 4. 프로젝트를 운영용으로 준비한다 — 선행 구현 필요

**이 단계를 완료하기 전에는 아래 Docker 이미지가 실행되지 않는다.** `src/oss/cloud_server.py`, `requirements-cloud.lock`, 클라우드 로그 처리 등은 현재 저장소에 없는 제안 파일·기능이다.

### 4-1. 운영용 HTTP 진입점을 만든다

예시 위치는 `src/oss/cloud_server.py`다. 기존 분석·PDF 함수를 재사용하되 FastAPI·Uvicorn으로 다음 경로를 제공한다.

| 경로 | 필요한 동작 |
| --- | --- |
| `GET /` 및 정적 파일 | `/app/web`의 화면 제공 |
| `GET /api/health` | Excel 적재 완료와 서버 준비 상태 반환. 내부 경로·PID·키 제외 |
| `POST /api/analyze` | 기존 분석 파이프라인·근거 검증·부분 오류 처리 유지 |
| `POST /api/report.pdf` | 기존 PDF·실패 진단 보고서 동작 유지 |
| `GET /api/demo` | 기존 화면 예시 기능 유지 |

운영 진입점은 `PORT`를 읽어 `0.0.0.0`에 바인딩하고 Uvicorn 프로세스는 1개로 실행한다. 동기 분석 함수를 비동기 이벤트 루프에서 직접 실행해 상태 확인·화면 요청까지 막지 않게 한다.

### 4-2. 시간·동시 실행·공개 API 제한을 구현한다

- 인스턴스당 동시 분석은 1건. 추가 분석에는 429/503과 재시도 안내를 제공한다.
- 분석 중에도 정적 화면·상태 확인·PDF 요청은 처리한다.
- IP별 호출 빈도와 분석 비용을 관리할 수 있는 요청량 제한을 둔다. 사용자·건수에 따라 정할 값이며 무제한 공개하지 않는다.
- 전체 처리시간 600초를 시작 목표로 설정하고 외부 호출·브라우저 정리까지 검증한다. Cloud Run의 600초 설정만으로 백엔드 작업이 취소되지는 않는다.
- 공개 주소·리다이렉트·robots·리소스 크기 제한 등 기존 수집 검증을 유지한다.

### 4-3. 파일과 로그를 클라우드에 맞게 분리한다

Excel은 Cloud Storage를 **읽기 전용 볼륨**으로 마운트해 기존 openpyxl로 읽는다. 별도 다운로드 코드를 줄일 수 있다. 볼륨은 Cloud Run 2세대 환경을 사용한다. [Cloud Storage 볼륨](https://docs.cloud.google.com/run/docs/configuring/services/cloud-storage-volume-mounts)

처리시간과 오류는 구조화 JSON으로 stdout/stderr에 기록해 Cloud Logging에서 조회한다. 기존 `searches.jsonl`·`summary.json`을 Cloud Run 로컬 디스크에 누적해도 재시작 후 전체 통계가 보존되지 않는다. 기존 누적 통계 파일을 이관할 필요가 있다면 별도 초기 이관 작업으로 처리한다.

불완전 출력 진단은 기존 저장 기준을 유지하면서 Cloud Storage의 **서로 다른 객체 이름**으로 저장한다. 예시는 `empty-output/2026/10/17/<고유ID>.json`이다. 파일 업로드는 응답 반환 전에 완료하거나 실패를 명확히 기록한다. 요청 종료 뒤 실행되는 임시 백그라운드 스레드에 보존을 맡기면 안 된다.

Cloud Storage 볼륨은 완전한 POSIX 파일시스템이 아니며 공유 파일의 동시 쓰기·파일 잠금을 제공하지 않는다. 기존 JSONL·summary 파일을 그대로 마운트 경로에 쓰는 방식은 사용하지 않는다. [볼륨 제약](https://docs.cloud.google.com/run/docs/configuring/services/cloud-storage-volume-mounts)

### 4-4. 의존성과 컨테이너 입력을 확정한다

현재 `pyproject.toml`의 `ax-llm` 포함 의존성에 운영용 FastAPI·Uvicorn과 진단 업로드용 `google-cloud-storage`를 추가하고, **Python 3.12/Linux에서 검증한 전체 고정 버전 파일**을 `requirements-cloud.lock`으로 만든다. 파일 이름은 이 안내에서 정한 예시이며 현재는 존재하지 않는다.

다음 표가 운영 진입점의 설정 계약이다.

| 환경변수 | 의미 | 현재 코드 지원 |
| --- | --- | --- |
| `PORT` | Cloud Run이 주입하는 HTTP 포트 | 운영 진입점에 추가 필요 |
| `SUPABASE_URL` | 기존 Supabase API 주소 | 지원 |
| `SUPABASE_SECRET_KEY` | 공급기업 조회 서버 키 | 지원 |
| `OPENAI_API_KEY` | 현재 분석용 AI API 키 | 지원 |
| `OPENAI_MODEL` | 모델 변경이 필요한 경우 지정 | 지원. 초기에는 현재 기본값 유지 |
| `OSS_WORKBOOK_PATH` | 마운트된 Excel 파일 경로 | 지원 |
| `OSS_DIAGNOSTICS_BUCKET` | 진단 객체 저장 버킷 | 추가 구현 필요 |
| `OSS_MAX_CONCURRENT_ANALYSES` | 인스턴스당 분석 수 제한 | 추가 구현 필요 |

완료 기준: 로컬 또는 Linux 컨테이너에서 위 경로·로그·종료 동작을 검증하고, 실제 외부 사이트용 Chromium 실행·격리 조건까지 확인했다. 비루트 실행만으로 Chromium sandbox가 자동 활성화되었다고 가정하지 않는다. 필요한 격리가 플랫폼에서 지원되지 않으면 브라우저 실행부 분리를 먼저 설계한다. [Playwright Docker 지침](https://playwright.dev/python/docs/docker)

## 5. Artifact Registry와 실행 계정 생성

### 5-1. Docker 이미지 저장소를 만든다

```powershell
gcloud artifacts repositories create $ArtifactRepo --repository-format=docker --location=$GcpRegion --description='OSS AX application images'
gcloud auth configure-docker "$GcpRegion-docker.pkg.dev"
```

같은 이름의 저장소가 이미 있으면 콘솔에서 형식·리전을 확인하고 재사용한다. 인증 변경 안내가 나오면 대상 호스트가 맞는지 확인한다. [Artifact Registry 인증](https://docs.cloud.google.com/artifact-registry/docs/docker/authentication)

### 5-2. Cloud Run 실행 전용 서비스 계정을 만든다

```powershell
gcloud iam service-accounts create $RuntimeSaName --display-name='OSS Cloud Run runtime'
```

아래에서 이 계정에 특정 비밀값 읽기·Excel 읽기·새 진단 객체 생성 권한만 부여한다. Google 서비스 계정 키 JSON을 만들거나 PC에서 클라우드로 복사할 필요는 없다. Cloud Run에 지정한 실행 계정을 통해 Google API에 접근한다.

배포하는 본인 계정에는 Run 배포, 이미지 push, 실행 계정 사용 권한이 필요하다. 새 개인 프로젝트를 직접 관리하는 경우와 회사가 관리하는 프로젝트는 권한 부여 절차가 다를 수 있다. 실행 계정에 프로젝트 Owner·Editor를 부여하는 방식으로 해결하지 않는다. [Cloud Run 배포 권한](https://docs.cloud.google.com/run/docs/deploying)

## 6. API 키를 Secret Manager에 등록

### 6-1. 콘솔에서 비밀값 2개를 만든다

Google Cloud Console → **Secret Manager → 보안 비밀 만들기**에서 다음을 등록한다. 값은 기존 로컬 `.env`에서 확인해 비밀값 입력란에 붙여 넣는다.

| Secret 이름 | 값 | 앱에서 보이는 환경변수 |
| --- | --- | --- |
| `oss-openai-key` | 기존 `OPENAI_API_KEY` 값 | `OPENAI_API_KEY` |
| `oss-supabase-secret` | 기존 `SUPABASE_SECRET_KEY` 값 | `SUPABASE_SECRET_KEY` |

처음 생성하면 보통 버전 `1`이 생긴다. 실제 활성 버전 번호를 확인한다. 키 값은 Dockerfile·이미지 빌드 인자·PowerShell 명령문에 넣지 않는다.

### 6-2. 실행 계정에 해당 비밀값의 읽기 권한을 준다

```powershell
gcloud secrets add-iam-policy-binding oss-openai-key --member="serviceAccount:$RuntimeSaEmail" --role='roles/secretmanager.secretAccessor'
gcloud secrets add-iam-policy-binding oss-supabase-secret --member="serviceAccount:$RuntimeSaEmail" --role='roles/secretmanager.secretAccessor'
```

환경변수로 전달하는 비밀값은 버전 번호를 고정한다. 키를 갱신할 때는 새 버전으로 새 Cloud Run 리비전을 배포하고 확인한다. [Cloud Run 비밀값 설정](https://docs.cloud.google.com/run/docs/configuring/services/secrets)

완료 기준: Secret 2개에 활성 버전이 있고 `oss-runtime`에 두 Secret의 접근 권한이 있다.

## 7. Excel·진단용 비공개 버킷 준비

### 7-1. 서울의 비공개 버킷 2개를 만든다

버킷 이름은 전 세계에서 고유해야 한다. 이름 충돌 시 변수에 고유한 접미사를 추가하고 아래 이후 명령에도 같은 값을 사용한다.

```powershell
gcloud storage buckets create "gs://$KnowledgeBucket" --location=$GcpRegion --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets create "gs://$DiagnosticsBucket" --location=$GcpRegion --uniform-bucket-level-access --public-access-prevention
```

### 7-2. Excel을 업로드한다

OneDrive에서 실제 사용 중인 Excel의 절대경로를 확인해 `REPLACE_WITH_ACTUAL_WORKBOOK_PATH.xlsx`를 바꾼다.

```powershell
$WorkbookPath = 'REPLACE_WITH_ACTUAL_WORKBOOK_PATH.xlsx'
Test-Path -LiteralPath $WorkbookPath
Get-FileHash -LiteralPath $WorkbookPath -Algorithm SHA256
gcloud storage cp "$WorkbookPath" "gs://$KnowledgeBucket/$WorkbookObject"
gcloud storage ls "gs://$KnowledgeBucket/"
```

`Test-Path`가 True일 때 업로드한다. 새 Excel 버전은 다른 객체 이름으로 올리고 배포 환경변수의 경로를 바꾼다. 예를 들어 `kb-v03-20261018.xlsx`를 사용하면 이전 정상 Excel로 돌아가기 쉽다.

### 7-3. 실행 계정의 권한을 설정한다

```powershell
gcloud storage buckets add-iam-policy-binding "gs://$KnowledgeBucket" --member="serviceAccount:$RuntimeSaEmail" --role='roles/storage.objectViewer'
gcloud storage buckets add-iam-policy-binding "gs://$DiagnosticsBucket" --member="serviceAccount:$RuntimeSaEmail" --role='roles/storage.objectCreator'
```

진단 버킷의 권한은 새 객체 생성용이다. 운영 진입점도 목록 조회·기존 객체 덮어쓰기 없이 고유 이름으로 업로드해야 한다. 본인 운영자 계정으로 콘솔에서 내용을 확인한다.

진단 버킷에는 Lifecycle 규칙으로 예를 들어 30일 보존 후 삭제를 설정한다. 버전 관리·soft delete 보존분도 저장 비용에 영향을 줄 수 있으므로 설정을 확인한다. **서울 Cloud Storage는 미국 일부 리전의 무료 저장 조건과 다르다.** 소량 Excel·진단이라도 별도 요금 항목으로 본다. [Cloud Storage 요금](https://cloud.google.com/storage/pricing)

완료 기준: Excel이 비공개로 업로드되어 있고, 실행 계정은 Excel을 읽고 진단은 새 객체로 쓸 수 있다.

## 8. Dockerfile과 제외 파일 준비

아래 두 파일은 **4단계의 운영 진입점·의존성 lock 작성 후 사용할 예시**다. 현재 저장소에 파일을 생성하거나 빌드한 것은 아니다.

### 8-1. Dockerfile 예시

프로젝트 루트에 `Dockerfile`을 만든다.

```dockerfile
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY pyproject.toml requirements-cloud.lock ./
COPY src ./src
COPY web ./web

RUN python -m pip install --no-cache-dir -r requirements-cloud.lock \
    && python -m pip install --no-cache-dir --no-deps -e . \
    && python -m playwright install --with-deps chromium \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /tmp/oss \
    && chown appuser:appuser /tmp/oss \
    && chmod -R a+rX /ms-playwright

USER appuser

EXPOSE 8080
CMD ["python", "-m", "oss.cloud_server"]
```

`oss.cloud_server`는 4단계에서 새로 만들 모듈이다. 운영용 서버는 `/app/web`과 내장 글꼴을 읽고, 로그용 로컬 임시 파일은 `/tmp/oss` 등을 사용하도록 구현한다. 검증한 베이스 이미지 digest도 최종 배포 기록에 남긴다.

### 8-2. `.dockerignore` 예시

프로젝트 루트에 `.dockerignore`를 만든다.

```text
.git
.env
.env.*
.venv
**/__pycache__
**/*.pyc
**/*.egg-info
data
reports
output
tmp
tests
docs
*.xlsx
*.xls
*.pem
*.key
```

현재 `.gitignore`가 `.env`를 제외하더라도 Docker 빌드 전송 제외는 별도 설정이다. Dockerfile도 필요한 파일만 명시적으로 복사한다. 키·Excel·진단 데이터가 이미지에 포함되지 않는지 확인한다.

## 9. 로컬 Linux 이미지 빌드·시험

4·8단계를 완료한 뒤 실행한다.

```powershell
docker build --platform linux/amd64 --tag oss-ax:local .
```

실패하면 Cloud Run으로 넘어가지 않고 고정 의존성·Linux 패키지·브라우저 설치 오류를 먼저 해결한다.

로컬 시험에서는 `.env`를 런타임에 전달하고 Excel은 읽기 전용으로 마운트한다. 이때 `OSS_WORKBOOK_PATH`를 컨테이너 경로로 덮어쓴다.

```powershell
docker run --rm --name oss-ax-local --publish 8080:8080 --env-file .env --env PORT=8080 --env OSS_WORKBOOK_PATH=/data/knowledge-base.xlsx --env OSS_MAX_CONCURRENT_ANALYSES=1 --mount "type=bind,source=$WorkbookPath,target=/data/knowledge-base.xlsx,readonly" oss-ax:local
```

브라우저에서 `http://127.0.0.1:8080`을 연다. 위 터미널은 서버 실행 중 유지한다. 종료는 해당 터미널에서 Ctrl+C로 한다.

로컬 모드에서는 `OSS_DIAGNOSTICS_BUCKET`을 지정하지 않았을 때 기존 로컬 진단 기록을 사용하도록 4단계의 운영 진입점에서 처리해 두어야 한다. 로컬 시험에 Google 서비스 계정 키를 복사할 필요가 없다. Cloud Storage 업로드·마운트는 다음 비공개 배포에서 별도로 검증한다.

완료 기준: 화면·정적 사이트 분석·동적 사이트 분석·PDF·실패 진단·서버 종료가 Linux 컨테이너에서 동작한다. Chromium의 프로세스와 메모리·격리 조건도 확인한다. 이 프로젝트의 로컬 HTTP 200 응답 평균 약 106초는 클라우드 성능 보장값이 아니다.

## 10. 이미지 업로드와 비공개 Cloud Run 배포

### 10-1. 이미지에 버전을 붙여 업로드한다

로컬 시험을 마친 소스를 그대로 빌드한 `oss-ax:local` 이미지에 태그를 붙인다. 이미지별 태그를 다르게 해 이전 버전과 구분한다.

```powershell
$ImageTag = Get-Date -Format 'yyyyMMdd-HHmmss'
$ImageUri = "$GcpRegion-docker.pkg.dev/$GcpProjectId/$ArtifactRepo/oss-ax:$ImageTag"

docker tag oss-ax:local $ImageUri
docker push $ImageUri
```

기록할 내용은 코드 커밋, 이미지 태그·digest, Excel 객체 이름·해시, 비밀값 버전, 배포 설정이다. 키 값은 기록하지 않는다.

### 10-2. 비공개로 첫 배포한다

아래는 PowerShell 배열을 사용한 명령이다. Secret 버전은 실제 활성 버전 번호로 바꾼다. `OSS_DIAGNOSTICS_BUCKET`·`OSS_MAX_CONCURRENT_ANALYSES`는 4단계에서 구현한 설정 계약이다.

```powershell
$DeployArgs = @(
    'run', 'deploy', $RunService,
    "--project=$GcpProjectId",
    "--region=$GcpRegion",
    "--image=$ImageUri",
    "--service-account=$RuntimeSaEmail",
    '--execution-environment=gen2',
    '--port=8080',
    '--cpu=1',
    '--memory=2Gi',
    '--cpu-throttling',
    '--min=0',
    '--max=1',
    '--concurrency=4',
    '--timeout=600',
    '--no-allow-unauthenticated',
    '--invoker-iam-check',
    "--set-env-vars=SUPABASE_URL=$SupabaseUrl,OSS_WORKBOOK_PATH=/mnt/knowledge/$WorkbookObject,OSS_DIAGNOSTICS_BUCKET=$DiagnosticsBucket,OSS_MAX_CONCURRENT_ANALYSES=1",
    '--set-secrets=OPENAI_API_KEY=oss-openai-key:1,SUPABASE_SECRET_KEY=oss-supabase-secret:1',
    "--add-volume=name=knowledge,type=cloud-storage,bucket=$KnowledgeBucket,readonly=true",
    '--add-volume-mount=volume=knowledge,mount-path=/mnt/knowledge'
)

& gcloud @DeployArgs
if ($LASTEXITCODE -ne 0) { throw 'Cloud Run deploy failed. Inspect the error before proceeding.' }
```

주요 설정의 의미는 다음과 같다.

| 설정 | 의미 |
| --- | --- |
| CPU 1개·2GiB | 시작 계획값. Chromium 포함 최고 메모리 실측 후 조정 |
| `--cpu-throttling` | 요청 중심 CPU 할당. 응답 후 작업 보존을 보장하지 않음 |
| 최소 0개 | 유휴 시 인스턴스를 0개로 줄일 수 있음. 다음 접속에는 시작 대기 가능 |
| 서비스 최대 1개 | 확장 범위를 줄임. 일시 초과 가능성이 있어 요금 상한과는 다름 |
| HTTP 동시 요청 4 | 화면·PDF·상태 확인을 분석과 함께 처리할 여유 |
| 앱 분석 동시 1 | 무거운 분석은 인스턴스당 1건만 실행 |
| 요청 제한 600초 | 긴 분석 응답을 기다릴 시간. 앱 작업 취소와는 별도 |
| 비공개 첫 배포 | 검증 전 일반 사용자가 유료 AI 분석을 호출하지 않게 함 |
| 읽기 전용 Excel 볼륨 | 코드·이미지·키와 Excel을 분리 |

Cloud Run HTTP 동시 요청 4는 분석 4건 동시 실행이라는 뜻이 아니다. 기존 조사에서 단순한 시작안으로 제시한 HTTP 동시 요청 1 대신, 이 가이드는 앱의 분석 제한 1과 HTTP 요청 여유 4를 구분한다. 배포 중 여러 인스턴스가 존재할 수 있으므로 인스턴스 내부 제한은 서비스 전체의 엄격한 전역 제한이 아니다. [배포 옵션](https://docs.cloud.google.com/sdk/gcloud/reference/run/deploy), [최대 인스턴스의 일시 초과](https://docs.cloud.google.com/run/docs/configuring/max-instances)

`--set-env-vars`·`--set-secrets`는 각 기존 설정을 교체한다. 최초 배포용 전체 목록이며, 이후 일부 값만 바꿀 때는 `--update-env-vars`·`--update-secrets`를 사용한다.

## 11. 비공개 URL에서 실제 검증

### 11-1. Cloud Run 콘솔에서 상태를 확인한다

Cloud Run → `oss-ax` → Revisions/리비전에서 Ready 상태를 확인한다. 서비스의 Variables & Secrets/보안 설정에는 Secret 참조가, Volumes에는 읽기 전용 `knowledge`가 있어야 한다. `PORT`는 플랫폼이 주입하므로 별도 일반 환경변수로 설정하지 않는다.

### 11-2. 인증 프록시로 화면을 연다

```powershell
gcloud run services proxy $RunService --project=$GcpProjectId --region=$GcpRegion --port=8080
```

프록시를 실행한 터미널을 유지하고 `http://127.0.0.1:8080`을 연다. 9단계의 로컬 Docker 서버는 먼저 종료해야 같은 포트를 사용할 수 있다. 로그인한 배포 계정에 서비스 호출 권한이 있어야 한다. 필요한 프록시 구성요소 설치 안내가 나오면 공식 gcloud 안내를 따른다. [인증 프록시](https://docs.cloud.google.com/sdk/gcloud/reference/run/services/proxy)

### 11-3. 실제 기능을 순서대로 확인한다

1. 상태 확인: `http://127.0.0.1:8080/api/health`.
2. 정적 HTML 홈페이지 분석: 기업 이해·업무·공급기업 표시와 부분 오류를 확인한다.
3. JavaScript 홈페이지 분석: Cloud Run에서 실제 Chromium 실행·본문 수집·종료를 확인한다.
4. 공급기업 조회: 로컬에서 확인한 프로필 조회가 클라우드에서도 성공하는지 확인한다. `/api/demo`도 추가 점검에 사용할 수 있다.
5. PDF: 모든 업무·공급기업·한글·연락처·상세정보와 실패 진단 PDF를 확인한다.
6. 동시에 분석 2건 요청: 1건 처리와 초과 요청 안내, 상태 확인 응답을 확인한다.
7. 실패 분석: 기존 기준에 해당하면 진단 버킷에 객체가 저장되고 오류 로그에 실패 위치가 남는지 확인한다.
8. 재기동·새 리비전 시험: Excel 재적재, 진단 객체 보존, 정상 결과의 자동 저장 없음, 누적 통계의 외부 집계를 확인한다.

분석 버튼을 누르면 실제 AI API 요금이 발생한다. 상태 확인 요청은 AI·크롤링을 호출하지 않도록 구현한다. 비공개 HTTP 401/403 자체를 DB 장애로 해석하지 않는다.

### 11-4. 로그를 확인한다

Cloud Run 서비스의 Logs 또는 Cloud Logging Logs Explorer에서 다음으로 범위를 좁힌다.

```text
resource.type="cloud_run_revision"
resource.labels.service_name="oss-ax"
```

컨테이너가 JSON을 stdout/stderr에 출력하면 Cloud Logging이 구조화된 로그로 수집한다. 처리시간, HTTP 상태, 실패 단계, 이미지/리비전, 메모리 사용량을 확인한다. 정상 결과 전체·키·진단 원문은 일반 로그에 출력하지 않는다. [Cloud Run 로그](https://docs.cloud.google.com/run/docs/logging)

완료 기준: 서비스가 Ready이고, 두 홈페이지 유형·공급기업 조회·PDF·동시 실행 제한·진단 보존을 모두 확인했다. 2GiB가 부족하면 OOM 여부를 확인하고 사양과 비용을 함께 조정한다.

## 12. 검증 완료 후 공개 접속으로 전환

비공개 검증과 API 호출량 제한 확인을 마친 뒤 실행하는 단계다.

```powershell
gcloud run services add-iam-policy-binding $RunService --project=$GcpProjectId --region=$GcpRegion --member='allUsers' --role='roles/run.invoker'
$ServiceUrl = (gcloud run services describe $RunService --project=$GcpProjectId --region=$GcpRegion --format='value(status.url)').Trim()
$ServiceUrl
```

출력된 `https://...run.app` 주소를 휴대폰·PC의 비로그인 브라우저에서 연다. 카카오톡 iOS·Android 인앱 브라우저와 외부 브라우저에서 결과·PDF 다운로드를 확인한다. 이 HTTPS 주소를 사용자에게 공유하면 된다. 최초 배포에는 별도 도메인 구매가 필수는 아니다.

회사 조직 정책이 `allUsers` 허용을 막으면 오류가 날 수 있다. 프로젝트 관리자와 공개 서비스 정책을 확인한다. 계정 권한을 넓히는 방법으로 임의 해결하지 않는다.

공개 Cloud Run 접근과 Supabase DB 공개는 별개다. Supabase의 RLS·테이블 권한·버킷 공개 설정은 그대로 유지한다.

## 13. 배포 후 운영·수정·복구

### 13-1. 비용·품질 확인

- Google Billing에서 Cloud Run·Artifact Registry·Storage·Secret Manager·Logging 항목을 각각 확인한다.
- Supabase Usage에서 egress·DB 크기·일시중지 여부를 확인한다.
- AI 사용량과 요청 수를 확인한다. Cloud Run 인스턴스 제한은 AI 호출 비용 한도가 아니다.
- 처리시간·부분 오류·빈 추천·Chromium 실패를 구분한다. HTTP 200만으로 추천 완성을 판단하지 않는다.
- 오래된 이미지에 Artifact Registry 정리 정책을 설정하되, 복구에 필요한 이미지와 Excel은 보존한다.

Cloud Run 무료 한도는 리전별 요율과 청구 계정 합산 사용량에 따라 적용된다. 서울의 인터넷 전송·파일 저장, 큰 Chromium 이미지 보관에는 별도 비용이 남을 수 있다. [Cloud Run 가격](https://cloud.google.com/run/pricing)

### 13-2. 코드 수정 배포

1. 로컬 코드를 수정하고 기존 테스트와 Linux 이미지 시험을 수행한다.
2. 새 `oss-ax:local` 이미지를 빌드한다.
3. 새로운 `$ImageTag`·`$ImageUri`를 만들고 tag/push한다.
4. 사용량이 적은 시점에 다음을 실행한다.

```powershell
gcloud run deploy $RunService --project=$GcpProjectId --region=$GcpRegion --image=$ImageUri
```

이미지만 지정하면 기존 서비스 설정을 재사용한다. 매번 10단계의 최초 배포 명령을 그대로 재사용하면 공개 IAM 설정이나 환경변수를 의도치 않게 바꿀 수 있으므로 변경 항목을 확인한다. 긴 분석은 재배포 중 유실될 수 있어 진행 중 분석과 배포 시점을 관리한다.

### 13-3. 이전 리비전으로 복구

```powershell
gcloud run revisions list --service=$RunService --project=$GcpProjectId --region=$GcpRegion
```

정상 동작했던 실제 리비전 이름을 골라 아래 값을 바꾼다.

```powershell
$PreviousRevision = 'REPLACE_WITH_KNOWN_GOOD_REVISION'
gcloud run services update-traffic $RunService --project=$GcpProjectId --region=$GcpRegion --to-revisions="$PreviousRevision=100"
```

과거 리비전이 참조하는 Secret 버전과 Excel 객체가 남아 있어야 복구된다. 키 폐기나 데이터 변경은 트래픽 복구만으로 되돌아가지 않는다. Supabase 데이터를 변경하지 않은 앱 배포라면 DB 복원은 별도 필요 여부를 판단한다.

## 14. 자주 생기는 오류

| 증상 | 먼저 확인할 내용 |
| --- | --- |
| 컨테이너가 PORT에서 대기하지 못함 | 운영 모듈 존재, `0.0.0.0` 바인딩, `PORT` 읽기, 시작 시 Excel·의존성 오류 |
| Secret 접근 거부 | 배포한 실행 계정이 `oss-runtime`인지, 특정 Secret 접근 권한·버전 번호가 맞는지 |
| Excel 파일 없음 | 버킷·객체 이름, 볼륨 마운트, `OSS_WORKBOOK_PATH`, objectViewer 권한 |
| Supabase 프로필 조회 실패 | 서버 secret key·URL, Free 일시중지, 배포 서버의 외부 HTTPS 접근, DB 권한 |
| Chromium 없음/실행 실패 | 이미지의 Playwright 버전과 설치 브라우저 일치, OS 의존성·사용자 권한·플랫폼 격리 제약 |
| 메모리 초과·컨테이너 종료 | 브라우저 포함 메모리, GCS 마운트 캐시, 분석 제한과 PDF 동시 처리 |
| 504 또는 오래 기다린 뒤 실패 | Cloud Run 제한·앱 전체 예산·외부 API 제한, 브라우저 연결 유지, 종료 후 작업 잔존 |
| 비공개 URL 401/403 | 호출자의 Google IAM 인증. 인증 프록시로 시험 |
| 진단 로그가 재시작 후 없음 | `/tmp`에만 저장했는지, 객체 업로드 완료 전 응답했는지, 객체 생성 권한 |
| `docker push` 권한 오류 | 로그인 계정, 프로젝트·리전·저장소 일치, Docker 인증 helper와 이미지 업로드 권한 |
| `gcloud` 실행 오류 | 설치 후 새 PowerShell, CLI 버전, 현재 명령의 `--help`, 프로젝트·계정 확인 |
| 예상하지 못한 비용 | 최소 인스턴스, 요청량·AI 재시도, 이미지 누적, Storage 보존분·전송, 무료 한도 계정 합산 |

## 실행 순서 체크리스트

- [ ] 1. 기존 Supabase 활성·백업·Usage 확인
- [ ] 2. Google Cloud 프로젝트·결제 계정·예산 알림 준비
- [ ] 3. gcloud·Docker 설치 및 프로젝트/API 설정
- [ ] 4. 운영 HTTP 진입점·동시 실행 제한·로그/진단 보존·의존성 lock 구현
- [ ] 5. 이미지 저장소·실행 서비스 계정 생성
- [ ] 6. Secret 2개 등록 및 실행 계정 권한 부여
- [ ] 7. 비공개 Excel·진단 버킷 생성, Excel 업로드
- [ ] 8. Dockerfile·dockerignore 작성
- [ ] 9. Linux 이미지 빌드·실제 기능 시험
- [ ] 10. 이미지 push·Cloud Run 비공개 배포
- [ ] 11. 클라우드에서 분석·PDF·기록·동시 요청·메모리 검증
- [ ] 12. 공개 접근 전환·모바일 시험·URL 공유
- [ ] 13. 사용량 관측·재배포·복구 절차 확인

가장 먼저 필요한 프로젝트 작업은 **4단계의 운영용 서버·클라우드 로그 처리와 8단계의 배포 파일 준비**다. Google Cloud에 먼저 화면만 올리는 것으로 현재 서비스의 배포가 완료되지는 않는다.
