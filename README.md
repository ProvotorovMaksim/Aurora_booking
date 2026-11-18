# Aurora Booking

Микросервис бронирования столов в ресторанах на **FastAPI**, **PostgreSQL** и **Redis**.  
Входит в экосистему Aurora — взаимодействует с API-шлюзом (`api_gateway`) для получения данных о залах и столах, а также хранит собственную историю броней с защитой от наложений временных интервалов.

## 🛠 Стек технологий

| Компонент | Технология | Назначение |
|-----------|-----------|------------|
| FastAPI 0.163 | Веб-API, валидация, авто-документация |
| PostgreSQL 13 | Хранение броней и outbox-событий |
| SQLAlchemy 2.1 (async) | Работа с БД, raw SQL |
| Alembic 1.20 | Миграции БД |
| Redis 6 | Кеширование списка броней |
| httpx 0.28 | Асинхронные запросы к api_gateway |
| Pydantic 2.14 | Настройки, валидация |
| Uvicorn 0.54 | ASGI-сервер |
| Docker + Docker Compose | Сборка и оркестровка |

## 🏗 Архитектура

```
Клиент ──▶ api_gateway ──▶ Aurora Booking ──▶ PostgreSQL (брони, outbox)
                                    │
                                    ├─▶ Redis (кеш броней)
                                    └─▶ api_gateway (залы и столы)
```

**Паттерны:** Outbox (события в таблицу outbox), Exclusion constraint (`bookings_no_overlap` на уровне БД), Async-first (asyncpg, httpx, SQLAlchemy async session), Разделение ответственности.

## 📡 API Endpoints

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/` | Проверка работоспособности |
| GET | `/health` | Health-check |
| GET | `/bookings` | Список всех броней (с дублированием в Redis) |
| GET | `/availible_restaurants` | Рестораны через api_gateway |
| GET | `/availible_tables_in_restaurant/{restaurant_id}` | Залы и столы через api_gateway |
| POST | `/book_table` | Создание брони с защитой от наложений |
| GET | `/halls_with_tables_with_booking_info` | Залы со столами, обогащённые бронями |

Пример бронирования:
```http
POST /book_table?user_id=1&table_id=3&starts_at=2026-05-20T12:30:00&ends_at=2026-05-20T14:30:00&status=pending
```
При конфликте времени возвращается **409 Conflict**: "Столик уже забронирован на это время".

## 🔧 Что реализовано и какие проблемы решены

### 1. Исправление декоратора без функции (Pylance)
Эндпоинт `/halls_with_tables_with_booking_info` имел декоратор без тела функции — ошибка статического анализатора. Добавлена полноценная асинхронная функция, которая запрашивает залы у `api_gateway`, подгружает брони из PostgreSQL и **обогащает** каждый стол списком связанных броней.

### 2. Защита от некорректных ответов API gateway
Нормализация ответа: поддерживаются и список, и словарь с ключом `halls`/`data`. Проверки `isinstance` исключают `AttributeError: 'str' object has no attribute 'get'`.

### 3. Обработка exclusion constraint через asyncpg
`asyncpg` не предоставляет атрибута `constraint_name`. Имя `bookings_no_overlap` извлекается из текста ошибки через регулярное выражение, что позволяет вернуть **409 Conflict** вместо необработанного **500**.

### 4. Поле `created_at` в raw SQL INSERT
При `text()` ORM-default `default=datetime.now` не подставляется. Добавлено явное поле `created_at` со значением `now()` — устранён `NotNullViolationError`.

### 5. Обработка ошибок на уровне `execute()`, а не только `commit()`
Блок `try/except IntegrityError` расширен на оба `session.execute()` и `session.commit()`, так как нарушение уникальности возникает на этапе выполнения `INSERT`.

## ▶️ Как запустить

### Переменные окружения (`.env`)
```env
DB_USER=user
DB_PASSWORD=password
DB_NAME=booking_db
DB_HOST=127.0.0.1
DB_PORT=5435
```

### Через Docker Compose
```bash
docker compose up --build
```
Сервис доступен на порту `8080` (проброшен на внутренний `8001`).

### Локальный запуск
```bash
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```
Документация: `http://localhost:8001/docs`

## 📊 Схема базы данных

### Таблица `bookings`
| Поле | Тип | Описание |
|------|-----|----------|
| `id` | Integer, PK | ID брони |
| `user_id` | Integer | ID пользователя |
| `table_id` | Integer | ID столика |
| `status` | String | Статус (pending, confirmed, cancelled) |
| `created_at` | DateTime | Время создания |
| `starts_at` | DateTime(tz) | Начало бронирования |
| `ends_at` | DateTime(tz) | Конец бронирования |

**Exclusion constraint:** `bookings_no_overlap` — запрещает пересечение интервалов для одного `table_id`.

### Таблица `outbox`
| Поле | Тип | Описание |
|------|-----|----------|
| `id` | Integer, PK | ID события |
| `event_type` | String | Тип события (например, `booking_created`) |
| `payload` | String | JSON-payload события |
| `created_at` | DateTime | Время создания |
| `posted_at` | DateTime | Время отправки (nullable) |

## 💡 Достоинства проекта

1. **Надёжность на уровне БД** — защита от двойного бронирования через PostgreSQL exclusion constraint, а не только прикладную логику.
2. **Асинхронность end-to-end** — все I/O операции неблокирующие (asyncpg, httpx, SQLAlchemy async).
3. **Готовность к масштабированию** — outbox pattern для событийной интеграции с другими сервисами.
4. **Чистая обработка ошибок** — ошибки БД мапятся в осмысленные HTTP-ответы (409 Conflict вместо 500).
5. **Docker-ready** — полная контейнеризация, фиксированные зависимости, ожидание готовности БД при старте.

## 📜 Лицензия

MIT
