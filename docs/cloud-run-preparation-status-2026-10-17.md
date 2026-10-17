# Cloud Run 배포 준비 진행 기록

2026년 10월 17일 한국시간 기준. 이 프로젝트에서 이미 완료한 설정을 다시 수동으로 적용할 필요는 없다.

## 완료한 설정

- 기존 Supabase `KMAC_CODExTOPZONE`가 Free·서울·정상 가동 중임을 확인했다.
- `cloud_runtime` 마이그레이션 `20261017110021`을 적용하고 같은 버전의 파일을 저장소에 기록했다.
- 운영 테이블의 RLS 활성, 브라우저 역할의 테이블·함수 접근 차단, 서버 역할의 필요한 접근 권한을 확인했다.
- 실제 DB에서 분석 수락·잠금 해제 함수를 시험하고 트랜잭션을 되돌렸다. 월 수락·완료 카운터는 모두 0이고 진행 중 잠금은 없다.
- 비공개 `oss-runtime` Storage 버킷을 생성했다. 사용 중인 v0.3 Excel은 약 1.10MiB이며 활성 Task 147개를 확인했다.
- Excel을 `knowledge/kb-v03-5a501eabc9d6.xlsx`에 업로드하고 내려받은 파일의 SHA256이 원본과 일치함을 확인했다.
- `deploy/cloud-run.env.yaml`에 실제 Supabase URL·객체 경로·체크섬을 입력했다.
- `.env.cloud.local`을 로컬에 준비했다. 비밀값이 들어 있어 Git·Docker·Cloud Build 전송에서 제외한다. 내용을 채팅에 붙여넣을 필요는 없다.
- 실제 운영 진입점으로 비공개 Excel 다운로드·서버 기동·한글 PDF 응답·잘못된 분석 입력 거절을 확인했다. AI 요청은 0회다.
- Docker·WSL 설치 대신 사용할 `cloudbuild.yaml`을 준비했다. Linux 이미지 빌드와 Chromium·한글 PDF 점검이 성공해야 이미지를 게시한다.
- `.gcloudignore`에 소스 전송 허용 목록을 설정했다. 비밀값·Excel·진단·Git 이력은 전송하지 않는다.
- Google Cloud CLI 589.0.0을 사용자 폴더에 설치하고 공식 배포 파일의 SHA256을 검증했다. 실행 경로는 `C:\Users\ujkio\AppData\Local\Google\CloudSdkPortable\google-cloud-sdk\bin\gcloud.cmd`다.
- 실제 `gcloud meta list-files-for-upload` 결과 54개 파일을 확인했다. 비밀 환경파일·Excel·진단·배포 설정은 0개였다.
- Google Cloud CLI 로그인을 확인했다.
- 별도 프로젝트 `KMAC OSS AX`를 생성했다. 프로젝트 ID는 `kmac-oss-ax-20261017-0e4a`, 번호는 `591110969614`다. 배포 대상 정보는 `deploy/gcp-context.json`에 기록했다.
- 실행 계정 `oss-runtime`과 빌드 계정 `oss-builder`를 생성했다. 필요한 Run·Artifact Registry·Secret Manager·IAM·Logging·Storage·Cloud Build·Billing Budgets API를 활성화했다.
- 사용자가 새로 만든 원화 결제 계정 `KMAC OSS AX`(`01BA23-14ECAE-59007D`)의 활성 상태를 확인하고 이 프로젝트에 연결했다. `billingEnabled=true`를 확인했다. 기존의 닫힌 결제 계정과 다른 프로젝트는 변경하지 않았다.
- 전체 프로젝트에 월 1,000원 알림 예산을 만들었다. 모든 크레딧을 반영하며 50%·80%·100%에 기본 결제 관리자·프로젝트 소유자에게 알린다.
- Cloud Run에 월 1,000원 spend cap을 만들고 `CONFIGURED` 상태를 확인했다. 이는 크레딧 차감 전 추정 비용 기준이다. 무료분 안에서도 중단될 수 있으며, 집행 지연과 진행 중 요청의 초과 비용·다른 서비스 비용은 남는다. [공식 한계](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps)
- Secret Manager에 `oss-openai-key:1`, `oss-supabase-key:1`을 등록하고 실행 계정에 이 두 Secret의 읽기 권한만 부여했다. 키 내용은 기록하지 않았다.
- 서울 Artifact Registry `oss-images`를 생성했다. 7일 지난 이미지는 삭제하고 최근 2개 버전은 보존하는 정책을 적용했다.
- 서울 비공개 빌드 소스 버킷 `kmac-oss-ax-20261017-0e4a-build-source`를 생성하고 공개 접근 차단·균일 접근·7일 후 객체 삭제를 설정했다.
- 빌드 계정에 해당 이미지 저장소 쓰기·소스 버킷 객체 읽기·로그 쓰기 권한을 부여했다. 빌드에 실행용 API 키나 Excel은 제공하지 않았다.
- Linux amd64 이미지 빌드·비관리자 Chromium JavaScript 실행·한글 PDF 생성·이미지 push가 모두 성공했다. [실제 Cloud Build 결과](https://console.cloud.google.com/cloud-build/builds;region=asia-northeast3/3dda215d-3a8f-41a1-8b31-02033d9ff097?project=591110969614)
- 검증된 이미지 태그는 `20261017-201713`, digest는 `sha256:3efbd670478e7a1bb03a85c1b6dc30e7b1c8777b1dc78b490dc02c172ec57c18`이다. 배포할 불변 이미지 URI는 `deploy/gcp-context.json`의 `deploy_image_uri`에 기록했다.

Supabase 보안 Advisor에는 서버 전용 설계에 따른 `RLS Enabled No Policy` 정보성 항목 18개가 있고 WARN·ERROR는 없었다. 브라우저 정책을 추가할 필요는 없다. [공식 설명](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy)

## 배포·외부 공유 완료

사용자가 비공개 시험 배포·주요 기능 검증·외부에서 사용 가능한 URL 제공을 요청해 비공개 배포부터 순서대로 진행했다. 인증 접속·실제 기업 분석·PDF·중복 분석 거절·실패 진단을 확인한 뒤 공개 호출 권한을 적용했다.

공유 주소는 **[OSS AX 매칭 서비스](https://oss-ax-591110969614.asia-northeast3.run.app/)**다. 현재 로그인 없이 접속할 수 있다. 실제 배포 리비전과 기능별 결과는 [운영 검증 기록](cloud-run-live-verification-2026-10-17.md)을 따른다. 계정·결제·키 복사·Docker 설치 등 사용자가 직접 해야 할 사전 설정은 남아 있지 않다.

배포 전 코드 검증은 Python 162개, 운영 서버 대상 14개, SQL의 역할 권한·RLS·경합·한도·월 전환·누적 통계를 통과했다. 실제 Supabase를 사용한 네이티브 서버 기동·한글 PDF·입력 검증과 원격 Linux 이미지·Chromium·PDF 검증도 통과했다. Cloud Run의 실제 기능 결과와 비용·공유 한도는 운영 검증 기록에 별도로 정리했다.

전체 절차와 명령은 [Cloud Run 설정 가이드](cloud-run-supabase-deployment-guide.md)를 참고한다.
