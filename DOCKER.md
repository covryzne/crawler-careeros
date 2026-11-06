# Docker Compose crawler worker

Compose menjalankan coordinator backend `python -m app.crawler.worker` dan Selenium subprocess dalam satu container, dengan Python environment terpisah. Tidak ada HTTP crawler atau scheduler baru.

Panduan lengkap: [DOCKER_COMPOSE.md](../specs-careeros/DOCKER_COMPOSE.md).

Development Windows, dari repo ini:

```powershell
$env:BACKEND_CONTEXT = '../careeros-backend'
docker compose --env-file ../careeros-backend/.env.development -f compose.development.yml up -d --build
```

Default build context backend adalah `../backend-careeros`, sesuai nama folder server. Backend source dan DB URL dipilih eksplisit; tidak memerlukan salinan secret DB dalam env crawler. Path conda/venv host tidak dipakai container. Image menyediakan Selenium headless maupun headed melalui Xvfb, bukan Browser Use. Compose staging membaca CRAWLER_BROWSER_MODE dari env backend yang dipilih.

Stop worker tmux environment yang sama sebelum transisi. Artefak/cache disimpan pada volume per environment. Worker sekarang mendukung staging dengan local identity dan embedded agent worker dinonaktifkan oleh Compose. Production worker masih ditolak. Ikuti [STAGING.md](STAGING.md) untuk build, smoke test display/browser, dan serve di VM. Sinkronkan perubahan backend worker dan crawler ke server sebelum build.
