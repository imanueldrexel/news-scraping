import re
import logging

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def preprocess_text(text):
    text = text.strip()
    text = text.replace("\n", "")
    text = re.sub(r"(\s+)(\1+)", r"\1", text)
    text = text.replace("\xa0", " ")

    return text
