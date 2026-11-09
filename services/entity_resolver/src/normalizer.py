"""Indonesian entity name normalizer."""

import re
from typing import Tuple, Dict, List


class IndonesianNameNormalizer:
    """Normalize Indonesian entity names."""

    # Titles to remove for PERSON entities
    TITLES = [
        "Bapak", "Ibu", "Pak", "Bu", "Dr.", "Prof.", "Ir.", "Drs.", "Drg.",
        "H.", "Hj.", "KH.", "S.H.", "S.E.", "S.T.", "M.M.", "M.B.A.",
        "Ph.D.", "M.Sc.", "S.Pd.", "M.Pd.", "S.Sos.", "M.Si.", "MBA",
    ]

    # Company prefixes to normalize
    COMPANY_PREFIXES = ["PT.", "PT", "CV.", "CV", "Tbk", "Tbk.", "TBK"]

    # Known Indonesian aliases mapping
    KNOWN_ALIASES: Dict[str, str] = {
        "jokowi": "Joko Widodo",
        "joko widodo": "Joko Widodo",
        "presiden jokowi": "Joko Widodo",
        "pak jokowi": "Joko Widodo",
        "gibran": "Gibran Rakabuming Raka",
        "prabowo": "Prabowo Subianto",
        "prabowo subianto": "Prabowo Subianto",
        "sri mulyani": "Sri Mulyani Indrawati",
        "bu sri mulyani": "Sri Mulyani Indrawati",
        "menkeu": "Kementerian Keuangan",
        "kemenkeu": "Kementerian Keuangan",
        "bi": "Bank Indonesia",
        "bank indonesia": "Bank Indonesia",
        "ojk": "Otoritas Jasa Keuangan",
        "bei": "Bursa Efek Indonesia",
        "idx": "Bursa Efek Indonesia",
        "ihsg": "Indeks Harga Saham Gabungan",
        "bumn": "Badan Usaha Milik Negara",
        "pertamina": "PT Pertamina",
        "pln": "PT PLN",
        "telkom": "PT Telkom Indonesia",
        "telkomsel": "PT Telkomsel",
        "bca": "PT Bank Central Asia Tbk",
        "bri": "PT Bank Rakyat Indonesia Tbk",
        "bni": "PT Bank Negara Indonesia Tbk",
        "mandiri": "PT Bank Mandiri Tbk",
        "goto": "PT GoTo Gojek Tokopedia Tbk",
        "gojek": "PT GoTo Gojek Tokopedia Tbk",
        "tokopedia": "PT GoTo Gojek Tokopedia Tbk",
    }

    def __init__(self):
        # Compile regex for title removal
        title_pattern = "|".join(re.escape(t) for t in self.TITLES)
        self.title_regex = re.compile(
            rf"^({title_pattern})\s*", re.IGNORECASE
        )

    def normalize(self, name: str, entity_type: str) -> Tuple[str, str]:
        """
        Normalize an entity name.

        Args:
            name: Original entity name
            entity_type: Type of entity (PERSON, COMPANY, etc.)

        Returns:
            Tuple of (canonical_name, original_name)
        """
        original = name.strip()
        normalized = original

        # Check known aliases first
        lookup = normalized.lower().strip()
        if lookup in self.KNOWN_ALIASES:
            return self.KNOWN_ALIASES[lookup], original

        # Type-specific normalization
        if entity_type == "PERSON":
            normalized = self._normalize_person(normalized)
        elif entity_type == "COMPANY":
            normalized = self._normalize_company(normalized)
        elif entity_type in ["GOVERNMENT", "ORGANIZATION"]:
            normalized = self._normalize_organization(normalized)

        # General cleanup
        normalized = self._general_cleanup(normalized)

        return normalized, original

    def _normalize_person(self, name: str) -> str:
        """Normalize person names."""
        # Remove titles
        name = self.title_regex.sub("", name)

        # Remove trailing credentials
        name = re.sub(r",\s*\w+\.?\s*$", "", name)

        return name.strip()

    def _normalize_company(self, name: str) -> str:
        """Normalize company names."""
        # Standardize PT prefix
        for prefix in self.COMPANY_PREFIXES:
            if name.upper().startswith(prefix.upper()):
                name = "PT " + name[len(prefix):].strip()
                break

        # Remove Tbk suffix for consistency, add back standardized
        if "tbk" in name.lower():
            name = re.sub(r"\s*tbk\.?\s*$", "", name, flags=re.IGNORECASE)
            if not name.endswith("Tbk"):
                name = name + " Tbk"

        return name.strip()

    def _normalize_organization(self, name: str) -> str:
        """Normalize organization names."""
        # Standard abbreviations
        abbreviations = {
            "kementerian": "Kementerian",
            "badan": "Badan",
            "lembaga": "Lembaga",
            "dewan": "Dewan",
        }

        for abbr, full in abbreviations.items():
            if name.lower().startswith(abbr):
                name = full + name[len(abbr):]

        return name.strip()

    def _general_cleanup(self, name: str) -> str:
        """General cleanup for all entity types."""
        # Remove extra whitespace
        name = re.sub(r"\s+", " ", name)

        # Remove quotes
        name = name.replace('"', "").replace("'", "")

        # Title case if all uppercase or lowercase
        if name.isupper() or name.islower():
            name = name.title()

        return name.strip()

    def get_aliases(self, canonical: str) -> List[str]:
        """Get known aliases for a canonical name."""
        aliases = []
        canonical_lower = canonical.lower()

        for alias, target in self.KNOWN_ALIASES.items():
            if target.lower() == canonical_lower and alias != canonical_lower:
                aliases.append(alias.title())

        return aliases
