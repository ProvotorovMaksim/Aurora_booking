from fastapi import FastAPI, Depends, HTTPException
from settings import settings
from db_provider import database
from redis_provider import redis
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
import json
import httpx
import re
from datetime import datetime

app = FastAPI()

@app.get("/")
async def read_root():
    return {"message": "Hello World"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/bookings")
async def get_bookings(db=Depends(database.get_session), redis=Depends(redis.get_client)):
    async with db as session:
        result = await session.execute(
            text("SELECT * FROM bookings")
        )
        bookings = [dict(row) for row in result.mappings()]
        redis.set("bookings", json.dumps(bookings))
        return {"bookings": bookings}

@app.get("/availible_restaurants")
async def get_availible_restaurants():
    async with httpx.AsyncClient() as client:
        response = await client.get("http://api_gateway:8000/restaurant/restaurants")
    return response.json()

@app.get("/availible_tables_in_restaurant/{restaurant_id}")
async def get_availible_halls_and_tables(restaurant_id: int):
    async with httpx.AsyncClient() as client:
        response = await client.get(f"http://api_gateway:8000/restaurant/restaurants/{restaurant_id}/halls/with_tables")
    return response.json()

@app.post("/book_table")
async def book_table(
    user_id: int,
    table_id: int,
    starts_at: datetime,
    ends_at: datetime,
    status: str = "pending",
    db=Depends(database.get_session),
    redis=Depends(redis.get_client),
):
    async with db as session:
        try:
            await session.execute(
                text(
                    "INSERT INTO bookings (user_id, table_id, starts_at, ends_at, status, created_at) "
                    "VALUES (:user_id, :table_id, :starts_at, :ends_at, :status, now())"
                ),
                {
                    "user_id": user_id,
                    "table_id": table_id,
                    "starts_at": starts_at,
                    "ends_at": ends_at,
                    "status": status,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO outbox (event_type, payload, created_at) "
                    "VALUES (:event_type, :payload, now())"
                ),
                {
                    "event_type": "booking_created",
                    "payload": json.dumps(
                        {
                            "user_id": user_id,
                            "table_id": table_id,
                            "starts_at": starts_at.isoformat(),
                            "ends_at": ends_at.isoformat(),
                            "status": status,
                        }
                    ),
                },
            )
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()

            driver_error = getattr(exc.orig, "__cause__", exc.orig)
            error_msg = str(driver_error)

            # asyncpg не предоставляет constraint_name как атрибут,
            # имя constraint извлекаем из строки ошибки
            constraint = None
            match = re.search(r'constraint "([^"]+)"', error_msg)
            if match:
                constraint = match.group(1)

            if constraint == "bookings_no_overlap":
                raise HTTPException(
                    status_code=409,
                    detail="Столик уже забронирован на это время",
                ) from exc

            raise

    return {
        "message": "Бронь создана успешно",
        "table_id": table_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": status,
    }

@app.get("/halls_with_tables_with_booking_info")
async def get_halls_with_tables_with_booking_info(
    restaurant_id: int,
    db=Depends(database.get_session),
    redis=Depends(redis.get_client),
):
    async with db as session:
        # Получаем залы со столами из сервиса ресторанов
        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://api_gateway:8000/restaurant/restaurants/{restaurant_id}/halls/with_tables")
        halls_data = response.json()

        # Нормализуем список залов (ответ может быть списком или словарем с ключом "halls")
        if isinstance(halls_data, dict):
            halls_list = halls_data.get("halls", halls_data.get("data", []))
        elif isinstance(halls_data, list):
            halls_list = halls_data
        else:
            halls_list = []

        # Получаем все брони из нашей базы
        result = await session.execute(
            text("SELECT id, user_id, table_id, starts_at, ends_at, status FROM bookings")
        )
        bookings = [dict(row) for row in result.mappings()]

        # Строим lookup броней по table_id
        bookings_by_table: dict[int, list[dict]] = {}
        for booking in bookings:
            table_id = booking["table_id"]
            bookings_by_table.setdefault(table_id, []).append(booking)

        # Обогащаем каждый стол информацией о бронях
        enriched_halls = []
        for hall in halls_list:
            if not isinstance(hall, dict):
                continue
            enriched_tables = []
            for table in hall.get("tables", []):
                if not isinstance(table, dict):
                    continue
                table_id = table.get("id")
                table_copy = dict(table)
                table_copy["bookings"] = bookings_by_table.get(table_id, []) # type: ignore
                enriched_tables.append(table_copy)
            enriched_hall = dict(hall)
            enriched_hall["tables"] = enriched_tables
            enriched_halls.append(enriched_hall)

        return {"halls": enriched_halls}