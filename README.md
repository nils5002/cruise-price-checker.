# Cruise Price Checker

Vergleicht die Preise **derselben Kreuzfahrt** unter verschiedenen, möglichst neutralen
Browserbedingungen und speichert den Preisverlauf inklusive Screenshots als Nachweis.

Erster unterstützter Anbieter: **MSC Cruises**. Die Architektur ist auf weitere Anbieter
(e-hoi, Kreuzfahrtberater, Dreamlines, Logitravel, HolidayCheck, CHECK24) vorbereitet –
jeder Anbieter bekommt einen eigenen Provider-Adapter.

---

## Inhalt

- [Was das Tool macht – und was bewusst nicht](#was-das-tool-macht--und-was-bewusst-nicht)
- [Installation](#installation)
- [Erster Selbsttest ohne MSC](#erster-selbsttest-ohne-msc)
- [Ports](#ports)
- [Volumes](#volumes)
- [Umgebungsvariablen](#umgebungsvariablen)
- [Datenbank](#datenbank)
- [Backup](#backup)
- [Updates](#updates)
- [Playwright und Browser](#playwright-und-browser)
- [Browserprofile und Testbedingungen](#browserprofile-und-testbedingungen)
- [Preiserfassung und Datenqualität](#preiserfassung-und-datenqualität)
- [Auswertung und Interpretation](#auswertung-und-interpretation)
- [Rate Limiting und Scheduler](#rate-limiting-und-scheduler)
- [Preisalarme](#preisalarme)
- [Proxy-Konfiguration](#proxy-konfiguration)
- [Reverse Proxy (Nginx Proxy Manager)](#reverse-proxy-nginx-proxy-manager)
- [Portainer](#portainer)
- [CI / GitHub Actions](#ci--github-actions)
- [Healthchecks](#healthchecks)
- [Fehleranalyse und Debug-Modus](#fehleranalyse-und-debug-modus)
- [API](#api)
- [Entwicklung und Tests](#entwicklung-und-tests)
- [Bekannte Einschränkungen](#bekannte-einschränkungen)
- [Roadmap](#roadmap)

---

## Was das Tool macht – und was bewusst nicht

**Es macht:**

- öffnet denselben Buchungslink in mehreren **vollständig isolierten** Browser-Sessions
  (frisches Profil: keine Cookies, kein Local/Session Storage, keine IndexedDB, kein Cache,
  keine Service Worker, kein Login),
- hält alle inhaltlichen Bedingungen identisch (`de-DE`, `Europe/Berlin`, EUR, gleiche Reise,
  gleiche Passagiere, gleiche Kabinen-/Tarifwahl),
- versucht, sich soweit möglich durch den normalen Buchungsprozess bis zur
  **letzten Seite vor der verbindlichen Buchung** zu bewegen,
- erfasst Einstiegspreis, Preis pro Person, Kabinenpreis, Gesamtpreis, Servicegebühren,
  Flug, Transfer, Getränkepaket, Extras, Rabatt und Endpreis,
- prüft, ob zwei Preise wirklich zum **gleichen Angebot** gehören,
- speichert Screenshots und (optional) sanitisierte HTML-Snapshots pro Schritt,
- speichert den Preisverlauf und kann Preisalarme senden.

**Es macht bewusst nicht:**

- kein Umgehen von CAPTCHAs, Bot-Schutz oder anderen Zugangsbeschränkungen –
  erkannte Sperren werden als `BLOCKED / CAPTCHA` bzw. `BLOCKED / Bot-Schutz` ausgewiesen
  und der Test endet sauber,
- **niemals** eine zahlungspflichtige Buchung: Buttons wie „zahlungspflichtig buchen“,
  „bezahlen“, „Buchung abschließen“ werden durch eine harte Sperre nie geklickt; sobald die
  Passagierdaten- oder Zahlungsseite erkannt wird, stoppt die Automatisierung,
- keine Logins, keine echten Namen, keine Zahlungsdaten,
- keine beliebigen URLs: es gilt eine Domain-Allowlist (aktuell `*.msccruises.de`,
  `.com`, `.at`, `.ch`), inklusive SSRF-Schutz,
- keine geschätzten Preise. Wenn ein Preis nicht zuverlässig erkennbar ist, steht dort
  `null` bzw. „Preis konnte nicht zuverlässig ermittelt werden“.

---

## Installation

```bash
git clone <repository-url> cruise-price-checker
cd cruise-price-checker
cp .env.example .env
# .env anpassen: mindestens POSTGRES_PASSWORD und DATABASE_URL
docker compose up -d --build
```

Danach ist die Weboberfläche erreichbar unter:

```
http://SERVER-IP:8080
```

Die API liegt unter `http://SERVER-IP:8080/api`, die interaktive
API-Dokumentation unter `http://SERVER-IP:8080/docs`. Ein separater Backend-Port
wird nicht veröffentlicht.

Der erste Build lädt das Playwright-Image (~2 GB) – das dauert einige Minuten.

**Wichtig:** In `.env` müssen `POSTGRES_PASSWORD` und das Passwort in `DATABASE_URL`
identisch sein. Beispiel:

```env
POSTGRES_PASSWORD=meinGeheimesPasswort
DATABASE_URL=postgresql+psycopg2://cruise:meinGeheimesPasswort@db:5432/cruise
```

---

## Erster Selbsttest ohne MSC

Damit sich die komplette Kette (Scan → Ergebnisse → Vergleich → Verlauf → Screenshots)
ohne echte Website testen lässt, ist ein Mock-Provider eingebaut
(`ENABLE_MOCK_PROVIDER=true`, Standard).

Im Dashboard als Link einfügen:

```
mock://cruise/demo?variant=default
```

Varianten:

| Variante | Verhalten |
| --- | --- |
| `default` | stabile Preise, iPhone und Returning Visitor teurer |
| `dynamic` | Preise schwanken → „Preis dynamisch / Ergebnis nicht eindeutig“ |
| `blocked` | simuliert ein CAPTCHA → `BLOCKED / CAPTCHA` |
| `noprice` | Seite lädt, aber kein Preis → „Preis konnte nicht zuverlässig ermittelt werden“ |
| `identity` | ein Profil zeigt einen anderen Tarif → „Angebote unterscheiden sich“ |

Für den Produktivbetrieb kann der Mock-Provider mit `ENABLE_MOCK_PROVIDER=false`
abgeschaltet werden.

---

## Ports

| Port | Container | Zweck | Variable |
| --- | --- | --- | --- |
| 8080 | frontend (nginx) | Weboberfläche **und** API: `/api`, `/health`, `/docs` | `WEB_PORT` |
| – | backend (uvicorn) | nur intern im Docker-Netz (Port 8000, nicht veröffentlicht) | `BACKEND_PORT`* |
| – | db (postgres) | nur intern im Docker-Netz (Port 5432, nicht veröffentlicht) | – |

\* Der Backend-Port ist absichtlich **nicht** veröffentlicht: die Oberfläche
erreicht die API intern, und ein belegter Host-Port 8000 lässt den Stack sonst
mit `port is already allocated` scheitern. Für direkten API-Zugriff in
`docker-compose.yml` den `ports`-Block des Backends einkommentieren und
`BACKEND_PORT` auf einen freien Port setzen.

---

## Volumes

| Volume | Mountpunkt | Inhalt |
| --- | --- | --- |
| `cpc-app-data` | `/data` (backend) | Screenshots, HTML-Snapshots, persistente Browserprofile, ggf. SQLite-Datei |
| `cpc-db-data` | `/var/lib/postgresql/data` | PostgreSQL-Daten |

Verzeichnisstruktur im Datenvolume:

```
/data/screenshots/scan-<id>/<profil>-r<runde>/<nn>-<schritt>.png
/data/snapshots/scan-<id>/<profil>-r<runde>/<nn>-<schritt>.html
/data/browser-profiles/returning_visitor/      # nur das persistente Profil
```

---

## Umgebungsvariablen

Alle Variablen stehen mit Erklärung in [`.env.example`](.env.example). Sie werden in
`docker-compose.yml` **explizit** an den Backend-Container übergeben (jeweils mit
Standardwert), damit der Stack sowohl mit einer `.env`-Datei als auch mit
Portainer-Umgebungsvariablen funktioniert – eine `.env`-Datei ist nicht zwingend
erforderlich. Die wichtigsten:

| Variable | Standard | Bedeutung |
| --- | --- | --- |
| `WEB_PORT` | `8080` | Port der Weboberfläche |
| `DATABASE_URL` | Postgres | `sqlite:////data/cruise.db` für Betrieb ohne Postgres |
| `API_KEY` | leer | wenn gesetzt: alle schreibenden Endpunkte und der Adminbereich brauchen `X-API-Key` |
| `HEADLESS` | `true` | `false` nur zum Debuggen (sichtbarer Browser) |
| `ENABLE_FIREFOX` | `true` | Firefox-Profil an/aus |
| `MAX_CONCURRENT_SCANS` | `1` | gleichzeitige Scans (bewusst niedrig) |
| `DELAY_BETWEEN_PROFILES_S` | `8` | Pause zwischen den Profilen eines Scans |
| `MIN/MAX_DELAY_BETWEEN_STEPS_MS` | `1200`/`2600` | Pause zwischen Interaktionen |
| `MAX_SCANS_PER_CRUISE_PER_DAY` | `6` | harte Obergrenze je Reise und Tag |
| `MAX_RETRIES_PER_PROFILE` | `2` | Wiederholungen mit exponentiellem Backoff |
| `VERIFICATION_ROUNDS` | `3` | maximale Runden zur Reproduktionsprüfung |
| `ENABLE_REFERRER_TESTS` | `false` | Google-/Bing-Referrer zusätzlich testen |
| `ENABLE_HTML_SNAPSHOTS` | `true` | HTML-Snapshots speichern (sanitisiert) |
| `ENABLE_SCHEDULER` | `true` | automatische Checks |
| `ENABLE_MOCK_PROVIDER` | `true` | Demo-/Testprovider |
| `PROXY_DE_1..3` | leer | optionale Proxys (siehe unten) |
| `ROOT_PATH` | leer | Basis-Pfad hinter einem Reverse Proxy |

---

## Datenbank

Standard ist **PostgreSQL** (Service `db` in `docker-compose.yml`).

Umstellung auf SQLite (z. B. für einen kleinen Testbetrieb):

```env
DATABASE_URL=sqlite:////data/cruise.db
```

Danach kann der `db`-Service in der Compose-Datei entfernt bzw. gestoppt werden
(`depends_on` beim Backend ebenfalls entfernen). Die Tabellen werden beim Start
automatisch erzeugt; ein Migrationstool wird für dieses Datenmodell nicht benötigt.

Tabellen: `cruises`, `scans`, `scan_results`, `scan_logs`, `price_history`, `price_alerts`.

---

## Backup

```bash
# Datenbank
docker exec cpc-db pg_dump -U cruise cruise > backup-$(date +%F).sql

# Screenshots, Snapshots, Browserprofile
docker run --rm -v cpc-app-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/cpc-data-$(date +%F).tar.gz -C /data .
```

Wiederherstellen:

```bash
cat backup-2026-08-23.sql | docker exec -i cpc-db psql -U cruise -d cruise
docker run --rm -v cpc-app-data:/data -v "$PWD":/backup alpine \
  sh -c "cd /data && tar xzf /backup/cpc-data-2026-08-23.tar.gz"
```

---

## Updates

```bash
git pull
docker compose build --pull
docker compose up -d
```

Volumes bleiben erhalten. Nach einem Update des Playwright-Images empfiehlt sich
`docker image prune -f`, um alte Layer freizugeben.

---

## Playwright und Browser

Das Backend basiert auf `mcr.microsoft.com/playwright/python:v1.49.0-jammy`; Chromium und
Firefox sind darin bereits installiert. Der Pin in `backend/requirements.txt`
(`playwright==1.49.0`) **muss** zum Image-Tag passen. Beim Aktualisieren beide Stellen
gemeinsam ändern.

Der Container benötigt Shared Memory für Chromium – in `docker-compose.yml` ist deshalb
`shm_size: "1gb"` gesetzt. Chromium startet mit `--no-sandbox --disable-dev-shm-usage`
(Container-Standard). Der Entrypoint korrigiert die Rechte auf `/data` und wechselt
anschließend auf den Benutzer `pwuser`.

---

## Browserprofile und Testbedingungen

| Profil | Browser | Gerät | Session |
| --- | --- | --- | --- |
| Clean Desktop Chrome Windows | Chromium | Desktop | frisch |
| Clean Desktop Chrome macOS | Chromium | Desktop | frisch |
| Clean iPhone | Chromium (Mobile-Emulation, DPR 3, Touch) | Mobile | frisch |
| Clean Android | Chromium (Mobile-Emulation, DPR 2.625, Touch) | Mobile | frisch |
| Clean Desktop Firefox | Firefox | Desktop | frisch |
| Returning Visitor | Chromium | Desktop | **persistent** |

- Jeder Clean-Test startet einen **eigenen Browserprozess mit Wegwerf-Profilverzeichnis**
  und darin einen neuen BrowserContext. Nach dem Test wird das Verzeichnis gelöscht.
  Beim Start wird geprüft und protokolliert, dass Cookies und Local Storage leer sind.
- Nur `Returning Visitor` nutzt ein persistentes Profil unter
  `/data/browser-profiles/returning_visitor` – absichtlich, um wiederholte Aufrufe zu
  testen. Clean-Tests und Returning-Visitor werden nie gemischt. Der Zustand kann im
  Adminbereich zurückgesetzt werden.
- Identisch in **allen** Profilen: Sprache/Locale `de-DE`, `Accept-Language`,
  Zeitzone `Europe/Berlin`, Währung EUR, Land DE, Farbschema, Reise, Datum, Passagiere,
  Kabinen- und Tarifwunsch. Diese Werte werden pro Ergebnis mitgespeichert.
- Cookie-Varianten: **A** nur notwendige · **B** alle akzeptieren · **C** Banner nicht
  bestätigen. Gespeichert wird zusätzlich, welche Variante tatsächlich angewendet werden
  konnte (z. B. `nur_notwendige`, `alle_akzeptiert`, `banner_ignoriert`, `kein_banner`,
  `banner_erkannt_aber_nicht_bedienbar`).
- Einstiegspfade (optional): Direktaufruf, Google-Referrer, Bing-Referrer.

---

## Preiserfassung und Datenqualität

- Die Erfassung ist **text- und ARIA-getrieben**: bevorzugt Rollen, sichtbare Texte und
  semantische Elemente, CSS nur als letzter Rückfall. Alle MSC-spezifischen Selektoren
  liegen ausschließlich in `backend/app/providers/msc/selectors.py`.
- Beträge werden nur übernommen, wenn sie eindeutig sind. Enthält eine Zeile mehrere
  verschiedene Beträge („ab 799 € statt 899 €“), wird **nichts** übernommen.
- Labels werden priorisiert klassifiziert: „Gesamtpreis inkl. Flug“ ist ein Gesamtpreis,
  kein Flugpreis; „Gesamtpreis pro Person“ ist ein Personenpreis.
- Unplausible Werte (< 20 € oder > 250.000 €) werden verworfen.
- Nicht gefundene Werte bleiben `null`. Es wird nie geschätzt.

Erkannte Sonderfälle mit eigenem Status: `TIMEOUT`, `UNREACHABLE`, `PRICE_NOT_FOUND`,
`SELECTOR_CHANGED`, `COOKIE_BANNER_CHANGED`, `BLOCKED_CAPTCHA`, `BOT_PROTECTION`,
`SESSION_EXPIRED`, `SOLD_OUT`, `CABIN_SOLD_OUT`, `PRICE_CHANGED_DURING_FLOW`,
`SITE_ERROR`, `PARTIAL`.

---

## Auswertung und Interpretation

- Vor jedem Preisvergleich wird die **Angebotsidentität** geprüft: Schiff, Abfahrtsdatum,
  Rückreisedatum, Dauer, Route, Kabinentyp, Kabinenkategorie, Tarif, Verpflegung,
  Passagierzahl, Flug enthalten, Getränkepaket, Stornobedingungen, Aktionsbedingungen,
  Preiscode. Fehlt ein Wert auf einer Seite, gilt das **nicht** als Unterschied, sondern
  als „nicht vergleichbar“.
- Sind die Angebote nicht identisch, lautet das Ergebnis „**Angebote unterscheiden sich**“
  mit Auflistung der konkreten Abweichungen – nicht „Preisunterschied erkannt“.
- Formulierungen sind neutral. Das Tool behauptet nie, ein Anbieter mache Device Pricing.
  Mögliche Ursachen werden als Hypothesen aufgelistet: anderer Tarif, andere Kabine,
  andere Aktion, Session-Effekt, Device-Effekt, andere Cookie-Variante, anderer
  Einstiegspfad, andere Ausgangs-IP, dynamische Preisänderung oder unbekannte Ursache.
- Mehrfachtest: Wird ein Unterschied gefunden, laufen (bis zu `VERIFICATION_ROUNDS`)
  weitere Runden. Ergebnis: „Preisunterschied 3x reproduziert.“ oder
  „Preis dynamisch / Ergebnis nicht eindeutig.“ Ohne Unterschied in Runde 1 entfallen
  weitere Runden – das schont die Zielseite.

---

## Rate Limiting und Scheduler

- Profile laufen strikt **nacheinander**, mit Pausen zwischen Interaktionen und zwischen
  Profilen (`DELAY_BETWEEN_PROFILES_S`).
- Maximal `MAX_CONCURRENT_SCANS` Scans gleichzeitig (Standard 1).
- Maximal `MAX_SCANS_PER_CRUISE_PER_DAY` Checks pro Reise und Tag (Standard 6) –
  darüber antwortet die API mit HTTP 429.
- Testmatrix pro Runde auf 24 Tests begrenzt; weggelassene Kombinationen werden
  **protokolliert** und im Scan hinterlegt (keine stille Kürzung).
- Wiederholungen nur bei technischen Fehlern, mit exponentiellem Backoff.
  **Blockaden werden nie erneut versucht.**
- Scheduler-Intervalle: `manual`, `6h`, `12h`, `daily`; geprüft wird alle 10 Minuten,
  ob eine Reise fällig ist.

---

## Preisalarme

Pro Reise können Alarme angelegt werden (Schwellenwert für den Gesamtpreis und/oder
prozentualer Rückgang gegenüber dem bisherigen Tiefstpreis). Kanäle:

| Kanal | Konfiguration | Ziel |
| --- | --- | --- |
| E-Mail | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Empfängeradresse |
| Telegram | `TELEGRAM_BOT_TOKEN`, optional `TELEGRAM_CHAT_ID` | Chat-ID |
| Discord | `DISCORD_WEBHOOK_URL` | optional eigene Webhook-URL |
| Home Assistant | `HOMEASSISTANT_WEBHOOK_URL` | optional eigene Webhook-URL |

Nicht konfigurierte Kanäle werden übersprungen und im Adminbereich als
„nicht konfiguriert“ angezeigt. Wiederholte Alarme sind für 6 Stunden entprellt.

---

## Proxy-Konfiguration

Standardmäßig läuft alles über die normale Internetverbindung. Optional:

```env
PROXY_DE_1=http://user:pass@host:3128
PROXY_DE_1_LABEL=DE Anschluss 1
PROXY_DE_2=socks5://host:1080
PROXY_DE_2_LABEL=DE Anschluss 2
PROXY_DE_3=
PROXY_DE_3_LABEL=DE Mobilfunk
```

- Im Ergebnis wird **ausschließlich das Label** gespeichert und angezeigt.
- Zugangsdaten erscheinen nie im Frontend, nie in der API und nie in Logs
  (mehrstufige Redaction: bekannte Secrets + Muster wie `user:pass@`).
- Es werden keine Proxys automatisch beschafft und keine Geo- oder
  Sicherheitsbeschränkungen umgangen. Nur eigene, legitime Zugänge verwenden.

---

## CI / GitHub Actions

Zwei Workflows liegen unter `.github/workflows/`:

| Workflow | Auslöser | Zweck |
| --- | --- | --- |
| `ci.yml` | Push, Pull Request | Backend: `ruff`, `mypy`, `pytest`; Frontend: `tsc --noEmit`, `vite build` |
| `docker-publish.yml` | Push auf `main` (Änderungen in `backend/` oder `frontend/`), manuell | Baut beide Images und pusht sie nach `ghcr.io/<user>/cruise-price-checker-{backend,frontend}` |

Tags: `latest` (nur `main`), `sha-<kurzhash>`, Branchname. Architektur
standardmäßig `linux/amd64` – für ARM-Hosts (z. B. Raspberry Pi) in
`docker-publish.yml` `platforms: linux/amd64,linux/arm64` setzen.

Ein eigenes Secret ist nicht nötig, der Workflow nutzt `GITHUB_TOKEN`.

## Reverse Proxy (Nginx Proxy Manager)

Ziel im NPM: `http://SERVER-IP:8080` (Container `cpc-frontend`).

- `X-Forwarded-For`, `X-Forwarded-Proto` und `X-Forwarded-Host` werden vom internen nginx
  weitergegeben; uvicorn läuft mit `--proxy-headers --forwarded-allow-ips=*`.
- WebSocket-Weiterleitung ist vorbereitet (aktuell nicht genutzt; die UI pollt).
- Betrieb unter einem Unterpfad: in `.env`
  `ROOT_PATH=/cruise` und `VITE_BASE_PATH=/cruise/` setzen, dann
  `docker compose up -d --build frontend backend`.
- „Websockets support“ im NPM kann aktiviert bleiben.

---

## Portainer

Es werden keine Kubernetes-Funktionen, keine externen Netzwerke und keine
Host-Bind-Mounts benötigt – nur benannte Volumes.

### Empfohlen: Stack mit fertigen Images (kein Build in Portainer)

1. **Stacks → Add stack → Repository**
2. Repository URL: `https://github.com/nils5002/cruise-price-checker.`
3. **Compose path:** `docker-compose.prebuilt.yml`
4. Unter **Environment variables** mindestens `POSTGRES_PASSWORD` und
   `DATABASE_URL` setzen.
5. **Deploy the stack** – dauert Sekunden, weil nur gezogen wird.

Voraussetzung: die von der GitHub Action veröffentlichten GHCR-Packages müssen
erreichbar sein. Einmalig unter `github.com/<user>?tab=packages` → Package →
*Package settings* → **Change visibility → Public**. Alternativ in Portainer
unter **Registries** eine Registry `ghcr.io` mit einem Personal Access Token
(Scope `read:packages`) anlegen.

### Alternative: Build in Portainer (`docker-compose.yml`)

Funktioniert, ist beim **ersten** Deploy aber langsam: das Playwright-Basisimage
ist ~2 GB. Siehe [504 Gateway Time-out](#504-gateway-time-out-in-portainer).

### Deploy direkt auf dem Host (umgeht alle Portainer-Timeouts)

Der zuverlässigste Weg, wenn Portainer beim Deploy abbricht – Portainer zeigt
den Stack anschließend als „external stack" an und kann ihn normal verwalten:

```bash
ssh dein-docker-host
git clone https://github.com/nils5002/cruise-price-checker. cpc
cd cpc
cp .env.example .env && nano .env      # POSTGRES_PASSWORD + DATABASE_URL
docker compose up -d --build           # erster Lauf dauert einige Minuten
docker compose ps                      # alle drei Container "healthy"?
docker compose logs -f backend
```

Aktualisieren später: `git pull && docker compose up -d --build`

### 504 Gateway Time-out in Portainer

```html
<html><head><title>504 Gateway Time-out</title></head>...openresty...
```

Das ist **kein Fehler der Anwendung**. Portainer baut beim Repo-Deploy die
Images synchron und antwortet erst danach; der vorgeschaltete Proxy bricht die
Anfrage vorher ab. Der Build läuft im Hintergrund oft trotzdem weiter.

Abhilfe, in dieser Reihenfolge:

1. **Fertige Images verwenden** – `docker-compose.prebuilt.yml` wie oben. Damit
   entfällt der Build vollständig (empfohlen).
2. **Vorab auf dem Host bauen**, danach in Portainer deployen – dann ist alles
   im Build-Cache und das Deploy ist schnell:

   ```bash
   git clone https://github.com/nils5002/cruise-price-checker. cpc
   cd cpc && cp .env.example .env
   docker compose build --pull          # dauert einige Minuten, einmalig
   ```

3. **Timeout des Proxys erhöhen**, der vor Portainer steht (Nginx Proxy Manager
   → Advanced):

   ```nginx
   proxy_read_timeout 600s;
   proxy_send_timeout 600s;
   proxy_connect_timeout 600s;
   ```

4. **Prüfen, was tatsächlich passiert ist** – trotz 504 läuft der Stack
   möglicherweise schon:

   ```bash
   docker ps --filter name=cpc-
   docker compose -p <stackname> logs -f backend
   docker images | grep cruise-price-checker
   ```

Wenn der Stack in Portainer als „failed" hängt, aber Container laufen: Stack
entfernen, dann mit `docker-compose.prebuilt.yml` neu anlegen.

---

## Healthchecks

| Ziel | Prüfung |
| --- | --- |
| Backend | `GET /health` → `{"status":"ok"}` (Docker-Healthcheck via Python-Request) |
| Frontend | `GET /healthz` → `{"status":"ok"}` (nginx, ohne Backend-Abhängigkeit) |
| Datenbank | `pg_isready` |

Der Backend-Container gilt erst als `healthy`, wenn `/health` antwortet; das Frontend
startet erst danach (`depends_on: condition: service_healthy`).

---

## Fehleranalyse und Debug-Modus

1. **Logs**

   ```bash
   docker compose logs -f backend
   ```

   Beispielzeile:

   ```
   2026-08-23 11:35:12 INFO app.scanner.runner :: MSC Clean iPhone - final price detected: 2876.0 EUR (Status OK)
   ```

   Cookies, Sessiontokens, Auth-Header, Proxy-Passwörter und Zahlungsdaten werden
   grundsätzlich nicht geloggt (Redaction-Filter).

2. **Adminbereich** (`http://SERVER-IP:8080/#/admin`): Systemstatus, Scheduler, Limits,
   Provider, Proxyprofile (nur Labels), Benachrichtigungskanäle, Speicherverbrauch,
   Browserprofile, Fehlerliste und Debug-Ansicht.

3. **Debug-Ansicht** pro Scan: aktuelle URL, erkannter Seitentyp, gefundene Preise samt
   Quelle, Playwright-Schritte, Fehler, Screenshots. Ohne Secrets.

4. **Sichtbarer Browser** (nur zum Debuggen, benötigt eine Desktop-Umgebung/X-Server):

   ```env
   HEADLESS=false
   ```

   Produktiv immer `HEADLESS=true`.

5. **Typische Ursachen**

   | Symptom | Ursache / Vorgehen |
   | --- | --- |
   | `BLOCKED / CAPTCHA` | Website zeigt eine Prüfung. Kein Workaround – Abstand vergrößern, Häufigkeit senken. |
   | `PRICE_NOT_FOUND` | Preis nicht eindeutig lesbar. Screenshot und HTML-Snapshot prüfen, ggf. Selektoren in `providers/msc/selectors.py` ergänzen. |
   | `SELECTOR_CHANGED` | Seitenaufbau geändert. Nur `selectors.py` anpassen. |
   | `TIMEOUT` | Netz/Seite langsam. `NAVIGATION_TIMEOUT_MS` erhöhen. |
   | Chromium startet nicht | `shm_size` prüfen, Container-Logs ansehen. |
   | `ZoneInfoNotFoundError: No time zone found with key Europe/Berlin` | Im Image fehlt die Zeitzonendatenbank. Behoben durch `tzdata` in `requirements.txt` und im Dockerfile – Image neu bauen (`docker compose build --no-cache backend`). Die App startet inzwischen auch ohne tzdata und fällt im Scheduler auf UTC zurück (Hinweis im Adminbereich). |
   | `port is already allocated` | Ein Host-Port des Stacks ist belegt. Belegung finden: `docker ps --format '{{.Names}} {{.Ports}}' \| grep 8080` bzw. `sudo lsof -i :8080`. Dann `WEB_PORT` auf einen freien Port setzen. Der Backend-Port wird standardmäßig nicht veröffentlicht. |
   | 504 beim Deploy in Portainer | Kein App-Fehler, siehe [504 Gateway Time-out](#504-gateway-time-out-in-portainer). |
   | `container name "/cpc-backend" is already in use` | Reste eines fehlgeschlagenen Deploys. `docker rm -f cpc-backend cpc-frontend cpc-db`, danach neu deployen. |
   | 502 in der UI, nachdem nur das Backend neu gestartet wurde | nginx cacht die IP des Backends beim Start. `docker restart cpc-frontend` (oder den ganzen Stack neu deployen). |
   | Stack lässt sich nicht neu deployen | In Portainer **Remove stack** (nicht nur „Stop"), dann neu anlegen. Volumes `cpc-app-data`/`cpc-db-data` bleiben dabei erhalten. |

---

## API

Basis: `http://SERVER-IP:8080/api`. Interaktive Doku: `/docs`.

| Methode | Pfad | Zweck |
| --- | --- | --- |
| GET | `/health` | Healthcheck |
| GET | `/api/meta` | Profile, Cookie-Varianten, Provider, Limits, erlaubte Domains |
| POST | `/api/parse-url` | Link prüfen und Reisedaten extrahieren (ohne Speichern) |
| GET/POST | `/api/cruises` | Reisen listen / anlegen (+ Scan starten) |
| GET/PATCH/DELETE | `/api/cruises/{id}` | Detail, Intervall/Titel ändern, löschen |
| GET | `/api/cruises/{id}/history` | Preisverlauf |
| POST | `/api/cruises/{id}/scans` | neuen Scan starten |
| GET | `/api/scans/{id}` | Scan mit Ergebnissen und Auswertung |
| GET | `/api/scans/{id}/logs` | Debug-Protokoll |
| GET/POST/DELETE | `/api/cruises/{id}/alerts`, `/api/alerts/{id}` | Preisalarme |
| POST | `/api/alerts/{id}/test` | Testbenachrichtigung |
| GET | `/api/artifacts/{pfad}` | Screenshot/HTML-Snapshot ausliefern |
| GET | `/api/admin/status`, `/api/admin/errors` | Adminübersicht |
| GET | `/api/admin/debug/scan/{id}` | Debug-Ansicht |
| POST | `/api/admin/profiles/{key}/reset` | persistentes Profil zurücksetzen |

Ist `API_KEY` gesetzt, brauchen alle schreibenden Endpunkte und `/api/admin/*` den Header
`X-API-Key`. Lesende Endpunkte bleiben offen (praktisch hinter einem Reverse Proxy mit
eigener Authentifizierung). In der Weboberfläche wird der Key oben rechts eingetragen.

HTML-Snapshots werden bewusst als `text/plain` ausgeliefert, damit gespeicherte Seiten
nie im Browser ausgeführt werden.

---

## Entwicklung und Tests

```bash
# Backend
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
playwright install chromium firefox           # nur lokal nötig

export DATA_DIR=./data DATABASE_URL="sqlite:///./data/dev.db"
pytest                                        # 166 Tests, ohne Netzwerk/Browser
ruff check app tests
mypy app
uvicorn app.main:app --reload --port 8000

# Frontend
cd ../frontend
npm ci                 # package-lock.json ist eingecheckt
npm run typecheck
npm run dev            # http://localhost:5173, proxyt /api auf :8000
```

Testabdeckung: MSC-URL-Parser, Preisparser, Label-Klassifikation, Datenbankmodell,
API-Endpunkte, Sicherheit (Allowlist/SSRF/Pfad-Traversal/Redaction), Browserprofile,
Preisvergleich, Angebots-Identität, Scheduler, Provider-Architektur und ein vollständiger
Scan-Durchlauf über den Mock-Provider.

Projektstruktur:

```
backend/app
├── api/routes.py            REST-API inkl. Adminbereich
├── browser/                 Profile, isolierte Sessions, Locator-Helfer
├── comparison/              Angebots-Identität, neutrale Auswertung
├── core/                    Logging mit Redaction, Sicherheit (Allowlist, Pfade)
├── flights/                 Flugvergleich (Schnittstelle, deaktiviert)
├── notify/                  E-Mail, Telegram, Discord, Home Assistant
├── providers/
│   ├── base.py              CruiseProvider-Interface + Standard-Flow
│   ├── registry.py          Registrierung, geplante Anbieter
│   ├── msc/                 MSC: URL-Parser, Preisparser, Selektoren, Adapter
│   └── mock/                Demo-/Testprovider
├── scanner/                 Testmatrix, Ausführung, Artefakte, Queue
└── scheduler/               periodische Checks
```

Neuen Anbieter ergänzen: `CruiseProvider` implementieren (`can_handle_url`, `parse_url`,
`open_offer`, `accept_cookies`, `extract_trip_details`, `select_cabin`, `select_rate`,
`extract_price`, `extract_final_price`, `take_snapshot`), Domains in
`app/core/security.py` freigeben und den Provider in `app/providers/registry.py`
registrieren. `run_flow` kann übernommen oder überschrieben werden.

---

## Bekannte Einschränkungen

- **MSC-Selektoren müssen gegen die Live-Seite verifiziert werden.** Die Erfassung ist
  absichtlich text-/rollenbasiert und mit Kandidatenlisten aufgebaut, sodass sie
  Änderungen übersteht oder ehrlich mit `PRICE_NOT_FOUND` / `SELECTOR_CHANGED` endet.
  Beim ersten echten Lauf lohnt ein Blick in Screenshots und Debug-Ansicht; Anpassungen
  betreffen ausschließlich `backend/app/providers/msc/selectors.py`.
- Die iPhone-Variante ist eine **Emulation** in Chromium (Viewport, Touch, DPR, UA), keine
  echte Safari-/WebKit-Engine.
- Wie tief der Buchungsprozess durchlaufen werden kann, hängt von der Website ab. Endet
  ein Test früher, wird der erreichte Schritt (`deepest_step`) und der Status `PARTIAL`
  gespeichert – kein geschätzter Endpreis.
- Der Flugvergleich ist als Schnittstelle vorhanden, aber deaktiviert: ohne saubere,
  zulässige Datenquelle werden bewusst keine Flugpreise ermittelt.
- Ein einzelner Preisunterschied ist kein Beweis. Erst mehrere reproduzierte Runden
  liefern eine belastbare Aussage – deshalb die Mehrfachverifikation.

---

## Roadmap

1. MSC-Selektoren gegen die Live-Seite feinjustieren.
2. Weitere Provider: e-hoi, Kreuzfahrtberater, Dreamlines, Logitravel, HolidayCheck, CHECK24.
3. Kreuzfahrt + Flug: Paketpreis gegen „ohne Flug + separater Flug“ (bevorzugte Flughäfen
   sind schon konfigurierbar: `PREFERRED_AIRPORTS`).
4. Ausbau der Preisalarme (mehrere Empfänger, Zeitfenster).

---

## Rechtlicher Hinweis

Das Tool ruft ausschließlich öffentlich zugängliche Angebotsseiten lesend auf, mit
konservativem Rate Limiting, ohne Login und ohne Buchung. Es umgeht keine technischen
Schutzmaßnahmen. Prüfe vor dem Einsatz die Nutzungsbedingungen des jeweiligen Anbieters
und halte die Abfragefrequenz niedrig.
