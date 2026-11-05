# Docker Compose crawler worker

Compose menjalankan coordinator backend `python -m app.crawler.worker` dan Selenium subprocess dalam satu container, dengan Python environment terpisah. Tidak ada HTTP crawler atau scheduler baru.

Panduan lengkap: [DOCKER_COMPOSE.md](../specs-careeros/DOCKER_COMPOSE.md).

Development Windows, dari repo ini:

```powershell
$env:BACKEND_CONTEXT = '../careeros-backend'
docker compose --env-file ../careeros-backend/.env.development -f compose.development.yml up -d --build
```

Default build context backend adalah `../backend-careeros`, sesuai nama folder server. Backend source dan DB URL dipilih eksplisit; tidak memerlukan salinan secret DB dalam env crawler. Path conda/venv host tidak dipakai container. Hanya Selenium headless yang disertakan, bukan Browser Use.

Stop worker tmux environment yang sama sebelum transisi. Artefak/cache disimpan pada volume per environment. **Worker saat ini menolak APP_ENV staging/production**; file Compose tersebut belum dapat menjalankan workflow sampai dukungan aplikasi ditambahkan.
