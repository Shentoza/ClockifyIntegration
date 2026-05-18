# Clockify Überstunden-Tracker — HA Custom Integration: Research & Bauplan

> Dieses Dokument fasst alles Notwendige für einen nachfolgenden Agent zusammen, der die Integration implementiert.

---

## 1. Ziel

Eine Home Assistant **Custom Integration** (`custom_components/clockify_overtime`), die:
1. Die Clockify API abfragt (alle Workspaces, alle Time Entries ab einem konfigurierbaren Startdatum)
2. Ist-Stunden vs. Soll-Stunden (konfigurierbar: h/Tag × Arbeitstage) berechnet
3. Das Überstunden-Saldo als HA-Sensoren bereitstellt
4. Einen manuell eingebbaren Auszahlungs-Offset unterstützt (Überstunden wurden ausgezahlt → Saldo-Korrektur)
5. Persistent ist (HA `recorder` speichert Verlauf, `ConfigEntry` speichert Konfiguration)

---

## 2. HA Custom Integration — Grundstruktur (offiziell)

### Pflichtdateien

```
custom_components/clockify_overtime/
├── __init__.py          # Domain-Konstante, async_setup, async_setup_entry, async_unload_entry
├── manifest.json        # Metadaten (domain, name, version, requirements, config_flow, iot_class)
├── config_flow.py       # UI-Formular zum Einrichten (API-Key, Konfigurationsparameter)
├── const.py             # Alle Konstanten
├── api.py               # Reiner HTTP-Client (kein HA-Code), nutzt aiohttp
├── sensor.py            # SensorEntity-Definitionen, lesen aus DataUpdateCoordinator
└── strings.json         # UI-Texte für config_flow
    translations/
    └── en.json          # Englische Übersetzungen (Pflicht, auch wenn nur DE gewünscht)
```

### manifest.json (Mindestinhalt für Custom Integration)

```json
{
  "domain": "clockify_overtime",
  "name": "Clockify Overtime Tracker",
  "version": "0.1.0",
  "documentation": "https://github.com/Shentoza/ClockifyIntegration",
  "codeowners": ["@Shentoza"],
  "requirements": ["aiohttp>=3.8.1"],
  "config_flow": true,
  "integration_type": "service",
  "iot_class": "cloud_polling",
  "single_config_entry": true
}
```

**Wichtig:** `version` ist bei Custom Integrations **Pflicht** (bei Core-Integrations nicht).  
`single_config_entry: true` verhindert doppeltes Einrichten.

---

## 3. HA Integration Lifecycle (Reihenfolge beim Start)

```
1. manifest.json geladen
2. async_setup(hass, config)         → Domain initialisieren, hass.data[DOMAIN] = {}
3. async_setup_entry(hass, entry)    → Coordinator erstellen, API-Key aus entry.data lesen,
                                       async_config_entry_first_refresh() aufrufen,
                                       Plattformen forwarden (sensor)
4. sensor.async_setup_entry(...)     → Entities erstellen, beim Coordinator registrieren
--- Laufbetrieb ---
5. Coordinator._async_update_data()  → Läuft im scan_interval, aktualisiert alle Entities
--- Beim Entfernen ---
6. async_unload_entry(hass, entry)   → Plattformen entladen, Verbindungen schließen
```

---

## 4. DataUpdateCoordinator (Kern-Pattern)

```python
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from datetime import timedelta

class ClockifyOvertimeCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, api, config):
        super().__init__(hass, logger, name=DOMAIN,
                         update_interval=timedelta(minutes=30))
        self.api = api
        self.config = config  # hours_per_day, work_days_per_week, start_date, payout_offset

    async def _async_update_data(self):
        try:
            # 1. Time entries von Clockify holen (seit start_date bis heute)
            # 2. Ist-Stunden berechnen
            # 3. Soll-Stunden berechnen (Arbeitstage × h/Tag)
            # 4. Saldo = Ist - Soll - payout_offset
            return {"actual_hours": ..., "target_hours": ..., "balance_hours": ...}
        except Exception as err:
            raise UpdateFailed(f"Clockify API error: {err}") from err
```

**Alle Entities erben von `CoordinatorEntity`** — kein eigenes Polling, nur `self.coordinator.data` lesen.

---

## 5. Config Flow

Pflichtdatei: `config_flow.py`. Klasse erbt von `config_entries.ConfigFlow, domain=DOMAIN`.

### Felder (Schritt 1 — Basis-Setup)

| Feld | Typ | Beschreibung |
|---|---|---|
| `api_key` | `str` (required) | Clockify API Key |
| `hours_per_day` | `float` (default: 8.0) | Soll-Stunden pro Arbeitstag |
| `work_days_per_week` | `int` (default: 5) | Arbeitstage pro Woche (1–7) |
| `start_date` | `str` (date, required) | Datum ab dem getrackt wird (z.B. "2024-01-01") |
| `payout_offset_hours` | `float` (default: 0.0) | Bereits ausgezahlte Überstunden (manuell) |

### Options Flow (optional, für spätere Anpassung ohne Neueinrichtung)

Zusätzliche Klasse `OptionsFlow` — erlaubt Änderung von `payout_offset_hours` und Soll-Stunden nachträglich über HA UI (Einstellungen → Integration → Konfigurieren).

### Validation in Config Flow

```python
async def validate_input(hass, api_key):
    session = async_get_clientsession(hass)
    api = ClockifyApi(api_key, session)
    user = await api.get_user_info()   # wirft Exception bei ungültigem Key
    return user  # {"id": "...", "name": "..."}
```

---

## 6. Clockify API

**Base URL:** `https://api.clockify.me/api/v1`  
**Auth-Header:** `X-Api-Key: <api_key>`

### Benötigte Endpoints

| Endpoint | Zweck |
|---|---|
| `GET /user` | User-Info abrufen (ID, Name) — für Config Flow Validation |
| `GET /workspaces` | Alle Workspaces des Users |
| `GET /workspaces/{wid}/user/{uid}/time-entries?start=...&end=...&page-size=500` | Time Entries für Zeitraum |
| `GET /workspaces/{wid}/user/{uid}/time-entries?in-progress=true` | Aktuell laufender Timer |

### Zeitraum-Abfrage

```python
# ISO 8601 mit Z-Suffix für UTC
start = "2024-01-01T00:00:00Z"
end   = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
```

**Pagination:** Clockify gibt max. 50 Einträge zurück (default), max. 500 per `page-size=500`.  
Bei mehr als 500 Einträgen: Paginierung über `page` Parameter (1-basiert) notwendig!  
**Empfehlung:** Schleife über Seiten bis Response < page-size.

### Duration berechnen

```python
def calculate_duration_seconds(entry):
    interval = entry["timeInterval"]
    if interval.get("end"):
        start = datetime.fromisoformat(interval["start"].replace("Z", "+00:00"))
        end   = datetime.fromisoformat(interval["end"].replace("Z", "+00:00"))
        return (end - start).total_seconds()
    elif interval.get("start"):  # laufender Timer
        start = datetime.fromisoformat(interval["start"].replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - start).total_seconds()
    return 0
```

---

## 7. Soll-Stunden-Berechnung

```python
from datetime import date
import holidays  # optional: für Feiertage (pip: holidays)

def calculate_target_hours(start_date: date, end_date: date,
                            hours_per_day: float, work_days_per_week: int) -> float:
    # Arbeitstage zählen: Wochentage (Mo-Fr bei 5 Tagen) zwischen start und heute
    work_day_numbers = list(range(work_days_per_week))  # 0=Mo, 1=Di, ...
    total_work_days = sum(
        1 for d in (start_date + timedelta(n) for n in range((end_date - start_date).days + 1))
        if d.weekday() in work_day_numbers
    )
    return total_work_days * hours_per_day
```

**Achtung Zeitzone:** HA-Zeitzone (`hass.config.time_zone`) für Tagesgrenzen verwenden, nicht UTC.

---

## 8. Sensors

Drei Sensoren, alle mit `state_class: SensorStateClass.TOTAL` für Langzeit-Verlauf im HA Dashboard:

| Entity ID | Name | Einheit | Wert |
|---|---|---|---|
| `sensor.clockify_overtime_actual_hours` | Clockify Ist-Stunden | h | Summe aller gebuchten Stunden |
| `sensor.clockify_overtime_target_hours` | Clockify Soll-Stunden | h | Berechnete Pflicht-Stunden |
| `sensor.clockify_overtime_balance` | Clockify Überstunden-Saldo | h | Ist - Soll - Payout-Offset |

Extra-Attribute auf dem Balance-Sensor: `payout_offset_hours`, `start_date`, `last_updated`.

---

## 9. Persistenz in Home Assistant

- **Konfiguration** (API-Key, Parameter): In `ConfigEntry` gespeichert → `.storage/core.config_entries` (JSON, überlebt Neustarts)
- **Saldo-Verlauf**: Automatisch durch HA `recorder` (SQLite) → nutzbar für `statistics-graph`-Cards
- **Payout-Offset**: Gespeichert in `ConfigEntry.options` via Options Flow — kein separater `input_number` nötig
- **Alternativer Weg für Offset**: `input_number`-Helper in HA anlegen, Integration liest via `hass.states.get("input_number.overtime_payout")` — einfacher, aber weniger sauber

**HA ist für diesen Use Case vollständig geeignet.** Für aufwändige Historien-Analysen wäre InfluxDB + Grafana besser, aber nicht notwendig.

---

## 10. Installation (Custom Integration)

1. Ordner `clockify_overtime/` nach `config/custom_components/` auf dem HA-Host kopieren
2. HA neu starten
3. Einstellungen → Geräte & Dienste → Integration hinzufügen → "Clockify Overtime Tracker"
4. API-Key eingeben, Parameter konfigurieren → fertig

**Kein HACS nötig** für eigene Nutzung. HACS-kompatibel machen: `hacs.json` + GitHub Release hinzufügen.

---

## 11. Referenz-Integration (Vorlage)

`https://github.com/BrunoJurkovic/ha-clockify-integration` — Basis-Clockify-Integration (nur Heute-Stunden).  
Wiederverwendbar: `api.py` (HTTP-Client-Struktur), `config_flow.py` (Basis), `manifest.json`.  
**Muss erweitert werden um:** Zeitraum-Abfrage, Pagination, Soll-Berechnung, Options Flow, 3 Sensoren statt 1.

---

## 12. Offene Entscheidungen für den implementierenden Agent

1. **Feiertage berücksichtigen?** → `holidays`-Library (pip) oder einfach weglassen (Benutzer justiert Offset manuell)
2. **Options Flow implementieren?** → Empfohlen für `payout_offset_hours`-Anpassung ohne Neueinrichtung
3. **`de.json` Translation?** → Empfohlen: `translations/en.json` (Pflicht) + `translations/de.json`
4. **Scan-Interval konfigurierbar?** → Optional als Options-Feld, Default: 30 Minuten
5. **Mehrere Workspaces?** → Ja, alle summieren (wie in Vorlage)
