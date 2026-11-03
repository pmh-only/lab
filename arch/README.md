# arch.pmh.codes

[고해상도 아키텍처 뷰어](https://arch.pmh.codes) · [draw.io 원본](../docs/architecture/lab-architecture.drawio) · [고해상도 PNG](../docs/architecture/lab-architecture-hires.png)

OpenSeadragon 6.1.1로 탐색하는 정적 Deep Zoom 사이트다. 외부 CDN·API·로그인·스토리지 연결 없이 이미지 안에 뷰어·타일·다운로드 원본을 함께 패키징한다.

- 원본 XML을 **4배 크기 15,360 × 17,200**으로 다시 렌더링했다. 기존 PNG를 단순 확대하지 않았다.
- **무손실 PNG 512px, overlap 1px, 16단계, 1,385개 타일**. 화면에 필요한 타일만 가져온다.
- 드래그·휠·터치 확대, 미니맵, 전체 화면, 영역 바로가기, PNG/draw.io 다운로드.
- 100%는 고해상도 이미지의 픽셀과 화면 CSS 픽셀이 1:1인 배율이다. 기존 draw.io 배율 100%는 여기서 약 25%다.
- 노드·서비스 배치는 **2026-11-03 스냅샷**이며 실시간 인프라 뷰어가 아니다.

## 배포

`Architecture viewer` workflow가 ARM64 이미지를 `ghcr.io/pmh-only/lab-arch:sha-<Git SHA>`로 빌드한다. 테스트가 성공해야 이미지를 게시한다. `kustomization.yml`에는 검증한 이미지 digest를 고정한다.

`apps/arch.yml` → Argo CD → namespace `arch` → 비특권 NGINX `:8080` → Service → 공용 Envoy HTTPRoute → 기존 NGINX TLS edge → `arch.pmh.codes`.

Pod는 읽기 전용 루트 파일시스템, 임시 `/tmp`, 서비스 계정 토큰 비활성화, capabilities 제거, non-root 사용자로 실행한다. PVC·Secret은 없다. 콘텐츠 해시가 포함된 타일/다운로드 URL은 1년 캐시하며 HTML·JS·manifest는 재검증한다. 누락된 타일은 HTML 대신 404를 반환한다.

## 로컬 검증

```sh
cd arch
npm ci
npm run build
npm test
python3 -m http.server 8769 --directory dist
```

프로덕션 헤더·권한 설정까지 확인하려면 저장소 루트에서 이미지를 빌드한다.

```sh
docker build -f arch/Dockerfile -t lab-arch:preview .
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=32m -p 127.0.0.1:8769:8080 lab-arch:preview
```

테스트는 DZI 크기, 모든 타일의 존재·가장자리 크기, 최고 배율의 원본 픽셀 일치, 렌더링 16구역의 잘림, 자체 제공 자산을 확인한다.

## 도면 갱신

1. draw.io 원본을 수정한 뒤 diagrams.net에서 4배 배율로 렌더링한다. 초대형 한 장 캡처는 브라우저가 하단을 빈 화면으로 만들 수 있으므로 **3840×4300 화면 4×4개를 좌표 이동으로 렌더링·무손실 합성**하고 전체 축소본도 검토한다.
2. `docs/architecture/lab-architecture-hires.png`와 `source.json`의 크기·snapshotDate·drawioSha256·pngSha256을 함께 갱신한다. 해시가 다르면 빌드를 중단한다.
3. `npm run build && npm test` 및 데스크톱·모바일 브라우저로 확대, 영역 이동, 다운로드를 검증한다.
4. 변경을 푸시하여 workflow를 실행한다. 성공한 이미지의 digest로 `kustomization.yml`을 갱신하고 푸시한다. Argo CD 동기화·rollout·공개 HTTPS와 실제 타일 요청을 확인한다.

생성 타일과 `node_modules`·`dist`는 Git에 넣지 않는다. 다운로드 원본 draw.io의 제품 아이콘은 외부 SVG URL을 참조하지만, 뷰어의 PNG 타일에는 이미 렌더링되어 있다. OpenSeadragon의 라이선스는 `/vendor/openseadragon/LICENSE.txt`에 함께 제공한다.
