class PageLoader:
    def get_soup(self, url):
        raise NotImplementedError

    def get_soup_with_reason(self, url):
        """(soup, None) on success, (None, reason) on failure. OPS-15: the reason
        is what ends up in sitemaps.last_fetch_error, so a loader that can tell a
        404 from a timeout should override this; the default only knows "failed"."""
        soup = self.get_soup(url)
        return (soup, None) if soup else (None, "page loader returned no document")
