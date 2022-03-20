from newscrawler.application.api.crawler_api import CrawlerAPI
from newscrawler.core.page_loader.headless_page_loader import HeadlessPageLoader
from newscrawler.infrastructure.datasource.dataflow.write.news_data_source import NewsDataSource
from newscrawler.infrastructure.datasource.scrapers.antara_news.antara_news_crawler import AntaraNewsCrawler
from newscrawler.infrastructure.datasource.scrapers.batampos.batampos_crawler import BatamposCrawler
from newscrawler.infrastructure.datasource.scrapers.bisnis.bisnis_crawler import BisnisCrawler
from newscrawler.infrastructure.datasource.scrapers.cnbc.cnbc_crawler import CNBCCrawler
from newscrawler.infrastructure.datasource.scrapers.cnn.cnn_crawler import CNNCrawler
from newscrawler.infrastructure.datasource.scrapers.grid_id.grid_id_crawler import GridIdCrawler
from newscrawler.infrastructure.datasource.scrapers.idx_channel.idxchannel_crawler import IdxChannelCrawler
from newscrawler.infrastructure.datasource.scrapers.jpnn.jpnn_crawler import JPNNCrawler
from newscrawler.infrastructure.datasource.scrapers.kapanlagi.kapanlagi_crawler import KapanlagiCrawler

from newscrawler.infrastructure.datasource.scrapers.kompas.kompas_crawler import KompasCrawler
from newscrawler.infrastructure.datasource.scrapers.kontan.kontan_crawler import KontanCrawler
from newscrawler.infrastructure.datasource.scrapers.liputan_enam.liputan_enam_crawler import LiputanEnamCrawler
from newscrawler.infrastructure.datasource.scrapers.pikiran_rakyat.pikiran_rakyat_crawler import PikiranRakyatCrawler
from newscrawler.infrastructure.datasource.scrapers.sindonews.sindonews_crawler import SindonewsCrawler
from newscrawler.infrastructure.datasource.scrapers.tempo.tempo_crawler import TempoCrawler
from newscrawler.infrastructure.datasource.scrapers.tribun.tribun_crawler import TribunCrawler
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.domain.services.crawler_service_impl import CrawlerServiceImpl
from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.infrastructure.repositories.dataflow.data_flow_repository_impl import DataFlowRepositoryImpl


def main():
    crawler_api = init_crawler()
    crawler_api.crawl_website_in_batch([
        "GRIDID",
        "KONTAN", # Lambat
        "SINDONEWS",
        "JPNN",
        "BATAMPOS",
        "CNN",
        "CNBC",
        "KOMPAS",
        "TRIBUN",
        # "TEMPO",
        "ANTARANEWS", # Lambat
        "PIKIRANRAKYAT",  # Lambat
        "BISNIS",
        "KAPANLAGI",
        "LIPUTAN6",
        "IDXCHANNEL"
    ])


def init_crawler():
    headless_browser = HeadlessPageLoader()
    website_name = WebsiteName
    crawler_dict = {
        website_name.SINDONEWS.value: SindonewsCrawler(),
        website_name.PIKIRANRAKYAT.value: PikiranRakyatCrawler(),
        website_name.JPNN.value: JPNNCrawler(),
        website_name.BATAMPOS.value: BatamposCrawler(),
        website_name.CNN.value: CNNCrawler(),
        website_name.CNBC.value: CNBCCrawler(),
        website_name.KOMPAS.value: KompasCrawler(),
        website_name.TRIBUN.value: TribunCrawler(),
        website_name.TEMPO.value: TempoCrawler(),
        website_name.ANTARANEWS.value: AntaraNewsCrawler(),
        website_name.GRIDID.value: GridIdCrawler(),
        website_name.KONTAN.value: KontanCrawler(),
        website_name.BISNIS.value: BisnisCrawler(),
        website_name.KAPANLAGI.value: KapanlagiCrawler(headless_browser),
        website_name.LIPUTAN6.value: LiputanEnamCrawler(headless_browser),
        website_name.IDXCHANNEL.value: IdxChannelCrawler()
    }
    web_url = {
        website_name.GRIDID.value: URL.GRIDID,
        website_name.SINDONEWS.value: URL.SINDONEWS,
        website_name.PIKIRANRAKYAT.value: URL.PIKIRANRAKYAT,
        website_name.KOMPAS.value: URL.KOMPAS,
        website_name.TRIBUN.value: URL.TRIBUN,
        website_name.TEMPO.value: URL.TEMPO,
        website_name.LIPUTAN6.value: URL.LIPUTAN6,
        website_name.KAPANLAGI.value: URL.KAPANLAGI,
        website_name.CNBC.value: URL.CNBC,
        website_name.CNN.value: URL.CNN,
        website_name.BATAMPOS.value: URL.BATAMPOS,
        website_name.JPNN.value: URL.JPNN,
        website_name.ANTARANEWS.value: URL.ANTARANEWS,
        website_name.KONTAN.value: URL.KONTAN,
        website_name.BISNIS.value: URL.BISNIS,
        website_name.IDXCHANNEL.value: URL.IDXCHANNEL
    }
    news_data_source = NewsDataSource()
    data_flow_repo = DataFlowRepositoryImpl(
        news_data_source
    )
    crawler_service = CrawlerServiceImpl(web_url_dict=web_url,
                                         crawler_dict=crawler_dict,
                                         data_flow_repo=data_flow_repo)

    return CrawlerAPI(crawler_service)


if __name__ == "__main__":
    main()
