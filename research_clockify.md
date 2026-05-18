# Clockify API v1 — Research & Findings

> Quelle: https://docs.developer.clockify.me/  
> Relevant für: Überstunden-Tracker HA Custom Integration

---

## 1. Authentifizierung

- **Header:** `X-Api-Key: <api_key>`
- Alternativ: `X-Addon-Token` (für Marketplace-Addons — nicht relevant)
- **Subdomain-Workspaces** (z.B. `firma.clockify.me`): separaten API-Key in den Profileinstellungen generieren — dieser Key gilt nur für diesen Workspace!
- Kein OAuth, kein Token-Refresh nötig — Key ist dauerhaft gültig

---

## 2. Base URL & API URLs

- **Standard:** `https://api.clockify.me/api/v1`
- **Subdomain-Workspaces:** `https://<subdomain>.api.clockify.me/api/v1`
- Alle Endpoints sind REST/JSON

---

## 3. Rate Limiting & Pagination

- **Pagination:** Query-Parameter `page` (1-basiert, Default: 1) und `page-size` (Default: **50**, max. je nach Endpoint)
- Bei Time Entries: `page-size` bis **500** möglich → bei vielen Einträgen Schleife über Seiten nötig!
- Wenn Response-Länge < page-size → letzte Seite erreicht
- **Rate Limiting:** Dokumentation erwähnt Rate Limiting, genaue Limits nicht öffentlich angegeben — bei normalem Single-User-Einsatz kein Problem

---

## 4. Benötigte Endpoints (für Überstunden-Tracker)

### 4.1 User Info

```
GET /v1/user
```
- Liefert eingeloggten User: `id`, `name`, `email`, `activeWorkspace`, `defaultWorkspace`
- Für Config-Flow-Validation und zum Ermitteln der `userId` + `defaultWorkspace`

**Response (relevante Felder):**
```json
{
  "id": "5a0ab5acb07987125438b60f",
  "name": "John Doe",
  "email": "johndoe@example.com",
  "activeWorkspace": "64a687e29ae1f428e7ebe303",
  "defaultWorkspace": "64a687e29ae1f428e7ebe303"
}
```

---

### 4.2 Workspaces

```
GET /v1/workspaces
```
- Liefert alle Workspaces des Users
- Enthält `id`, `name`, `workspaceSettings` (u.a. `workingDays` — relevant für Soll-Berechnung!)

**Response (relevante Felder):**
```json
[{
  "id": "64a687e29ae1f428e7ebe303",
  "name": "Cool Company",
  "workspaceSettings": {
    "workingDays": ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"]
  }
}]
```

> ⚠️ **Wichtig:** `workspaceSettings.workingDays` enthält die konfigurierten Arbeitstage! Das kann direkt für die Soll-Stunden-Berechnung genutzt werden — kein manuelles Konfigurieren nötig, wenn man den Workspace nutzt.

---

### 4.3 Time Entries für Zeitraum (Haupt-Endpoint)

```
GET /v1/workspaces/{workspaceId}/user/{userId}/time-entries
```

**Query-Parameter:**

| Parameter | Typ | Beschreibung |
|---|---|---|
| `start` | string | ISO 8601: `yyyy-MM-ddThh:mm:ssZ` — Start des Zeitraums |
| `end` | string | ISO 8601: `yyyy-MM-ddThh:mm:ssZ` — Ende des Zeitraums |
| `page` | int | Seitennummer (ab 1) |
| `page-size` | int | Einträge pro Seite (Default 50, max 500) |
| `in-progress` | boolean | Nur laufende Einträge |
| `hydrated` | boolean | Zusatzinfos (Projektname etc.) |

**Response (pro Entry — relevante Felder):**
```json
{
  "id": "64c777ddd3fcab07cfbb210c",
  "description": "...",
  "projectId": "...",
  "userId": "...",
  "timeInterval": {
    "start": "2024-01-15T08:00:00Z",
    "end": "2024-01-15T17:00:00Z",
    "duration": "PT9H"   // ISO 8601 Duration — ACHTUNG: kann null sein bei laufendem Timer!
  },
  "type": "REGULAR",     // REGULAR | BREAK
  "billable": true,
  "isLocked": false
}
```

> ⚠️ **Wichtig:** `type: "BREAK"` Einträge sollten für Stunden-Berechnung **herausgefiltert** werden!  
> ⚠️ **Wichtig:** `timeInterval.end` ist `null` bei laufendem Timer → separat behandeln

---

### 4.4 Laufenden Timer abrufen

```
GET /v1/workspaces/{workspaceId}/user/{userId}/time-entries?in-progress=true
```

Oder workspace-weit:
```
GET /v1/workspaces/{workspaceId}/time-entries/status/in-progress
```

Gibt laufende Einträge zurück (ohne `end` im `timeInterval`). Dauer muss manuell berechnet werden: `now - start`.

---

### 4.5 Holidays (Feiertage) — BONUS

```
GET /v1/workspaces/{workspaceId}/holidays/in-period
  ?assigned-to={userId}
  &start=...
  &end=...
```

Liefert dem User zugewiesene Feiertage in einem Zeitraum. Kann für präzisere Soll-Stunden-Berechnung genutzt werden (Feiertag = kein Arbeitstag).

**Response:**
```json
[{
  "id": "...",
  "name": "New Year's Day",
  "datePeriod": { "start": "2024-01-01", "end": "2024-01-01" },
  "occursAnnually": true
}]
```

> 💡 **Optional** aber empfohlen: Feiertage aus Clockify lesen statt eigene Library zu benötigen!

---

## 5. Duration-Berechnung

### Option A: `timeInterval.duration` parsen (ISO 8601)
Die API liefert `duration` als ISO 8601 Duration String, z.B. `"PT8H30M"`.  
Python: `import isodate; isodate.parse_duration("PT8H30M").total_seconds()`  
→ Nur verfügbar für abgeschlossene Einträge.

### Option B: start/end selbst berechnen (empfohlen, robuster)
```python
from datetime import datetime, timezone

def get_duration_seconds(entry: dict) -> float:
    interval = entry["timeInterval"]
    start = datetime.fromisoformat(interval["start"].replace("Z", "+00:00"))
    
    if interval.get("end"):
        end = datetime.fromisoformat(interval["end"].replace("Z", "+00:00"))
    else:
        # Laufender Timer
        end = datetime.now(timezone.utc)
    
    return (end - start).total_seconds()
```

---

## 6. Pagination-Pattern (vollständig)

```python
async def get_all_time_entries(workspace_id, user_id, start, end):
    all_entries = []
    page = 1
    page_size = 500
    
    while True:
        entries = await api_request(
            f"/workspaces/{workspace_id}/user/{user_id}/time-entries",
            params={"start": start, "end": end, "page": page, "page-size": page_size}
        )
        all_entries.extend(entries)
        
        if len(entries) < page_size:
            break  # Letzte Seite erreicht
        
        page += 1
    
    return all_entries
```

---

## 7. Datumsformat

Alle Datumswerte in der API:
- **Format:** `yyyy-MM-ddThh:mm:ssZ` (UTC, Z-Suffix)
- **Beispiel:** `"2024-01-15T08:00:00Z"`
- Python-Konvertierung: `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`

---

## 8. Time Entry Types — Wichtig für Filterung

| `type` | Bedeutung |
|---|---|
| `REGULAR` | Normaler Arbeitseintrag — **zählen** |
| `BREAK` | Pause — **nicht zählen** |

Im `api.py` immer filtern: `if entry["type"] != "BREAK"`

---

## 9. Workspace Settings — nützliche Felder

Aus `GET /v1/workspaces/{workspaceId}` → `workspaceSettings`:

| Feld | Bedeutung |
|---|---|
| `workingDays` | Array: `["MONDAY", "TUESDAY", ...]` — konfigurierte Arbeitstage |
| `trackTimeDownToSecond` | bool — Sekundengenauigkeit |
| `lockTimeEntries` | Datum bis zu dem Einträge gesperrt sind |
| `durationFormat` | `"FULL"` / `"COMPACT"` |

> 💡 `workingDays` direkt aus dem Workspace lesen → kein manuelles "Arbeitstage pro Woche" im Config Flow nötig! Kann aber als Override-Option trotzdem angeboten werden.

---

## 10. Summary Report (Alternative zu Time Entries)

```
POST /v1/workspaces/{workspaceId}/reports/summary
```

Liefert aggregierte Stunden für einen Zeitraum ohne Pagination-Problem. Für einfache Gesamt-Stunden ggf. effizienter als alle Time Entries abzufragen.

**Request Body:**
```json
{
  "dateRangeStart": "2024-01-01T00:00:00Z",
  "dateRangeEnd": "2024-12-31T23:59:59Z",
  "summaryFilter": { "groups": ["USER"] },
  "users": { "ids": ["<userId>"] }
}
```

> 💡 **Überlegung für den Agent:** Summary Report API könnte für die Gesamt-Stunden-Berechnung einfacher sein als alle Time Entries paginiert abzufragen. Aber: kein direkter Zugriff auf einzelne Einträge, keine BREAK-Filterung auf API-Seite.

---

## 11. Zusammenfassung — Was der Agent wissen muss

### Minimal benötigte API-Calls pro Update-Zyklus:

1. `GET /v1/user` → userId + defaultWorkspace (einmalig, cached in Coordinator)
2. `GET /v1/workspaces` → workingDays (einmalig, cached)
3. `GET /v1/workspaces/{wid}/user/{uid}/time-entries?start=...&end=...&page-size=500` + Pagination → alle Einträge seit start_date
4. Optinal: `GET /v1/workspaces/{wid}/holidays/in-period?assigned-to={uid}&start=...&end=...` → Feiertage

### Python-Abhängigkeiten:
- `aiohttp>=3.8.1` — für async HTTP (bereits in HA vorhanden)
- `async-timeout` — für Timeouts (bereits in HA vorhanden)
- **Kein** `isodate` nötig wenn start/end manuell berechnet wird

### Kritische Fallstricke:
1. **BREAK-Einträge filtern** (`type != "BREAK"`)
2. **Laufender Timer** hat kein `end` → `now()` als End-Zeit verwenden
3. **Subdomain-Workspaces** brauchen eigenen API-Key → im Config Flow Hinweis geben
4. **Pagination** bei vielen Einträgen (> 500) — Schleife implementieren
5. **UTC vs. lokale Zeit** — API immer UTC, Tagesgrenzen in lokaler Zeitzone berechnen
