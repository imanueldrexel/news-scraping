from selenium.webdriver import Firefox
from selenium.webdriver.firefox.options import Options
from bs4 import BeautifulSoup
import os
import logging

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class HeadlessBrowser:
    def __init__(self):
        self.options = Options()
        self.options.headless = True
        self.driver = Firefox(
            options=self.options, executable_path=os.getenv("geckodriver.exe")
        )

    def get_soup_selenium(self, url: str):
        try:
            self.driver.get(url)
            self.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            page_response = self.driver.page_source
            soup = BeautifulSoup(page_response, "html.parser")
            return soup

        except BaseException as e:
            logger.info(e)
            return None

    def close_session(self):
        self.driver.close()
        self.driver.quit()
