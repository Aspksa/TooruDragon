# Core Manager

Core Manager — единый слой управления процессами ядер TooruDragon.

## Зачем он нужен

Раньше Launcher, Watchdog и BAT-скрипты могли запускать ядра разными способами.
Теперь Main Core предоставляет единый управляющий API, а Watchdog и GUI используют
один и тот же Core Manager.

## Управляемые ядра

- `tooru_ai`
- `laboratory`
- `home`
- `work`
- `mobile`

Main Core намеренно не останавливает и не перезапускает сам себя через собственный
HTTP API. Его жизненным циклом управляет внешний Launcher / Update Manager.

## API

### Состояние всех ядер

```http
GET /api/cores
```

Ответ содержит:

- display name;
- version;
- host/port;
- online;
- PID;
- latency;
- role;
- capabilities;
- error, если health-check не прошёл.

### Универсальная управляющая команда

```http
POST /api/core/action
Content-Type: application/json

{
  "core": "tooru_ai",
  "action": "restart"
}
```

Поддерживаются:

- `start`
- `stop`
- `restart`

### Короткие маршруты

Для каждого специализированного ядра также создаются маршруты:

```text
POST /api/core/tooru_ai/start
POST /api/core/tooru_ai/stop
POST /api/core/tooru_ai/restart

POST /api/core/laboratory/start
POST /api/core/laboratory/stop
POST /api/core/laboratory/restart

POST /api/core/home/start
POST /api/core/home/stop
POST /api/core/home/restart

POST /api/core/work/start
POST /api/core/work/stop
POST /api/core/work/restart

POST /api/core/mobile/start
POST /api/core/mobile/stop
POST /api/core/mobile/restart
```

### История действий

```http
GET /api/core/history?limit=100
```

История хранится в SQLite-таблице `core_actions`.

## Watchdog

Watchdog больше не обязан открывать отдельные BAT/CMD-окна для восстановления ядра.
При достижении failure threshold он вызывает Core Manager:

```text
health failure
    ↓
Watchdog
    ↓
CoreManager.restart(core)
    ↓
stop → start → health-check
    ↓
core_actions + Event Bus
```

## Event Bus

Каждая команда через Main API публикует событие:

```text
core.manager.action
```

Payload содержит:

- core;
- action;
- ok;
- message.

## Launcher

Страница «Ядра» в Windows Launcher отправляет команды в:

```text
POST http://127.0.0.1:8700/api/core/action
```

Таким образом GUI не содержит отдельной процессной логики.

## Безопасность

Управляющие маршруты защищены общим AuthService. Пока `auth.required=false`,
они доступны локально без токена. При включении Bearer auth Launcher использует
`TOORUDRAGON_API_TOKEN`.
