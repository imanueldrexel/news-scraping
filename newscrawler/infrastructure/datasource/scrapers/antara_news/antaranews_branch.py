class AntaraNewsNetwork:
    def __init__(self):
        self.Politik = "https://www.antaranews.com/rss/politik.xml"
        self.Hukum = "https://www.antaranews.com/rss/hukum.xml"
        self.Ekonomi = "https://www.antaranews.com/rss/ekonomi.xml"
        self.Finansial = "https://www.antaranews.com/rss/ekonomi-finansial.xml"
        self.Bisnis = "https://www.antaranews.com/rss/ekonomi-bisnis.xml"
        self.Bursa = "https://www.antaranews.com/rss/ekonomi-bursa.xml"
        self.BUMNUntukNegeri = (
            "https://www.antaranews.com/rss/ekonomi-bumn-untuk-negeri.xml"
        )
        self.Metro = "https://www.antaranews.com/rss/metro.xml"
        self.Kriminalitas = "https://www.antaranews.com/rss/metro-kriminalitas.xml"
        self.LintasKota = "https://www.antaranews.com/rss/metro-lintas-kota.xml"
        self.LenggangJakarta = (
            "https://www.antaranews.com/rss/metro-lenggang-jakarta.xml"
        )
        self.Sepakbola = "https://www.antaranews.com/rss/sepakbola.xml"
        self.SepakbolaIndonesia = (
            "https://www.antaranews.com/rss/sepakbola-liga-indonesia.xml"
        )
        self.SepakbolaInternasional = (
            "https://www.antaranews.com/rss/sepakbola-internasional.xml"
        )
        self.SepakbolaLigaInggris = (
            "https://www.antaranews.com/rss/sepakbola-liga-inggris-premier.xml"
        )
        self.SepakbolaLigaSpanyol = (
            "https://www.antaranews.com/rss/sepakbola-liga-spanyol.xml"
        )
        self.SepakbolaLigaChampions = (
            "https://www.antaranews.com/rss/sepakbola-liga-champions.xml"
        )
        self.SepakbolaLigaItalia = (
            "https://www.antaranews.com/rss/sepakbola-liga-italia-seri-a.xml"
        )
        self.SepakbolaLigaJerman = (
            "https://www.antaranews.com/rss/sepakbola-liga-jerman.xml"
        )
        self.SepakbolaLigaPrancis = (
            "https://www.antaranews.com/rss/sepakbola-liga-prancis.xml"
        )
        self.SepakbolaLigaLigaLain = (
            "https://www.antaranews.com/rss/sepakbola-liga-liga-dunia.xml"
        )
        self.SepakbolaBintang = "https://www.antaranews.com/rss/sepakbola-bintang.xml"
        self.Olahraga = "https://www.antaranews.com/rss/olahraga.xml"
        self.OlahragaBulutangkis = (
            "https://www.antaranews.com/rss/olahraga-bulutangkis.xml"
        )
        self.OlahragaBolaBasket = (
            "https://www.antaranews.com/rss/olahraga-bola-basket.xml"
        )
        self.OlahragaTenis = "https://www.antaranews.com/rss/olahraga-tenis.xml"
        self.OlahragaBalap = "https://www.antaranews.com/rss/olahraga-balap.xml"
        self.OlahragaESport = "https://www.antaranews.com/rss/olahraga-e-sport.xml"
        self.OlahragaAllSport = "https://www.antaranews.com/rss/olahraga-all-sport.xml"
        self.OlahragaSportainment = (
            "https://www.antaranews.com/rss/olahraga-sportainment.xml"
        )
        self.Humaniora = "https://www.antaranews.com/rss/humaniora.xml"
        self.Lifestyle = "https://www.antaranews.com/rss/lifestyle.xml"
        self.LifestyleKuliner = "https://www.antaranews.com/rss/lifestyle-kuliner.xml"
        self.LifestyleTravel = "https://www.antaranews.com/rss/lifestyle-travel.xml"
        self.LifestyleFashion = "https://www.antaranews.com/rss/lifestyle-fashion.xml"
        self.LifestyleBugar = "https://www.antaranews.com/rss/lifestyle-bugar.xml"
        self.LifestyleBeauty = "https://www.antaranews.com/rss/lifestyle-beauty.xml"
        self.LifestyleReview = "https://www.antaranews.com/rss/lifestyle-review.xml"
        self.Hiburan = "https://www.antaranews.com/rss/hiburan.xml"
        self.HiburanSinema = "https://www.antaranews.com/rss/hiburan-sinema.xml"
        self.HiburanMusik = "https://www.antaranews.com/rss/hiburan-musik.xml"
        self.HiburanPentas = "https://www.antaranews.com/rss/hiburan-pentas.xml"
        self.HiburanAntaraKustik = (
            "https://www.antaranews.com/rss/hiburan-antarakustik.xml"
        )
        self.Dunia = "https://www.antaranews.com/rss/dunia.xml"
        self.DuniaAsean = "https://www.antaranews.com/rss/dunia-asean.xml"
        self.DuniaInternasional = (
            "https://www.antaranews.com/rss/dunia-internasional.xml"
        )
        self.DuniaInternasionalCorner = (
            "https://www.antaranews.com/rss/dunia-internasional-corner.xml"
        )
        self.Tekno = "https://www.antaranews.com/rss/tekno.xml"
        self.TeknoGadget = "https://www.antaranews.com/rss/tekno-gadget.xml"
        self.TeknoGame = "https://www.antaranews.com/rss/tekno-game.xml"
        self.TeknoAplikasi = "https://www.antaranews.com/rss/tekno-aplikasi.xml"
        self.TeknoUmum = "https://www.antaranews.com/rss/tekno-umum.xml"
        self.TeknoReview = "https://www.antaranews.com/rss/tekno-review.xml"
        self.Otomotif = "https://www.antaranews.com/rss/otomotif.xml"
        self.OtomotifUmum = "https://www.antaranews.com/rss/otomotif-umum.xml"
        self.OtomotifGoGreen = "https://www.antaranews.com/rss/otomotif-go-green.xml"
        self.OtomotifPrototype = "https://www.antaranews.com/rss/otomotif-prototype.xml"
        self.OtomotifReview = "https://www.antaranews.com/rss/otomotif-review.xml"
        self.WartaBumi = "https://www.antaranews.com/rss/warta-bumi.xml"
        self.RilisPers = "https://www.antaranews.com/rss/rilis-pers.xml"

    @staticmethod
    def get_all_url():
        tmp = {}
        for site in dir(AntaraNewsNetwork()):
            if "__" not in site and isinstance(
                AntaraNewsNetwork().__getattribute__(site), str
            ):
                tmp[site] = AntaraNewsNetwork().__getattribute__(site)
        return tmp
