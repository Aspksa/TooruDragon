# TooruDragon v0.3.0

Дата старта: **29 сентября 2026**

TooruDragon — модульная AI-система с единым системным слоем и специализированными ядрами.

## Версии ядер

Каждое ядро имеет собственную версию и может развиваться независимо:

- **Главное ядро** — `127.0.0.1:8700` — **v0.3.0**
- **Tooru/AI** — `127.0.0.1:8701` — **v0.3.0**
- **Лаборатория Tooru/AI** — `127.0.0.1:8702` — **v0.3.0**
- **Домашнее ядро** — `127.0.0.1:8703` — **v0.3.0**
- **Рабочее ядро** — `127.0.0.1:8704` — **v0.3.0**
- **Мобильное ядро** — `127.0.0.1:8705` — **v0.3.0**

Системная платформа проекта — **v0.3.0**, а версии самих ядер теперь отображаются просто как **v0.3.0** и хранятся централизованно в `config/cores.json`.

## System Layer

Общий системный слой находится в `core/system/`.

Он единый для всех ядер и отвечает за:
- конфигурацию;
- SQLite и доступ к данным;
- API/HTTP runtime;
- Bearer-авторизацию;
- логирование и ротацию логов;
- обновление из GitHub;
- единый runtime ядра;
- реестр адресов, портов, имён и версий ядер.

Каждое специализированное ядро содержит только свои маршруты и бизнес-логику.

### Системная конфигурация

`config/system.json`:
- системная версия;
- база данных;
- авторизация;
- параметры логирования;
- стратегия обновления.

`config/cores.json`:
- host;
- порт каждого ядра;
- версия каждого ядра;
- отображаемое имя каждого ядра.

Для включения Bearer-авторизации:
1. установить `"required": true` в `config/system.json`;
2. задать переменную окружения `TOORUDRAGON_API_TOKEN`;
3. передавать `Authorization: Bearer <token>`.

`/health` остаётся публичным. Защищённые системные маршруты используют единый AuthService.

## Специализация ядер

### Главное ядро
Оркестрация, health-check и состояние всех сервисов.

### Tooru/AI
Диалог, модели, память, инструменты и AI orchestration.

### Лаборатория Tooru/AI
Эксперименты, код, тестирование, сборка и инженерные инструменты.

### Дом
Домашняя автоматизация и персональные сценарии.

### Работа
Проекты, документы, задачи и рабочие интеграции.

### Мобильное ядро
Мобильный шлюз, синхронизация устройств, сессии и будущие push-интеграции.

## Системные возможности

1. **Event Bus** — центральная шина событий в Main Core. Ядра могут публиковать события через `runtime.events.publish(...)`, а последние события доступны через `GET /events`.

2. **Watchdog** — Main Core сохраняет мониторинг состояния. При включённом External Supervisor автоматическое восстановление выполняет Supervisor, чтобы исключить двойной restart. Состояние Watchdog доступно через `GET /watchdog`.

3. **Compatibility Manager** — проверяет совместимость версий ядер по правилам из `config/compatibility.json`. Результат доступен через `GET /compatibility`.

## Общие компоненты

- `StartTooruDragon.bat` — единый запуск Windows;
- `scripts/update.py` — обновление через System Layer;
- Web UI — `127.0.0.1:8710`;
- SQLite — общая локальная база;
- логи — локальная папка `logs/`.

## Репозиторий

`https://github.com/Aspksa/TooruDragon`

## Статус

**v0.3.0**


## 🐉 Русский переносной лаунчер

Запуск выполняется через **`StartTooruDragon.bat`**.

Лаунчер полностью русифицирован и работает относительно своей папки, поэтому проект можно держать:
- на внутреннем диске;
- на другом разделе;
- на внешнем SSD/HDD;
- на USB-накопителе.

Буква диска не зашивается в конфигурацию.

### Автоматический Python

Если подходящего Python **3.11+** нет, лаунчер автоматически загружает переносной Python в:

`runtime/python/`

Python не устанавливается в Windows и не изменяет системный Python. Для Windows используется официальный embeddable package Python.org с обязательной проверкой SHA-256 перед распаковкой.

Поддерживаются:
- Windows x64;
- Windows ARM64;
- Windows x86.

Папка `runtime/` локальная и в Git не отправляется.

### 🧪 Проверки перед запуском

Перед стартом система красиво показывает результаты проверки:

1. доступ на запись к текущему носителю;
2. версия и работоспособность Python;
3. наличие необходимых стандартных библиотек;
4. корректность JSON-конфигурации;
5. синтаксическая проверка Python-кода;
6. создание и проверка SQLite;
7. состояние портов ядер;
8. проверка русского текста и UTF-8;
9. наличие Git для автообновления.

При критической ошибке ядра не запускаются, а пользователь получает русское сообщение о причине.

### 🇷🇺 Русский язык

При запуске автоматически включаются:
- Windows console code page `65001`;
- `PYTHONUTF8=1`;
- `PYTHONIOENCODING=utf-8`;
- UTF-8 для PowerShell.

Поэтому русские названия, сообщения, JSON и Python-файлы проходят отдельную проверку до запуска.

### ✨ Web Control Center

Web Control Center на `http://127.0.0.1:8710` русифицирован и предоставляет полный интерфейс управления системой. Ядра отображаются с визуальными значками и статусами:
- 🐉 Tooru/AI;
- 🧪 Лаборатория;
- 🏠 Дом;
- 💼 Работа;
- 📱 Mobile.


## ✨ TooruDragon Launcher GUI

Основной красивый запуск:

`TooruDragonLauncher.bat`

Резервный технический запуск:

`StartTooruDragon.bat`

GUI содержит только четыре основных раздела:
- **Главная** — запуск, остановка, перезапуск, обновление, Web UI и общий статус;
- **Ядра** — управление шестью ядрами отдельно;
- **Логи** — просмотр системных логов;
- **Настройки** — переносимый режим и оформление.

Статусы ядер обновляются автоматически через `/health`.

Для фирменного оформления GUI автоматически ищет:

`assets/launcher/tooru-maid.png`

Если арт отсутствует, используется встроенное тёмное неоновое оформление. Логика запуска от изображения не зависит.


## ✅ Launcher GUI — полный набор

Фирменный Windows Launcher теперь включает:

- тёмную неоновую дизайн-систему TooruDragon;
- Segoe UI и единый стиль кнопок/карточек;
- логотип `assets/launcher/logo.svg`;
- встроенный компактный аниме-арт, который при первом запуске распаковывается в `runtime/launcher/tooru-maid.jpg`;
- splash-screen «Пробуждение системы...»;
- hover-анимацию кнопок;
- четыре раздела: **Главная / Ядра / Логи / Настройки**;
- живые статусы всех шести ядер через `/health`;
- реальные проверки Python, Git, SQLite, портов, Watchdog и UTF-8;
- запуск, остановку и перезапуск всей системы;
- отдельное управление каждым ядром;
- чтение логов;
- обновление из GitHub;
- системный tray Windows;
- уведомления Windows;
- автозапуск с Windows через Task Scheduler;
- автоматический запуск всех ядер при входе в Windows;
- создание ярлыка на рабочем столе;
- собственную иконку TooruDragon, генерируемую локально;
- тихий запуск GUI через `TooruDragonLauncher.vbs`, без консольного окна.

### Основной запуск

Двойной клик по:

`TooruDragonLauncher.bat`

или по созданному ярлыку **TooruDragon** на рабочем столе.

### Резервный запуск

`StartTooruDragon.bat`

остаётся техническим резервным способом запуска всей системы.

### Windows-интеграция

Также доступны отдельные команды:

- `InstallTooruDragonStartup.bat` — включить автозапуск;
- `UninstallTooruDragonStartup.bat` — убрать автозапуск;
- `CreateTooruDragonShortcut.bat` — создать ярлык.

При закрытии окна Launcher не завершает TooruDragon, а сворачивается в системный tray. Полный выход выполняется через пункт **Выход** в меню tray.


## 🛡 Безопасность Windows, Backup/Rollback и Service Registry

### Windows-совместимость

Launcher теперь имеет дополнительные fallback-механизмы:
- остановка процесса по порту использует `Get-NetTCPConnection`, а на старой Windows может перейти на `netstat`;
- автозапуск сначала использует Task Scheduler, а при недоступности его PowerShell API создаёт ярлык в системной папке Startup;
- пути к проекту передаются в кавычках, поэтому переносимый запуск рассчитан на пробелы и кириллицу в пути;
- локально генерируемые runtime-файлы, backups и `.ico` исключены из Git и не блокируют автообновление.

### Backup / Rollback

Новая схема обновления:

```text
Git update
   ↓
Backup SQLite + config + Git HEAD
   ↓
git fetch / pull --ff-only
   ↓
compileall + DB init
   ↓
запуск ядер
   ↓
health-check
   ├── OK → update подтверждён
   └── FAIL → rollback к backup
```

Резервные копии находятся локально в `backups/` и не отправляются в Git.

Доступны:
- `BackupTooruDragon.bat`;
- `RollbackTooruDragon.bat`;
- кнопки **Создать backup** и **Откатить последний** в GUI.

Хранятся последние 10 резервных копий.

### Service Registry

Main Core предоставляет живой реестр:

- `GET http://127.0.0.1:8700/registry`
- `POST http://127.0.0.1:8700/registry/register`

Каждое специализированное ядро автоматически отправляет heartbeat и публикует:
- имя;
- отображаемое имя;
- версию;
- host/port;
- PID;
- uptime;
- роль;
- capabilities;
- время последнего heartbeat.

Heartbeat выполняется каждые 10 секунд. После 35 секунд без heartbeat сервис получает статус `stale`.

Main Core также обновляет собственный heartbeat.


## ♻ Rolling Update — обновление без ручного перезапуска

Обычное обновление TooruDragon теперь применяется к уже работающей системе автоматически.

```text
Проверка GitHub
   ↓
Backup
   ↓
git pull --ff-only
   ↓
Проверка Python
   ↓
Определение изменённых компонентов
   ↓
Перезапуск только затронутых ядер по одному
   ↓
health-check каждого ядра
   ↓
Main Core перезапускается последним
   ↓
Подтверждение обновления
```

Особенности:
- незатронутые ядра продолжают работать во время обновления;
- ядро, которое было выключено до обновления, остаётся выключенным;
- обновляется только то, что затронуто изменёнными файлами;
- изменение `core/system/`, `config/` или схемы данных считается системным и требует последовательного обновления всех работавших ядер;
- Web UI перезапускается отдельно, только если изменён `web/` или общий системный слой;
- при провале health-check выполняется rollback;
- после rollback автоматически возвращается именно прежнее состояние сервисов;
- ручной перезапуск после нормального обновления больше не требуется.

На текущей архитектуре каждое ядро имеет один экземпляр, поэтому у конкретного обновляемого ядра возможна короткая пауза на его перезапуск. Остальные компоненты в это время продолжают работать. Для настоящего zero-downtime следующим уровнем будет схема blue/green с двумя экземплярами ядра и переключением трафика.


## 🎛 Core Manager

Управление процессами специализированных ядер теперь централизовано в
`core/system/core_manager.py`.

Main Core предоставляет:

- `GET /api/cores` — состояние всех ядер;
- `POST /api/core/action` — start/stop/restart;
- `GET /api/core/history` — история управляющих действий;
- короткие маршруты вида `POST /api/core/tooru_ai/restart`.

Watchdog использует тот же Core Manager для автоматического восстановления,
а страница **Ядра** в Windows Launcher больше не запускает BAT-файлы напрямую.

Действия записываются в SQLite `core_actions` и публикуются в Event Bus как
`core.manager.action`.

Подробности: `docs/CORE_MANAGER.md`.


## 🧠 Core Platform v0.2

TooruDragon получил новый фундамент Control Plane без ломки существующих ядер:

- **Supervisor boundary** — стабильный интерфейс между управляющим процессом и Main Core;
- **Contract Layer v1** — языконезависимые JSON Schema + traceable envelope;
- **Durable Workflow Engine** — SQLite-задачи с lease, heartbeat, retry, idempotency и transition audit;
- **Policy Engine** — модель capabilities с default-deny;
- **SecretStore** — секреты через заменяемые providers без хранения plaintext в БД/config;
- **Safe Update quality gate** — compile + unit tests перед rolling apply.

Новые API:

- `GET /platform`
- `GET /api/tasks`
- `POST /api/task/create`
- `POST /api/task/claim`
- `POST /api/task/update`
- `GET /api/task/transitions?task_id=...`

Контракты:

- `contracts/envelope.v1.schema.json`
- `contracts/task.v1.schema.json`

Подробная архитектура: `docs/PLATFORM_V02.md`.

Важно: текущий Supervisor пока **embedded abstraction** внутри Python-платформы. Это намеренный migration seam для будущего отдельного Rust/Windows Service/Linux daemon, а не фиктивное заявление о уже существующем внешнем supervisor.


## 🐉 Core Platform v0.3 — независимый Control Plane

TooruDragon теперь имеет внешний Supervisor на `127.0.0.1:8699`, который живёт
отдельно от Main Core и способен восстановить Main после сбоя.

Ключевые изменения v0.3:

- **External Supervisor** с desired-state, recovery и Safe Mode;
- crash-loop protection с restart budget;
- **Durable Event Fabric** вместо только in-memory событий;
- replay / ack / consumer offsets / dead-letter queue;
- `/live`, `/ready`, `/health`;
- request correlation через `X-Request-Id`;
- Observability API;
- capability-gated **Agent Runtime**;
- bounded deterministic Planner;
- Policy-gated Tool Router;
- dependency-aware Workflow Engine;
- каскадная отмена потомков при terminal dependency failure;
- Blue/Green candidate staging на временном порту;
- staged candidate не может затереть production Service Registry;
- Launcher управляет lifecycle через внешний Supervisor;
- Stop All сохраняет desired-state и не вызывает автоматическое «воскрешение» сервисов.

### Supervisor

```text
GET  http://127.0.0.1:8699/health
GET  http://127.0.0.1:8699/status
POST http://127.0.0.1:8699/core/action
POST http://127.0.0.1:8699/safe-mode/enable
POST http://127.0.0.1:8699/safe-mode/disable
```

При включённом Bearer auth управляющие POST-запросы Supervisor используют тот же
`TOORUDRAGON_API_TOKEN`.

### Durable Event Fabric

```text
GET  /events
POST /events/publish
GET  /events/replay?consumer=<name>
POST /events/ack
POST /events/dlq
```

### Agent Runtime

```text
POST /agents/plan
GET  /agents/tools?agent_id=tooru_ai
POST /agents/tool/invoke
```

Агенты работают по принципу **default deny**. Наличие Agent Runtime не означает
автоматический доступ LLM к shell, файлам или секретам.

### Observability

```text
GET /observability
```

Возвращает uptime, PID, память процесса, CPU-time (где поддерживается),
runtime counters и статистику Event Fabric.

### Blue/Green Gateway

В v0.3 работает локальный Gateway на `127.0.0.1:8698`.

Для специализированного ядра Rolling Update:

```text
candidate :970x
    ↓ health OK
Gateway → candidate
    ↓
restart canonical :870x
    ↓ health OK
Gateway → canonical
    ↓
candidate stop
```

Supervisor управляет `promote / rollback / complete`, а активное deployment-state
хранится в SQLite и восстанавливается после рестарта control-plane.

Маршруты Gateway:

```text
/core/tooru_ai/...
/core/laboratory/...
/core/home/...
/core/work/...
/core/mobile/...
```

Для клиентов, использующих Gateway, переключение специализированного ядра
происходит без ожидания рестарта canonical-процесса. При прямом подключении к
legacy-портам `8701–8705` короткий рестарт по-прежнему виден. Main Core `8700`
и Web UI `8710` пока также не имеют полного Blue/Green fronting.

Подробности: `docs/PLATFORM_V03.md`.


## 🌐 Web Control Center v0.3.0

Web-интерфейс на `http://127.0.0.1:8710` теперь является полноценным локальным
Control Center.

Разделы:

- **Обзор** — system health, ядра, память, события, uptime;
- **Ядра** — Start / Restart / Stop через External Supervisor и Safe Mode;
- **Задачи** — Durable Workflow Engine и создание задач;
- **События** — Durable Event Fabric;
- **Агент** — разрешённые tools, tool invocation и plan → workflow;
- **Control Plane** — Supervisor, Gateway, consumers и Blue/Green deployments.

Браузер не хранит Bearer token и не ходит напрямую к портам `8700/8699/8698`.
Локальный Web Server использует allowlisted same-origin proxy и при необходимости
добавляет `TOORUDRAGON_API_TOKEN` на серверной стороне.

Управляющие POST-запросы принимаются только как JSON и только от доверенного
origin Web Control Center. Произвольного localhost-proxy нет.

Health endpoint Web Control Center:

```text
GET http://127.0.0.1:8710/health
```

Подробности: `docs/WEB_CONTROL_CENTER.md`.


### Web Control Center 2.0

Control Center дополнен операционным live-слоем:

- SSE-поток Durable Event Fabric без обычного polling;
- графики RAM, CPU и средней latency ядер;
- SVG Workflow Graph по `workflow_id / parent_id`;
- просмотр transition history выбранной задачи;
- Agent Console с реальными Tool Router / Planner операциями;
- Audit dashboard: lifecycle history, DLQ, consumer lag и retention gaps.

Для графиков и workflow-визуализации не добавлены npm/CDN-зависимости: используются
нативные Canvas, SVG и EventSource.


## 🧠 Tooru/AI Model Runtime

Tooru/AI теперь имеет настоящий model/runtime слой:

- provider-independent **Model Router**;
- OpenAI-compatible local/remote providers;
- реальные `/chat`, `/inference`, `/models`, `/runtime`;
- persistent conversations;
- explicit retrieval memory;
- локальный RAG document index;
- RAG chunk injection в chat context;
- provider keys через `SecretStore`, без plaintext в Git/config;
- Web Agent Console подключён к Tooru/AI через Blue/Green Gateway.

По умолчанию provider templates выключены. TooruDragon не делает вид, что модель
установлена: пока provider не включён и не настроен, `/chat` честно возвращает
`provider_unavailable`.

Подробности: `docs/AI_RUNTIME.md`.
