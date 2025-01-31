# -*- coding: utf-8 -*-
# Copyright 2018 Adrien Vergé
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import asyncio
import hashlib
import hmac
import json
import logging
import pickle
import requests

from .redis_store import redis_master, fetch_all

import aiohttp


class Webhook(object):
    object = 'webhook'

    def __init__(self, url, secret, events):
        self.url = url
        self.secret = secret
        self.events = events


def register_webhook(id, url, secret, events):
    webhook = Webhook(url, secret, events)
    redis_master.set(f"{Webhook.object}:{id}", pickle.dumps(webhook))


async def _send_webhook(event, delay: int = 1):
    logger = logging.getLogger('localstripe.webhooks')

    logger.warning(f"Preparing event {event.type}")
    webhook_body = event._export()
    webhook_body['pending_webhooks'] = 0

    payload = json.dumps(webhook_body, indent=2, sort_keys=True)
    payload = payload.encode('utf-8')
    signed_payload = b'%d.%s' % (event.created, payload)

    await asyncio.sleep(delay)

    for webhook in fetch_all(f"{Webhook.object}:*"):
        if webhook.events is not None and event.type not in webhook.events:
            continue

        signature = hmac.new(webhook.secret.encode('utf-8'),
                             signed_payload, hashlib.sha256).hexdigest()
        headers = {
            'Content-Type': 'application/json; charset=utf-8',
            'Stripe-Signature': 't=%d,v1=%s' % (event.created, signature)}
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(webhook.url,
                                        data=payload, headers=headers) as r:
                    if 200 <= r.status < 300:
                        logger.warning(f'webhook "{event.type}" successfully delivered')
                        logger.warning(f'"{event.type}" webhook body: {json.dumps(webhook_body, indent=2, sort_keys=True)}')
                    else:
                        logger.warning(
                            f'webhook "{event.type}" failed with response code {r.status} and body:\n{await r.text()}')
            except aiohttp.client_exceptions.ClientError as e:
                logger.warning('webhook "%s" failed: %s' % (event.type, e))


# TODO - Actually make this synchronous/awaitable
def send_synchronous_webhook(event):
    asyncio.ensure_future(_send_webhook(event, 0))


def schedule_webhook(event):
    asyncio.ensure_future(_send_webhook(event))
