"""Indonesian triplet extraction prompt templates."""

# Valid entity types
ENTITY_TYPES = [
    "PERSON",
    "COMPANY",
    "ORGANIZATION",
    "GOVERNMENT",
    "LOCATION",
    "FINANCIAL_INSTRUMENT",
    "AMOUNT",
    "DATE",
    "EVENT",
]

# Valid relation types
RELATION_TYPES = [
    "WORKS_FOR",
    "APPOINTED_AS",
    "RESIGNED_FROM",
    "LEADS",
    "OWNED_BY",
    "OWNS",
    "INVESTED_IN",
    "RAISED_FUNDING",
    "ACQUIRED",
    "PARTNERED_WITH",
    "COMPETES_WITH",
    "SUPPLIES_TO",
    "LOCATED_IN",
    "HEADQUARTERED_IN",
    "OPERATES_IN",
    "MENTIONED_IN",
    "ANNOUNCED",
    "RELATED_TO",
]

# Main extraction prompt template
TRIPLET_EXTRACTION_PROMPT = """Anda adalah ekstractor informasi untuk berita Indonesia. Tugas Anda adalah mengekstrak triplet (Subjek, Predikat, Objek) dari teks berita.

## Tipe Entitas yang Valid:
- PERSON: Nama orang, individu, pejabat
- COMPANY: Perusahaan, PT, CV, Tbk, bank swasta
- ORGANIZATION: Organisasi non-pemerintah, LSM, asosiasi, serikat
- GOVERNMENT: Lembaga pemerintah, kementerian, BUMN, bank sentral (Bank Indonesia, OJK)
- LOCATION: Lokasi, kota, provinsi, negara
- FINANCIAL_INSTRUMENT: Saham, obligasi, reksa dana, SBN, sukuk
- AMOUNT: Nilai uang, persentase, angka signifikan
- DATE: Tanggal, periode waktu, tahun
- EVENT: Acara, kejadian, IPO, merger

## Tipe Relasi yang Valid:
- WORKS_FOR: Bekerja untuk/di
- APPOINTED_AS: Ditunjuk/diangkat sebagai
- RESIGNED_FROM: Mundur/resign dari
- LEADS: Memimpin
- OWNED_BY: Dimiliki oleh
- OWNS: Memiliki
- INVESTED_IN: Berinvestasi di/menanam modal
- RAISED_FUNDING: Mendapat pendanaan/investasi
- ACQUIRED: Mengakuisisi/membeli
- PARTNERED_WITH: Bermitra/bekerjasama dengan
- COMPETES_WITH: Bersaing dengan
- SUPPLIES_TO: Memasok ke
- LOCATED_IN: Berlokasi di
- HEADQUARTERED_IN: Berkantor pusat di
- OPERATES_IN: Beroperasi di
- ANNOUNCED: Mengumumkan

## Instruksi:
1. Baca teks dengan teliti
2. Identifikasi semua entitas penting (orang, perusahaan, organisasi, dll)
3. Identifikasi hubungan antar entitas
4. Ekstrak triplet dalam format JSON
5. Berikan confidence score (0.0-1.0) berdasarkan keyakinan Anda

## Format Output (JSON):
```json
{{
  "triplets": [
    {{
      "subject": "nama subjek",
      "subject_type": "TIPE_ENTITAS",
      "predicate": "TIPE_RELASI",
      "object": "nama objek",
      "object_type": "TIPE_ENTITAS",
      "confidence": 0.9
    }}
  ]
}}
```

## Contoh:
Teks: "PT Bank Central Asia Tbk (BCA) mengumumkan penunjukan Jahja Setiaatmadja sebagai Presiden Direktur menggantikan posisi yang ditinggalkan oleh Armand W. Hartono."

Output:
```json
{{
  "triplets": [
    {{
      "subject": "PT Bank Central Asia Tbk",
      "subject_type": "COMPANY",
      "predicate": "APPOINTED_AS",
      "object": "Jahja Setiaatmadja",
      "object_type": "PERSON",
      "confidence": 0.95
    }},
    {{
      "subject": "Jahja Setiaatmadja",
      "subject_type": "PERSON",
      "predicate": "WORKS_FOR",
      "object": "PT Bank Central Asia Tbk",
      "object_type": "COMPANY",
      "confidence": 0.95
    }},
    {{
      "subject": "Armand W. Hartono",
      "subject_type": "PERSON",
      "predicate": "RESIGNED_FROM",
      "object": "PT Bank Central Asia Tbk",
      "object_type": "COMPANY",
      "confidence": 0.85
    }}
  ]
}}
```

## Teks untuk diekstrak:
{text}

## Output JSON:"""


# Simplified prompt for shorter texts
TRIPLET_EXTRACTION_PROMPT_SHORT = """Ekstrak triplet (Subjek-Relasi-Objek) dari teks berita Indonesia berikut.

Tipe Entitas: PERSON, COMPANY, ORGANIZATION, GOVERNMENT, LOCATION
Tipe Relasi: WORKS_FOR, OWNS, INVESTED_IN, PARTNERED_WITH, ACQUIRED, APPOINTED_AS, ANNOUNCED

Output format JSON dengan triplets. Contoh:
{{"triplets": [{{"subject": "Gojek", "subject_type": "COMPANY", "predicate": "ACQUIRED", "object": "Tokopedia", "object_type": "COMPANY", "confidence": 0.9}}]}}

Teks: {text}

Output:"""
