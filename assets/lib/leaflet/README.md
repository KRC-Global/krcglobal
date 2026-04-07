# Leaflet 라이브러리 설치 안내

이 디렉토리에 다음 파일들이 필요합니다:

## 필요한 파일

1. **leaflet.css** - Leaflet CSS 스타일시트
2. **leaflet.js** - Leaflet JavaScript 라이브러리
3. **images/** 디렉토리:
   - marker-icon.png
   - marker-icon-2x.png
   - marker-shadow.png

## 설치 방법

자세한 내용은 프로젝트 루트의 `LEAFLET_DOWNLOAD_GUIDE.md` 파일을 참고하세요.

### 빠른 설치 (외부 인터넷 환경)

외부 인터넷이 연결된 컴퓨터에서 다음 URL들을 브라우저로 열어서 다운로드:

1. https://unpkg.com/leaflet@1.9.4/dist/leaflet.css
2. https://unpkg.com/leaflet@1.9.4/dist/leaflet.js
3. https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png
4. https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png
5. https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png

다운로드한 파일을 이 디렉토리에 배치하세요.

## 디렉토리 구조

```
frontend/lib/leaflet/
  ├── leaflet.css
  ├── leaflet.js
  └── images/
      ├── marker-icon.png
      ├── marker-icon-2x.png
      └── marker-shadow.png
```

## 확인

파일이 올바르게 설치되었는지 확인:

```bash
# Mac/Linux
ls -la frontend/lib/leaflet/
ls -la frontend/lib/leaflet/images/

# Windows
dir frontend\lib\leaflet
dir frontend\lib\leaflet\images
```

