import re
import logging

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def preprocess_text(text):
    text = text.strip()
    text = text.replace("\n", "")
    text = text.replace("\xa0", " ")
    text = re.sub(r" {2,}", " ", text)

    return text
