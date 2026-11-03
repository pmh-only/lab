# 고해상도 아키텍처 타일

- **뷰어**: https://arch.pmh.codes/ — 기존 OpenSeadragon **4.1.0**, HTML·라우팅 변경 없음.
- **고해상도 PNG**: [저장소 원본](./lab-architecture-hires.png) · [배포된 이미지](https://arch.pmh.codes/lab-architecture-hires.png).
- **DZI**: https://arch.pmh.codes/diagram.dzi — 기존 뷰어의 `tileSources` 경로를 유지한다.
- **타일**: `s3://arch/diagram-6fd4e8df3d4163b8_files/` — 512px 무손실 PNG, overlap 1px, 16단계·1,385개.
- **해상도**: 15,360 × 17,200. draw.io XML을 4배 배율로 다시 렌더링했으며 기존 PNG의 단순 확대가 아니다.
- **스냅샷**: 2026-11-03. 실시간 상태가 아니다.

## 생성·배포 기록

브라우저의 초대형 캡처 하단 잘림을 피하기 위해 3840×4300 화면을 원본 좌표로 이동하며 4×4개 렌더링하고 무손실 합성했다. Sharp 0.35.5로 `png({compressionLevel:9}).tile({size:512,overlap:1,layout:'dz',depth:'onepixel',skipBlanks:-1})`을 사용했다.

모든 단계의 타일 수·가장자리 크기, 최고 배율 원본 픽셀 일치, 렌더링 16구역의 콘텐츠 존재를 검사했다. S3 업로드 후 모든 파일의 크기·MD5와 공개 타일 샘플을 대조하고, 마지막에 `diagram.dzi`의 `Url`만 새 타일 디렉터리로 전환했다. 뷰어 HTML은 변경 전후 SHA256이 동일하다. 실제 사이트에서 전체 도면과 확대 로딩을 확인했다.

기존 `diagram_files/` JPG 타일은 보존했다. 새 타일은 1년 캐시하며 `diagram.dzi`는 `no-cache,max-age=0,must-revalidate`다. 갱신 시 새 버전 경로로 타일을 먼저 모두 올리고 검증한 뒤 DZI를 전환한다. 새 컨테이너·CI·Kubernetes 앱은 필요하지 않다.

| 파일 | SHA256 |
| --- | --- |
| `lab-architecture.drawio` | `efae525ceb6468fe7e36fbc2e676a8401d666db74b4f840248cb89340af72051` |
| `lab-architecture-hires.png` | `6fd4e8df3d4163b8a6933fa4a8e829236cf75856eae21e183d97d3c773fa9ac4` |
