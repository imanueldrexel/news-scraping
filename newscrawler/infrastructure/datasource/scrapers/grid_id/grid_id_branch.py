class GridIdNetwork:
    def __init__(self):
        self.Bobo = "https://bobo.grid.id/sitemap/news/sitemap.xml"
        self.CewekBanget = "https://cewekbanget.grid.id/sitemap/news/sitemap.xml"
        self.Fotokita = "https://fotokita.grid.id/sitemap/news/sitemap.xml"
        self.GridFame = "https://fame.grid.id/sitemap/news/sitemap.xml"
        self.GridGames = "https://games.grid.id/sitemap/news/sitemap.xml"
        self.GridHealth = "https://health.grid.id/sitemap/news/sitemap.xml"
        self.GridHot = "https://hot.grid.id/sitemap/news/sitemap.xml"
        self.GridPop = "https://pop.grid.id/sitemap/news/sitemap.xml"
        self.GridStar = "https://star.grid.id/sitemap/news/sitemap.xml"
        self.GridID = "https://www.grid.id/sitemap/news/sitemap.xml"
        self.Hai = "https://hai.grid.id/sitemap/news/sitemap.xml"
        self.HIts = "https://hits.grid.id/sitemap/news/sitemap.xml"
        self.Hype = "https://hype.grid.id/sitemap/news/sitemap.xml"
        self.iDEA = "https://idea.grid.id/sitemap/news/sitemap.xml"
        self.InfoKomputer = "https://infokomputer.grid.id/sitemap/news/sitemap.xml"
        self.Intisari = "https://intisari.grid.id/sitemap/news/sitemap.xml"
        self.Kids = "https://kids.grid.id/sitemap/news/sitemap.xml"
        self.MakeMac = "https://makemac.grid.id/sitemap/news/sitemap.xml"
        self.Nakita = "https://nakita.grid.id/sitemap/news/sitemap.xml"
        self.NationalGeographic = (
            "https://nationalgeographic.grid.id/sitemap/news/sitemap.xml"
        )
        self.Nextren = "https://nextren.grid.id/sitemap/news/sitemap.xml"
        self.Nova = "https://nova.grid.id/sitemap/news/sitemap.xml"
        self.Otofemale = "https://otofemale.grid.id/sitemap/news/sitemap.xml"
        self.Sajian = "https://sajiansedap.grid.id/sitemap/news/sitemap.xml"
        self.Sosok = "https://sosok.grid.id/sitemap/news/sitemap.xml"
        self.Stylo = "https://stylo.grid.id/sitemap/news/sitemap.xml"
        self.Suar = "https://suar.grid.id/sitemap/news/sitemap.xml"
        self.Video = "https://video.grid.id/sitemap/news/sitemap.xml"
        self.Wiken = "https://wiken.grid.id/sitemap/news/sitemap.xml"
        self.BolaSport = "https://www.bolasport.com/sitemap-news.xml"
        self.Juara = "https://juara.bolasport.com/sitemap-news.xml"
        self.Sportfeat = "https://sportfeat.bolasport.com/sitemap/news/sitemap.xml"
        self.SuperBall = "https://superball.bolasport.com/sitemap-news.xml"
        self.BolaStylo = "https://bolastylo.bolasport.com/sitemap/news/sitemap.xml"
        self.Gridoto = "https://www.gridoto.com/sitemap-news.xml"
        self.Otomania = "https://otomania.gridoto.com/sitemap-news.xml"
        self.Otomotifnet = "https://otomotifnet.gridoto.com/sitemap-news.xml"
        self.Otorace = "https://otorace.gridoto.com/sitemap-news.xml"
        self.Otoseken = "https://otoseken.gridoto.com/sitemap-news.xml"
        self.Motorplus = "https://www.motorplus-online.com/sitemap/news/sitemap.xml"
        self.GridMotor = (
            "https://gridmotor.motorplus-online.com/sitemap/news/sitemap.xml"
        )
        self.Bolasport = "https://www.bolasport.com/sitemap-news.xml"
        self.Bolanas = "https://bolanas.bolasport.com/sitemap/news/sitemap.xml"
        self.BolaStylo = "https://bolastylo.bolasport.com/sitemap/news/sitemap.xml"

    @staticmethod
    def get_all_url():
        tmp = {}
        for site in dir(GridIdNetwork()):
            if "__" not in site and isinstance(
                GridIdNetwork().__getattribute__(site), str
            ):
                tmp[site] = GridIdNetwork().__getattribute__(site)

        return tmp
