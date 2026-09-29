# Архитектура TooruDragon — v0.1.0 Alpha

## Главное правило

Системные функции реализуются один раз в `core/system/`.
Ядра не копируют базу данных, авторизацию, API runtime, обновление, логи или загрузку конфигурации.

```text
                         Web / Mobile clients
                                |
                          Main Core :8700
                                |
              +-----------------+-----------------+
              |                 |                 |
         specialized cores   System Layer    shared data
              |                 |                 |
      +-------+-------+         |              SQLite
      |       |       |         |
   Tooru   Laboratory Home    config
   :8701     :8702    :8703   auth
      |                 |      API
    Work :8704        Mobile   logs
                      :8705    updater
                               database
```

## System Layer

### `core/system/config.py`
Загружает `config/system.json` и `config/cores.json`. Ядра не хранят собственные копии портов и системных настроек.

### `core/system/database.py`
Единый доступ к SQLite, инициализация схемы, query/execute и управление соединениями.

### `core/system/auth.py`
Общая Bearer-авторизация. Токен берётся из переменной окружения, а требование авторизации задаётся централизованно.

### `core/system/server.py`
Общий HTTP/API runtime:
- GET/POST;
- JSON;
- CORS;
- public/protected routes;
- единая обработка ошибок.

### `core/system/logging.py`
Единое консольное и файловое логирование с ротацией.

### `core/system/updater.py`
Единый механизм обновления Git через `fetch` + `pull --ff-only`.

### `core/system/runtime.py`
Связывает конфигурацию, БД, авторизацию, логи и API в объект `CoreRuntime`, который использует каждое ядро.

## Специализированные ядра

Каждое ядро объявляет:
1. имя;
2. роль;
3. только собственные маршруты и функции.

Системные маршруты `/health` и `/system` добавляет `CoreRuntime`.

## Конфигурация

### `config/system.json`
Содержит общесистемные настройки:
- version;
- database;
- auth;
- logging;
- update.

### `config/cores.json`
Содержит единый реестр:
- Main — 8700;
- Tooru/AI — 8701;
- Laboratory — 8702;
- Home — 8703;
- Work — 8704;
- Mobile — 8705.

## Запуск

`StartTooruDragon.bat`:
1. проверяет Git и Python;
2. вызывает System Layer updater;
3. инициализирует общую БД;
4. запускает специализированные ядра;
5. запускает Main Core;
6. запускает Web UI;
7. выполняет общий health-check.

## Правило дальнейшей разработки

Новая системная возможность сначала добавляется в `core/system/`.
В конкретное ядро код добавляется только тогда, когда он относится исключительно к его предметной области.
