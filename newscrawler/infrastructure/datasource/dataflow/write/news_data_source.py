import datetime
import re
import logging
from typing import List

from newscrawler.infrastructure.datasource.dataflow.model.news_data_model import (
    NewsDataModel,
)
from newscrawler.infrastructure.datasource.dataflow.write.s3repository.s3repository_news_data_source import (
    S3RepositoryNewsDataSource,
)

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class NewsDataSource:
    def __init__(self):
        self.s3_repository = S3RepositoryNewsDataSource()

    def save(self, merchants: List[NewsDataModel]):
        source = merchants[0].sources
        logger.info("Saving to S3...")
        date_now = str(datetime.datetime.utcnow()).split(".")[0]
        date_now = re.sub(r"([\s:,-])", r"_", date_now)
        key_name = f"{date_now}"
        merchants_dict = []
        for merchant in merchants:
            merchants_dict.append(merchant.to_dict())
        self.s3_repository.save(
            key=key_name, batch_results=merchants_dict, news_source=source
        )
