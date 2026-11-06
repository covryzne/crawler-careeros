# Rencana crawler service: profil Indeed, retry, paralelisme, dan jadwal per user

Tanggal: 7 November 2026 (Asia/Jakarta). Status: rencana untuk ditinjau; bukan implementasi fitur service/UI.

Dokumen ini menyimpan konteks percobaan server dan keputusan diskusi agar pekerjaan bisa dilanjutkan tanpa membaca ulang chat. Basis kode saat ditulis: crawler `61fd405`, backend `a4d79f9`, frontend `7803a1b`. Branch `dev` dan `staging` ketiga repo telah diselaraskan. Sesuai arahan pengguna, pekerjaan dilanjutkan langsung pada branch `dev` yang sudah ada, tanpa membuat branch baru.

## 1. Keputusan yang sudah disepakati

- Tahap sekarang adalah uji stabilitas portal lewat tombol crawl manual. Scheduler belum menjadi pemicu operasional.
- Nanti user memilih jadwal sendiri dari pilihan waktu yang disediakan UI, tanpa mengetik ekspresi cron. Contoh: setiap hari pukul 05.00 dan 17.00 Asia/Jakarta.
- Setiap user memiliki jadwal, konfigurasi, riwayat crawl, dan daftar lowongannya sendiri. User A tidak bisa melihat atau mengubah data user B.
- Tombol manual dan scheduler masuk ke sistem antrean/worker yang sama.
- Setiap jadwal dieksekusi sebagai crawl baru. Retry sumber gagal tetap berada pada crawl yang sama, dengan riwayat percobaan baru.
- Profil persisten dipakai khusus Indeed, dikelola aplikasi/operator di server. Profil bukan milik browser pribadi pengguna; tidak meminta cookie pengguna atau login akun Google/Indeed pengguna.
- Tidak membangun dashboard admin atau browser jarak jauh lewat web pada tahap ini. Operator bersedia memperbarui sesi lewat Chrome server dan MobaXterm/X11.
- Pekerjaan user berbeda dan portal berbeda harus bisa berjalan paralel sesuai kapasitas. Satu profil Indeed tidak boleh dibuka oleh beberapa proses Chrome sekaligus.
- Beberapa profil Indeed yang terpisah dapat diuji sebagai pool untuk menambah kapasitas paralel. Jumlah dan kestabilannya belum ditentukan.
- Opsi menggabungkan pencarian identik antar-user hanya gagasan optimasi lanjutan; belum disepakati untuk diimplementasikan. Rencana awal tetap crawl dan hasil terpisah per user.

## 2. Bukti percobaan dan kondisi kode saat ini

### CLI yang sudah tersedia

Implementasi ada di [model request](../src/crawler/models.py), [CLI](../src/crawler/cli.py), [browser runner](../src/crawler/runner.py), dan [verifikasi](../src/crawler/verification.py).

- `--auto-verify`: mencoba interaksi checkbox pada JobStreet/Indeed.
- `--verification-max-clicks`: batas klik total per tahap verifikasi, default 1, rentang 1–20.
- `--verification-timeout`: deadline bersama seluruh percobaan pada tahap tersebut, default 60 detik, maksimum 300.
- Jeda minimal 5 detik setelah klik berhasil dikirim. Checkbox yang tercentang tidak diklik ulang.
- Pencarian widget mencakup shadow root tertutup yang diekspos WebDriver. Jika input tersembunyi, gunakan label yang terhubung ke input tersebut.
- `--indeed-user-data-dir`: folder profil persisten khusus Indeed; portal lain tetap memakai konfigurasi browser yang ada.
- Folder `.browser-profiles/` sudah diabaikan Git. Cookie dan isi profil tidak di-commit.

### Hasil yang sudah diamati

| Percobaan | Hasil |
| --- | --- |
| JobStreet dengan checkbox otomatis | User mengonfirmasi lolos verifikasi, ditemukan dan diterima 3 lowongan |
| Indeed dengan klik otomatis berulang | Klik berhasil dikirim, tetapi challenge tetap berulang |
| Indeed dengan klik manual pada Chrome Selenium | Tetap tidak masuk listing pada percobaan user |
| Indeed dengan Chrome biasa di server | User mengonfirmasi bisa masuk listing setelah verifikasi manual |
| Indeed memakai profil khusus yang disiapkan lewat Chrome biasa | Run `20261106T170523Z-0ac6be` selesai, ditemukan dan diterima 3 lowongan |

Satu run sukses belum membuktikan profil akan selalu diterima, tahan lama, atau stabil untuk banyak user. Profil baru tidak menjamin kelolosan. Menambah retry tidak menjamin Cloudflare menerima browser.

Suite crawler terakhir setelah perubahan dipindahkan ke basis `dev`: 174 tes lulus, termasuk fixture Chrome lokal dan persistensi cookie/localStorage setelah restart browser. Itu bukan pengujian beban atau bukti keberhasilan scheduler/service.

### Celah service yang harus ditangani

- [Worker backend](../../backend-careeros/app/crawler/worker.py) belum meneruskan konfigurasi profil Indeed dan opsi verifikasi CLI ke request engine service.
- Compose crawler belum memasang volume profil persisten. Folder profil host yang dipakai CLI tidak otomatis terlihat di container.
- `.dockerignore` perlu ditinjau agar `.browser-profiles/` tidak terkirim sebagai build context atau tersalin ke image. Git-ignore saja tidak mencukupi.
- [Model crawler backend](../../backend-careeros/app/models/crawler.py) saat ini membatasi satu run aktif secara global melalui `execution_slot=1`, indeks `uq_crawl_active_slot`, dan singleton `CrawlWorkerSlot`.
- Worker memproses platform dan keyword secara berurutan. Pemisahan antrean per sumber belum tersedia.
- Sudah ada `owner_id`, `trigger_type` manual/scheduled, dan `schedule_id` pada run. Komentar model menyatakan tabel/FK jadwal masih ditunda. Field ini bukan scheduler yang sudah berfungsi.
- [Ingestion](../../backend-careeros/app/services/crawler/ingestion.py) dan [layanan run](../../backend-careeros/app/services/crawler/runs.py) telah memiliki pemeriksaan/pencarian berdasarkan pemilik. Perlindungan ini harus dipertahankan dan diuji untuk endpoint baru.
- Belum ada integrasi retry sumber gagal dengan semantik yang dijelaskan di bawah, pool profil Indeed, atau penguncian profil lintas worker/operator.

## 3. Sasaran arsitektur

```text
UI user: crawl manual / pengaturan jadwal / retry sumber gagal
                         |
                  API dengan owner_id
                         |
             Run dan percobaan di PostgreSQL
                         |
                  Antrean per sumber
                   /             \
        Worker JobStreet/dll.    Worker Indeed
          browser terpisah       lease satu profil kosong
                   \             /
              Hasil disimpan untuk pemilik run
```

Scheduler nantinya hanya menambahkan pekerjaan ke antrean. Scheduler tidak menjalankan Chrome langsung dan tidak membuat proses cron OS baru untuk setiap user.

Contoh A dan B sama-sama meminta JobStreet + Indeed:

- JobStreet A dan B boleh berjalan bersamaan dengan browser terpisah, sesuai limit portal/server.
- Dengan satu profil Indeed, Indeed A berjalan dan Indeed B menunggu profil. Menunggu Indeed tidak boleh menahan JobStreet B.
- Dengan dua profil Indeed yang tersedia dan tervalidasi, keduanya bisa diuji berjalan paralel.
- Antrean tetap diperlukan ketika kapasitas penuh. UI membedakan waktu dijadwalkan, masuk antrean, mulai berjalan, dan selesai.

## 4. Isolasi data dan akses

- Pemilik run berasal dari identitas yang diautentikasi backend, bukan `owner_id` bebas dari request browser.
- Jadwal, run, source task, attempt, event/progres, hasil, retry, cancel, dan artefak harus dibatasi menurut pemiliknya.
- Scheduler menggunakan pemilik jadwal ketika membuat run. Worker mempertahankan identitas itu ketika menyimpan hasil.
- Deduplication lowongan harus mempertahankan scope pemilik. Lowongan portal yang sama boleh ada pada daftar A dan B tanpa berbagi status lamaran, catatan, atau keputusan pengguna.
- Mengetahui ID milik user lain tidak boleh memberi akses ke detail, retry, pembatalan, stream progres, atau screenshot-nya.
- Pool profil adalah sumber daya browser aplikasi untuk membaca lowongan publik. Jangan dipakai login akun portal pengguna. Jika kelak ada fitur akun portal pribadi, perlu desain isolasi sesi tersendiri.
- Path profil, cookie, dan data browser tidak dikirim ke frontend pengguna. UI cukup mendapat status sumber yang relevan.

## 5. Integrasi profil Indeed ke service

Konfigurasi berikut merupakan usulan internal worker, bukan opsi path yang bebas dikirim user dari UI:

- Direktori dasar profil persisten yang di-mount ke worker.
- Daftar ID profil Indeed beserta path internalnya.
- Batas paralel global, per portal, dan per profil.
- Opsi verifikasi khusus portal, timeout, dan batas percobaan yang ditentukan operator.

Profil harus berada di storage persisten di luar image. Perubahan data profil pada path yang tetap tidak membutuhkan rebuild/deploy aplikasi; job berikutnya membuka profil yang diperbarui setelah browser sebelumnya benar-benar berhenti.

Mengubah path melalui environment Compose biasanya memerlukan recreate container untuk membaca konfigurasi baru. Dukungan profil/volume/config service yang belum tersedia saat ini memerlukan implementasi dan deployment awal.

Uji kompatibilitas profil host dan container: user Linux/UID, izin folder, versi Chrome, cara penyimpanan cookie, dan lingkungan browser. Jangan menganggap keberhasilan CLI host otomatis berlaku pada service container. Bila perlu, lakukan pemanasan/verifikasi profil pada lingkungan browser yang sama dengan worker.

### Penguncian dan lifecycle profil

Usulan state: `available`, `leased`, `maintenance`, `needs_verification`, `disabled`.

- Ambil profil kosong secara atomik sebelum meluncurkan Chrome; satu lease aktif per profil.
- Ikat lease ke task/attempt dan worker, dengan heartbeat serta fencing token.
- Tolak pemakaian paralel profil yang sama, termasuk dari worker di host/container lain.
- Lease kedaluwarsa bukan bukti Chrome lama sudah mati. Sebelum pemakaian ulang, pastikan proses pemegang sebelumnya sudah dihentikan; bila tidak bisa dipastikan, karantina profil untuk pemeriksaan operator.
- Ketika worker gagal/crash, jangan menghapus lock Chrome secara membabi buta. Catat status pemulihan.
- Operator hanya membuka profil setelah profil masuk maintenance dan tidak lagi dipakai Chrome worker.
- Jika verifikasi berulang melewati batas, tandai profil/sumber membutuhkan verifikasi. Jangan membuat retry tak terbatas.
- Mengganti profil saat menelusuri halaman dapat kehilangan konteks/session listing. Restart percobaan sumber dari checkpoint yang didukung, bukan menukar browser di tengah ekstraksi.

## 6. Runbook operator tanpa dashboard admin

### Memperbarui profil yang sama

1. Hentikan penugasan baru ke profil yang akan dirawat. Tunggu pekerjaan selesai atau batalkan secara terkendali, lalu pastikan proses Chrome sudah berhenti.
2. Di sesi MobaXterm/X11 server, buka profil yang dipakai worker. Untuk CLI host dari direktori crawler, contoh yang sudah diuji:

   ```bash
   google-chrome \
     --user-data-dir="$PWD/.browser-profiles/indeed" \
     'https://id.indeed.com/jobs?q=AI+Engineer&l=&fromage=7'
   ```

3. Selesaikan verifikasi sampai listing muncul. Tidak perlu login Google atau akun Indeed pengguna.
4. Tutup semua Chrome dengan profil tersebut dan tunggu prosesnya keluar.
5. Lakukan smoke test kecil dengan path profil yang sama; kembalikan ke pool bila berhasil.
6. Retry sumber gagal dari run yang dimaksud.

Perintah ini membuka profil lama jika folder sudah ada. Untuk benar-benar membuat profil baru, pakai folder berbeda seperti `.browser-profiles/indeed-v2`, selesaikan verifikasi, uji, kemudian daftarkan/aktifkan path baru pada konfigurasi worker. Jangan menghapus profil lama sebelum pergantian terverifikasi.

Pada implementasi sekarang, maintenance/lease/pool belum ada. Hentikan penggunaan profil secara manual sebelum membuka Chrome. Runbook container yang tepat harus ditulis ketika mount, UID, dan lifecycle worker telah ditentukan.

## 7. Retry sumber gagal pada crawl yang sama

UI menampilkan sumber gagal beserta alasan dan tombol **Coba ulang sumber gagal**. Tombol ini berbeda dari **Crawl baru**.

Aturan:

- Pertahankan `run_id`, pemilik, serta snapshot keyword/lokasi/filter/batas dari crawl awal.
- Buat attempt baru dengan nomor percobaan, scope, waktu, status, alasan, dan profil internal yang dipakai. Simpan error percobaan lama.
- Ulangi hanya portal/sumber yang gagal. Jika gagal sebelum listing, ulangi pencarian sumber tersebut.
- Retry detail per job hanya jika adapter dapat membangun kembali konteksnya. Indeed menggunakan panel listing; jangan memaksa URL detail mandiri yang dapat mengarah ke login.
- Jangan menghapus hasil yang berhasil dari portal lain. Perbarui status agregat run setelah seluruh task selesai.
- Pertahankan dedup berdasarkan pemilik dan identitas lowongan. Catatan attempt/provenance baru boleh ditambah tanpa membuat job duplikat.
- Tentukan semantik `seen_ids` secara hati-hati: ID detail yang gagal harus bisa dicoba lagi, sedangkan job yang sudah berhasil tidak diambil ulang tanpa alasan. Worker saat ini mengambil semua `CrawlRunItem` sebagai seen, sehingga tidak bisa digunakan apa adanya untuk retry.
- Tentukan anggaran retry: default usulan adalah memakai sisa batas job sukses pada konfigurasi run, dengan batas percobaan terpisah agar kegagalan tidak membuat loop tanpa batas. Rincian ini perlu disetujui sebelum implementasi.
- Request retry harus idempotent dan ditolak jika scope yang sama sedang berjalan. Backend memeriksa kepemilikan dan transisi state secara atomik.
- Tombol nonaktif saat attempt aktif; setelah gagal, tampilkan alasan terbaru beserta riwayat percobaannya.
- Verifikasi diperlukan bukan berarti user harus memasukkan cookie. Beri pesan sumber menunggu pemulihan operator.

Usulan endpoint, belum tersedia: `POST /crawler/runs/{run_id}/retry` dengan pilihan sumber gagal dan idempotency key. Penamaan final mengikuti konvensi API yang ada.

## 8. Antrean dan paralelisme multi-user

Ini perubahan backend, bukan sekadar menjalankan beberapa Chrome dari worker lama.

- Ganti pembatas run global tunggal dengan kapasitas yang eksplisit. Buat migrasi untuk indeks/check constraint dan singleton worker slot yang terkait; jangan hanya menghapus lock di kode.
- Jadikan sumber portal sebagai unit penugasan yang dapat dijalankan mandiri. Tetapkan urutan keyword/pagination dalam satu sumber agar checkpoint dan batas job konsisten.
- Klaim task secara atomik, dukung heartbeat, pemulihan lease, fencing, dan pembatalan.
- Terapkan limit global, per user, per portal, dan profil Indeed. Gunakan antrean adil agar satu user tidak menghabiskan seluruh worker.
- Profil Indeed sibuk hanya menunda pekerjaan Indeed yang memerlukannya. Worker harus bisa mengambil task portal lain.
- Agregasi status/counter/event run harus aman ketika beberapa sumber memperbaruinya bersamaan; audit juga penomoran sequence event saat ini.
- Alokasi sumber daya berdasarkan pengujian CPU/RAM/browser, bukan jumlah profil saja. Mulai kecil dan ukur.
- Jangan menyalin profil aktif untuk membuka Chrome paralel. Setiap profil pool memiliki direktori dan lifecycle sendiri.

## 9. Scheduler per user — tahap setelah stabilitas manual

User memilih preset yang disediakan aplikasi. Contoh awal untuk ditinjau: setiap hari 05.00, 17.00, atau keduanya. Selalu tampilkan zona waktu, dengan Asia/Jakarta sebagai default usulan untuk pengguna saat ini.

Data usulan jadwal: ID, owner, nama, snapshot konfigurasi crawl, preset waktu, timezone IANA, enabled, next_due_at, last_triggered_at, serta versi konfigurasi.

- Simpan waktu kejadian dalam UTC; hitung jadwal menurut timezone pengguna. Jangan mengikuti timezone host server secara implisit.
- Scheduler menambahkan run dengan `trigger_type=scheduled`, `schedule_id`, dan snapshot konfigurasi saat pemicu terjadi.
- Pastikan hanya satu run per kejadian jadwal melalui unique occurrence key, misalnya `(schedule_id, due_at)`, sehingga beberapa scheduler atau restart tidak menggandakan pekerjaan.
- Klaim kejadian due secara transaksional dan perbarui next_due_at dengan aman.
- Usulan overlap policy: jika eksekusi sebelumnya untuk jadwal yang sama masih queued/running, lewati kejadian berikutnya dan catat alasan. Ini tidak melarang user lain atau jadwal lain berjalan paralel sesuai kapasitas.
- Usulan saat server mati: tandai kejadian terlewat tanpa menjalankan seluruh backlog saat hidup kembali. Pilihan catch-up terbatas dapat dibahas terpisah.
- Menonaktifkan jadwal mencegah pemicu berikutnya; pembatalan run yang sedang berjalan adalah tindakan terpisah.
- Edit jadwal tidak mengubah konfigurasi historis run sebelumnya.
- User hanya bisa CRUD jadwal miliknya. Preset divalidasi backend; browser tidak menentukan identitas pemilik.

Overlap/missed-run policy dan daftar preset merupakan usulan yang perlu dikonfirmasi sebelum coding scheduler.

## 10. UI yang direncanakan

- Konfigurasi crawl manual tetap tersedia selama pengujian portal.
- Daftar hasil, riwayat, progres, dan error hanya untuk pemilik.
- Status sumber membedakan menunggu antrean, berjalan, berhasil, sebagian berhasil, gagal, dan perlu pemulihan operator. Sesuaikan skema backend sebelum menambahkan nilai status baru.
- Tombol retry menampilkan sumber mana yang akan dicoba ulang dan mempertahankan run yang sama.
- Tahap scheduler menambahkan pilihan preset, timezone, aktif/nonaktif, waktu berikutnya, dan riwayat pemicu per user.
- Tidak ada tombol “bypass”, unggah cookie, pemilihan folder server, atau akses profil pada UI user.
- Tidak ada dashboard admin pada cakupan awal. Operator memakai runbook server.

## 11. Tahapan implementasi

| Tahap | Pekerjaan | Syarat selesai |
| --- | --- | --- |
| 0 — evaluasi manual | Uji portal lewat tombol/CLI, catat durasi dan alasan gagal | Ada hasil berulang per portal dan batas operasi yang dipahami |
| 1 — profil Indeed service | Wiring config internal, volume, UID/browser, pengecualian build context, satu profil + maintenance/lease | Service bisa memakai sesi persisten dan menolak pemakaian profil bersamaan |
| 2 — retry | Model attempt, endpoint, state/counter/checkpoint, tombol retry | Hanya sumber gagal dicoba ulang pada run yang sama tanpa duplikasi hasil |
| 3 — paralelisme | Migrasi singleton global, task per sumber, kapasitas/fairness, pool profil terpisah yang diuji | A/B bisa berjalan bersamaan; Indeed sibuk tidak menahan portal lain |
| 4 — scheduler | Preset per user, timezone, occurrence idempotency, overlap/missed-run, UI | Jadwal user memicu run privat melalui antrean yang sama |

Lease/proteksi satu profil diperlukan sejak tahap 1. Pool beberapa profil dan kapasitas multi-user ditingkatkan pada tahap 3. Tahap scheduler tidak diluncurkan sebelum isolasi, retry, dan penanganan kapasitas siap.

## 12. Kriteria penerimaan dan pengujian

1. User A tidak dapat membaca/retry/cancel run, jadwal, event, atau artefak B, termasuk dengan menebak ID.
2. A dan B boleh memiliki lowongan portal yang sama tanpa berbagi status/catatan pribadi.
3. JobStreet A/B bisa paralel sesuai limit; sumber Indeed yang menunggu profil tidak memblokir task portal lain.
4. Dua worker yang mengklaim satu profil menghasilkan satu pemegang lease; operator tidak membuka profil yang sedang leased.
5. Crash/lease expiry tidak menyebabkan browser lama dan baru memakai profil bersamaan; fencing mencegah hasil worker lama menimpa attempt aktif.
6. Retry mempertahankan run ID, hasil sukses, dan error historis; detail gagal tetap eligible; klik tombol ganda tidak menambah attempt paralel.
7. Cookie/profil tidak masuk Git, image build context, log, API, atau artefak yang dapat diakses user.
8. Pembaruan sesi di path tetap dapat dipakai job berikutnya tanpa rebuild image, setelah maintenance selesai.
9. Restart worker/container mempertahankan profil. Penolakan Cloudflare dicatat sebagai kegagalan sumber, bukan hasil kosong yang sukses.
10. Pemicu 05.00/17.00 mengikuti timezone pilihan; dua scheduler tidak menghasilkan run ganda; overlap dan downtime mengikuti policy yang disetujui.
11. Batas CPU/RAM, jumlah Chrome, antrean per user, durasi tunggu profil, rasio kegagalan/verifikasi, dan durasi eksekusi dapat diukur tanpa membocorkan isi sesi.
12. Migrasi dan perubahan kontrak diuji sebelum staging. Smoke test live dibatasi, dicatat, dan tidak dianggap menjamin stabilitas portal.

## 13. Workflow repo dan kelanjutan pekerjaan

- Dokumen ini tidak mengimplementasikan worker/profile pool, retry UI/API, migrasi paralelisme, ataupun scheduler.
- Sesuai arahan pengguna, sumber dan pekerjaan berikutnya langsung memakai branch `dev` yang sudah ada di setiap repo. Periksa sinkronisasi dengan `origin/dev` sebelum mengubah file; tidak perlu membuat branch fitur/dokumentasi baru. Setelah perubahan ditinjau dan diuji, alur promosi adalah dev → staging.
- Crawler, backend, dan frontend adalah tiga repo terpisah. Cocokkan perubahan kontrak/request dan urutan deployment antar-repo.
- Pertahankan hasil eksperimen CLI yang sudah masuk `61fd405`. Jangan memasukkan folder profil, `.env`, atau hasil crawl ke commit.
- Sebelum implementasi, baca dokumen ini, cek branch/working tree, lalu audit kembali file sumber yang dirujuk; kondisi runtime/remote bisa berubah.
- Prioritas coding berikutnya perlu dikonfirmasi pengguna. Tidak ada izin implisit dari dokumen ini untuk meluncurkan scheduler atau mengubah konfigurasi produksi.

### Hal yang masih perlu diputuskan

- Batas paralel global/per user/per portal, jumlah profil Indeed, dan ambang stabilitas portal sebelum dijadwalkan.
- Lokasi volume, user/UID, lingkungan browser untuk verifikasi operator, serta mekanisme maintenance/lock yang dipakai runbook.
- Anggaran retry dan dukungan retry detail setiap adapter.
- Preset jadwal final, batas jumlah jadwal per user, overlap/missed-run policy, dan masa simpan artefak.
- Penggabungan fetch identik antar-user tidak masuk tahap awal; bahas ulang hanya bila diperlukan.
