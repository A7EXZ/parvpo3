import json
import os
import sqlite3
import time

import pika
from pika.exceptions import AMQPConnectionError

RABBITMQ_HOST = "rabbitmq"
QUEUE_NAME = "orders"
DATABASE = r"C:\Users\rogoz\PycharmProjects\TimaHelp\bookstore.db"

DATABASE_PATH = os.getenv("DATABASE_PATH", "book_store.db")


def on_message_callback(ch, method, properties, body):
    data = json.loads(body)

    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
                        INSERT INTO orders (name, address, book_title, status)
                        VALUES (?, ?, ?, ?)""",
                       (data.get("name"), data.get("address"), data.get("book_title"), "received"))
        conn.commit()
    ch.basic_ack(delivery_tag=method.delivery_tag)


def send_to_queue(queue_name, message):
    connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
    channel = connection.channel()
    channel.queue_declare(queue=queue_name, durable=True)

    connection.close()


def on_message_callback_1(channel, method, properties, body):
    data = json.loads(body)
    with sqlite3.connect(DATABASE_PATH) as conn:
        cursor = conn.cursor()
        s = cursor.execute(
            f"SELECT id, name, address, book_title, status FROM orders WHERE id = {data['order_id']}").fetchall()
        if s:
            mess = {
                'message': 'ok',
                "name": s[0][1],
                "address": s[0][2],
                "book_title": s[0][3],
                "status": s[0][4],
            }
        else:
            mess = {
                'message': 'not found'
            }
        conn.commit()

    channel.basic_publish(
        exchange='',
        body=json.dumps(mess).encode('utf-8'),
        routing_key=properties.reply_to,
    )
    channel.basic_ack(delivery_tag=method.delivery_tag)


def main():
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBITMQ_HOST))
        # connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    except AMQPConnectionError:
        time.sleep(3)
        return main()

    channel = connection.channel()
    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    channel.queue_declare(queue='order_get', durable=True)

    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=on_message_callback)
    channel.basic_consume(queue='order_get', on_message_callback=on_message_callback_1)
    channel.start_consuming()


if __name__ == "__main__":
    main()
