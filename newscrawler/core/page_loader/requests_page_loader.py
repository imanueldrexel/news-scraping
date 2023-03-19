import logging
import requests

from bs4 import BeautifulSoup

from newscrawler.core.constants import REQUEST_MAX_RETRIES
from newscrawler.core.page_loader.page_loader import PageLoader

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class RequestsPageLoader(PageLoader):
    def __init__(self):
        self.max_retries = REQUEST_MAX_RETRIES
        self.headers = {
            "Accept-Encoding": "gzip, deflate, sdch",
            "Accept-Language": "en-US,en;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.87 "
            "Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
        }

    def get_url(self, url_path):
        try:
            response = requests.get(
                url_path, headers=self.headers, timeout=(10, 27), stream=True
            )
            return response
        except requests.exceptions.ReadTimeout or requests.exceptions.ConnectionError:
            for idx in range(self.max_retries):
                logger.info(f"Retry {idx} to connect")
                try:
                    response = requests.get(
                        url_path, headers=self.headers, timeout=(10, 27)
                    )
                    return response
                except requests.exceptions.ReadTimeout or requests.exceptions.ConnectionError:
                    continue
            return None
        except BaseException as e:
            logger.info(f"Failed to get {url_path}. Reason {e}, Returning None")
            return None

    def get_soup(self, url_path: str):
        response = self.get_url(url_path)
        if response and response.status_code == 200:
            try:
                soup = BeautifulSoup(response.content, "html.parser")
                return soup
            except BaseException as e:
                logger.info(
                    f"Failed to get the HTML for {url_path}. Reason: {e}, Returning None"
                )
                return None
        elif response:
            logger.info(
                f"Failed to get {url_path}. Status Code: {response.status_code}, Returning None"
            )
            return None



if __name__ == '__main__':
    import pandas as pd
    x = RequestsPageLoader()
    level_1_data = []
    level_2_data = []
    level_3_data = []
    level_4_data = []
    postal_code = []
    soup = x.get_soup("https://kodepos.id/")
    h3_headers = soup.find_all(["td"])
    for h3_header in h3_headers:
        province = f"{h3_header.find('a')['href']}"
        province_soup = x.get_soup(province)
        last_page_element = province_soup.find('div',{'class':'pagination'})
        last_page = last_page_element.find_all('a')
        if last_page:
            last_page = last_page[-2]['href']
            last_page = int(last_page.replace("?page=",''))
        else:
            last_page = 1
        for n in range(1, last_page+1):
            province = f"{h3_header.find('a')['href']}?page={n}"
            province_soup = x.get_soup(province)
            table = province_soup.find("tbody")
            if table:
                rows = table.find_all("tr")
                for row in rows:
                    data = [x.text for x in row.find_all('td')]
                    data = [x for x in data if len(x)>0]
                    if len(data) == 5:
                        print(data)
                        level_1_data.append(data[0])
                        level_2_data.append(data[1])
                        level_3_data.append(data[2])
                        level_4_data.append(data[3])
                        postal_code.append(data[4])
        #     break
        # break
    df = pd.DataFrame({"level_1_data":level_1_data,
                       "level_2_data":level_2_data,
                       "level_3_data":level_3_data,
                       "level_4_data":level_4_data,
                       "postal_code":postal_code})
    df.to_csv("C:/Users/bdrex/Documents/provinsi.csv")