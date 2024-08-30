import logging

from newscrawler.application.api.lambda_function import (
    lambda_handler,
    full_text_scraper_lambda_handler,
)

logger = logging.getLogger(__name__)


def main():
    SLOW = [
        "KONTAN",
        "SINDONEWS",
        "CNN",
        "CNBC",
        "TRIBUN",
        "ANTARANEWS",
        "JPNN",
        "PIKIRANRAKYAT",
        "VIVA",
        "GRIDID",
        "IDXCHANNEL",
        "KOMPAS",
        "KUMPARAN",
        "TIRTO",
        "INVESTORID",
        "MEDIAINDONESIA",
        "LIPUTAN6",
        "KAPANLAGI",
        "BATAMPOS",
        "BISNIS",
        "TEMPO",
        "SUARA",
        "BERITASATU",
        "DETIK",
        "MERDEKA",
        "ERAID",
        "OKEZONE",
        "INEWS",
        "WARTAEKONOMI",
        "TVONENEWS",
        "IDNTIMES",
        "EMITENNEWS",
    ]
    WEBSITES = SLOW

    if isinstance(WEBSITES, list):
        WEBSITES = ",".join(WEBSITES)
    elif isinstance(WEBSITES, str):
        WEBSITES = WEBSITES

    lambda_handler.process_event({"website": WEBSITES}, None)
    # full_text_scraper_lambda_handler.process_event({"website":WEBSITES}, None)


if __name__ == "__main__":
    main()
