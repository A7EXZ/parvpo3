import asyncio
import os
from fastapi import FastAPI, HTTPException, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import sqlite3
import aio_pika
import json

app = FastAPI()

# Инициализация шаблонов
templates = Jinja2Templates(directory="templates")

# Подключение к SQLite
DATABASE_PATH = os.getenv("DATABASE_PATH", "book_store.db")


def init_db():
    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            address TEXT NOT NULL,
            book_title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'received'
        )
        """)
        conn.commit()


init_db()


class NewOrder(BaseModel):
    name: str
    address: str
    book_title: str


# RabbitMQ настройки
RABBITMQ_HOST = "rabbitmq"
QUEUE_NAME = "orders"
SEARCH_QUEUE_NAME = "search_orders"
RESULT_QUEUE_NAME = "search_results"
RABBIT_REPLY = "amqp.rabbitmq.reply-to"


async def send_to_queue(queue_name, message):
    connection = await aio_pika.connect_robust(
        host=RABBITMQ_HOST
    )
    async with connection:
        channel = await connection.channel()
        await channel.declare_queue(queue_name, durable=True)
        mes = aio_pika.Message(
            body=json.dumps(message).encode('utf-8'),
            content_type="application/json",
            content_encoding="utf-8",
            delivery_mode=aio_pika.abc.DeliveryMode.PERSISTENT,
        )
        await channel.default_exchange.publish(routing_key=queue_name, message=mes)


@app.get("/", response_class=HTMLResponse)
async def main(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/order", response_class=HTMLResponse)
async def order_form(request: Request):
    books = ["Книга 1", "Книга 2", "Книга 3"]  # Список доступных книг
    return templates.TemplateResponse("order_form.html", {"request": request, "books": books})


@app.post("/order", response_class=HTMLResponse)
async def create_order(request: Request, name: str = Form(...), address: str = Form(...), book_title: str = Form(...)):
    # Формируем данные заказа
    order = {"name": name, "address": address, "book_title": book_title}

    # Отправка заказа в очередь RabbitMQ
    await send_to_queue(QUEUE_NAME, order)

    # asyncio.sleep(0.05)

    # Уведомляем пользователя о принятии заказа
    return templates.TemplateResponse("order_success.html", {"request": request})


@app.get("/orders", response_class=HTMLResponse)
async def list_orders(request: Request):
    # Извлечение всех заказов из базы данных
    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, address, book_title, status FROM orders")
        orders = cursor.fetchall()

    return templates.TemplateResponse("orders.html", {"request": request, "orders": orders})


@app.get("/orders/{order_id}", response_class=HTMLResponse)
async def get_order_by_id(request: Request, order_id: int):
    connection = await aio_pika.connect_robust(
        host=RABBITMQ_HOST
    )
    order_json = json.dumps({"order_id": order_id})
    async with connection:
        channel = await connection.channel()
        await channel.declare_queue(RABBIT_REPLY, durable=True)
        callback_queue = await channel.get_queue(RABBIT_REPLY)
        rq = asyncio.Queue(maxsize=1)

        consumer_tag = await callback_queue.consume(
            callback=rq.put,
            no_ack=True,
        )

        await channel.default_exchange.publish(
            message=aio_pika.Message(
                body=order_json.encode('utf-8'),
                reply_to=RABBIT_REPLY
            ),
            routing_key='order_get'
        )
        response = await rq.get()
        response_json = response.body.decode('utf-8')
        response_data = json.loads(response_json)
        await callback_queue.cancel(consumer_tag)
        await connection.close()
    if response_data['message'] == 'ok':
        return templates.TemplateResponse("order_detail.html",
                                          {"request": request,
                                           "order": list(response_data.values())[1:]})
    else:
        return templates.TemplateResponse("order_not_found.html",
                                          {"request": request})
