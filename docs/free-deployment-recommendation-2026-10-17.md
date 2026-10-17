# OSS AX 매칭 프로젝트 무료 배포 방식 검토

조사 기준일: 2026년 10월 17일 한국시간. 코드 기준: `1a11d4e`. 소규모 시범 운영과 간헐적 사용을 전제로 비교했다.

후속 준비: Dockerfile·운영 서버·영속 한도·비공개 파일 처리를 구현했다. 현재 설정과 남은 검증은 [실제 Cloud Run 준비 가이드](cloud-run-supabase-deployment-guide.md)를 따른다. 아래 처리시간은 조사 시점의 로컬 관측이다.

**가장 적합한 구성은 Google Cloud Run의 무료 사용량을 활용한 Docker 배포와 기존 Supabase Free의 조합이다.** Python 서버에서 화면·분석·PDF를 함께 제공하면 현재 구조를 유지하면서 긴 분석과 Chromium 실행을 수용할 수 있다.

다만 이 구성은 **무료 한도 안에서 서버 비용을 줄이는 방식**이다. 결제 계정이 필요하고 한도 초과·이미지 보관·인터넷 전송 비용이 발생할 수 있다. 현재 앱이 호출하는 AI API 비용도 별도다. 전체 서비스의 영구적인 월 0원을 보장하는 배포안으로 해석하면 안 된다. [Google 무료 프로그램](https://docs.cloud.google.com/free/docs/free-cloud-features), [Cloud Run 과금](https://cloud.google.com/run/pricing)

## 프로젝트의 배포 요구 조건

| 확인한 구조 | 무료 배포 선택에 미치는 영향 |
| --- | --- |
| Python 3.11 이상과 HTML·CSS·JavaScript 화면 | 화면과 서버를 하나의 컨테이너에 넣을 수 있음 |
| 요청 안에서 크롤링·여러 AI 호출·검증·공급기업 조회 수행 | 긴 HTTP 요청을 수용해야 함 |
| Playwright가 Chromium을 실행 | 브라우저 바이너리·OS 패키지·메모리가 필요함 |
| 시작 시 Excel을 메모리로 적재 | 클라우드에서 접근 가능한 비공개 Excel이 필요함 |
| Supabase는 서버에서 REST로 조회 | 기존 DB를 재사용할 수 있음 |
| ReportLab과 포함된 한글 글꼴로 PDF 생성 | 별도 PDF 서비스는 필요하지 않음 |
| 처리시간·실패 진단을 로컬 파일로 저장 | 인스턴스 종료 후에도 보존하려면 외부 저장 필요 |
| 현재 실행부는 `ThreadingHTTPServer` | 공개 운영 전에 운영용 HTTP 실행부를 준비해야 함 |

근거 파일: `pyproject.toml`, `src/oss/web_server.py`, `browser_render.py`, `pdf_report.py`, `search_timing.py`, `empty_output.py`, `env.example`. Python 공식 문서도 현재 사용하는 `http.server`를 운영용으로 권장하지 않는다. [Python 문서](https://docs.python.org/3/library/http.server.html)

### 실제 분석 시간

`reports/search-timing/searches.jsonl`의 323건을 집계했다. 기록 기간은 2026년 10월 15일 20:05부터 10월 17일 19:26 KST까지다. P95는 정렬한 값의 `ceil(0.95 × 건수)`번째 값이다.

| HTTP 200 응답 표본 | 건수 | 평균 | 중앙값 | P95 | 최장 | 300초 초과 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 전체 기록의 HTTP 200 | 268 | 144.07초 | 117.13초 | 327.94초 | 457.87초 | 24 |
| 마지막 코드 식별자 `b297b3ba92144e57` | 59 | **278.13초** | 282.15초 | **408.01초** | **457.87초** | **24** |

최근 구간은 10월 17일 17:25부터 19:26 KST까지다. 이전 코드의 빠른 요청이 섞인 전체 평균보다 최근 구간을 용량 계산에 사용했다. 로그의 마지막 코드 식별자와 현재 Git HEAD는 서로 다른 식별 방식이므로 동일 커밋이라고 단정하지 않는다.

이는 로컬 관측이며 클라우드 성능이나 동시 부하 측정은 아니다. HTTP 200에도 부분 오류·빈 추천이 포함될 수 있다. 그래도 현재 단일 요청 구조에는 5분보다 긴 실행 여유가 필요하다는 근거가 된다.

## 무료 서비스 비교

| 후보 | 공식 무료 조건과 제약 | 이 프로젝트에 대한 판단 |
| --- | --- | --- |
| **Cloud Run** | 요청 기반 무료 사용량 제공. 컨테이너 실행, 요청 제한 최대 60분 | **종합 1순위.** 긴 분석과 Chromium에 적합. 초과 과금 가능 |
| **Oracle Cloud Always Free VM** | A1은 현재 문서 기준 총 2 OCPU·12GB 상당, 블록 저장 200GB. 무료 자원 확보와 유휴 회수 조건 존재 | **서버 요금 0원 우선 시 대안.** 직접 OS·TLS·백업 관리와 ARM 브라우저 검증 필요 |
| **Render Free** | 0.1 CPU·512MB, 월 750시간 공유. 15분 유휴 후 정지, 영구 디스크 불가 | Chromium 포함 분석에는 자원 부족 위험이 큼 |
| **Railway Free** | 월 $1 크레딧, RAM 최대 0.5GB | 현재 전체 분석 서버에는 자원이 제한적 |
| **Vercel Hobby** | Fluid Compute의 Python 최대 300초. 개인·비상업 용도 한정 | 최근 표본의 24건이 시간 한도를 넘음. 기업용 서비스에도 우선 선택하기 어려움 |
| **Hugging Face Docker Spaces** | CPU Basic의 시간당 요금은 무료지만 현재 새 Docker Space 생성에는 유료 플랜 필요 | 신규 무료 배포안에서 제외 |
| **Supabase Edge Functions Free** | 메모리 256MB, worker 실행 150초, 요청 idle timeout 150초 | 현재 분석 서버를 통째로 이전하기 부적합. Supabase는 DB·파일 저장 역할로 유지 |

Cloud Run 조건: [요청 제한](https://docs.cloud.google.com/run/docs/configuring/request-timeout), [무료 사용량](https://cloud.google.com/run/pricing). Oracle 조건: [Always Free 공식 문서](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm). Render 조건: [사양](https://render.com/docs/compute-plans), [무료 운영 제한](https://render.com/docs/free). Railway 조건: [플랜별 자원](https://docs.railway.com/pricing/plans). Vercel 조건: [함수 제한](https://vercel.com/docs/functions/limitations), [Hobby 사용 범위](https://vercel.com/docs/plans/hobby). Hugging Face 조건: [Spaces 생성 요건](https://huggingface.co/docs/hub/spaces-overview). Supabase 조건: [Edge Functions 제한](https://supabase.com/docs/guides/functions/limits).

Oracle A1의 유휴 회수 기준은 7일 동안 CPU의 95백분위 사용률·네트워크 사용률·메모리 사용률이 각각 20% 미만인 경우다. 간헐적 시연 앱은 이 조건의 영향을 받을 수 있다. 널리 알려진 과거의 4 OCPU·24GB 값을 이번 견적에 사용하지 않았다. 무료 인스턴스의 실제 생성 가능 여부는 계정과 홈 리전의 가용 자원에 따라 확인해야 한다. [Oracle 공식 조건](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)

정적 화면만 무료 호스팅에 올려서는 크롤링·AI 분석·PDF API가 실행되지 않는다. 현재 규모에서는 화면 호스팅을 별도로 분리할 실익도 작다.

## 추천 구성과 초기 설정

사용자 브라우저 → Cloud Run의 화면·분석 API·PDF API → 기존 Supabase 및 외부 AI API로 구성한다. Cloud Run은 **서울 `asia-northeast3`**를 우선한다. 국내 사용자 접근성과 기존 서울 Supabase 배치를 고려한 선택이다. 서울은 Tier 2 요율, 도쿄는 Tier 1 요율이므로 국내 배치가 필요 없고 무료 사용량 효율이 더 중요하면 도쿄도 비교할 수 있다. [리전과 요율 구분](https://docs.cloud.google.com/run/docs/locations)

| 설정 | 초기 제안 |
| --- | --- |
| 배포 단위 | Python·Chromium·글꼴·화면을 포함한 Docker 이미지 1개 |
| 과금 | 요청 기반 |
| CPU·메모리 | 1 vCPU·2GiB에서 시작하고 Linux 실측 후 조정 |
| 최소 인스턴스 | 0 |
| 최대 인스턴스 | 서비스 단위 1에서 시작 |
| HTTP 요청 제한 | 900초 |
| 서버 프로세스 | 1개 |
| HTTP 동시 요청 | 예: 4개. 별도로 분석 실행은 프로세스당 1건 제한 |
| 추가 분석 요청 | 오래 대기시키지 않고 혼잡 안내·재시도 응답 |

분석 제한과 HTTP 요청 수를 구분해야 분석 중에도 상태 확인·화면 요청을 처리할 수 있다. 2GiB는 시험 시작값이며 충분함을 검증한 값은 아니다. 인스턴스 최대값도 일시적으로 초과될 수 있으므로 비용의 절대 상한으로 사용하지 않는다. [인스턴스 제한 동작](https://docs.cloud.google.com/run/docs/configuring/max-instances)

Excel은 기존 Supabase의 비공개 Storage에 두고 시작 시 다운로드하는 방식을 우선 검토한다. 서버 키는 비밀값으로 주입한다. 실패 진단은 비공개 Storage에, 처리시간은 구조화된 로그에 기록하고 기존 누적 집계가 필요하면 작은 DB 테이블로 유지한다. 정상 분석 결과를 저장하지 않는 현재 정책도 유지할 수 있다. 이 설계는 별도 GCS 버킷을 필수로 추가하지 않아도 된다는 장점이 있다.

Cloud Run의 기본 쓰기 파일시스템은 메모리를 사용하고 인스턴스 종료 시 사라진다. 현재 JSONL과 summary 파일을 그대로 두면 재시작 뒤 기록이 유실되므로 저장 경로 변경은 배포 준비에 포함해야 한다. [컨테이너 파일시스템](https://docs.cloud.google.com/run/docs/container-contract#file_system)

## 무료 사용량과 비용 범위

Cloud Run 요청 기반 무료 사용량은 **월 180,000 vCPU초·360,000 GiB초·200만 요청**에 해당한다. 청구 계정별로 합산하며 Tier 1 가격에 해당하는 금액 할인으로 적용된다. 따라서 서울에서 위 초 수가 그대로 무료라고 가정하면 안 된다. 분석 시간 동안 AI 응답을 기다리는 시간도 할당 자원의 처리시간에 들어간다. [Cloud Run 가격](https://cloud.google.com/run/pricing)

최근 평균 278.125초와 1 vCPU·2GiB, 한 번에 분석 1건이라는 가정으로 계산하면 다음과 같다.

| 월 분석 건수 | CPU 사용량 | 메모리 사용량 |
| --- | ---: | ---: |
| 100건 | 약 27,813 vCPU초 | 약 55,625 GiB초 |
| 300건 | 약 83,438 vCPU초 | 약 166,875 GiB초 |
| 500건 | 약 139,063 vCPU초 | 약 278,125 GiB초 |
| 1,000건 | 약 278,125 vCPU초 | 약 556,250 GiB초 |

**월 100~300건의 시범 사용부터 시작하고 실제 청구 사용량으로 조정하는 것이 합리적이다.** 표는 요청 처리 자원의 단순 추정으로 시작·종료 시간, 실패·재시도, PDF와 화면 요청, 다른 프로젝트 사용량을 제외한다. 월 1,000건은 이 가정만으로 Tier 1 무료 자원량도 초과한다. 서울에서 월 500건까지 무료라고 확정할 근거는 없다.

| 비용 항목 | 판단 |
| --- | --- |
| Cloud Run 처리 자원 | 소규모·간헐 사용이면 무료분 활용 가능 |
| 기존 Supabase Free | 한도 안에서 기본 요금 0원 유지 가능 |
| AI API | 배포 무료분에 포함되지 않음. 현재 로그에는 토큰별 비용 자료가 없음 |
| Artifact Registry 이미지 | 무료 보관 0.5GiB. Chromium 이미지와 과거 버전이 한도를 넘길 수 있음 |
| 인터넷 전송 | 서울의 인터넷 발신 전송까지 무료라고 가정할 수 없음 |
| 추가 저장·빌드·비밀값·로그 | 각 서비스의 별도 무료분·사용량 확인 필요 |
| 도메인 | 기본 서비스 주소로 시작하면 별도 구매 불필요 |

이미지 보관 조건은 [Artifact Registry 가격](https://cloud.google.com/artifact-registry/pricing), 인터넷 전송 조건은 [Cloud Run 가격](https://cloud.google.com/run/pricing)에 따른다. 초기 체험 크레딧의 유효기간과 매월 제공되는 무료 사용량은 구분해야 한다. [Google 무료 프로그램](https://docs.cloud.google.com/free/docs/free-cloud-features)

기존 [Supabase 실점검 기록](supabase-deployment-readiness-2026-10-17.md)은 10월 17일 02:09~02:12 KST에 Free·서울·DB 약 37MB를 확인했다. 이번에는 이 기록을 활용했으며 현재 계정을 재조회한 값은 아니다. 공식 Free 한도는 DB 500MB·파일 1GB·일반 egress 5GB이고, 1주 비활성 일시중지와 자동 백업 미포함 조건이 있다. Excel·진단을 추가하면 기존 저장·전송 사용량과 합산해 관리해야 한다. [Supabase 가격](https://supabase.com/pricing)

## 무료 운영을 유지하기 위한 준비

1. **운영 서버와 Docker 준비.** 기존 분석 함수를 재사용하고 HTTP 진입부를 운영용으로 바꾼다. `0.0.0.0`과 플랫폼의 `PORT`를 읽고, 설치된 Playwright 버전과 일치하는 Chromium을 이미지에 포함한다.
2. **분석 실행과 총량 제한.** 분석 동시 실행 1건, 요청 빈도 제한, 전체 처리시간 제한을 둔다. 월 분석 제한은 재시작으로 초기화되지 않는 공용 저장소에서 실패·재시도까지 계산한다. 공개 API에는 로그인 없는 사용 흐름에 맞는 자동 호출 억제 장치를 적용한다.
3. **Excel과 운영 기록 보존.** 비공개 파일 배포·다운로드와 실패 진단 업로드를 구현하고, 키를 프런트에 노출하지 않는다. 기존 누적 통계가 재기동 후에도 유지되는지 확인한다.
4. **실제 비용 제한 설정.** Billing의 알림 예산과 Cloud Run spend cap을 구분한다. 알림 예산만으로는 사용이 중단되지 않는다. 현재 공식 문서는 Cloud Run의 spend cap을 지원하지만 할인 전 추정 비용을 사용하고 집행 지연·진행 중 요청의 초과 비용이 남을 수 있다. 이미지 저장·외부 AI 등 다른 비용도 별도로 관리한다. [알림 예산](https://docs.cloud.google.com/billing/docs/how-to/budgets), [spend cap 조건](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps)
5. **Linux와 클라우드에서 검증.** 일반 사이트·JavaScript 사이트 분석, 공급기업 조회, 한글 PDF, 분석 중 두 번째 요청, 5분 초과 요청, 재시작 뒤 Excel·진단·통계, 최고 메모리를 확인한다. 이후 실제 청구 항목을 보고 월 사용 한도를 조정한다.

후속 작업에서 Dockerfile과 운영 HTTP 진입부를 준비했다. [Cloud Run 배포 가이드](cloud-run-supabase-deployment-guide.md)에 실제 구현에 맞는 설정·명령·남은 Linux 검증을 정리했다.

## 최종 선택 기준

- **현재 프로젝트의 소규모 공개 시범 운영:** Cloud Run 무료분과 기존 Supabase Free를 선택한다. 기능 적합성과 관리 부담을 함께 고려한 최우선안이다.
- **서버 청구가 반드시 0원이어야 함:** Oracle Always Free를 대안으로 검토하되 자원 확보·유휴 회수·직접 운영을 감수해야 한다. 외부 AI 비용은 계속 남는다.
- **전체 서비스 비용이 반드시 0원이어야 함:** 현재의 외부 AI API 분석 구조까지 포함하면 이번에 비교한 호스팅만으로 충족할 수 없다. 분석 방식·사용량·비용 조건을 별도로 바꿔야 한다.

기존 배포 보고서의 Render 유료 추천은 운영 편의성과 고정비를 우선한 판단이다. 무료 사용을 우선하는 이번 요구에서는 Cloud Run을 추천한다. 이 검토에서는 앱 코드 변경이나 실제 배포·요금제 변경을 수행하지 않았다.
