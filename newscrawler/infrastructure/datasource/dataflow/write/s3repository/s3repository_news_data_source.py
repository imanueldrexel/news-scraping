import logging
from typing import List, Dict, Any

import csv
# import boto3
from pathlib import Path

from newscrawler.core.constants import S3_BUCKET, REGION

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class S3RepositoryNewsDataSource:
    def __init__(self):
        self.bucket = S3_BUCKET
        self.region = REGION

    def save(self, key: str, news_source: str, batch_results: List[Dict[str, Any]]):
        if batch_results:
            csv_path = self._list_of_dict_to_csv(
                news_source=news_source, key=key, batch_results=batch_results
            )
            # offers_csv_path = f"{news_source}/{csv_path}"

            # # Upload to s3
            # s3_url = self.upload_document(
            #     data_path=csv_path,
            #     bucket=self.bucket,
            #     region=self.region,
            #     key=offers_csv_path,
            # )

            # remove the saved file
            # os.remove(csv_path)

            # if s3_url:
            #     logger.info(f"Data {key} has been uploaded into {s3_url}")
            # else:
            #     logger.info(f"Data {key} upload failure")
        else:
            logger.info("Empty data found. Cancel saving process")

    @staticmethod
    def _list_of_dict_to_csv(
        news_source: str, key: str, batch_results: List[Dict[str, Any]]
    ):
        csv_path = f"{news_source}_{key}.csv"
        if batch_results:
            with open(csv_path, "w", encoding="utf8", newline="") as output_file:
                fc = csv.DictWriter(output_file, fieldnames=batch_results[0].keys())
                fc.writeheader()
                fc.writerows(batch_results)
                logger.info(f"Saved as {csv_path}")
        return csv_path

    @staticmethod
    def upload_document(data_path, bucket, region, key=None):
        def _get_s3_url(bucket, key, region):
            return "https://{}.s3-{}.amazonaws.com/{}".format(bucket, region, key)

        s3 = boto3.client("s3")
        try:
            if key is None:
                key = Path(data_path).name

            s3.upload_file(Filename=data_path, Bucket=bucket, Key=key)
            s3_url = _get_s3_url(bucket=bucket, region=region, key=key)
            return s3_url
        except Exception as e:
            logging.error(e)
            return None
