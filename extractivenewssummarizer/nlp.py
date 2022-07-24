# -*- coding: utf-8 -*-
"""
Anything natural language related should be abstracted into this file.
"""
__title__ = 'newspaper'
__author__ = 'Lucas Ou-Yang'
__license__ = 'MIT'
__copyright__ = 'Copyright 2014, Lucas Ou-Yang'

import re
import math
from os import path

from collections import Counter

from extractivenewssummarizer.constant import SUMMARY_MAX_SENTENCES
from extractivenewssummarizer import settings

ideal = 20.0

stopwords = set()


def load_stopwords(language):
    """
    Loads language-specific stopwords for keyword selection
    """
    global stopwords

    # stopwords for nlp in English are not the regular stopwords
    # to pass the tests
    # can be changed with the tests
    if language == 'en':
        stopwords_file = settings.NLP_STOPWORDS_EN
    else:
        stopwords_file = path.join(settings.STOPWORDS_DIR,'stopwords-{}.txt'.format(language))
    with open(stopwords_file, 'r', encoding='utf-8') as f:
        stopwords.update(set([w.strip() for w in f.readlines()]))


def summarize(title, text, max_sents=SUMMARY_MAX_SENTENCES):
    if not text or not title or max_sents <= 0:
        return []

    summaries = []
    sentences = split_sentences(text)
    keys = keywords(text)
    title_words = split_words(title)

    # Score sentences, and use the top 5 or max_sents sentences
    ranks = score(sentences=sentences, titleWords=title_words, keywords=keys).most_common(max_sents)
    for rank in ranks:
        summaries.append(rank[0])
    summaries.sort(key=lambda summary: summary[0])
    return [summary[1] for summary in summaries]


def score(sentences, titleWords, keywords):
    """Score sentences based on different features
    """
    senSize = len(sentences)
    ranks = Counter()
    for i, s in enumerate(sentences):
        sentence = split_words(s)
        title_feature = title_score(titleWords, sentence)
        sentence_length = length_score(len(sentence))
        sentence_position = get_sentence_position(i + 1, senSize)
        sbs_feature = sbs(sentence, keywords)
        dbs_feature = dbs(sentence, keywords)
        frequency = (sbs_feature + dbs_feature) / 2.0 * 10.0
        # Weighted average of scores from four categories
        totalScore = (title_feature * 1.5 + frequency * 2.0 +
                      sentence_length * 1.0 + sentence_position * 1.0) / 4.0
        ranks[(i, s)] = totalScore
    return ranks


def sbs(words, keywords):
    score = 0.0
    if len(words) == 0:
        return 0
    for word in words:
        if word in keywords:
            score += keywords[word]
    return (1.0 / math.fabs(len(words)) * score) / 10.0


def dbs(words, keywords):
    if len(words) == 0:
        return 0
    summ = 0
    first = []
    second = []

    for i, word in enumerate(words):
        if word in keywords:
            score = keywords[word]
            if first == []:
                first = [i, score]
            else:
                second = first
                first = [i, score]
                dif = first[0] - second[0]
                summ += (first[1] * second[1]) / (dif ** 2)
    # Number of intersections
    k = len(set(keywords.keys()).intersection(set(words))) + 1
    return (1 / (k * (k + 1.0)) * summ)


def split_words(text):
    """Split a string into array of words
    """
    try:
        text = re.sub(r'[^\w ]', '', text)  # strip special chars
        return [x.strip('.').lower() for x in text.split()]
    except TypeError:
        return None


def keywords(text):
    """Get the top 10 keywords and their frequency scores ignores blacklisted
    words in stopwords, counts the number of occurrences of each word, and
    sorts them in reverse natural order (so descending) by number of
    occurrences.
    """
    NUM_KEYWORDS = 10
    text = split_words(text)
    # of words before removing blacklist words
    if text:
        num_words = len(text)
        text = [x for x in text if x not in stopwords]
        freq = {}
        for word in text:
            if word in freq:
                freq[word] += 1
            else:
                freq[word] = 1

        min_size = min(NUM_KEYWORDS, len(freq))
        keywords = sorted(freq.items(),
                          key=lambda x: (x[1], x[0]),
                          reverse=True)
        keywords = keywords[:min_size]
        keywords = dict((x, y) for x, y in keywords)

        for k in keywords:
            article_score = keywords[k] * 1.0 / max(num_words, 1)
            keywords[k] = article_score * 1.5 + 1
        return dict(keywords)
    else:
        return dict()


def split_sentences(text):
    """Split a large string into sentences
    """
    import nltk.data
    tokenizer = nltk.data.load('tokenizers/punkt/english.pickle')

    sentences = tokenizer.tokenize(text)
    sentences = [x.replace('\n', '') for x in sentences if len(x) > 10]
    return sentences


def length_score(sentence_len):
    return 1 - math.fabs(ideal - sentence_len) / ideal


def title_score(title, sentence):
    if title:
        title = [x for x in title if x not in stopwords]
        count = 0.0
        for word in sentence:
            if word not in stopwords and word in title:
                count += 1.0
        return count / max(len(title), 1)
    else:
        return 0


def get_sentence_position(i, size):
    """Different sentence positions indicate different
    probability of being an important sentence.
    """
    normalized = i * 1.0 / size
    if normalized > 1.0:
        return 0
    elif normalized > 0.9:
        return 0.15
    elif normalized > 0.8:
        return 0.04
    elif normalized > 0.7:
        return 0.04
    elif normalized > 0.6:
        return 0.06
    elif normalized > 0.5:
        return 0.04
    elif normalized > 0.4:
        return 0.05
    elif normalized > 0.3:
        return 0.08
    elif normalized > 0.2:
        return 0.14
    elif normalized > 0.1:
        return 0.23
    elif normalized > 0:
        return 0.17
    else:
        return 0


if __name__ == '__main__':
    title = "Anthony Ginting Target Juara di Malaysia Open: Sudah Lama Enggak Naik Podium"
    text = "Anthony Ginting berhasil meraih kemenangan di partai perdana Malaysia Open 2022, Selasa (27/6). " \
           "Ia pun menargetkan juara di turnamen berlevel BWF Super 750 ini. " \
           "Anthony bersua wakil India, Sai Praneeth, di Axiata Arena, Kuala Lumpur Malaysia. " \
           "Tunggal putra peringkat ke-6 dunia itu menang lewat tiga gim dengan skor 21-15, 19-21, dan 21-9. " \
           "Dengan kemenangan tersebut, Anthony berhak melaju ke babak 16 besar. " \
           "Pria asal Cimahi itu juga berharap bisa sampai ke final dan juara karena sudah lama tidak naik podium." \
           "\"Target pasti mau jadi yang terbaik, sudah lama juga saya tidak naik podium dan juara,\" tutur Anthony usai pertandingan dalam keterangan resmi. " \
           "\"Tapi untuk mencapai ke sana tidak mudah, jadi saya fokus satu pertandingan demi satu pertandingan dulu, anggap setiap laga adalah final,\" tambahnya. " \
           "Anthony Ginting memang sudah lama tak naik podium juara. " \
           "Terakhir kali, ia naik podium adalah di kejuaraan beregu Thomas Cup 2020 pada Oktober 2021. " \
           "Sementara itu, untuk prestasi individu, Anthony kali terakhir menjuarai Indonesia Masters pada Januari 2020. " \
           "Apakah Malaysia Open akan menjadi momen kembalinya Anthony ke atas podium? " \
           "Selanjutnya, Anthony Ginting akan melawan wakil Thailand, Sitthikom Thammasin, di babak 16 besar pada Kamis (30/6). " \
           "Pria 25 tahun tersebut akan memanfaatkan pelajaran yang didapatnya saat melawan Praneeth. " \
           "\"Untuk selanjutnya saya harus lebih fokus menggunakan strategi dengan baik,\" tutur Anthony." \
           "\"Lalu dari keyakinan dan ketenangan harus benar-benar mantap karena tadi pun kehilangan satu-dua poin langsung berpengaruh sekali kepada permainan saya,\" lanjutnya."
    summary = summarize(title=title, text=text)
    print(" ".join(summary))