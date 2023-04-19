CREATE EXTENSION pg_trgm;

CREATE TABLE public.sitemaps (
    sitemap_id      bigserial       NOT NULL,
    headline        text            NOT NULL,
    link            text            NOT NULL,
    sources         varchar(50)     NULL,
    category        varchar(100)    NULL,
    posted_at       timestamp       NOT NULL,
    keywords        jsonb           NULL,
    CONSTRAINT sitemap_pk PRIMARY KEY (sitemap_id)
);


CREATE TABLE public.articles (
    articles_id             bigserial       NOT NULL,
    sitemap_id              int8            NOT NULL,
    extracted_text          text            NOT NULL,
    meta_data               jsonb           NULL,
    writer                  jsonb           NULL
);