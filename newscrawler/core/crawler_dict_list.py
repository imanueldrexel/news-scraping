from newscrawler.domain.entities.extraction.website_name import WebsiteName
from newscrawler.infrastructure.datasource.scrapers.antara_news.antara_news_crawler import AntaraNewsCrawler
from newscrawler.infrastructure.datasource.scrapers.batampos.batampos_crawler import BatamposCrawler
from newscrawler.infrastructure.datasource.scrapers.berita_satu.beritasatu_crawler import BeritaSatuCrawler
from newscrawler.infrastructure.datasource.scrapers.bisnis.bisnis_crawler import BisnisCrawler
from newscrawler.infrastructure.datasource.scrapers.cnbc.cnbc_crawler import CNBCCrawler
from newscrawler.infrastructure.datasource.scrapers.cnn.cnn_crawler import CNNCrawler
from newscrawler.infrastructure.datasource.scrapers.grid_id.grid_id_crawler import GridIdCrawler
from newscrawler.infrastructure.datasource.scrapers.idx_channel.idxchannel_crawler import IdxChannelCrawler
from newscrawler.infrastructure.datasource.scrapers.investor_id.investorid_crawler import InvestorIDCrawler
from newscrawler.infrastructure.datasource.scrapers.jpnn.jpnn_crawler import JPNNCrawler
from newscrawler.infrastructure.datasource.scrapers.kapanlagi.kapanlagi_crawler import KapanlagiCrawler
from newscrawler.infrastructure.datasource.scrapers.kompas.kompas_crawler import KompasCrawler
from newscrawler.infrastructure.datasource.scrapers.kontan.kontan_crawler import KontanCrawler
from newscrawler.infrastructure.datasource.scrapers.kumparan.kumparan_crawler import KumparanCrawler
from newscrawler.infrastructure.datasource.scrapers.liputan_enam.liputan_enam_crawler import LiputanEnamCrawler
from newscrawler.infrastructure.datasource.scrapers.media_indonesia.mediaindonesia_crawler import MediaIndonesiaCrawler
from newscrawler.infrastructure.datasource.scrapers.pikiran_rakyat.pikiran_rakyat_crawler import PikiranRakyatCrawler
from newscrawler.infrastructure.datasource.scrapers.sindonews.sindonews_crawler import SindonewsCrawler
from newscrawler.infrastructure.datasource.scrapers.suara_group.suara_crawler import SuaraCrawler
from newscrawler.infrastructure.datasource.scrapers.tempo.tempo_crawler import TempoCrawler
from newscrawler.infrastructure.datasource.scrapers.tirto.tirto_crawler import TirtoCrawler
from newscrawler.infrastructure.datasource.scrapers.tribun.tribun_crawler import TribunCrawler
from newscrawler.infrastructure.datasource.scrapers.viva.viva_crawler import VivaCrawler

CRAWLER_DICT = {
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
            WebsiteName.KUMPARAN.value: KumparanCrawler()
        }