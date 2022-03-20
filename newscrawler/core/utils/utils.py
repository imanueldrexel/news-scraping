import pickle
import os
import re
from typing import Union, Dict
import logging
from datetime import date

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def get_last_crawling_time(dir_path: str, website_name: str) -> Union[Dict[str, date], None]:
    try:
        pickle_name = f'{website_name.lower()}.pkl'
        pickle_path = os.path.join(dir_path, pickle_name)
        file = open(pickle_path, "rb")
        last_crawling_time = pickle.load(file)
        return last_crawling_time
    except IOError:
        return {}


def set_last_crawling_time(last_crawling_time: Union[Dict[str, str], None], dir_path: str, website_name: str) -> None:
    try:
        pickle_name = f'{website_name.lower()}.pkl'
        pickle_path = os.path.join(dir_path, pickle_name)
        file = open(pickle_path, "wb")
        pickle.dump(last_crawling_time, file)
        logger.info(f"Successfully save the data into {pickle_path}")
    except BaseException as e:
        logger.error(f"Fail to save the data to dump file.\n Reason: {e}")


def preprocess_text(text):
    text = text.strip()
    text = text.replace('\n', '')
    text = re.sub(r'(\s+)(\1+)', r'\1', text)
    text = text.replace(u"\xa0", " ")

    return text
