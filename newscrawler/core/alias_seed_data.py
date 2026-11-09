# Seed data for entity_aliases table.
# Each entry: canonical_name, entity_type, subtype, ticker (or None), aliases list.
ENTITY_SEED_DATA = [
    # ── Top IDX Emiten ──────────────────────────────────────────────────────
    {
        "canonical_name": "Bank Central Asia",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "BBCA",
        "aliases": ["BCA", "Bank BCA", "PT BCA", "PT BCA Tbk",
                    "PT Bank Central Asia Tbk", "BBCA"],
    },
    {
        "canonical_name": "Bank Rakyat Indonesia",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "BBRI",
        "aliases": ["BRI", "Bank BRI", "PT BRI", "PT BRI Tbk",
                    "PT Bank Rakyat Indonesia Tbk", "BBRI"],
    },
    {
        "canonical_name": "Bank Mandiri",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "BMRI",
        "aliases": ["Mandiri", "PT Bank Mandiri", "PT Bank Mandiri Tbk", "BMRI"],
    },
    {
        "canonical_name": "Bank Negara Indonesia",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "BBNI",
        "aliases": ["BNI", "Bank BNI", "PT BNI", "PT BNI Tbk",
                    "PT Bank Negara Indonesia Tbk", "BBNI"],
    },
    {
        "canonical_name": "Telkom Indonesia",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "TLKM",
        "aliases": ["Telkom", "PT Telkom", "PT Telekomunikasi Indonesia Tbk",
                    "PT Telkom Indonesia Tbk", "TLKM"],
    },
    {
        "canonical_name": "Astra International",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "ASII",
        "aliases": ["Astra", "PT Astra", "PT Astra International Tbk", "ASII"],
    },
    {
        "canonical_name": "Pertamina",
        "entity_type": "ORGANIZATION", "subtype": "soe", "ticker": None,
        "aliases": ["PT Pertamina", "PT Pertamina Persero", "Pertamina Persero"],
    },
    {
        "canonical_name": "Adaro Energy",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "ADRO",
        "aliases": ["Adaro", "PT Adaro Energy Tbk",
                    "PT Adaro Energy Indonesia Tbk", "ADRO"],
    },
    {
        "canonical_name": "Unilever Indonesia",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "UNVR",
        "aliases": ["Unilever", "PT Unilever Indonesia Tbk", "UNVR"],
    },
    {
        "canonical_name": "Indofood CBP Sukses Makmur",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "ICBP",
        "aliases": ["Indofood CBP", "ICBP", "PT Indofood CBP Sukses Makmur Tbk"],
    },
    {
        "canonical_name": "Indofood Sukses Makmur",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "INDF",
        "aliases": ["Indofood", "INDF", "PT Indofood Sukses Makmur Tbk"],
    },
    {
        "canonical_name": "Gudang Garam",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "GGRM",
        "aliases": ["GGRM", "PT Gudang Garam Tbk"],
    },
    {
        "canonical_name": "Bukalapak",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "BUKA",
        "aliases": ["BUKA", "PT Bukalapak.com Tbk"],
    },
    {
        "canonical_name": "GoTo Gojek Tokopedia",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "GOTO",
        "aliases": ["GoTo", "GOTO", "Gojek", "Tokopedia",
                    "PT GoTo Gojek Tokopedia Tbk"],
    },
    {
        "canonical_name": "Medco Energi Internasional",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "MEDC",
        "aliases": ["Medco", "MEDC", "PT Medco Energi Internasional Tbk"],
    },
    {
        "canonical_name": "Kalbe Farma",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "KLBF",
        "aliases": ["Kalbe", "KLBF", "PT Kalbe Farma Tbk"],
    },
    {
        "canonical_name": "Mitra Adiperkasa",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "MAPI",
        "aliases": ["MAP", "MAPI", "PT Mitra Adiperkasa Tbk"],
    },
    {
        "canonical_name": "Summarecon Agung",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "SMRA",
        "aliases": ["Summarecon", "SMRA", "PT Summarecon Agung Tbk"],
    },
    {
        "canonical_name": "Semen Indonesia",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "SMGR",
        "aliases": ["Semen Indonesia", "SMGR", "PT Semen Indonesia Tbk",
                    "Semen Gresik"],
    },
    {
        "canonical_name": "Aneka Tambang",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "ANTM",
        "aliases": ["Antam", "ANTM", "PT Aneka Tambang Tbk"],
    },
    {
        "canonical_name": "Vale Indonesia",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "INCO",
        "aliases": ["Vale", "INCO", "PT Vale Indonesia Tbk"],
    },
    {
        "canonical_name": "Bukit Asam",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "PTBA",
        "aliases": ["Bukit Asam", "PTBA", "PT Bukit Asam Tbk"],
    },
    {
        "canonical_name": "Bank Tabungan Negara",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "BBTN",
        "aliases": ["BTN", "Bank BTN", "PT Bank Tabungan Negara Tbk", "BBTN"],
    },
    {
        "canonical_name": "Wijaya Karya",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "WIKA",
        "aliases": ["WIKA", "PT Wijaya Karya Tbk", "Wijaya Karya"],
    },
    {
        "canonical_name": "Waskita Karya",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "WSKT",
        "aliases": ["Waskita", "WSKT", "PT Waskita Karya Tbk"],
    },
    {
        "canonical_name": "Jasa Marga",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "JSMR",
        "aliases": ["Jasa Marga", "JSMR", "PT Jasa Marga Tbk"],
    },
    {
        "canonical_name": "Barito Pacific",
        "entity_type": "ORGANIZATION", "subtype": "emiten", "ticker": "BRPT",
        "aliases": ["Barito", "BRPT", "PT Barito Pacific Tbk"],
    },
    # ── Key Institutions ────────────────────────────────────────────────────
    {
        "canonical_name": "Bank Indonesia",
        "entity_type": "ORGANIZATION", "subtype": "central_bank", "ticker": None,
        "aliases": ["BI", "Bank Sentral Indonesia", "Bank Sentral", "Bank Indonesia"],
    },
    {
        "canonical_name": "Otoritas Jasa Keuangan",
        "entity_type": "ORGANIZATION", "subtype": "regulator", "ticker": None,
        "aliases": ["OJK", "Otoritas Jasa Keuangan"],
    },
    {
        "canonical_name": "Bursa Efek Indonesia",
        "entity_type": "ORGANIZATION", "subtype": "exchange", "ticker": None,
        "aliases": ["BEI", "IDX", "Bursa Efek Indonesia", "Bursa Efek"],
    },
    {
        "canonical_name": "Kementerian Keuangan",
        "entity_type": "ORGANIZATION", "subtype": "ministry", "ticker": None,
        "aliases": ["Kemenkeu", "Kementerian Keuangan RI", "Menkeu",
                    "Kementerian Keuangan"],
    },
    {
        "canonical_name": "Kementerian BUMN",
        "entity_type": "ORGANIZATION", "subtype": "ministry", "ticker": None,
        "aliases": ["Kemen BUMN", "Kementerian BUMN", "Menteri BUMN"],
    },
    {
        "canonical_name": "Badan Pusat Statistik",
        "entity_type": "ORGANIZATION", "subtype": "government", "ticker": None,
        "aliases": ["BPS", "Badan Pusat Statistik"],
    },
    {
        "canonical_name": "Lembaga Penjamin Simpanan",
        "entity_type": "ORGANIZATION", "subtype": "regulator", "ticker": None,
        "aliases": ["LPS", "Lembaga Penjamin Simpanan"],
    },
    {
        "canonical_name": "Perusahaan Listrik Negara",
        "entity_type": "ORGANIZATION", "subtype": "soe", "ticker": None,
        "aliases": ["PLN", "PT PLN", "PT PLN Persero",
                    "Perusahaan Listrik Negara"],
    },
    {
        "canonical_name": "International Monetary Fund",
        "entity_type": "ORGANIZATION", "subtype": "international", "ticker": None,
        "aliases": ["IMF", "Dana Moneter Internasional"],
    },
    {
        "canonical_name": "World Bank",
        "entity_type": "ORGANIZATION", "subtype": "international", "ticker": None,
        "aliases": ["Bank Dunia", "World Bank"],
    },
]
