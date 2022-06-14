import logging

from newscrawler.application.api.lambda_function import lambda_handler

logger = logging.getLogger(__name__)


def main():
    FAST = [
        "BERITASATU",
        "TIRTO",
        "INVESTORID",
        "MEDIAINDONESIA",
        "IDXCHANNEL",
        "LIPUTAN6",
        "BATAMPOS",
        "JPNN",
        "KAPANLAGI",
        "BISNIS",
    ]
    SLOW = [
        "KONTAN",
        "SINDONEWS",
        "CNN",
        "CNBC",
        "TRIBUN",
        "ANTARANEWS",
        "PIKIRANRAKYAT",
        "VIVA",
        "GRIDID",
    ]
    WEBSITES = FAST + SLOW
    if isinstance(WEBSITES, list):
        WEBSITES = ",".join(WEBSITES)
    elif isinstance(WEBSITES, str):
        WEBSITES = WEBSITES

    lambda_handler.process_event({"website": WEBSITES}, None)


if __name__ == "__main__":
    main()
