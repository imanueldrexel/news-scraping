from newscrawler.domain.dtos.dataflow.news_information_dto import NewsInformationDTO
from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.infrastructure.datasource.dataflow.model.news_information_model import (
    NewsInformationModel,
)
from newscrawler.infrastructure.datasource.scrapers.antara_news.antara_news_crawler import (
    AntaraNewsCrawler,
)
from newscrawler.infrastructure.datasource.scrapers.batampos.batampos_crawler import (
    BatamposCrawler,
)
from newscrawler.infrastructure.datasource.scrapers.berita_satu.beritasatu_crawler import (
    BeritaSatuCrawler,
)
from newscrawler.infrastructure.datasource.scrapers.bisnis.bisnis_crawler import (
    BisnisCrawler,
)
from newscrawler.infrastructure.datasource.scrapers.cnbc.cnbc_crawler import CNBCCrawler
from newscrawler.infrastructure.datasource.scrapers.cnn.cnn_crawler import CNNCrawler
from newscrawler.domain.repositories.data_flow_repository.data_flow_repository import (
    DataFlowRepository,
)
from newscrawler.domain.services.crawler_service import CrawlerService
from typing import Union

from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler
from newscrawler.infrastructure.datasource.scrapers.grid_id.grid_id_crawler import (
    GridIdCrawler,
)
from newscrawler.infrastructure.datasource.scrapers.idx_channel.idxchannel_crawler import (
    IdxChannelCrawler,
)
from newscrawler.infrastructure.datasource.scrapers.investor_id.investorid_crawler import (
    InvestorIDCrawler,
)
from newscrawler.infrastructure.datasource.scrapers.jpnn.jpnn_crawler import JPNNCrawler
from newscrawler.infrastructure.datasource.scrapers.kapanlagi.kapanlagi_crawler import (
    KapanlagiCrawler,
)
from newscrawler.infrastructure.datasource.scrapers.kompas.kompas_crawler import (
    KompasCrawler,
)
from newscrawler.infrastructure.datasource.scrapers.kontan.kontan_crawler import (
    KontanCrawler,
)
from newscrawler.infrastructure.datasource.scrapers.liputan_enam.liputan_enam_crawler import (
    LiputanEnamCrawler,
)
from newscrawler.infrastructure.datasource.scrapers.media_indonesia.mediaindonesia_crawler import (
    MediaIndonesiaCrawler,
)
from newscrawler.infrastructure.datasource.scrapers.pikiran_rakyat.pikiran_rakyat_crawler import (
    PikiranRakyatCrawler,
)
from newscrawler.infrastructure.datasource.scrapers.sindonews.sindonews_crawler import (
    SindonewsCrawler,
)
from newscrawler.infrastructure.datasource.scrapers.suara_group.suara_crawler import (
    SuaraCrawler,
)
from newscrawler.infrastructure.datasource.scrapers.tempo.tempo_crawler import (
    TempoCrawler,
)
from newscrawler.infrastructure.datasource.scrapers.tirto.tirto_crawler import (
    TirtoCrawler,
)
from newscrawler.infrastructure.datasource.scrapers.tribun.tribun_crawler import (
    TribunCrawler,
)
from newscrawler.infrastructure.datasource.scrapers.viva.viva_crawler import VivaCrawler


class CrawlerServiceImpl(CrawlerService):
    def __init__(
            self,
            data_flow_repo: DataFlowRepository,
    ):
        self.crawler_dict = {
            WebsiteName.SINDONEWS.value: SindonewsCrawler(),
            WebsiteName.PIKIRANRAKYAT.value: PikiranRakyatCrawler(),
            WebsiteName.JPNN.value: JPNNCrawler(),
            WebsiteName.BATAMPOS.value: BatamposCrawler(),
            WebsiteName.CNN.value: CNNCrawler(),
            WebsiteName.CNBC.value: CNBCCrawler(),
            WebsiteName.KOMPAS.value: KompasCrawler(),
            WebsiteName.TRIBUN.value: TribunCrawler(),
            WebsiteName.TEMPO.value: TempoCrawler(),
            WebsiteName.ANTARANEWS.value: AntaraNewsCrawler(),
            WebsiteName.GRIDID.value: GridIdCrawler(),
            WebsiteName.KONTAN.value: KontanCrawler(),
            WebsiteName.BISNIS.value: BisnisCrawler(),
            WebsiteName.KAPANLAGI.value: KapanlagiCrawler(),
            WebsiteName.LIPUTAN6.value: LiputanEnamCrawler(),
            WebsiteName.IDXCHANNEL.value: IdxChannelCrawler(),
            WebsiteName.MEDIAINDONESIA.value: MediaIndonesiaCrawler(),
            WebsiteName.VIVA.value: VivaCrawler(),
            WebsiteName.TIRTO.value: TirtoCrawler(),
            WebsiteName.INVESTORID.value: InvestorIDCrawler(),
            WebsiteName.BERITASATU.value: BeritaSatuCrawler(),
            WebsiteName.SUARA.value: SuaraCrawler(),
        }
        self.web_url_dict = {
            WebsiteName.GRIDID.value: URL.GRIDID,
            WebsiteName.SINDONEWS.value: URL.SINDONEWS,
            WebsiteName.PIKIRANRAKYAT.value: URL.PIKIRANRAKYAT,
            WebsiteName.KOMPAS.value: URL.KOMPAS,
            WebsiteName.TRIBUN.value: URL.TRIBUN,
            WebsiteName.TEMPO.value: URL.TEMPO,
            WebsiteName.LIPUTAN6.value: URL.LIPUTAN6,
            WebsiteName.KAPANLAGI.value: URL.KAPANLAGI,
            WebsiteName.CNBC.value: URL.CNBC,
            WebsiteName.CNN.value: URL.CNN,
            WebsiteName.BATAMPOS.value: URL.BATAMPOS,
            WebsiteName.JPNN.value: URL.JPNN,
            WebsiteName.ANTARANEWS.value: URL.ANTARANEWS,
            WebsiteName.KONTAN.value: URL.KONTAN,
            WebsiteName.BISNIS.value: URL.BISNIS,
            WebsiteName.IDXCHANNEL.value: URL.IDXCHANNEL,
            WebsiteName.MEDIAINDONESIA.value: URL.MEDIAINDONESIA,
            WebsiteName.VIVA.value: URL.VIVA,
            WebsiteName.TIRTO.value: URL.TIRTO,
            WebsiteName.INVESTORID.value: URL.INVESTORID,
            WebsiteName.BERITASATU.value: URL.BERITASATU,
            WebsiteName.SUARA.value: URL.SUARA,
        }
        self.data_flow_repo = data_flow_repo

    def crawl_url(self, website_name: str) -> NewsInformationDTO:
        web_crawler: Crawler = self.crawler_dict.get(website_name)
        last_crawling_time = web_crawler.get_last_crawling_time()
        last_crawling_time, news = web_crawler.get_news_in_bulk(
            last_crawling_time=last_crawling_time,
        )
        news_data = web_crawler.batch_crawling(news)
        web_crawler.set_last_crawling_time(last_crawling_time)
        return news_data

    def save_scraped_data(self, scraped_data) -> Union[None, NewsInformationModel]:
        final_result = None
        if isinstance(scraped_data, NewsInformationDTO):
            final_result = self.data_flow_repo.save_news_data(scraped_data)

        return final_result
