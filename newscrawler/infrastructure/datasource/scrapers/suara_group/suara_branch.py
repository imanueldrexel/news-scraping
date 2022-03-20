
class SuaraNetwork:
    def __init__(self):
        self.SuaraJakarta = "https://jakarta.suara.com/static/news/jakarta-sitemap.xml"
        self.SuaraBogor = "https://bogor.suara.com/static/news/bogor-sitemap.xml"
        self.SuaraBekaci = "https://bekaci.suara.com/static/news/bekaci-sitemap.xml"
        self.SuaraJabar = "https://jabar.suara.com/static/news/jabar-sitemap.xml"
        self.SuaraJogja = "https://jogja.suara.com/static/news/jogja-sitemap.xml"
        self.SuaraJateng = "https://jateng.suara.com/static/news/jateng-sitemap.xml"
        self.SuaraMalang = "https://malang.suara.com/static/news/malang-sitemap.xml"
        self.SuaraJatim = "https://jatim.suara.com/static/news/jatim-sitemap.xml"
        self.SuaraBali = "https://bali.suara.com/static/news/bali-sitemap.xml"
        self.SuaraLampung = "https://lampung.suara.com/static/news/lampung-sitemap.xml"
        self.SuaraBanten = "https://banten.suara.com/static/news/banten-sitemap.xml"
        self.SuaraSurakarta = "https://surakarta.suara.com/static/news/surakarta-sitemap.xml"
        self.SuaraKaltim = "https://kaltim.suara.com/static/news/kaltim-sitemap.xml"
        self.SuaraKalbar = "https://kalbar.suara.com/static/news/kalbar-sitemap.xml"
        self.SuaraSulsel = "https://sulsel.suara.com/static/news/sulsel-sitemap.xml"
        self.SuaraSumut = "https://sumut.suara.com/static/news/sumut-sitemap.xml"
        self.SuaraSumbar = "https://sumbar.suara.com/static/news/sumbar-sitemap.xml"
        self.SuaraSumsel = "https://sumsel.suara.com/static/news/sumsel-sitemap.xml"
        self.SuaraBatam = "https://batam.suara.com/static/news/batam-sitemap.xml"
        self.SuaraRiau = "https://riau.suara.com/static/news/riau-sitemap.xml"

    @staticmethod
    def get_all_url():
        tmp = {}
        for site in dir(SuaraNetwork()):
            if "__" not in site and isinstance(SuaraNetwork().__getattribute__(site), str):
                tmp[site] = SuaraNetwork().__getattribute__(site)

        return tmp