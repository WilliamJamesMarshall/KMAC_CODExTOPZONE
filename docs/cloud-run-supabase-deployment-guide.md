# Cloud Run 무료 사용량으로 OSS AX 배포하기

작성 기준: 2026년 10월 17일 한국시간. Windows PowerShell과 Linux Docker 이미지 기준.

Cloud Run에 Python 화면·분석·PDF 서버를 하나로 배포하고 기존 Supabase Free를 사용한다. 배포 코드와 Dockerfile은 준비되어 있다. **설정과 비공개 시험 배포를 완료했다. 사용자의 외부 공유 요청에 따라 로그인 없이 접속할 수 있도록 공개했다.** [실제 서비스](https://oss-ax-591110969614.asia-northeast3.run.app/), [운영 검증 기록](cloud-run-live-verification-2026-10-17.md). 현재 완료 상태는 [준비 진행 기록](cloud-run-preparation-status-2026-10-17.md)을 따른다.

Cloud Run 무료 사용량을 활용하는 구성이며 전체 월 0원을 보장하지 않는다. 결제 계정, 이미지 보관·인터넷 전송 등의 별도 비용, 외부 AI API 호출료가 남는다. [Cloud Run 요금](https://cloud.google.com/run/pricing), [Google 무료 프로그램](https://docs.cloud.google.com/free/docs/free-cloud-features)

## 설정 순서와 현재 담당

| 순서 | 설정 | 현재 상태·담당 |
| --- | --- | --- |
| 1 | Google 로그인·결제 계정 생성 | 사용자가 완료 |
| 2 | 프로젝트 결제 연결·예산·지출 제한 | 에이전트가 완료 |
| 3 | Google Cloud CLI·빌드 계정·권한 | 에이전트가 완료. Docker Desktop 설치 불필요 |
| 4 | Supabase 운영 SQL·비공개 Excel·체크섬 | 에이전트가 완료 |
| 5 | Secret Manager 키 2개·실행 계정 접근 | 에이전트가 완료. 두 Secret 모두 버전 `1` |
| 6 | Linux 이미지 빌드·Chromium·PDF 검증 | Cloud Build 결과는 준비 진행 기록 참고 |
| 7 | 비공개 Cloud Run 서비스 생성·실제 API 확인 | 완료. 화면·예시·실제 기업 분석·PDF·동시 요청·실패 진단 확인 |
| 8 | 로그인 없는 공개 접근 허용 | 사용자 요청에 따라 완료. 공유 URL과 점검 결과는 운영 검증 기록 참고 |

이 PC에는 Docker와 WSL이 없어 **Cloud Build 원격 빌드를 우선 사용**한다. 이 경로에서는 Docker Desktop·WSL 설치가 필요 없다. 아래 Docker 절차는 Docker가 있는 환경의 대안으로 남겼다. [Cloud Build 빌드 안내](https://docs.cloud.google.com/build/docs/build-push-docker-image)

## 준비된 코드의 동작

| 파일 | 역할 |
| --- | --- |
| `Dockerfile`, `.dockerignore` | Python 3.12·Chromium Headless Shell·글꼴 설치. 비관리자 사용자로 실행. `.env`·Excel·보고서·Git 이력은 빌드 문맥에서 제외 |
| `requirements-cloud.lock` | 런타임 의존성을 버전·해시로 잠금 |
| `src/oss/cloud_server.py` | FastAPI·Uvicorn 운영 서버, `0.0.0.0:$PORT`, 화면·분석·PDF·상태 확인·기존 demo API |
| `src/oss/cloud_worker.py` | 분석별 별도 프로세스. 제한 시간 초과·요청 취소 시 부모가 프로세스 그룹과 Chromium 종료 |
| `src/oss/cloud_runtime.py` | 비공개 Excel 다운로드·체크섬 검증, DB 한도, 진단 업로드, 구조화된 운영 로그 |
| `deploy/cloud-runtime.sql` | 서버만 접근하는 운영 행과 RPC 2개. 월 한도·동시 실행·요청 간격·누적 처리시간 |
| `deploy/cloud-run.env.yaml` | Cloud Run 일반 환경변수. 비밀키 입력 금지 |
| `deploy/cloud.env.example` | Docker 로컬 기동용 비밀 환경파일의 빈 예시 |
| `src/oss/cloud_smoke.py` | 외부 AI 호출 없이 Chromium JavaScript와 한글 PDF 점검 |

현재 기본값은 **월 분석 100건, 전 서비스 동시 분석 1건, 수락 간격 30초, 분석 프로세스 제한 840초**다. 월 기준은 한국시간이다. 수락 뒤 실패·시간 초과한 요청도 한도에 포함하고 환불하지 않는다. 잘못된 입력·혼잡·한도 초과로 수락되지 않은 요청과 PDF·demo·상태 확인은 분석 한도에 포함하지 않는다.

한도와 실행 잠금은 DB에서 원자적으로 처리하므로 컨테이너 재시작·새 리비전에도 유지된다. 프로세스 내부 잠금도 중복 요청을 즉시 거절한다. 컨테이너가 비정상 종료되어 잠금 해제가 실패하면 최대 900초 뒤 다시 분석할 수 있다. 이 분석 건수 제한은 개별 요청의 토큰 사용량이나 전체 청구액을 제한하는 장치는 아니다.

분석은 로컬 서버와 같은 `AnalysisService`를 사용한다. 각 클라우드 분석은 새 프로세스에서 Excel과 공급기업 데이터를 읽으므로 로컬 상주 서버와 캐시·처리시간은 다를 수 있다. 정상 분석 결과는 파일·DB에 자동 보관하지 않는다. PDF도 메모리에서 생성한다.

## Supabase 설정

### 기존 DB와 서버 키 확인

기존 프로젝트를 계속 사용한다. `SUPABASE_URL`과 `sb_secret_...` 형식의 서버 키를 확인한다. 브라우저용 publishable/anon 키를 사용하지 않는다. 기존 공급기업 테이블의 RLS와 권한은 유지한다. [API 키 구분](https://supabase.com/docs/guides/getting-started/api-keys)

Free 사용량에서 DB·Storage·egress 여유를 확인하고 외부 백업을 확보한다. Free에는 DB 500MB·Storage 1GB·일반 egress 5GB 한도와 1주 비활성 일시중지 조건이 있다. [무료 조건](https://supabase.com/pricing), [백업 안내](https://supabase.com/docs/guides/platform/backups)

### 운영 SQL 적용

Supabase SQL Editor에서 `deploy/cloud-runtime.sql` 내용을 실행한다. 운영 테이블 1개와 RPC 2개가 생성된다. 반복 실행해도 기존 카운터를 초기화하지 않는다. `anon`·`authenticated`의 테이블 접근과 함수 실행은 차단하며 `service_role`만 필요한 SELECT·UPDATE·EXECUTE 권한을 갖는다. 함수는 `SECURITY INVOKER`다.

Data API가 `public` 스키마를 노출하는지 확인한다. 자동 테이블 노출을 끈 프로젝트에서도 이 SQL의 **서버 역할 명시적 grant**가 필요하다. 오류 해결을 위해 브라우저 역할에 권한을 추가하지 않는다. 시작 시 앱은 서버 키로 운영 행이 읽히는지 확인한다. [Data API 권한 설정](https://supabase.com/docs/guides/api/securing-your-api)

현재 프로젝트에는 `20261017110021_cloud_runtime.sql` 마이그레이션을 이미 적용했고 저장소에도 같은 버전을 기록했다. `deploy/cloud-runtime.sql`은 검토·상태 조회용 원본이다. 다시 적용할 필요가 없다.

### 비공개 Excel과 진단 버킷

Storage에서 **`oss-runtime` 버킷을 Private로 생성**하고 버전이 포함된 객체 경로로 실제 v0.3 Excel을 업로드한다. 현재 객체는 `knowledge/kb-v03-5a501eabc9d6.xlsx`이며 환경 YAML에 반영되어 있다. 브라우저 공개 정책은 추가하지 않는다. 앱은 Public 버킷이면 시작을 거부한다. Excel은 최대 20MiB까지 받는다. [비공개 파일 다운로드](https://supabase.com/docs/guides/storage/serving/downloads)

로컬 원본의 체크섬을 계산한다. 아래 경로는 실제 파일로 바꾼다.

```powershell
$WorkbookFile = 'C:\private\실제-v0.3.xlsx'
$WorkbookSha256 = (Get-FileHash -LiteralPath $WorkbookFile -Algorithm SHA256).Hash.ToLowerInvariant()
$WorkbookSha256
```

이 값을 `deploy/cloud-run.env.yaml`의 `OSS_WORKBOOK_SHA256`에 입력한다. `SUPABASE_URL`도 실제 프로젝트 URL로 바꾼다. Excel 교체 시 객체 경로나 체크섬도 함께 갱신해 새 리비전으로 배포한다. 내려받은 바이트가 체크섬과 다르면 앱은 시작하지 않는다. 이미지에 개인 OneDrive 경로나 Excel 자체를 넣을 필요가 없다.

불완전·실패 진단만 `diagnostics/날짜/case-....json`에 저장한다. 기존과 같은 원문·단계·누락 필드를 담고 연락처 값은 제외한다. 일반 로그에는 입력 URL·기업명·원문·키를 출력하지 않는다. 진단 업로드가 실패하면 `diagnostic_upload_failed` 로그를 남기고 원래 분석 응답을 유지한다. 시간 초과 시에는 부모가 최소 실패 진단을 저장하며 종료된 작업의 중간 원문 전체는 복원할 수 없다.

Storage에는 자동 만료를 구현하지 않았다. 운영자가 보존 기간을 정해 오래된 `diagnostics/` 객체를 삭제하고 무료 용량을 관리해야 한다. `knowledge/` 원본은 함께 삭제하지 않는다.

## Google Cloud 계정과 비밀값 설정

프로젝트 생성·결제 연결·API 활성화·서비스 계정 생성·IAM 부여·배포 권한을 가진 계정으로 진행한다. 조직 정책이 공개 서비스를 제한한다면 관리자와 해당 정책을 확인한다.

다음은 같은 PowerShell 세션에서 실행할 공통 변수다. 실제 프로젝트 ID로 교체한다.

```powershell
Set-Location -LiteralPath 'C:\KMAC_CODExTOPZONE'
$GcpProjectId = 'kmac-oss-ax-20261017-0e4a'
$GcpRegion = 'asia-northeast3'
$RunService = 'oss-ax'
$RuntimeSaEmail = "oss-runtime@$GcpProjectId.iam.gserviceaccount.com"

gcloud auth login
gcloud config set project $GcpProjectId
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com iam.googleapis.com logging.googleapis.com cloudbuild.googleapis.com storage.googleapis.com billingbudgets.googleapis.com
gcloud iam service-accounts create oss-runtime --display-name='OSS runtime'
gcloud artifacts repositories create oss-images --repository-format=docker --location=$GcpRegion
gcloud auth configure-docker "$GcpRegion-docker.pkg.dev"
```

계정·저장소 생성은 최초 1회다. 이미 있으면 재사용한다. 앱 데이터용 별도 GCS 버킷·로드밸런서·VPC 커넥터는 필요하지 않다. 원격 빌드를 사용하면 Cloud Build의 소스 임시 보관용 Storage가 별도로 사용된다.

## Docker 설치 없이 원격 빌드

`cloudbuild.yaml`은 Linux 이미지를 빌드한 뒤 Chromium·한글 PDF 오프라인 점검이 통과해야 이미지를 올린다. `.gcloudignore`는 전송할 파일을 허용 목록으로 제한해 `.env`·Excel·진단·Git 이력·배포 설정을 제외한다. 빌드에 앱 API 키나 공급기업 데이터는 전달하지 않는다.

프로젝트 로그인·결제 연결 후 Cloud Build API를 활성화하고, 빌드 계정에는 해당 Artifact Registry 저장소의 쓰기 권한·빌드 로그 쓰기·소스 임시 보관 객체 읽기 권한을 준비한다. 실행 계정과 빌드 계정은 역할이 다르다. 기본 계정에 광범위한 Editor 권한을 추가하는 방법으로 해결하지 않는다.

```powershell
gcloud services enable cloudbuild.googleapis.com
$ImageTag = Get-Date -Format 'yyyyMMdd-HHmmss'
$ImageUri = "$GcpRegion-docker.pkg.dev/$GcpProjectId/oss-images/oss-ax:$ImageTag"
gcloud meta list-files-for-upload
$BuildSaEmail = "oss-builder@$GcpProjectId.iam.gserviceaccount.com"
$SourceBucket = "$GcpProjectId-build-source"
gcloud builds submit . --project=$GcpProjectId --region=$GcpRegion --config=cloudbuild.yaml --service-account="projects/$GcpProjectId/serviceAccounts/$BuildSaEmail" --gcs-source-staging-dir="gs://$SourceBucket/source" --substitutions="_IMAGE_URI=$ImageUri"
```

빌드 성공 후 아래 비공개 배포 명령에서 같은 `$ImageUri`를 사용한다. `docker build/tag/push`는 실행하지 않는다. 기본 풀의 기본 머신은 `e2-standard-2`이며 현재 월 2,500분 무료 빌드분이 제공되지만, 청구 계정 합산 사용량과 소스 저장·전송 비용은 별도로 확인한다. [빌드 설정](https://docs.cloud.google.com/build/docs/build-config-file-schema), [Cloud Build 요금](https://cloud.google.com/build/pricing)

현재 두 Secret은 등록되어 있다. 다른 환경을 새로 구성할 때 Google Cloud Console의 Secret Manager에서 다음 비밀값을 만든다. 키는 콘솔의 비밀값 입력란에 붙여넣고 버전 번호를 기록한다. 명령줄·환경 YAML·Dockerfile에 키를 직접 적지 않는다.

| Secret 이름 | 비밀값 |
| --- | --- |
| `oss-openai-key` | 현재 앱의 `OPENAI_API_KEY` |
| `oss-supabase-key` | 기존 Supabase 서버 secret key |

실행 계정에 해당 Secret 두 개의 읽기 권한만 부여한다.

```powershell
gcloud secrets add-iam-policy-binding oss-openai-key --member="serviceAccount:$RuntimeSaEmail" --role=roles/secretmanager.secretAccessor
gcloud secrets add-iam-policy-binding oss-supabase-key --member="serviceAccount:$RuntimeSaEmail" --role=roles/secretmanager.secretAccessor
```

Cloud Run에서 Secret을 환경변수로 주입하는 공식 방식이다. 기존 Secret에 새 버전을 추가했다면 이후 배포 명령의 `:1`을 실제 사용할 버전으로 바꾼다. [Cloud Run Secret 설정](https://docs.cloud.google.com/run/docs/configuring/services/secrets)

## 배포 전 Docker 검증

Docker Desktop을 Linux 컨테이너 모드로 실행한다.

```powershell
docker version
gcloud version
docker build --platform linux/amd64 -t oss-ax:local .
docker run --rm --entrypoint python oss-ax:local -m oss.cloud_smoke
```

마지막 명령이 Chromium JavaScript·한글 PDF 점검 성공을 출력해야 한다. 외부 AI·DB 요청은 하지 않는다. Playwright와 브라우저 버전은 Dockerfile의 설치 명령이 맞춘다. [Playwright 컨테이너 안내](https://playwright.dev/python/docs/docker)

실제 서버 기동 시험에는 비밀 환경파일을 로컬에 준비한다.

```powershell
if (-not (Test-Path -LiteralPath .env.cloud.local)) {
    Copy-Item -LiteralPath deploy/cloud.env.example -Destination .env.cloud.local
}
```

`.env.cloud.local`의 빈 키·프로젝트 URL·체크섬을 채운다. Docker env 파일은 따옴표 없이 `KEY=value`로 입력한다. 이 파일은 Git과 Docker 빌드에서 제외된다.

```powershell
docker run --rm --name oss-ax-check --env-file .env.cloud.local -p 8080:8080 oss-ax:local
```

별도 PowerShell에서 상태를 확인한다.

```powershell
Invoke-RestMethod http://127.0.0.1:8080/api/health
```

브라우저에서 `http://127.0.0.1:8080`을 열고 정적 사이트·JavaScript 사이트 분석, 한글 PDF, 두 번째 동시 분석의 혼잡 안내를 확인한다. **실제 분석은 AI 요금과 월 분석 한도를 사용한다.** 파일·SQL 검증 실패로 컨테이너가 종료되면 로그와 아래 오류표를 확인한다.

## 이미지 업로드와 비공개 배포

아래는 재현·재배포용 명령이다. 최초 비공개 배포는 이미 완료했다. 아래 명령은 원격 빌드 경로이며 `deploy/gcp-context.json`의 검증된 불변 digest를 사용한다. 로컬 Docker로 빌드한 경우에는 해당 이미지를 별도로 tag/push한 뒤 실제 digest를 사용한다.

```powershell
$Deployment = Get-Content -Raw deploy/gcp-context.json | ConvertFrom-Json
$ImageUri = $Deployment.deploy_image_uri
if (-not $ImageUri) { throw '검증된 이미지 URI가 없습니다.' }

gcloud run deploy $RunService --project=$GcpProjectId --region=$GcpRegion --image=$ImageUri --service-account=$RuntimeSaEmail --execution-environment=gen2 --port=8080 --cpu=1 --memory=2Gi --min=0 --max=1 --concurrency=4 --timeout=900 --cpu-throttling --no-cpu-boost --no-allow-unauthenticated --env-vars-file=deploy/cloud-run.env.yaml --set-secrets='OPENAI_API_KEY=oss-openai-key:1,SUPABASE_SECRET_KEY=oss-supabase-key:1'
```

1 vCPU·2GiB는 시작 사양이며 Linux에서 최고 메모리를 확인해 조정한다. 인스턴스를 최소 0으로 두고 요청 기반 과금을 사용한다. HTTP 동시 요청 4와 별개로 실제 분석은 DB 잠금과 프로세스 잠금으로 1건만 수락한다. Cloud Run 최대 인스턴스 설정도 일시적으로 초과될 수 있으므로 비용의 절대 상한으로 사용하지 않는다. [컨테이너 요구사항](https://docs.cloud.google.com/run/docs/container-contract), [요청 제한](https://docs.cloud.google.com/run/docs/configuring/request-timeout), [최대 인스턴스](https://docs.cloud.google.com/run/docs/configuring/max-instances)

최초에는 비공개 상태로 배포하고 인증 프록시로 시험한다.

```powershell
gcloud run services proxy $RunService --project=$GcpProjectId --region=$GcpRegion --port=8080
```

프록시가 실행 중인 동안 `http://127.0.0.1:8080`을 열어 같은 기능을 확인한다. 최소 인스턴스 0이므로 유휴 후 첫 접속에는 시작 대기가 생길 수 있다. `api/health`가 성공해도 실제 AI·공급기업·Chromium 분석을 모두 검증한 것은 아니다.

## 공개 전 비용과 기능 확인

현재 전체 프로젝트에 월 1,000원 알림 예산(크레딧 반영 후)과 Cloud Run에 월 1,000원 spend cap(크레딧 차감 전 추정 비용)을 설정했다. 둘 다 50%·80%·100%에 기본 결제 관리자와 프로젝트 소유자에게 알린다. 현재 공식 문서는 Cloud Run에 **spend cap 예산**도 지원한다. 일반 알림 예산과 구분해 설정하되, 할인 전 추정 비용·집행 지연·진행 중 요청의 초과분과 다른 서비스 비용까지 고려해야 한다. 서버 월 분석 100건 제한을 청구액 보장으로 해석하지 않는다. [예산 알림](https://docs.cloud.google.com/billing/docs/how-to/budgets), [spend cap](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps)

Artifact Registry에는 7일 지난 이미지를 삭제하고 최근 2개는 보존하는 정책을 적용했다(`deploy/artifact-cleanup.json`). 빌드 소스 버킷은 비공개·균일 접근이며 7일 후 소스를 자동 삭제한다(`deploy/build-source-lifecycle.json`). Chromium 이미지가 무료 보관 0.5GiB를 넘을 수 있다. 서울 인터넷 전송·Storage·비밀값·로그도 각 서비스의 사용량을 관측한다. [이미지 보관 요금](https://cloud.google.com/artifact-registry/pricing)

공개 전 확인할 실제 기능은 다음과 같다.

- 일반 사이트와 JavaScript 사이트에서 분석 결과·부분 오류·공급기업 추천 확인
- 모든 업무·연락처·상세정보와 한글을 포함한 PDF 확인
- 분석 중 상태 확인과 두 번째 분석의 429 응답 확인
- 실패·시간 초과 진단이 비공개 Storage에 저장되는지 확인
- 컨테이너 재기동 뒤 월 카운터·누적 처리시간·Excel·진단이 유지되는지 확인
- OOM·Chromium 실행 오류·실제 사용량과 청구 항목 확인

검증 완료 후 공개하려면 다음을 실행한다. 이 단계부터 로그인 없이 누구나 화면과 API에 접근한다.

```powershell
gcloud run services add-iam-policy-binding $RunService --project=$GcpProjectId --region=$GcpRegion --member=allUsers --role=roles/run.invoker
gcloud run services describe $RunService --project=$GcpProjectId --region=$GcpRegion --format='value(status.url)'
```

출력된 HTTPS 주소로 휴대폰·PC에서 결과와 PDF 다운로드를 확인한다. 기존 공급기업 DB·Storage를 브라우저에 공개하는 설정은 필요하지 않다.

## 기록 조회와 재배포

Cloud Logging에서 다음 필터를 사용한다.

```text
resource.type="cloud_run_revision"
resource.labels.service_name="oss-ax"
```

`cloud_startup`의 마지막 stage로 설정·비공개 버킷·운영 행·다운로드·체크섬·Excel 해석 중 어디서 멈췄는지 확인한다. `supabase_http_error`는 응답 상태만 기록한다. `cloud_ready`, `search_timing`, `analysis_finished`, `analysis_timeout`, `diagnostic_saved`, `diagnostic_upload_failed`, `analysis_admission_failed`, `analysis_release_failed`도 확인한다. 일반 앱 로그는 원문·SDK 오류 본문이 유출되지 않도록 logger와 오류 종류만 출력한다. `search_timing`은 분석 파이프라인 시간, `analysis_finished`는 부모가 관측한 실행·기록 시간을 나타내며 브라우저 렌더링 시간은 제외한다.

월 수락 건수와 누적 평균은 `deploy/cloud-runtime.sql` 마지막 SELECT로 SQL Editor에서 확인한다. 완료 통계는 부모의 finish 호출이 성공한 건만 포함하므로 강제 종료·DB 장애 때 수락 건수와 차이가 날 수 있다. 월 카운터만 한국시간 월초에 자동 전환하고 누적 완료 통계는 유지한다. 기존 로컬 JSONL·summary 파일은 클라우드로 자동 이관하지 않는다.

코드를 수정하면 테스트 → 새 이미지 빌드 → 새 태그 push → 같은 서비스 배포 순서로 진행한다. `deploy/cloud-run.env.yaml` 또는 Secret 버전 변경도 새 리비전 배포로 반영한다. 진행 중 분석을 피해서 배포한다. 종료·강제 재시작 중의 분석은 복원되지 않고 수락 한도에는 남을 수 있다.

이전 리비전으로 복구할 때는 실제 정상 버전을 조회해 선택한다.

```powershell
gcloud run revisions list --service=$RunService --project=$GcpProjectId --region=$GcpRegion
$PreviousRevision = 'REPLACE_WITH_KNOWN_GOOD_REVISION'
gcloud run services update-traffic $RunService --project=$GcpProjectId --region=$GcpRegion --to-revisions="$PreviousRevision=100"
```

과거 리비전의 Secret 버전과 Excel 객체도 보존해야 한다. 운영 SQL을 재실행해도 카운터를 초기화하지 않으며 앱 복구와 DB 초기화는 별개다.

## 오류 확인

| 증상 | 확인할 설정 |
| --- | --- |
| 시작 실패 | 필수 환경변수·SHA256·비공개 버킷·Excel 경로·운영 SQL·서버 키 |
| Supabase 401·403 | publishable 키 사용 여부, Secret 버전, service_role 테이블·함수 grant |
| 운영 행 또는 RPC 없음 | SQL 적용 대상 프로젝트, public Data API 노출·스키마 캐시 |
| 429 | 진행 중 분석, 30초 간격, 한국시간 월 수락 한도 |
| 503 | 사용량 RPC 접근 실패. 보호 장치를 건너뛰지 않고 DB 연결을 복구 |
| 504 | 앱 840초 또는 Cloud Run 900초 제한. 이미지·초기 적재·대상 사이트·AI 응답 시간 확인 |
| Chromium 실패·OOM | Docker 오프라인 점검, 브라우저 버전, Linux 격리 조건, 최고 메모리 |
| 분석 뒤 잠시 계속 429 | finish 실패·강제 종료 뒤 lease 만료 대기. 임의 카운터 초기화 금지 |
| 진단 없음 | `diagnostic_upload_failed`, Storage 용량·권한·전송 한도 |
| 예상하지 못한 요금 | AI 사용량, 다른 프로젝트와 공유하는 무료분, 이미지 누적, 서울 발신 전송 |

## 코드 검증

해시 잠금 파일은 다음 명령으로 갱신한다. 의존성을 변경할 때만 갱신하고 재검증한다.

```powershell
uv pip compile pyproject.toml --extra ax-llm --extra cloud --python-version 3.12 --universal --generate-hashes --output-file requirements-cloud.lock
```

개발 환경에 `python -m pip install -e ".[ax-llm,cloud,test]"`를 설치한 뒤 `python -m unittest discover -s tests -v`로 테스트한다. 실제 Excel 계약 시험은 `OSS_WORKBOOK_PATH`가 실제 v0.3 파일을 가리켜야 한다. SQL은 `tests/test_cloud_sql.cjs`로 로컬 PGlite에서 역할 권한·RLS·잠금·한도·월 전환·통계를 검증할 수 있다. 실제 Supabase REST와 Cloud Run의 Linux Chromium 실행은 앞의 배포 전 시험에서 최종 확인한다.
