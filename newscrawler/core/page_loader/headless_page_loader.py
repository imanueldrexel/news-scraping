import logging

from bs4 import BeautifulSoup
from selenium.webdriver import Chrome
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.expected_conditions import presence_of_element_located
from selenium.webdriver.support.wait import WebDriverWait
from selenium.common.exceptions import TimeoutException

from newscrawler.core.constants import EXECUTABLE_PATH

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class HeadlessPageLoader:
    def __init__(self, is_headless=True):
        options = Options()
        options.headless = is_headless
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-infobars")

        self.driver = Chrome(options=options,
                             executable_path=EXECUTABLE_PATH)

    def get_soup(self, url_path: str, scroll_to_bottom=True, element_to_wait=None):
        try:
            self.driver.get(url_path)
            if element_to_wait:
                wait = WebDriverWait(self.driver, 15)
                wait.until(
                    presence_of_element_located((By.CSS_SELECTOR, element_to_wait))
                )
                if scroll_to_bottom:
                    self.driver.execute_script(
                        "window.scrollTo(0, document.body.scrollHeight);"
                    )
            page_response = self.driver.page_source
            soup = BeautifulSoup(page_response, "html.parser")
            return soup
        except TimeoutException:
            page_response = self.driver.page_source
            soup = BeautifulSoup(page_response, "html.parser")
            return soup
        except BaseException as e:
            logger.info(f"Failed to fetch {url_path}. Reason: {e}. Returning None")
            return None

    def scroll_n_pages(self, number_of_page_to_scroll: int):
        for x in range(number_of_page_to_scroll):
            self.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            if x % 10:
                logger.info(f"Scrolled to page {x}/{number_of_page_to_scroll}")

        page_response = self.driver.page_source
        soup = BeautifulSoup(page_response, "html.parser")
        return soup

    def close_session(self):
        self.driver.close()
        self.driver.quit()

if __name__ == '__main__':
    x = HeadlessPageLoader()
    soup = x.get_soup("https://m.nomor.net/_kodepos.php?_i=kota-kodepos&daerah=Provinsi&jobs=&urut=&asc=0000111&sby=010000&no1=2&prov=Papua")
    print(soup)
    rows = soup.find_all("tr",{"class":"cstr"})
    for row in rows:
        print(row)