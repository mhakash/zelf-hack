import logging
import os
from email import header

import requests
from django.core.cache import cache

from contentapi.celery import app

logger = logging.getLogger(__name__)
import redis

from contents.models import Content


@app.task(queue="content_pull")
def pull_and_store_content():
    logger.info("Pulling and storing content")

    url = "https://hackapi.hellozelf.com/api/v1/contents/"
    res = requests.get(url).json()
    print(res)
    # api_url = "http://localhost:3000/contents/"
    # for item in res:
    #     payload = {**item}
    #     requests.post(api_url, json=payload)


@app.task
def generate_comment():
    url = "https://hackapi.hellozelf.com/api/v1/ai_comment/"

    # get last 10 content
    contents = Content.objects.select_related("author").all().order_by("-timestamp")[:10]
    for content in contents:
        value = cache.get(f"comment-{content.id}")
        if value:
            return

        body = {
            "content_id": content.id,
            "title": content.title,
            "url": content.url,
            "author_username": content.author.username,
        }
        headers = {"Content-Type": "application/json", "x-api-key": os.getenv("API_KEY")}
        response = requests.post(url, json=body, headers=headers)

        if response.status_code == 200:
            cache.set(f"comment-{content.id}", response.json(), timeout=60 * 60 * 24)


@app.task
def post_comment():
    url = "https://hackapi.hellozelf.com/api/v1/ai_comment/"
    #  TODO
