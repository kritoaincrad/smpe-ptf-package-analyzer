# SMP/E PTF Package Analyzer

IBM z/OS için gönderilen **BMC / IBM SMP/E servis paketlerini** (`.pax.Z`, `.Z` ve
bölünmüş `.XofY` parçaları) alıp; parçaları birleştiren, açan, içindeki SMP/E
metadata'sını (SMPPTFIN / SMPMCS, HOLDDATA, GIMFAF.XML) okuyan ve her PTF'i
açıklamasıyla birlikte listeleyen üretim kalitesinde bir analiz uygulaması.

Windows ve Linux üzerinde, harici bir araç kurulmadan çalışır.

---

Uygulama PySide6/Qt tabanlı yerel masaüstü arayüzüyle çalışır. Dosyalar diskte
işlenir; sunucu veya tarayıcı gerekmez.

### Ürün özellikleri

- Açık/koyu tema, kalıcı sütun görünürlüğü, sıralama ve yeniden kullanılabilir PTF filtre profilleri
- Son kullanılan klasörü hatırlayan, alt klasörleri destekleyen Explorer sürükle-bırak akışı
- Geçmişteki iki analizi eklenen/kaldırılan/değişen PTF düzeyinde karşılaştırma
- PTF ilk/son görülme, FMID envanteri ve SHA-256 ile tekrar yüklenen paket tespiti
- Analiz etiketi, notu, arşiv durumu ve doğrulanmış veritabanı yedekleme/geri yükleme
- Yönetici özeti, PE, kritik HOLD ve aksiyon bölümleri içeren Excel/PDF kurumsal raporlar
- Firma adı, rapor başlığı, logo ve raporlarda hassas yol/e-posta/IP maskeleme
- Yazdırılabilir PTF detay görünümü ve analiz tamamlandı masaüstü bildirimi
- Varsayılan çevrimdışı analiz; analiz boyunca outbound socket bağlantıları engellenir
- Arşiv traversal, aşırı member, büyük member ve olağandışı açılma oranı korumaları
- Opsiyonel SQLCipher geçmiş şifrelemesi ve Ed25519 imzalı güncelleme manifesti

---

## 1. Kurulum

```bash
python -m pip install -r requirements.txt
```

Gereksinim: **Python 3.11+**. `unlzw3` ve 7-Zip opsiyoneldir; uygulamanın kendi
`.Z` decoder'ı her zaman mevcuttur.

Geçmişi SQLCipher ile şifrelemek için Preferences > Security seçeneğini açın,
`PTFANALYZER_DB_KEY` ortam değişkenini tanımlayın ve uyumlu `sqlcipher3` veya
`pysqlcipher3` sürücüsünü kurun. Anahtar uygulama ayarlarına kaydedilmez.

İmzalı güncelleme kontrolü için `PTFANALYZER_UPDATE_MANIFEST_URL` ve base64
Ed25519 public key içeren `PTFANALYZER_UPDATE_PUBLIC_KEY` tanımlanmalıdır.
Offline mode açıkken uygulama güncelleme sunucusuna bağlanmaz.

Windows `.exe` üretimi `scripts/build_windows.ps1` ile yapılır. Kurumsal PFX
sertifikası `SIGN_PFX_PATH` ve `SIGN_PFX_PASSWORD` üzerinden verilirse çıktı
SHA-256 + timestamp ile imzalanır ve imza build sonunda doğrulanır. Sertifika
ve parolası repoya yazılmaz.

### Masaüstü uygulaması (PySide6 / Qt)

```bash
python desktop_app.py
python desktop_app.py example-package.*   # parçaları doğrudan yükleyerek aç
```

Masaüstü arayüzü:

* üst kısımda **dropdown menü çubuğu** — File / Analysis / History / View / Tools / Help
  (klavye: `Ctrl+O` dosya ekle, `F5` analiz, `Ctrl+H` geçmiş, `Ctrl+,` tercihler,
  `Ctrl+1..6` sekmeler),
* **History > Recent analyses** ile son analizler tek tıkla açılır; History sekmesinde
  tümü listelenir, aranır, yeniden adlandırılır, silinir,
* **Tools > Preferences** — kategorili (Decompression / SMP/E metadata / History /
  Diagnostics), her ayarın altında ne işe yaradığını anlatan açıklama; ayarlar
  `QSettings` ile kalıcı saklanır,
* sol panelde dosya listesi, tespit edilen paketler ve canlı ilerleme kartı.

Başlıca özellikler:

* dosyalar **sürükle-bırak** ile veya `Add folder...` ile klasörden toplu eklenir,
* dosyalar diskte oldukları yerden okunur — **kopyalanmaz**; yalnızca birleştirilmiş
  ve açılmış akış geçici dizine yazılır (yüzlerce MB'lık paketlerde belirgin fark),
* seçilen dosyalar arka planda hash'lenip gruplanır; eksik parça daha **Analyze**
  demeden ağaçta görünür,
* analiz ayrı bir iş parçacığında çalışır: pencere donmaz, ilerleme çubuğu ve
  **Cancel** vardır, log satırları akarken görünür,
* PTF tablosu ile detay paneli yan yanadır; satır seçtikçe detay anında güncellenir,
* yerel dosyalar için uygulama kaynaklı bir yükleme boyutu sınırı yoktur.

---

## 2. Mimari

Her aşama bağımsız bir modüldür; her biri ayrı test edilebilir ve bir aşamanın
hatası diğer paketleri durdurmaz.

```
uploads ─► parts ─► gruplama/doğrulama ─► birleştirme ─► .Z açma ─► PAX/TAR
        ─► SMPPTFIN / HOLDDATA / GIMFAF ─► MCS parse ─► PTF nesneleri ─► UI
```

| Modül | Sorumluluk |
|---|---|
| `parts.py` | `.XofY` tespiti, **numerik** sıralama, eksik/duplicate/çakışma kontrolü, SHA-256, birleştirme |
| `compression.py` | `.Z` magic byte doğrulama, dahili LZW decoder + encoder, fallback zinciri |
| `archive.py` | PAX/TAR listeleme, rol tespiti (SMPPTFIN/HOLDDATA/GIMFAF), iç içe arşivler |
| `encoding.py` + `ebcdic.py` | EBCDIC/ASCII tespiti, Python'da bulunmayan `cp1047` codec'i |
| `records.py` | 80-byte fixed record ayrıştırma, sütun 73-80 (sequence) kuralı |
| `mcs.py` | MCS statement tokenizer'ı (comment/quote/parantez farkındalıklı) |
| `smpe.py` | SYSMOD (PTF/APAR/USERMOD) birleştirme, element/HOLD/bağımlılık çıkarımı |
| `holddata.py`, `gimfaf.py` | HOLDDATA ve GIMFAF/GIMPAF XML çözümleme |
| `pipeline.py` | Uçtan uca orkestrasyon, hata izolasyonu, workspace yönetimi |
| `progress.py` | Aşama bazlı ilerleme olayları (arayüzden bağımsız) |
| `serialize.py` | Raporun JSON'a ve JSON'dan tam sadakatli dönüşümü |
| `database.py` | SQLite analiz geçmişi, PTF indeksi ve arama |
| `export.py` | pandas tabloları, CSV/JSON rapor |

Masaüstü arayüzü motora bağımlıdır; analiz motoru Qt import etmez:

| Modül | Sorumluluk |
|---|---|
| `desktop/` | PySide6 masaüstü arayüzü (`theme`, `models`, `widgets`, `worker`, `main_window`) |

---

## 3. Gerçek zamanlı ilerleme

Analiz opak tek bir adım değil; her aşama `ptfanalyzer/progress.py` üzerinden
rapor verir ve arayüz ne yapıldığını anlık gösterir:

```
  [ 29%] Package 1/2 - Decompressing: 214.6 MB of 486.0 MB
  [ 71%] example-package - Parsing SMPPTFIN: 12,400 statements
```

Aşamalar ve genel yüzdeye ağırlıkları: dosyaları okuma/hash'leme (4), parçaları
birleştirme (8), format tespiti (1), **.Z açma (45)**, arşivi okuma (14),
**SMP/E metadata parse (25)**, HOLDDATA (2), bitiriş (1). Yüzde
`(paket indeksi + paket içi ilerleme) / paket sayısı` ile hesaplanır, yani çok
paketli yüklemelerde de doğru ilerler ve **hiçbir zaman geriye gitmez**.

* **Masaüstü:** sol altta PROGRESS kartı — yüzde çubuğu, o an yapılan iş
  ("Decompressing: 214.6 MB of 486.0 MB"), aşama adı, geçen süre ve **Cancel**.
  Log satırları da akarken görünür.

Olaylar 80 ms'de bir sınırlandırılır (`THROTTLE_SECONDS`), yani milyonlarca
kayıtlık bir SMPPTFIN'de bile arayüz yavaşlamaz.

---

## 4. Yerel veritabanı (analiz geçmişi)

Her analiz **SQLite**'a kaydedilir ve sonradan tekrar açılabilir — paket bir kez
işlenir. Ek bağımlılık yoktur, veritabanı tek dosyadır ve herhangi bir SQL
aracıyla incelenebilir.

Konum (`PTFANALYZER_DB` ortam değişkeniyle değiştirilebilir):

| Platform | Yol |
|---|---|
| Windows | `%LOCALAPPDATA%\PTFAnalyzer\analyses.db` |
| Linux | `~/.local/share/ptfanalyzer/analyses.db` |
| macOS | `~/Library/Application Support/PTFAnalyzer/analyses.db` |

Şema:

| Tablo | İçerik |
|---|---|
| `analyses` | Her koşu için bir satır: tarih, etiket, süre, sayaçlar ve **raporun tamamı JSON olarak** |
| `packages` | Paket başına özet (statü, parça sayısı, decoder, fingerprint) |
| `ptf_index` | PTF başına bir satır — **tüm analizlerde PTF/APAR/FMID/açıklama araması** için |

Arayüzdeki **History** sekmesi: kayıtlı analizleri listeler, filtreler, açar,
yeniden adlandırır, siler; ayrıca "Find a PTF across every stored analysis"
kutusu ile geçmişteki bütün paketlerde PTF arar (çift tıklayınca ilgili analiz
açılır). Kayıt, Options panelindeki *Save every analysis to the local database*
ile kapatılabilir.

Saklanmayanlar (büyük ve yeniden üretilebilir oldukları için): ham MCS statement
nesneleri (geri yüklenen analizde *Raw MCS* sekmesi boştur) ve geçici workspace
dosyaları. Bunun dışındaki her şey — PTF'ler, açıklamalar, bağımlılıklar,
element ve HOLD listeleri, arşiv üyeleri, encoding bilgisi, hata/uyarılar ve
loglar — birebir geri yüklenir.

Başarısız analizler de saklanır: "bu paket şu tarihte şu sebeple açılamadı"
kaydı, sorunu satıcıya bildirirken işe yarar.

---

## 5. Desteklenen dosya yapısı

```
example-package.1of3
example-package.2of3
...
example-package.3of3
```

* Uzantı olmayabilir; `.1of7`, `.01OF07`, `_3of4`, `-1 of 2`, `.1of7.Z` biçimleri tanınır.
* Sıralama **her zaman numeriktir** — `10of12`, `9of12`'den sonra gelir. Alfabetik
  sıraya asla güvenilmez.
* Tek parçalı paketler (`package.pax.Z`) de desteklenir.

### Doğrulamalar

| Durum | Davranış |
|---|---|
| `1,2,3,5,6,7` yüklendi | `Part 4 is missing.` — analiz durur, sebep açıkça yazılır |
| `1,3,7` yüklendi | `Parts 2, 4, 5, 6 are missing.` |
| Aynı parça iki kez, **aynı** içerik | Duplicate olarak işaretlenir, bir kez işlenir |
| Aynı parça iki kez, **farklı** içerik | Hata: `Part 1 was supplied twice with different content` |
| `.1of7` ve `.2of8` karışık | Hata: `Inconsistent part counts` |

### Duplicate paket kontrolü

Tüm dosyalar SHA-256 ile karşılaştırılır:

* `paket.1of7` + `paket(1).1of7` → aynı pakete ait kopya; yok sayılır ve
  **Duplicate package detected** uyarısı gösterilir.
* İçerik olarak birebir aynı ama farklı isimli iki paket → ikincisi
  `DUPLICATE` statüsüyle listelenir, tekrar analiz edilmez
  (isteğe bağlı olarak "Analyze duplicate packages too" ile açılabilir).

---

## 6. `.Z` açma ve fallback stratejisi

Birleştirilen akış önce magic byte ile doğrulanır:

```
data[:2] == b"\x1f\x9d"
```

Geçersizse teknik detay yerine okunabilir hata verilir:

```
Invalid Unix .Z stream.
Expected magic bytes: 1F 9D
Detected: 50 4B
```

Ek olarak gerçek format tespit edilip ipucu verilir (gzip, ZIP, TSO XMIT,
sıkıştırılmamış TAR vb.). Sıkıştırılmamış PAX ve gzip akışları doğrudan işlenir.

Decoder sırası (ilk başarılı olan kazanır):

1. `unlzw3` (kuruluysa)
2. **Dahili LZW decoder** (her zaman mevcut, bağımlılıksız)
3. 7-Zip (`7z` / `7za` / `7zz`, Windows'ta Program Files dahil aranır)
4. `uncompress` / `gzip` / `zcat`

Bir decoder patlarsa uygulama çökmez; log'a

```
'unlzw3' failed: ... Trying fallback decoder 'built-in LZW decoder'...
```

yazılır ve sıradaki denenir. Hepsi başarısız olursa tek bir özet hata ve olası
sebepler (eksik parça, yanlış sıra, ASCII modunda FTP) gösterilir. Python
traceback'i yalnızca **Debug Mode** açıkken görünür.

> **Performans:** dahili saf-Python decoder metin ağırlıklı veride ~10 MB/s,
> binary ağırlıklı veride ~2.5 MB/s üretir. Bu yüzden 96 MB üzerindeki paketlerde
> (ayarlanabilir) varsa harici araçlar öne alınır.

### Dahili LZW uygulaması hakkında

Unix `compress` formatı kayıtsız ve tuzaklıdır. Bu uygulamadaki kritik noktalar:

* kod genişliği her seviyede tam `2^(w-1)` kod sonra artar,
* genişlik artışında ve `CLEAR` kodunda çıkış, **o genişlik bölümünün başına
  göre** 8'lik kod grubuna hizalanır (mutlak dosya konumuna göre değil),
* decoder sözlükte encoder'ın bir adım gerisindedir.

Üretilen akışlar standart `gzip -d` / `uncompress` decoder'larıyla uyumludur.

---

## 7. Arşiv içeriği

Açılan akış `tarfile` ile PAX/TAR olarak okunur. Aranan üyeler dizin altında
olabileceği için **exact path değil, isim soneki** ile aranır:

```python
member.name.upper().endswith("SMPPTFIN")
```

Aranan roller: `SMPPTFIN`, `SMPMCS`, `HOLDDATA`, `GIMFAF.XML`, `GIMPAF.XML`,
`GIMZIP.XML`. GIMZIP tarzı paketlerde iç içe arşivlere (`.pax`, `.pax.Z`)
yapılandırılabilir derinlikte inilir. Sadece ilgili üyeler belleğe okunur;
gigabaytlık RELFILE'lar yalnızca listelenir.

Arşiv değilse (ör. düz sequential data set image) akışın tamamı tek bir SMP/E
girdisi gibi analiz edilir. Kırpılmış arşivlerde listeleme çöker değil,
"archive ends unexpectedly / truncated" uyarısı verilir.

---

## 8. Encoding tespiti

SMPPTFIN genellikle EBCDIC'tir. Sırasıyla `cp037`, `cp500`, `cp1047`, `cp273`,
`cp870`, `utf-8`, `latin-1` denenir ve her biri gerçek SMP/E token'ları için
puanlanır:

```
++PTF(   ++VER(   ++APAR(   ++HOLD(   FMID(   PRE(   SUP(   REQ(  ...
```

En çok token üreten encoding seçilir; böylece binary dosya yanlış encoding ile
okunup anlamsız karakter üretmez. Hiç token yoksa ve içerik yeterince okunabilir
değilse (%85 altı) member binary kabul edilir ve açık bir hata verilir.

> **Not:** Python `cp1047` codec'ini içermez. Uygulama bunu `ebcdic.py` içinde
> `cp037` üzerinden üç kod noktası çiftini takas ederek kaydeder
> (`^`↔`¬`, `[`, `]` konumları) — z/OS C kaynaklarının `X'AD'`/`X'BD'` kullanmasının
> sebebi de budur. SMP/E sözdiziminde kullanılan karakterler her üç kod sayfasında
> aynı olduğundan fark yalnızca açıklama metinlerinde görünür.

---

## 9. SMP/E kayıt yapısı ve MCS parse

* Satır sonu yoksa veri **80 byte'lık sabit record'lara** bölünür.
* Sütun **73-80 sequence number** alanıdır ve SMP/E gibi yok sayılır
  (arayüzden kapatılabilir).
* Bir statement, parantez/tırnak/comment dışındaki ilk `.` karakterine kadar
  sürer; istediği kadar record'a yayılabilir.
* Record'lar **araya boşluk konmadan** birleştirilir — SMP/E bir operand'ın
  72. sütunda bölünmesine izin verir, bu sayede `FM` + `ID(FMID001)` doğru
  şekilde `FMID(FMID001)` olur.
* `/* ... */` yorumları yakalanır (PTF açıklamaları buradadır); yorum içindeki
  `.` statement'ı bitirmez.
* `COMMENT(...)` gibi serbest metin operand'ları virgülden bölünmez.
* Dosya başındaki yorum bloğu **paket başlığı** olarak ayrı tutulur, ilk PTF'in
  açıklamasına karışmaz.

Çıkarılan bilgiler: SYSMOD id/tipi, FMID, VER/RMID, PRE / REQ / SUP / DELETE,
`++IF ... THEN REQ(...)` koşulları, düzeltilen APAR'lar, element listesi
(MOD/SRC/MAC/ZAP/...) ve DISTLIB/RELFILE bilgileri, JCLIN varlığı, HOLD/RELEASE
kayıtları ve açıklama metni.

**PE (in error) tespiti:** `++HOLD(...) ERROR` kayıtları PTF'e bağlanır ve
arayüzde kırmızı `PE - IN ERROR` rozetiyle gösterilir. HOLDDATA member'ındaki
daha zengin bilgi (CLASS, RESOLVER, uzun açıklama) SMPPTFIN'deki aynı hold ile
birleştirilir.

---

## 10. Arayüz

* **Summary** — paket başına statü, kullanılan decoder, encoding, parça listesi,
  hata/uyarılar, paket başlığı metni.
* **PTF list** — aranabilir/filtrelenebilir tablo (metin arama, FMID, sadece PE,
  sadece HOLD'lu), CSV/JSON indirme.
* **PTF detail** — açıklama, bağımlılıklar, APAR'lar, element tablosu, HOLD
  tablosu, (Debug Mode'da) ham MCS statement'ları.
* **HOLDDATA** — tüm HOLD/RELEASE kayıtları, ERROR hold'lar için uyarı.
* **Package contents** — arşiv üyeleri, GIMFAF/GIMPAF tablosu, encoding aday
  puanları (Debug Mode).
* **Logs** — seviyeye göre filtrelenebilir yapısal log, CSV indirme.

Tasarım düz kurumsal paletle yapılmıştır; **gradient kullanılmamıştır**.
Masaüstü sürümü aynı paleti Qt stylesheet ile uygular (`desktop/theme.py`);
PE (hatalı) PTF satırları tabloda kırmızı, HOLD'lu satırlar amber tonla işaretlenir.

## 11. Bilinen sınırlar

* `max_bits = 9` ile üretilmiş `.Z` akışları desteklenmez (gerçekte kullanılmayan
  dejenere bir yapılandırma; `compress` kendisi de bu durumda tablo taşırır).
  Gerçek paketler 12-16 bit kullanır.
* TSO XMIT (`INMR01`) veri setleri tanınır ama açılmaz; z/OS tarafında önce
  `RECEIVE` edilmelidir.
* `cp037`/`cp500`/`cp1047` arasındaki fark yalnızca birkaç özel karakterde
  olduğundan, SMP/E sözdizimi dışında ayırt edici karakter içermeyen
  member'larda tespit edilen kod sayfası `cp037` olarak raporlanabilir —
  çözülen metin aynıdır. Gerekirse arayüzden encoding zorlanabilir.
