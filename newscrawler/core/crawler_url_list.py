from newscrawler.domain.entities.extraction.url_data import URL
from newscrawler.domain.entities.extraction.website_name import WebsiteName

WEB_URL_DICT = {
            WebsiteName.GRIDID.value: URL.GRIDID.value,
            WebsiteName.SINDONEWS.value: URL.SINDONEWS.value,
            WebsiteName.PIKIRANRAKYAT.value: URL.PIKIRANRAKYAT.value,
            WebsiteName.KOMPAS.value: URL.KOMPAS.value,
            WebsiteName.TRIBUN.value: URL.TRIBUN.value,
            WebsiteName.TEMPO.value: URL.TEMPO.value,
            WebsiteName.LIPUTAN6.value: URL.LIPUTAN6.value,
            WebsiteName.KAPANLAGI.value: URL.KAPANLAGI.value,
            WebsiteName.CNBC.value: URL.CNBC.value,
            WebsiteName.CNN.value: URL.CNN.value,
            WebsiteName.BATAMPOS.value: URL.BATAMPOS.value,
            WebsiteName.JPNN.value: URL.JPNN.value,
            WebsiteName.ANTARANEWS.value: URL.ANTARANEWS.value,
            WebsiteName.KONTAN.value: URL.KONTAN.value,
            WebsiteName.BISNIS.value: URL.BISNIS.value,
            WebsiteName.IDXCHANNEL.value: URL.IDXCHANNEL.value,
            WebsiteName.MEDIAINDONESIA.value: URL.MEDIAINDONESIA.value,
            WebsiteName.VIVA.value: URL.VIVA.value,
            WebsiteName.TIRTO.value: URL.TIRTO.value,
            WebsiteName.INVESTORID.value: URL.INVESTORID.value,
            WebsiteName.BERITASATU.value: URL.BERITASATU.value,
            WebsiteName.SUARA.value: URL.SUARA.value,
            WebsiteName.KUMPARAN.value: URL.KUMPARAN.value
        }