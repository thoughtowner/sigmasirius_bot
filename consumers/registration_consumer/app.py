import logging.config

import aio_pika
import msgpack

from logger import LOGGING_CONFIG, logger, correlation_id_ctx
from storage.rabbit import channel_pool

from ..mappers.user_mapper import from_parsed_registration_data
from config.settings import settings
from src.storage.db import async_session


async def main() -> None:
    logging.config.dictConfig(LOGGING_CONFIG)
    logger.info('Starting registration consumer...')

    queue_name = "registration_queue"

    async with channel_pool.acquire() as channel:  # type: aio_pika.Channel

        await channel.set_qos(prefetch_count=10)

        queue = await channel.declare_queue(queue_name, durable=True)

        async with queue.iterator() as queue_iter:
            async for message in queue_iter: # type: aio_pika.Message
                async with message.process():
                    # correlation_id_ctx.set(message.correlation_id)
                    parsed_registration_data = msgpack.unpackb(message.body)
                    logger.info("Received message %s", parsed_registration_data)
                    user = from_parsed_registration_data(parsed_registration_data)
                    queue_name = settings.REGISTRATION_QUEUE_NAME.format(user_id=parsed_registration_data["user_id"])

                    try:
                        async with async_session() as db:
                            db.add(user)
                            await db.commit()
                            exchange = await channel.get_exchange("registration_exchange")
                            await exchange.publish(aio_pika.Message(msgpack.packb(True)), '')
                    except IntegrityError:
                        logger.info("This user with this data is already registered: %s", parsed_registration_data)
                        await exchange.publish(aio_pika.Message(msgpack.packb(False)), '')