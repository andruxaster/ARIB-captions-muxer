#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
arib_caption_mux.py
===================

Вставляет субтитры (SRT) в MPEG-2 Transport Stream в формате ARIB STD-B24
(«字幕», как в японском цифровом ТВ) — то есть делает обратное тому, что
делает libaribcaption — и пересобирает поток в «partial TS» по ARIB STD-B21,
в том виде, в каком его выдаёт BS/CS/наземный цифровой тюнер по i.LINK
(IEEE 1394) при записи на D-VHS.

Что получается на выходе
------------------------
* PAT  — ровно одна программа (без записи NIT, PID 0x0000).
* PMT  — исходная PMT выбранного сервиса + ES субтитров:
         stream_type 0x06, stream_identifier_descriptor (component_tag 0x30),
         data_component_descriptor (data_component_id 0x0008,
         additional_arib_caption_info 0x3D) — байт-в-байт как на BS.
         digital_copy_control / content_availability сохраняются как есть.
* ES   — видео, звук, PCR-PID и прочие ES сервиса (ECM, NIT, SDT, EIT, TOT,
         BIT, SDTT и null-пакеты выбрасываются: в partial TS их быть не должно).
* SIT  — Selection Information Table (PID 0x001F, table_id 0x7F), раз в секунду
         (ARIB требует не реже 1 раза в 3 с):
           transmission_info_loop:
             partial_transport_stream_descriptor (0x63)   — обязательный
             network_identification_descriptor  (0xC2)    — обязательный
           service_loop:
             partial_TS_time_descriptor (0xC3) — время события + JST из TOT
             дескрипторы сервиса из SDT (service_descriptor и т.п.)
             дескрипторы текущего события из EIT[p/f] (short/extended event,
             component, audio_component, content, data_content, DCCD, ...)
* DIT  — Discontinuity Information Table (PID 0x001E) в местах разрыва PCR.
* Субтитры — синхронные PES (stream_id 0xBD) с data_group:
         caption_management_data каждые 0.5 с и caption_statement_data
         на каждую фразу; раскладка экрана как у BS-вещателей:
         SWF 7 (960x540), SDF 620x480, SDP 170,30, SSM 36x36, SHS 4, SVS 24,
         позиционирование ACPS, полупрозрачная чёрная подложка, до 15
         полноширинных знаков в строке, выравнивание по центру.

Режимы служебных таблиц (--si)
------------------------------
  partial   (по умолчанию) partial TS для D-VHS: PAT/PMT/SIT/DIT, всё прочее
            SI выбрасывается — так поток выдаёт тюнер по i.LINK.
  broadcast как в эфире BS: PAT (с NIT), PMT, NIT (network_name,
            system_management, service_list, satellite_delivery), SDT,
            EIT[p/f] и базовое расписание EIT, TOT, BIT, служебный поток
            суперимпоза 0x138. Для потока не из японского эфира таблицы
            строятся из ключей --service-name/--event-name/--jst/--genre...,
            компоненты (1080i/16:9, AAC стерео 48 кГц и т.п.) — по самим ES.
            Японский поток с полным SI остаётся как есть (--si-regenerate).
  both      эфирные таблицы + SIT.
  keep      исходный поток не трогается, только субтитры (= --no-partial-ts).
  --arib-pids — эфирная нумерация PID: PMT 0x01F0, видео 0x0100, звук 0x0110.
  Не генерируются: ECM/EMM (условный доступ), SDTT, CDT, карусели данных BML.

ASS/SSA
-------
Позиция (\\pos, начало \\move), выравнивание, поля, основной цвет (8 цветов
ARIB), размер (обычный или малый SSZ), прозрачность FF переносятся;
рисунки, повороты, масштаб, анимации, затухания, обводка, клипы, шрифты и
караоке пропускаются. Одновременные события компонуются в один экран,
покадровый трекинг склеивается в статичные надписи, строки одной надписи
собираются в блок (порядок — с учётом \\frz). Ключи --ass-signs,
--ass-skip-styles, --ass-only-styles, --ass-small, --ass-min-duration.

--ass-dialogue-only — только реплики. Стиль отбрасывается по имени (Signs,
Надписи, OP/ED, Karaoke, Notes, Title... — в т.ч. FrierenSigns, OP-Romaji)
или по содержимому (обычных строк меньше 70%, если их не 20+ и 40%+).
В оставшихся стилях отбрасывается каждое событие с \\pos (не в точке
стиля), \\move, \\k, \\clip, \\org, поворотом, наклоном, рисунком, Effect
fx/karaoke или «надпись» в поле Name. \\an8, курсив, цвет, \\fad — остаются.
--ass-list-styles — показать решение по каждому стилю и выйти; ошибку
эвристики правят --ass-only-styles / --ass-skip-styles.

Позиционирование строк (--positioning)
--------------------------------------
По умолчанию APS (строка/столбец от угла области). Проверено на реальной
деке: ACPS она отсчитывает от угла области SDP (+170,+30), а не от угла
экрана, поэтому строки уезжали вправо-вниз и переносились по кругу наверх.
--positioning acps — прежнее поведение (точки, как BS-вещатель в образце).

Без субтитров
-------------
  python3 arib_caption_mux.py in.m2t -o out.m2t    # только перемукс/SI/звук

Управление копированием
-----------------------
  --show/--list                показывает 0xC1 и 0xDE входного потока
  --copy free|once|never|broadcaster (или биты 00 01 10 11)
  --user-defined N             младший полубайт 0xC1
  --content-availability 0xEF  байт 0xDE целиком
  --diff ФАЙЛ                  побайтовое сравнение двух файлов
Значения попадают в PMT, а при генерации SI — ещё в EIT и SIT, как у вещателя.
Если задать только эти ключи (без субтитров, звука и смены SI, с --si keep),
секции PMT правятся на месте с пересчётом CRC, а остальной файл копируется
байт в байт, включая заголовок перед синхробайтом и неполный хвост.
На i.LINK поверх этого работает DTCP, и режим на шине задаёт передающее
устройство: биты в потоке — сигнализация, а не сама защита. Для записи из
эфира они отражают условия вещателя.

Звук
----
  --audio FILE         дорожка AAC: WAV/FLAC -> MPEG-2 AAC-LC 48 кГц (fdkaac: ADTS
                       с CRC, как у вещателя; иначе ffmpeg) или готовый .aac.
                       Повторяйте для нескольких дорожек — порядок сохраняется,
                       первая основная (main_component_flag). Синонимы:
                       --audio-wav / --audio-aac.
  --keep-audio         исходный звук остаётся, новые дорожки идут после него.
  --audio-lang jpn,rus языки всех звуковых ES по порядку PMT.
  --audio-name NAME    название новой дорожки в EIT/SIT (повторяйте).
  --audio-channels 6   5.1 (3/2+LFE): в ARIB это component_type 0x09; по умолчанию
                       столько каналов, сколько в WAV (1, 2 или 6).
  --audio-mp2 FILE     дорожка MPEG-1 Layer II, stream_type 0x03 (WAV кодируется
                       libtwolame, готовый .mp2 берётся как есть). В японском
                       вещании такого звука нет и ARIB-приёмники его игнорируют,
                       но деки других производителей ждут именно его — поэтому
                       обычную сборку делают из двух дорожек: AAC и MP2.
                       Layer II многоканальным не бывает: 5.1 сводится в стерео.
  Готовые файлы .aac/.mp2/.mpa берутся как есть, перекодирования нет; параметры
  (частота, каналы, битрейт) читаются из самих кадров. Задержка кодировщика в
  готовом файле не записана: для Layer II она задана форматом (482 отсч.), для
  AAC берётся 2048 — если звук уедет, поставьте --audio-delay-samples 1024.
  --audio-offset 0,-0.1 / --audio-bitrate 384,192 — по дорожкам
                       (по умолчанию 256, для 5.1 — 384, для моно — 144).
  --audio-lang-pmt     ISO 639 в PMT, чтобы языки видели плееры (у BS его нет).
  PID 0x0110, 0x0111... (с --arib-pids), component_tag 0x10, 0x11...;
  PES по 736 байт с PTS, задержка кодера учитывается.

Использование
-------------
  python3 arib_caption_mux.py input.m2t subs.srt -o output.m2t
  python3 arib_caption_mux.py input.m2t --list                 # что внутри
  python3 arib_caption_mux.py input.m2t subs.srt -o out.m2t --service-id 171
  python3 arib_caption_mux.py in.m2t subs.srt -o out.m2t --no-partial-ts
  python3 arib_caption_mux.py in.m2t subs.srt -o out.m2t --existing keep  # второй ES 0x31
  python3 arib_caption_mux.py my.m2t episode.ass -o out.m2t \
      --audio jp.wav --audio-mp2 jp.wav      # AAC японским декам, MP2 прочим
  python3 arib_caption_mux.py my.m2t episode.ass -o out.m2t --cyrillic half \
      --si broadcast --arib-pids --out-service-id 171 --ts-id 0x4012 \
      --service-name "ＢＳテスト" --event-name "Серия 1" --genre anime \
      --caption-lang rus --jst "2026-08-02 07:00:00"

Поток не из японского эфира (HDV, ffmpeg и т.п.): SDT/EIT/TOT из него не
копируются (там DVB-строки и UTC), данные для SIT задаются ключами:
  python3 arib_caption_mux.py hdv.m2t subs.srt -o out.m2t --network-id 4 \
      --service-name "ＢＳテスト" --event-name "ホームビデオ" --jst "2026-08-02 07:00:00"

Отсчёт времени SRT: 0 = самый ранний PTS аудио/видео (как у ffmpeg/mpv/VLC).
При разрыве PCR (склейка) вставляется DIT, а время SRT идёт по непрерывной
шкале воспроизведения.

Несколько дорожек субтитров
---------------------------
Файлов субтитров можно указать сколько угодно (до 8 — предел ARIB): каждый
станет отдельным ES с component_tag 0x30, 0x31... (字幕1, 字幕2...), между
которыми приёмник переключается. Языки и сдвиги — по дорожкам:
  python3 arib_caption_mux.py in.m2t ru.ass jp.srt -o out.m2t \
      --caption-lang rus,jpn --offset 0,-0.5

SRT: UTF-8, поддерживаются <font color="yellow|#RRGGBB">...</font>
(цвет приводится к 8 цветам ARIB) и {\\an8} — субтитр вверху кадра.

Русский и другие языки
----------------------
Кириллица (включая Ё/ё) есть в JIS X 0208 и кодируется штатно. Буквы стоят
в полноширинных клетках, как иероглифы: 15 букв в строке, перенос по словам.
  --cyrillic half     кириллица вполширины (MSZ): 30 букв в строке, приёмник
                      сжимает глифы вдвое по горизонтали
  --drcs-font auto    знаки, которых нет в JIS (« » „ “ ‹ › і ї є ґ ў и т.п.),
                      рисуются картинками DRCS 36x36 в 4 градации — так же,
                      как вещатель передаёт свои особые знаки; нужен Pillow.
                      Можно указать путь к .ttf с кириллицей.
Без --drcs-font « » -> ≪ ≫, „“ -> “”, ‹ › -> 〈 〉, і -> i; ї є ґ ў -> 〓.

Зависимостей нет, нужен только Python 3.8+.
Таблица дополнительных символов ARIB (ряды 85–86, 90–94) взята из
libaribcaption (c) magicxqq, лицензия ISC.
"""

import argparse
import collections
import datetime
import math
import os
import re
import sys
import unicodedata

TS = 188
PID_PAT, PID_NIT, PID_SDT, PID_EIT, PID_TOT = 0x0000, 0x0010, 0x0011, 0x0012, 0x0014
PID_DIT, PID_SIT, PID_NULL = 0x001E, 0x001F, 0x1FFF
PTS_WRAP = 1 << 33

VIDEO_TYPES = {0x01, 0x02, 0x10, 0x1B, 0x24}
AUDIO_TYPES = {0x03, 0x04, 0x0F, 0x11, 0x81}


def log(msg):
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# CRC
# ---------------------------------------------------------------------------

def _make_table(poly, width):
    top = 1 << (width - 1)
    mask = (1 << width) - 1
    table = []
    for i in range(256):
        c = i << (width - 8)
        for _ in range(8):
            c = ((c << 1) ^ poly) if c & top else (c << 1)
        table.append(c & mask)
    return table


_CRC32 = _make_table(0x04C11DB7, 32)
_CRC16 = _make_table(0x1021, 16)


def crc32_mpeg(data):
    c = 0xFFFFFFFF
    for b in data:
        c = ((c << 8) & 0xFFFFFFFF) ^ _CRC32[((c >> 24) ^ b) & 0xFF]
    return c


def crc16_ccitt(data):
    """CRC-16 из ARIB STD-B24 (x^16+x^12+x^5+1, начальное значение 0)."""
    c = 0
    for b in data:
        c = ((c << 8) & 0xFFFF) ^ _CRC16[((c >> 8) ^ b) & 0xFF]
    return c


# ---------------------------------------------------------------------------
# Кодирование текста в 8-единичный код ARIB STD-B24
# ---------------------------------------------------------------------------
ARIB_ADDITIONAL_ROWS = {
    85: (
        "\u3402\U00020158\u4efd\u4eff\u4f9a\u4fc9\u509c\u511e\u51bc\u351f\u5307\u5361\u536c\u8a79\U00020bb7\u544d"
        "\u5496\u549c\u54a9\u550e\u554a\u5672\u56e4\u5733\u5734\ufa10\u5880\u59e4\u5a23\u5a55\u5bec\ufa11"
        "\u37e2\u5eac\u5f34\u5f45\u5fb7\u6017\ufa6b\u6130\u6624\u66c8\u66d9\u66fa\u66fb\u6852\u9fc4\u6911"
        "\u693b\u6a45\u6a91\u6adb\U000233cc\U000233fe\U000235c4\u6bf1\u6ce0\u6d2e\ufa45\u6dbf\u6dca\u6df8\ufa46\u6f5e"
        "\u6ff9\u7064\ufa6c\U000242ee\u7147\u71c1\u7200\u739f\u73a8\u73c9\u73d6\u741b\u7421\ufa4a\u7426\u742a"
        "\u742c\u7439\u744b\u3eda\u7575\u7581\u7772\u4093\u78c8\u78e0\u7947\u79ae\u9fc6\u4103"
    ),
    86: (
        "\u9fc5\u79da\u7a1e\u7b7f\u7c31\u4264\u7d8b\u7fa1\u8118\u813a\ufa6d\u82ae\u845b\u84dc\u84ec\u8559"
        "\u85ce\u8755\u87ec\u880b\u88f5\u89d2\u8af6\u8dce\u8fbb\u8ff6\u90dd\u9127\u912d\u91b2\u9233\u9288"
        "\u9321\u9348\u9592\u96de\u9903\u9940\u9ad9\u9bd6\u9dd7\u9eb4\u9eb5\x00\x00\x00\x00\x00"
        "\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        "\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        "\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    ),
    90: (
        "\u26cc\u26cd\u2757\u26cf\u26d0\u26d1\x00\u26d2\u26d5\u26d3\u26d4\x00\x00\x00\x00\U0001f17f"
        "\U0001f18a\x00\x00\u26d6\u26d7\u26d8\u26d9\u26da\u26db\u26dc\u26dd\u26de\u26df\u26e0\u26e1\u2b55"
        "\u3248\u3249\u324a\u324b\u324c\u324d\u324e\u324f\x00\x00\x00\x00\u2491\u2492\u2493\U0001f14a"
        "\U0001f14c\U0001f13f\U0001f146\U0001f14b\U0001f210\U0001f211\U0001f212\U0001f213\U0001f142\U0001f214\U0001f215\U0001f216\U0001f14d\U0001f131\U0001f13d\u2b1b"
        "\u2b24\U0001f217\U0001f218\U0001f219\U0001f21a\U0001f21b\u26bf\U0001f21c\U0001f21d\U0001f21e\U0001f21f\U0001f220\U0001f221\U0001f222\U0001f223\U0001f224"
        "\U0001f225\U0001f14e\u3299\U0001f200\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    ),
    91: (
        "\u26e3\u2b56\u2b57\u2b58\u2b59\u2613\u328b\u3012\u26e8\u3246\u3245\u26e9\u0fd6\u26ea\u26eb\u26ec"
        "\u2668\u26ed\u26ee\u26ef\u2693\u2708\u26f0\u26f1\u26f2\u26f3\u26f4\u26f5\U0001f157\u24b9\u24c8\u26f6"
        "\U0001f15f\U0001f18b\U0001f18d\U0001f18c\U0001f179\u26f7\u26f8\u26f9\u26fa\U0001f17b\u260e\u26fb\u26fc\u26fd\u26fe\U0001f17c"
        "\u26ff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        "\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        "\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    ),
    92: (
        "\u27a1\u2b05\u2b06\u2b07\u2b2f\u2b2e\u5e74\u6708\u65e5\u5186\u33a1\u33a5\u339d\u33a0\u33a4\U0001f100"
        "\u2488\u2489\u248a\u248b\u248c\u248d\u248e\u248f\u2490\u6c0f\u526f\u5143\u6545\u524d\u65b0\U0001f101"
        "\U0001f102\U0001f103\U0001f104\U0001f105\U0001f106\U0001f107\U0001f108\U0001f109\U0001f10a\u3233\u3236\u3232\u3231\u3239\u3244\u25b6"
        "\u25c0\u3016\u3017\u27d0\u00b2\u00b3\U0001f12d\ue2a5\ue2a6\ue2a7\ue2a8\ue2a9\ue2aa\ue2ab\ue2ac\ue2ad"
        "\ue2ae\ue2af\ue2b0\ue2b1\ue2b2\ue2b3\ue2b4\ue2b5\ue2b6\ue2b7\ue2b8\ue2b9\ue2ba\ue2bb\ue2bc\ue2bd"
        "\ue2be\ue2bf\ue2c0\ue2c1\ue2c2\U0001f12c\U0001f12b\u3247\U0001f190\U0001f226\u213b\x00\x00\x00"
    ),
    93: (
        "\u322a\u322b\u322c\u322d\u322e\u322f\u3230\u3237\u337e\u337d\u337c\u337b\u2116\u2121\u3036\u26be"
        "\U0001f240\U0001f241\U0001f242\U0001f243\U0001f244\U0001f245\U0001f246\U0001f247\U0001f248\U0001f12a\U0001f227\U0001f228\U0001f229\U0001f214\U0001f22a\U0001f22b"
        "\U0001f22c\U0001f22d\U0001f22e\U0001f22f\U0001f230\U0001f231\u2113\u338f\u3390\u33ca\u339e\u33a2\u3371\x00\x00\u00bd"
        "\u2189\u2153\u2154\u00bc\u00be\u2155\u2156\u2157\u2158\u2159\u215a\u2150\u215b\u2151\u2152\u2600"
        "\u2601\u2602\u26c4\u2616\u2617\u26c9\u26ca\u2666\u2665\u2663\u2660\u26cb\u2a00\u203c\u2049\u26c5"
        "\u2614\u26c6\u2603\u26c7\u26a1\u26c8\x00\u269e\u269f\u266c\u260e\x00\x00\x00"
    ),
    94: (
        "\u2160\u2161\u2162\u2163\u2164\u2165\u2166\u2167\u2168\u2169\u216a\u216b\u2470\u2471\u2472\u2473"
        "\u2474\u2475\u2476\u2477\u2478\u2479\u247a\u247b\u247c\u247d\u247e\u247f\u3251\u3252\u3253\u3254"
        "\U0001f110\U0001f111\U0001f112\U0001f113\U0001f114\U0001f115\U0001f116\U0001f117\U0001f118\U0001f119\U0001f11a\U0001f11b\U0001f11c\U0001f11d\U0001f11e\U0001f11f"
        "\U0001f120\U0001f121\U0001f122\U0001f123\U0001f124\U0001f125\U0001f126\U0001f127\U0001f128\U0001f129\u3255\u3256\u3257\u3258\u3259\u325a"
        "\u2460\u2461\u2462\u2463\u2464\u2465\u2466\u2467\u2468\u2469\u246a\u246b\u246c\u246d\u246e\u246f"
        "\u2776\u2777\u2778\u2779\u277a\u277b\u277c\u277d\u277e\u277f\u24eb\u24ec\u325b\x00"
    ),
}

# Управляющие коды
LS0, LS1, APS, CS, SP = 0x0F, 0x0E, 0x1C, 0x0C, 0x20
BKF, RDF, GRF, YLF, BLF, MGF, CNF, WHF = range(0x80, 0x88)
SSZ, MSZ, NSZ, COL, CSI = 0x88, 0x89, 0x8A, 0x90, 0x9B

# 8 основных цветов палитры 0 (для SRT <font color>)
ARIB_COLORS = [
    ((0, 0, 0), BKF), ((255, 0, 0), RDF), ((0, 255, 0), GRF), ((255, 255, 0), YLF),
    ((0, 0, 255), BLF), ((255, 0, 255), MGF), ((0, 255, 255), CNF), ((255, 255, 255), WHF),
]
NAMED_COLORS = {
    'black': (0, 0, 0), 'red': (255, 0, 0), 'green': (0, 255, 0), 'lime': (0, 255, 0),
    'yellow': (255, 255, 0), 'blue': (0, 0, 255), 'magenta': (255, 0, 255),
    'fuchsia': (255, 0, 255), 'cyan': (0, 255, 255), 'aqua': (0, 255, 255),
    'white': (255, 255, 255),
}


def color_code(spec):
    """'yellow' / '#ffff00' / None -> код C1 (BKF..WHF)."""
    if not spec:
        return WHF
    spec = spec.strip().lower()
    rgb = NAMED_COLORS.get(spec)
    if rgb is None:
        m = re.fullmatch(r'#?([0-9a-f]{6})', spec)
        if not m:
            return WHF
        v = int(m.group(1), 16)
        rgb = (v >> 16, (v >> 8) & 255, v & 255)
    return min(ARIB_COLORS, key=lambda c: sum((a - b) ** 2 for a, b in zip(c[0], rgb)))[1]


class AribCharset:
    """Unicode -> коды наборов «Кандзи» (JIS X 0208 + доп. символы ARIB) и
    «Алфавитно-цифровой» (G1)."""

    # Символы, которые в Windows/macOS-текстах выглядят иначе, чем в JIS
    ALIASES = {
        '\uff5e': '\u301c',  # ～ -> 〜
        '\u2212': '\uff0d',  # − -> －
        '\u2015': '\u2014',  # ― -> —
        '\u2225': '\u2016',  # ∥ -> ‖
        '\uffe0': '\u00a2', '\uffe1': '\u00a3', '\uffe2': '\u00ac',
        '\u00a5': None,      # ¥ кодируется в алфавитно-цифровом наборе (0x5C)
    }

    # Замены знаков, которых нет в JIS X 0208 (когда не задан --drcs-font)
    SUBST = {
        '\u00ab': '\u226a', '\u00bb': '\u226b',      # « » -> ≪ ≫
        '\u2039': '\u3008', '\u203a': '\u3009',      # ‹ › -> 〈 〉
        '\u201e': '\u201c', '\u201a': '\u2018',      # „ ‚ -> “ ‘
        '\u2013': '\u2014',                          # – -> —
        '\u2010': '-', '\u2011': '-',
        '\u00a0': ' ', '\u202f': ' ', '\u2009': ' ', '\u2007': ' ',
        '\u0456': 'i', '\u0406': 'I', '\u0458': 'j', '\u0408': 'J',   # і І ј Ј
    }

    def __init__(self, half_letters=False, drcs=None):
        """half_letters — кириллицу и греческий из набора Кандзи выводить
        вполширины (MSZ); drcs — DrcsFont для знаков вне наборов ARIB."""
        self.half = half_letters
        self.drcs = drcs
        self.kanji = {}
        for b1 in range(0xA1, 0xFF):
            for b2 in range(0xA1, 0xFF):
                if b1 - 0xA0 >= 85:          # ряды 85+ — у ARIB свои
                    continue
                try:
                    ch = bytes((b1, b2)).decode('euc_jp')
                except UnicodeDecodeError:
                    continue
                if len(ch) == 1 and ch not in self.kanji:
                    self.kanji[ch] = bytes((b1 - 0x80, b2 - 0x80))
        for alias, target in self.ALIASES.items():
            if target and alias not in self.kanji:
                code = self.kanji.get(target)
                if code is None:
                    # обратное направление: target отсутствует, alias есть
                    continue
                self.kanji[alias] = code
        for alias, target in self.ALIASES.items():
            if target and target not in self.kanji and alias in self.kanji:
                self.kanji[target] = self.kanji[alias]
        for ku, row in ARIB_ADDITIONAL_ROWS.items():
            for ten, ch in enumerate(row):
                if ch != '\x00' and ch not in self.kanji:
                    self.kanji[ch] = bytes((ku + 0x20, ten + 0x21))

    @staticmethod
    def is_alnum(ch):
        o = ord(ch)
        return (0x21 <= o <= 0x7E and o not in (0x5C, 0x7E)) or ch == '\u00a5' or ch == '\u203e'

    @staticmethod
    def alnum_code(ch):
        if ch == '\u00a5':
            return 0x5C
        if ch == '\u203e':
            return 0x7E
        return ord(ch)

    def direct(self, ch):
        """Знак кодируется штатными наборами ARIB (без DRCS)."""
        if ENCODING == 'utf8':
            return True                  # в UCS кодируется что угодно
        return ch == ' ' or ch in self.kanji or self.is_alnum(ch)

    def normalize(self, text, allow_drcs=True):
        use_drcs = allow_drcs and self.drcs is not None
        # NFC собирает й = и+◌̆, ё = е+◌̈, が = か+゛; совместимые иероглифы
        # (U+F900..U+FAFF, есть в доп. наборе ARIB) NFC не трогаем
        if any(unicodedata.combining(c) or c in '\u3099\u309a' for c in text):
            text = ''.join(part if re.fullmatch(r'[\uf900-\ufaff]+', part) else unicodedata.normalize('NFC', part)
                           for part in re.split(r'([\uf900-\ufaff]+)', text))
        out = []
        low_quote = False
        for ch in text:
            o = ord(ch)
            if 0xFF61 <= o <= 0xFF9F:        # полуширинная катакана -> полноширинная
                ch = unicodedata.normalize('NFKC', ch)
            elif ch == '\\':
                ch = '\uff3c'
            elif ch == '~':
                ch = '\u301c'
            elif ch in '\t\u00a0\u202f\u2009\u2007\u2002\u2003':
                ch = ' '
            elif ch in '\u200b\u200c\u200d\u2060\ufeff':
                continue
            if not self.direct(ch) and not use_drcs and ch in self.SUBST:
                if ch == '\u201e':
                    low_quote = True
                ch = self.SUBST[ch]
                if 'A' <= ch <= 'z' and ch.isalpha() and not self.half:
                    ch = chr(ord(ch) + 0xFEE0)   # i -> ｉ, чтобы не выбиваться из полноширинной кириллицы
            elif ch == '\u201c' and low_quote and not use_drcs:
                ch = '\u201d'                      # „…“ -> “…”
                low_quote = False
            out.append(ch)
        return ''.join(out)

    def is_narrow_letter(self, ch):
        return self.half and ('\u0370' <= ch <= '\u04ff')

    def width(self, ch):
        """Ширина в полуклетках: MSZ-знак = 1, NSZ-знак = 2."""
        if ENCODING == 'utf8':
            if unicodedata.east_asian_width(ch) in 'WF':
                return 2
            return 1 if (ord(ch) < 0x2E80 and (self.half or ord(ch) < 0x0370)) else 2
        if ch == ' ' or self.is_alnum(ch):
            return 1
        if ch in self.kanji:
            return 1 if self.is_narrow_letter(ch) else 2
        if self.drcs is not None:
            return 1 if self.half and unicodedata.east_asian_width(ch) not in 'WF' else 2
        return 2


class DrcsFont:
    """Рисует знаки, которых нет в наборах ARIB, как DRCS: 36x36, 4 градации,
    режим 1 — тот же формат, что у BS-вещателя в образце. Нужен Pillow."""

    CANDIDATES = [
        'C:/Windows/Fonts/arial.ttf', 'C:/Windows/Fonts/segoeui.ttf',
        '/System/Library/Fonts/Supplemental/Arial.ttf', '/Library/Fonts/Arial.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/TTF/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf',
    ]

    def __init__(self, path):
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            raise SystemExit('для --drcs-font нужен Pillow: pip install pillow')
        self.Image, self.ImageDraw = Image, ImageDraw
        if path == 'auto':
            path = self._find()
        self.path = path
        self.S = 4                                   # суперсэмплинг
        self.ImageFont = ImageFont
        self.fonts = {}
        self.cache = {}
        self._font(36)

    def _font(self, size):
        if size not in self.fonts:
            try:
                self.fonts[size] = self.ImageFont.truetype(self.path, int(size * 0.86) * self.S)
            except OSError:
                raise SystemExit('не удалось открыть шрифт %r для --drcs-font' % self.path)
        return self.fonts[size]

    def _find(self):
        import os
        import shutil
        import subprocess
        if shutil.which('fc-match'):
            try:
                f = subprocess.run(['fc-match', '-f', '%{file}', 'sans-serif:lang=ru'],
                                   capture_output=True, text=True, timeout=10).stdout.strip()
                if f and os.path.exists(f):
                    return f
            except (OSError, subprocess.SubprocessError):
                pass
        for f in self.CANDIDATES:
            if os.path.exists(f):
                return f
        raise SystemExit('не нашёл шрифт с кириллицей, укажите путь: --drcs-font /путь/к/шрифту.ttf')

    def pattern(self, ch, half, size=36):
        key = (ch, half, size)
        if key in self.cache:
            return self.cache[key]
        S, N = self.S, size
        font = self._font(size)
        asc, desc = font.getmetrics()
        adv = max(1, int(font.getlength(ch)))
        tmp = self.Image.new('L', (adv + 8 * S, N * S), 0)
        self.ImageDraw.Draw(tmp).text((4 * S, (N * S - (asc + desc)) // 2 + S), ch, fill=255, font=font)
        box = tmp.getbbox()
        if box is None:
            self.cache[key] = None
            return None
        glyph = tmp.crop((box[0], 0, box[2], N * S))
        cell = (N // 2 if half else N) * S
        limit = int(cell * 0.9)
        if glyph.width > limit:
            glyph = glyph.resize((limit, N * S))
        canvas = self.Image.new('L', (cell, N * S), 0)
        canvas.paste(glyph, ((cell - glyph.width) // 2, 0))
        if half:                                     # приёмник сожмёт MSZ-знак вдвое
            canvas = canvas.resize((N * S, N * S))
        small = canvas.resize((N, N), self.Image.BOX)
        acc = bytearray()
        bits, nbits = 0, 0
        for v in small.getdata():
            bits = (bits << 2) | min(3, (v * 4) // 256)
            nbits += 2
            if nbits == 8:
                acc.append(bits)
                bits, nbits = 0, 0
        if nbits:
            acc.append(bits << (8 - nbits))
        self.cache[key] = bytes(acc)
        return self.cache[key]


class StatementBody:
    """Сборка тела caption_statement (data_unit 0x20) с отслеживанием
    состояния GL (G0 кандзи / G1 латиница), размера, цвета и DRCS."""

    def __init__(self, charset, warn, allow_drcs=True):
        self.cs = charset
        self.warn = warn
        self.buf = bytearray()
        self.gl = 0          # 0 = G0 (Кандзи), 1 = G1 (алфавитно-цифровой)
        self.size = None
        self.fg = None
        self.allow_drcs = allow_drcs and charset.drcs is not None
        self.drcs_codes = {}  # знак -> (код 0x21.., шаблон)
        self.g2_drcs = False
        self.si_style = False  # строки SI: сначала LS1, потом MSZ; без LS0 в конце
        self.utf8 = ENCODING == 'utf8' and allow_drcs is not False

    def c1(self, code):
        """Код C1: в режиме UCS он передаётся как UTF-8 (0xC2 + код)."""
        if self.utf8:
            self.buf.append(0xC2)
        self.buf.append(code)

    def csi(self, params, final):
        self.c1(CSI)
        self.buf += ';'.join(str(p) for p in params).encode('ascii')
        self.buf += bytes((0x20, final))

    def set_size(self, size):
        if self.size != size:
            self.c1(size)
            self.size = size

    def set_gl(self, g):
        if self.utf8:
            return                       # в UCS наборов нет, переключать нечего
        if self.gl != g:
            self.buf.append(LS1 if g else LS0)
            self.gl = g

    def set_fg(self, code):
        if self.fg != code:
            self.c1(code)
            self.fg = code

    def _drcs(self, ch, small):
        half = not small and self.cs.width(ch) == 1
        size = CHAR_H // 2 if small else CHAR_H
        key = (ch, half, size)
        if key in self.drcs_codes:
            return self.drcs_codes[key][0]
        if len(self.drcs_codes) >= 94:
            return None
        pat = self.cs.drcs.pattern(ch, half, size)
        if pat is None:
            return None
        code = 0x21 + len(self.drcs_codes)
        self.drcs_codes[key] = (code, pat, size)
        return code

    def put(self, ch, small=False):
        """small=True — малый размер SSZ (18x18) для всех знаков."""
        if self.utf8:
            self.set_size(SSZ if small else MSZ if self.cs.width(ch) == 1 else NSZ)
            self.buf += ch.encode('utf-8')
            return
        if ch == ' ':
            self.set_size(SSZ if small else MSZ)
            self.buf.append(SP)
        elif self.cs.is_alnum(ch):
            if self.si_style:
                self.set_gl(1)
            self.set_size(SSZ if small else MSZ)
            self.set_gl(1)
            self.buf.append(self.cs.alnum_code(ch))
        elif ch in self.cs.kanji:
            self.set_size(SSZ if small else MSZ if self.cs.is_narrow_letter(ch) else NSZ)
            self.set_gl(0)
            self.buf += self.cs.kanji[ch]
        else:
            code = self._drcs(ch, small) if self.allow_drcs else None
            if code is not None:
                if not self.g2_drcs:
                    self.buf += bytes((0x1B, 0x2A, 0x20, 0x41))   # G2 <- DRCS-1, как в эфире
                    self.g2_drcs = True
                self.set_size(SSZ if small else MSZ if self.cs.width(ch) == 1 else NSZ)
                self.buf.append(0x80 | code)                    # вызов через GR
                return
            hint = '' if self.allow_drcs else ' (можно нарисовать через --drcs-font)'
            self.warn('символ %r (U+%04X) отсутствует в наборах ARIB, заменён на 〓%s' % (ch, ord(ch), hint))
            self.set_size(NSZ)
            self.set_gl(0)
            self.buf += self.cs.kanji['\u3013']

    def drcs_unit(self):
        if not self.drcs_codes:
            return None
        payload = bytearray((len(self.drcs_codes),))
        for code, pat, n in self.drcs_codes.values():
            # CharacterCode 0x41xx (DRCS-1), 1 шрифт, font_id 0 / mode 1, depth 2 (4 градации)
            payload += bytes((0x41, code, 0x01, 0x01, 0x02, n, n)) + pat
        return data_unit(0x30, bytes(payload))

    def finish(self):
        if self.utf8:
            return bytes(self.buf)
        if self.si_style:
            return bytes(self.buf)   # каждая строка SI декодируется с исходного состояния
        self.set_gl(0)       # вернуть исходное состояние GL
        if self.g2_drcs:
            self.buf += bytes((0x1B, 0x2A, 0x30))                # G2 <- Хирагана (по умолчанию)
        return bytes(self.buf)


# ---------------------------------------------------------------------------
# data_group / PES субтитров
# ---------------------------------------------------------------------------

def data_unit(parameter, payload):
    n = len(payload)
    return bytes((0x1F, parameter, n >> 16, (n >> 8) & 255, n & 255)) + payload


def data_group(group_id, payload, version=0):
    n = len(payload)
    head = bytes(((group_id << 2) | version, 0x00, 0x00, n >> 8, n & 255))
    dg = head + payload
    c = crc16_ccitt(dg)
    return dg + bytes((c >> 8, c & 255))


def caption_management_data(langs=(b'jpn',), dmf=0b1010, fmt=0b1000, tcs=None):
    """Как на BS: TMD=free, 1 язык, DMF 1010 (выбор пользователем при
    приёме и воспроизведении), Format 1000 = горизонтально 960x540, TCS 8 бит."""
    if tcs is None:
        tcs = 1 if ENCODING == 'utf8' else 0        # 0 — наборы ARIB, 1 — UCS/UTF-8
    if isinstance(langs, (bytes, bytearray)):
        langs = [bytes(langs)]
    body = bytes((0x3F, len(langs)))
    for tag, lang in enumerate(langs):              # language_tag 0 -> 字幕1, 1 -> 字幕2
        body += bytes(((tag << 5) | 0x10 | dmf,)) + lang + bytes(((fmt << 4) | (tcs << 2),))
    body += b'\x00\x00\x00'
    return data_group(0x00, body)


def caption_statement_data(units, lang_tag=0):
    """data_group_id = 1 + language_tag: так приёмник отличает 字幕1 от 字幕2."""
    loop = b''.join(units)
    n = len(loop)
    return data_group(0x01 + lang_tag, bytes((0x3F, n >> 16, (n >> 8) & 255, n & 255)) + loop)


def encode_pts(pts):
    pts %= PTS_WRAP
    return bytes((
        0x21 | ((pts >> 29) & 0x0E),
        (pts >> 22) & 0xFF,
        0x01 | ((pts >> 14) & 0xFE),
        (pts >> 7) & 0xFF,
        0x01 | ((pts << 1) & 0xFE),
    ))


def caption_pes(dg, pts, broadcast_header=True):
    """Синхронный PES (stream_id 0xBD). Заголовок по умолчанию повторяет
    BS-вещателя из образца: PTS + PES_extension с 16 байтами PES_private_data."""
    payload = b'\x80\xff\xf0' + dg     # data_identifier, private_stream_id, header_length=0
    if broadcast_header:
        opt = encode_pts(pts) + b'\x8e' + b'\xff' * 16 + b'\xff'
        hdr = bytes((0x80, 0x81, len(opt))) + opt
    else:
        opt = encode_pts(pts)
        hdr = bytes((0x80, 0x80, len(opt))) + opt
    n = len(hdr) + len(payload)
    return b'\x00\x00\x01\xbd' + bytes((n >> 8, n & 255)) + hdr + payload


# ---------------------------------------------------------------------------
# Раскладка фразы на экране (как у японских BS-вещателей)
# ---------------------------------------------------------------------------

PLANE_SWF = 7                 # 960x540, горизонтальное письмо
ENCODING = 'jis'              # jis — наборы ARIB; utf8 — UCS (TCS=1), текст в UTF-8
POSITIONING = 'aps'           # aps — строка/столбец от угла области; acps — точки (как BS-вещатель)
AREA_X, AREA_Y, AREA_W, AREA_H = 170, 30, 620, 480
CHAR_W, CHAR_H, HSPACE, VSPACE = 36, 36, 4, 24
CELL = CHAR_W + HSPACE        # 40 точек на полноширинный знак
LINE = CHAR_H + VSPACE        # 60 точек на строку
MAX_HALF = AREA_W // (CELL // 2)   # 31 -> 15 полноширинных знаков
MAX_LINES = AREA_H // LINE         # 8


def set_area(spec):
    """--area ШxВ+X+Y: область субтитров внутри плоскости 960x540."""
    global AREA_X, AREA_Y, AREA_W, AREA_H, MAX_HALF, MAX_LINES, GRID_COLS, GRID_ROWS
    m = re.fullmatch(r'\s*(\d+)x(\d+)([+-]\d+)([+-]\d+)\s*', spec)
    if not m:
        raise SystemExit('--area задаётся как ШxВ+X+Y, например 880x480+40+30')
    w, h, x, y = (int(v) for v in m.groups())
    w, h = w // 20 * 20, h // 60 * 60          # по сетке полуклеток и строк
    if w < 40 or h < 60 or x < 0 or y < 0 or x + w > 960 or y + h > 540:
        raise SystemExit('--area не помещается в плоскость 960x540 (получилось %dx%d+%d+%d)' % (w, h, x, y))
    AREA_X, AREA_Y, AREA_W, AREA_H = x, y, w, h
    MAX_HALF = AREA_W // (CELL // 2)
    MAX_LINES = AREA_H // LINE
    GRID_COLS = AREA_W // 20
    GRID_ROWS = AREA_H // 30
NO_LINE_START = set('、。，．・：；？！゛゜ヽヾゝゞ々ー）］｝」』〕〉》】…‥ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ,.:;?!)]}»›”’')
NO_LINE_END = set('（［｛「『〔〈《【≪«„‹“‘([{')


def _word_char(ch):
    """Буква/цифра алфавитного письма: такие слова не рвём посередине."""
    o = ord(ch)
    return (ch.isalnum() and o < 0x2E80) or 0xFF10 <= o <= 0xFF5A or ch in "-'\u2019"


def _greedy(chars, cs, target, nlines, small=False):
    """Жадная раскладка: строки до target, последняя (nlines-я) — до MAX_HALF."""
    width = (lambda c: 1) if small else cs.width
    lines, cur, w = [], [], 0
    for ch, col in chars:
        cw = width(ch)
        limit = target if len(lines) < nlines - 1 else MAX_HALF
        if cur and w + cw > limit:
            if ch in ' \u3000':
                lines.append(cur)
                cur, w = [], 0
                continue
            if ch in NO_LINE_START and w + cw <= MAX_HALF:
                cur.append((ch, col))
                w += cw
                continue
            # последний пробел, левее которого есть хоть одна буква/цифра
            # (чтобы «—» диалога не оставалось на строке одно)
            sp = max((k for k, (c, _) in enumerate(cur)
                      if c in ' \u3000' and any(x.isalnum() for x, _ in cur[:k])), default=None)
            in_word = _word_char(ch) and _word_char(cur[-1][0])
            if sp is not None and sp > 0 and (in_word or sp >= len(cur) // 3):
                lines.append(cur[:sp])
                cur = cur[sp + 1:]
            elif in_word and w + cw <= MAX_HALF:
                cur.append((ch, col))          # дотягиваем слово до края строки
                w += cw
                continue
            elif ch in NO_LINE_START and len(cur) > 1:
                lines.append(cur[:-1])
                cur = cur[-1:]
            else:
                lines.append(cur)              # слово длиннее строки — режем
                cur = []
            w = sum(width(c) for c, _ in cur)
        if not cur and ch in ' \u3000':
            continue
        cur.append((ch, col))
        w += cw
    if cur:
        lines.append(cur)
    # открывающая скобка/кавычка не должна оставаться в конце строки
    for k in range(len(lines) - 1):
        while len(lines[k]) > 1 and lines[k][-1][0] in NO_LINE_END:
            lines[k + 1].insert(0, lines[k].pop())
    return lines


def wrap_line(spans, cs, small=False):
    """spans: [(text, color)] -> строки [(char, color)] не шире 15 полноширинных
    знаков. Строки выравниваются по длине (как в вещании); японский текст
    переносится по знакам с учётом 、。」, алфавитный — только по пробелам."""
    chars = [(ch, col) for text, col in spans for ch in text]
    while chars and chars[-1][0] in ' \u3000':
        chars.pop()
    width = (lambda c: 1) if small else cs.width
    total = sum(width(ch) for ch, _ in chars)
    if total <= MAX_HALF:
        return [chars]
    base = [ln for ln in _greedy(chars, cs, MAX_HALF, MAX_LINES * 2, small) if ln]
    k = len(base)
    for target in range(-(-total // max(k, 1)), MAX_HALF):
        lines = [ln for ln in _greedy(chars, cs, target, k, small) if ln]
        if len(lines) <= k:
            return lines                       # самые ровные строки при том же их числе
    return base


def layout_srt(sub, cs, warn):
    """SRT-фраза -> [(x, y, small, [(char, color)])] — по центру, снизу или сверху."""
    lines = []
    for spans in sub['lines']:
        lines.extend(wrap_line(spans, cs))
    lines = [ln for ln in lines if ln]
    if len(lines) > MAX_LINES:
        warn('больше %d строк, лишние отброшены' % MAX_LINES)
        lines = lines[-MAX_LINES:]
    placed = []
    n = len(lines)
    for i, line in enumerate(lines):
        width = sum(cs.width(ch) for ch, _ in line) * (CELL // 2)
        x = AREA_X + max(0, (AREA_W - width) // 2) // 20 * 20
        if sub.get('top'):
            y = AREA_Y + LINE * (i + 1) - 1
        else:
            y = AREA_Y + AREA_H - 1 - LINE * (n - 1 - i)
        placed.append((x, y, False, line))
    return placed


def build_statement(sub, cs, warn, lang_tag=0):
    """Фраза (SRT) или экран (ASS) -> caption_statement_data (data_group)."""
    placed = sub['placed'] if 'placed' in sub else layout_srt(sub, cs, warn)
    body = StatementBody(cs, warn)
    body.csi([PLANE_SWF], 0x53)                   # SWF
    body.csi([AREA_W, AREA_H], 0x56)              # SDF
    body.csi([AREA_X, AREA_Y], 0x5F)              # SDP
    body.csi([HSPACE], 0x58)                      # SHS
    body.csi([VSPACE], 0x59)                      # SVS
    body.csi([CHAR_W, CHAR_H], 0x57)              # SSM
    for i, (x, y, small, line) in enumerate(placed):
        if POSITIONING == 'aps':
            # APS (0x1C): строка/столбец в клетках текущего размера от угла области SDP.
            # Проверено на железе: дека считает и ACPS от угла области (+170,+30),
            # а libaribcaption — от угла экрана; APS оба понимают одинаково.
            unit_y = 30 if small else 60
            body.set_size(SSZ if small else MSZ)      # клетка MSZ = 20x60, SSZ = 20x30
            body.buf += bytes((APS, 0x40 + (y + 1 - AREA_Y) // unit_y - 1, 0x40 + (x - AREA_X) // 20))  # APS — C0
        else:
            body.csi([x, y], 0x61)                # ACPS
        if i == 0:
            body.c1(COL); body.buf += b'\x20\x44'            # подложка: палитра 4, цвет 1 (чёрный 50%)
            body.c1(COL); body.buf += b'\x51'
            body.c1(COL); body.buf += b'\x20\x40'            # назад на палитру 0 для цвета текста
        for ch, col in line:
            body.set_fg(col)
            body.put(ch, small)
    text = body.finish()
    units = [data_unit(0x20, bytes((CS,)))]
    if body.drcs_unit():
        units.append(body.drcs_unit())                 # DRCS перед текстом, как в эфире
    units.append(data_unit(0x20, text))
    return caption_statement_data(units, lang_tag)


def arib_string(text, cs, warn=log):
    """Текст -> строка ARIB STD-B24 для SI (service_descriptor, short_event...).
    Состояние по умолчанию в SI: GL=G0 (Кандзи), нормальный размер."""
    body = StatementBody(cs, warn, allow_drcs=False)   # DRCS в SI не бывает
    body.size = NSZ
    body.si_style = True
    for ch in cs.normalize(text, allow_drcs=False):
        body.put(ch)
    return body.finish()


def service_descriptor(name, provider, cs, service_type=0x01):
    n, p = arib_string(name, cs), arib_string(provider, cs)
    body = bytes((service_type, len(p))) + p + bytes((len(n),)) + n
    return bytes((0x48, len(body))) + body


def arib_string_fit(text, cs, limit, warn=log):
    """Строка ARIB не длиннее limit байт; обрезается по знакам, а не посреди
    двухбайтного кода или управляющей последовательности. -> (байты, остаток)."""
    body = StatementBody(cs, warn, allow_drcs=False)
    body.size = NSZ
    body.si_style = True
    out, chars = b'', cs.normalize(text, allow_drcs=False)
    for i, ch in enumerate(chars):
        body.put(ch)
        if len(body.buf) > limit:
            return out, chars[i:]
        out = bytes(body.buf)
    return out, ''


def short_event_descriptor(name, text, cs, lang=b'jpn'):
    """Название и короткое описание. Длина дескриптора — один байт, поэтому
    тело обязано уложиться в 255: имя в приоритете, хвост описания уходит
    в extended_event_descriptors."""
    n, _ = arib_string_fit(name, cs, 200)
    t, _rest = arib_string_fit(text, cs, 255 - len(lang) - 2 - len(n))
    body = lang + bytes((len(n),)) + n + bytes((len(t),)) + t
    return bytes((0x4D, len(body))) + body


def short_event_text_tail(name, text, cs, lang=b'jpn'):
    """Часть описания, не поместившаяся в short_event_descriptor."""
    n, _ = arib_string_fit(name, cs, 200)
    _t, rest = arib_string_fit(text, cs, 255 - len(lang) - 2 - len(n))
    return rest


def extended_event_descriptors(text, cs, lang=b'jpn', max_parts=16):
    """Длинное описание передачи: цепочка дескрипторов 0x4E, как в эфирном EIT.
    В каждом — номер части, номер последней, пустой список позиций и текст."""
    parts, rest = [], text
    while rest and len(parts) < max_parts:
        chunk, rest = arib_string_fit(rest, cs, 255 - len(lang) - 3)
        if not chunk:
            break
        parts.append(chunk)
    last = len(parts) - 1
    out = []
    for i, chunk in enumerate(parts):
        body = bytes(((i << 4) | last,)) + lang + b'\x00' + bytes((len(chunk),)) + chunk
        out.append(bytes((0x4E, len(body))) + body)
    return out


def build_clear_statement(lang_tag=0):
    return caption_statement_data([data_unit(0x20, bytes((CS,)))], lang_tag)


# ---------------------------------------------------------------------------
# TS: пакеты, секции, PES
# ---------------------------------------------------------------------------

class CC:
    """Счётчики непрерывности для PID, которые генерируем сами."""

    def __init__(self):
        self.cc = {}

    def next(self, pid):
        v = self.cc.get(pid, -1)
        v = (v + 1) & 0x0F
        self.cc[pid] = v
        return v


def section_packets(pid, section, cc):
    data = b'\x00' + section
    out = bytearray()
    first = True
    while data:
        chunk, data = data[:184], data[184:]
        hdr = bytes((0x47, (0x40 if first else 0) | (pid >> 8), pid & 255, 0x10 | cc.next(pid)))
        out += hdr + chunk + b'\xff' * (184 - len(chunk))
        first = False
    return bytes(out)


def pes_packets(pid, pes, cc):
    out = bytearray()
    first = True
    while pes:
        chunk, pes = pes[:184], pes[184:]
        b1 = (0x40 if first else 0) | (pid >> 8)
        if len(chunk) == 184:
            out += bytes((0x47, b1, pid & 255, 0x10 | cc.next(pid))) + chunk
        else:
            stuff = 184 - len(chunk)            # >= 1
            if stuff == 1:
                af = b'\x00'
            else:
                af = bytes((stuff - 1, 0x00)) + b'\xff' * (stuff - 2)
            out += bytes((0x47, b1, pid & 255, 0x30 | cc.next(pid))) + af + chunk
        first = False
    return bytes(out)


def long_section(table_id, ext, version, body, private=False):
    length = 5 + len(body) + 4
    head = bytes((
        table_id, 0x80 | (0x40 if private else 0) | 0x30 | (length >> 8), length & 255,
        ext >> 8, ext & 255, 0xC1 | ((version & 0x1F) << 1), 0x00, 0x00))
    sec = head + body
    c = crc32_mpeg(sec)
    return sec + c.to_bytes(4, 'big')


class SectionAssembler:
    def __init__(self):
        self.buf = None

    def feed(self, payload, pusi):
        out = []
        if pusi:
            if not payload:
                return out
            ptr = payload[0]
            if self.buf is not None:
                self.buf += payload[1:1 + ptr]
                out += self._drain()
            self.buf = bytearray(payload[1 + ptr:])
        elif self.buf is not None:
            self.buf += payload
        else:
            return out
        out += self._drain()
        return out

    def _drain(self):
        out = []
        b = self.buf
        while b is not None and len(b) >= 3:
            if b[0] == 0xFF:
                self.buf = None
                return out
            n = ((b[1] & 0x0F) << 8) | b[2]
            if len(b) < 3 + n:
                break
            sec = bytes(b[:3 + n])
            del b[:3 + n]
            if not (sec[1] & 0x80) or crc32_mpeg(sec) == 0:
                out.append(sec)
        return out


def parse_descriptors(data):
    out, i = [], 0
    while i + 2 <= len(data):
        tag, n = data[i], data[i + 1]
        out.append(bytes(data[i:i + 2 + n]))
        i += 2 + n
    return out


def parse_pat(sec):
    progs = []
    for i in range(8, len(sec) - 4, 4):
        progs.append((int.from_bytes(sec[i:i + 2], 'big'), ((sec[i + 2] & 0x1F) << 8) | sec[i + 3]))
    return {'tsid': int.from_bytes(sec[3:5], 'big'), 'version': (sec[5] >> 1) & 0x1F, 'programs': progs}


def parse_pmt(sec):
    pil = ((sec[10] & 0x0F) << 8) | sec[11]
    info = {
        'program': int.from_bytes(sec[3:5], 'big'), 'version': (sec[5] >> 1) & 0x1F,
        'pcr_pid': ((sec[8] & 0x1F) << 8) | sec[9],
        'descs': parse_descriptors(sec[12:12 + pil]), 'es': [],
    }
    i = 12 + pil
    while i + 5 <= len(sec) - 4:
        st = sec[i]
        pid = ((sec[i + 1] & 0x1F) << 8) | sec[i + 2]
        n = ((sec[i + 3] & 0x0F) << 8) | sec[i + 4]
        info['es'].append({'type': st, 'pid': pid, 'descs': parse_descriptors(sec[i + 5:i + 5 + n])})
        i += 5 + n
    return info


def component_tag(es):
    for d in es['descs']:
        if d[0] == 0x52 and len(d) >= 3:
            return d[2]
    return None


def is_caption_es(es):
    tag = component_tag(es)
    if es['type'] != 0x06:
        return False
    for d in es['descs']:
        if d[0] == 0xFD and len(d) >= 4 and d[2:4] == b'\x00\x08':
            return tag is None or 0x30 <= tag <= 0x37
    return tag is not None and 0x30 <= tag <= 0x37


def build_pmt(info, version):
    body = bytearray((0xE0 | (info['pcr_pid'] >> 8), info['pcr_pid'] & 255))
    pd = b''.join(info['descs'])
    body += bytes((0xF0 | (len(pd) >> 8), len(pd) & 255)) + pd
    for es in info['es']:
        ed = b''.join(es['descs'])
        body += bytes((es['type'], 0xE0 | (es['pid'] >> 8), es['pid'] & 255,
                       0xF0 | (len(ed) >> 8), len(ed) & 255)) + ed
    return long_section(0x02, info['program'], version, bytes(body))


def build_pat(tsid, programs, version):
    body = bytearray()
    for num, pid in programs:
        body += bytes((num >> 8, num & 255, 0xE0 | (pid >> 8), pid & 255))
    return long_section(0x00, tsid, version, bytes(body))


def mjd_bcd_to_datetime(b):
    mjd = (b[0] << 8) | b[1]
    if mjd == 0xFFFF:
        return None
    bcd = lambda v: (v >> 4) * 10 + (v & 15)
    try:
        return (datetime.datetime(1858, 11, 17) + datetime.timedelta(days=mjd)
                + datetime.timedelta(hours=bcd(b[2]), minutes=bcd(b[3]), seconds=bcd(b[4])))
    except (ValueError, OverflowError):
        return None


def datetime_to_mjd_bcd(dt):
    mjd = (dt.date() - datetime.date(1858, 11, 17)).days
    bcd = lambda v: ((v // 10) << 4) | (v % 10)
    return bytes((mjd >> 8, mjd & 255, bcd(dt.hour), bcd(dt.minute), bcd(dt.second)))


def read_pcr(pkt):
    if pkt[3] & 0x20 and pkt[4] >= 7 and pkt[5] & 0x10:
        return (pkt[6] << 25) | (pkt[7] << 17) | (pkt[8] << 9) | (pkt[9] << 1) | (pkt[10] >> 7)
    return None


def payload_of(pkt):
    afc = (pkt[3] >> 4) & 3
    if not afc & 1:
        return None
    off = 4 + (1 + pkt[4] if afc & 2 else 0)
    return pkt[off:188] if off < 188 else None


def pes_pts(payload):
    if payload is None or len(payload) < 14 or payload[:3] != b'\x00\x00\x01':
        return None
    if not payload[7] & 0x80:
        return None
    h = payload[9:14]
    return (((h[0] >> 1) & 7) << 30) | (h[1] << 22) | ((h[2] >> 1) << 15) | (h[3] << 7) | (h[4] >> 1)


def iter_packets(path, limit_bytes=None, from_end=None):
    """Отдаёт 188-байтные пакеты; понимает 188/192(TTS)/204(RS) и мусор в начале."""
    with open(path, 'rb') as f:
        head = f.read(204 * 8)
        size, start = None, None
        for sz in (188, 192, 204):
            for off in range(sz):
                tso = off + (4 if sz == 192 else 0)
                if all(tso + k * sz < len(head) and head[tso + k * sz] == 0x47 for k in range(6)):
                    size, start = sz, off
                    break
            if size:
                break
        if size is None:
            raise SystemExit('не найден синхробайт 0x47: это не MPEG-TS?')
        tso = 4 if size == 192 else 0
        if from_end:
            import os
            fsize = os.path.getsize(path)
            start += max(0, (fsize - start - from_end) // size) * size
        f.seek(start)
        total = 0
        carry = b''
        while True:
            chunk = f.read(size * 32768)
            if not chunk:
                break
            data = carry + chunk
            n = len(data) // size
            carry = data[n * size:]
            mv = memoryview(data)
            i = 0
            while i < n:
                o = i * size + tso
                if data[o] != 0x47:
                    # потеря синхронизации: ищем следующий 0x47
                    j = data.find(b'\x47', o + 1)
                    while j != -1 and j + size * 2 < len(data) and not (data[j + size] == 0x47):
                        j = data.find(b'\x47', j + 1)
                    if j == -1:
                        break
                    data = data[j - tso:]
                    n = len(data) // size
                    carry = data[n * size:]
                    mv = memoryview(data)
                    i = 0
                    continue
                yield mv[o:o + 188]
                i += 1
            total += len(chunk)
            if limit_bytes and total >= limit_bytes:
                break


# ---------------------------------------------------------------------------
# SRT
# ---------------------------------------------------------------------------

def parse_srt_time(s):
    m = re.fullmatch(r'\s*(\d+):(\d{1,2}):(\d{1,2})[,.](\d{1,3})\s*', s)
    if not m:
        raise ValueError(s)
    h, mi, se, ms = m.groups()
    return int(h) * 3600 + int(mi) * 60 + int(se) + int(ms.ljust(3, '0')) / 1000


def parse_srt(path, cs):
    text = open(path, encoding='utf-8-sig').read().replace('\r\n', '\n').replace('\r', '\n')
    subs = []
    for block in re.split(r'\n\s*\n', text.strip()):
        rows = block.split('\n')
        k = next((i for i, r in enumerate(rows) if '-->' in r), None)
        if k is None:
            continue
        a, b = rows[k].split('-->')[:2]
        start, end = parse_srt_time(a), parse_srt_time(b.split()[0] if b.split() else b)
        raw = '\n'.join(rows[k + 1:])
        top = bool(re.search(r'\{\\an[789]\}', raw))
        raw = re.sub(r'\{\\[^}]*\}', '', raw)
        lines = []
        for rawline in raw.split('\n'):
            spans, stack = [], [WHF]
            pos = 0
            for m in re.finditer(r'<\s*(/?)\s*(\w+)([^>]*)>', rawline):
                if m.start() > pos:
                    spans.append((cs.normalize(rawline[pos:m.start()]), stack[-1]))
                pos = m.end()
                closing, tag, attrs = m.group(1), m.group(2).lower(), m.group(3)
                if tag == 'font':
                    if closing:
                        if len(stack) > 1:
                            stack.pop()
                    else:
                        cm = re.search(r'color\s*=\s*["\']?([#\w]+)', attrs)
                        stack.append(color_code(cm.group(1)) if cm else stack[-1])
            if pos < len(rawline):
                spans.append((cs.normalize(rawline[pos:]), stack[-1]))
            spans = [(t, c) for t, c in spans if t]
            if spans:
                lines.append(spans)
        if lines and end > start:
            subs.append({'start': start, 'end': end, 'lines': lines, 'top': top})
    subs.sort(key=lambda s: s['start'])
    return subs


# ---------------------------------------------------------------------------
# ASS/SSA: всё, что ARIB STD-B24 умеет, переносим; остальное пропускаем
# ---------------------------------------------------------------------------
#
# Переносится: текст, \N, \h, \q2, выравнивание (\an, \a, стиль), позиция
#   (\pos; у \move — начальная точка), поля MarginL/R/V, основной цвет
#   (\c, \1c, \r, стиль) -> 8 цветов ARIB, размер (\fs, стиль) -> обычный
#   NSZ или малый SSZ, прозрачность \alpha/\1a = FF -> текст не показывается.
# Пропускается: рисунки \p1.., повороты \frz/\frx/\fry, масштаб \fscx/\fscy,
#   наклон \fax/\fay, межбуквенный \fsp, анимации \t, движение \move,
#   затухание \fad/\fade, обводка/тень/размытие, \clip, \org, шрифты \fn,
#   жирный/курсив/подчёркивание, караоке \k, поле Effect, неизвестные теги.
# ARIB показывает один «экран» за раз, поэтому одновременные события
# компонуются в один экран, а покадрово размноженные надписи (трекинг)
# склеиваются в одну статичную.

ASS_TAG_NAMES = sorted([
    'xbord', 'ybord', 'xshad', 'yshad', 'iclip', 'alpha', 'blur', 'bord', 'shad',
    'fscx', 'fscy', 'fade', 'move', 'clip', 'fsp', 'frx', 'fry', 'frz', 'fax', 'fay',
    'pos', 'org', 'pbo', 'fad', 'an', 'fn', 'fs', 'fr', 'fe', 'be', 'kf', 'ko',
    '1c', '2c', '3c', '4c', '1a', '2a', '3a', '4a',
    'a', 'b', 'c', 'i', 'k', 'K', 'p', 'q', 'r', 's', 't', 'u'], key=len, reverse=True)

GRID_COLS = AREA_W // 20      # 31 полуклетка по 20 точек
GRID_ROWS = AREA_H // 30      # 16 полустрок по 30 точек (строка NSZ = 2, SSZ = 1)


ASS_SIGN_WORDS = {'sign', 'signs', 'ts', 'typeset', 'typesetting', 'screen', 'note', 'notes', 'title', 'titles',
                  'logo', 'eyecatch', 'preview', 'next', 'credit', 'credits', 'staff', 'caption', 'captions',
                  'надпись', 'надписи', 'примечание', 'примечания', 'прим', 'титр', 'титры', 'лого', 'анонс',
                  'заголовок', 'подпись', 'подписи', 'вывеска', 'вывески'}
ASS_SONG_WORDS = {'op', 'ed', 'opening', 'ending', 'song', 'songs', 'insert', 'kara', 'karaoke', 'lyrics', 'lyric',
                  'romaji', 'kanji', 'опенинг', 'эндинг', 'песня', 'песни', 'караоке', 'ромадзи'}
ASS_SUBSTR = {'sign': 'надписи', 'надпис': 'надписи', 'typeset': 'надписи', 'karaoke': 'песня', 'караоке': 'песня',
              'opening': 'песня', 'ending': 'песня', 'lyric': 'песня', 'romaji': 'песня'}
ASS_EVENT_SIGN_FEATURES = ('drawing', 'karaoke', 'effect', 'actor', 'rotation', 'clip', 'org', 'shear', 'move', 'pos')


def ass_name_kind(name):
    """'надписи' / 'песня' / None по имени стиля или актёра (FrierenSigns, OP_Romaji, Надписи...)."""
    if not name:
        return None
    spaced = re.sub(r'([a-zа-яё])([A-ZА-ЯЁ])', r'\1 \2', name)
    tokens = set(re.split(r'[^0-9a-zа-яё]+', spaced.lower()))
    if tokens & ASS_SONG_WORDS:
        return 'песня'
    if tokens & ASS_SIGN_WORDS:
        return 'надписи'
    low = name.lower()
    for sub, kind in ASS_SUBSTR.items():
        if sub in low:
            return kind
    return None


def classify_ass_styles(style_stats, only_styles, skip_styles):
    """Стиль -> (реплики?, причина)."""
    out = {}
    for name, c in style_stats.items():
        total = max(1, c['total'])
        plain = c['plain'] / total
        if name in skip_styles:
            out[name] = (False, '--ass-skip-styles')
        elif only_styles:
            out[name] = (name in only_styles, '--ass-only-styles')
        elif ass_name_kind(name):
            out[name] = (False, 'по имени: %s' % ass_name_kind(name))
        elif c['karaoke'] >= 0.3 * total:
            out[name] = (False, 'караоке \\k: песня')
        elif plain >= 0.7 or (c['plain'] >= 20 and plain >= 0.4):
            # надписи внутри стиля реплик отсекаются поштучно, поэтому стиль с
            # большим числом обычных строк — реплики, даже если в нём много надписей
            out[name] = (True, 'обычный текст %d%%' % round(plain * 100))
        else:
            top = max((f for f in ASS_EVENT_SIGN_FEATURES), key=lambda f: c[f])
            out[name] = (False, 'надписи: %s в %d%% событий' % ({
                'pos': '\\pos', 'move': '\\move', 'karaoke': '\\k', 'clip': '\\clip', 'org': '\\org',
                'rotation': 'поворот', 'shear': 'наклон', 'drawing': 'рисунки', 'effect': 'Effect',
                'actor': 'имя «надпись»'}[top], round(c[top] / total * 100)))
    return out


def print_ass_styles(style_stats, verdicts, samples):
    log('%-22s %6s %7s  %-9s %s' % ('Стиль', 'событ.', 'обычн.', 'решение', 'причина / пример'))
    for name, c in sorted(style_stats.items(), key=lambda kv: -kv[1]['total']):
        ok, why = verdicts[name]
        log('%-22s %6d %6d%%  %-9s %s%s' % (name[:22], c['total'], round(100 * c['plain'] / max(1, c['total'])),
                                           'реплики' if ok else 'пропуск', why,
                                           ('  «%s»' % samples.get(name, '')[:40]) if samples.get(name) else ''))


def ass_time(v):
    h, m, sec = v.strip().split(':')
    return int(h) * 3600 + int(m) * 60 + float(sec)


def ass_color(v, default=(255, 255, 255, 0)):
    """'&HAABBGGRR' / '&HBBGGRR&' / десятичное (SSA) -> (r, g, b, alpha)."""
    v = v.strip()
    try:
        if v[:2].upper() == '&H' or v[:1].upper() == 'H':
            n = int(v.upper().lstrip('&').lstrip('H').rstrip('&') or '0', 16)
        else:
            n = int(v)
    except ValueError:
        return default
    return (n & 255, (n >> 8) & 255, (n >> 16) & 255, (n >> 24) & 255)


def ass_alpha(v):
    try:
        return int(v.strip().upper().lstrip('&').lstrip('H').rstrip('&') or '0', 16) & 255
    except ValueError:
        return 0


def rgb_to_arib_on_dark(rgb):
    """Ближайший из 8 цветов; чёрный и синий на тёмной подложке не читаются."""
    code = min(ARIB_COLORS, key=lambda c: sum((a - b) ** 2 for a, b in zip(c[0], rgb[:3])))[1]
    return {BKF: WHF, BLF: CNF}.get(code, code)


def iter_ass_tags(block):
    i = 0
    while True:
        i = block.find('\\', i)
        if i < 0:
            return
        i += 1
        name = next((t for t in ASS_TAG_NAMES if block.startswith(t, i)), None)
        if name is None:
            continue
        i += len(name)
        if i < len(block) and block[i] == '(':
            depth, k = 0, i
            while k < len(block):
                if block[k] == '(':
                    depth += 1
                elif block[k] == ')':
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            yield name, block[i + 1:k]
            i = k + 1
        else:
            k = block.find('\\', i)
            k = len(block) if k < 0 else k
            yield name, block[i:k].strip()
            i = k


def _floats(arg):
    out = []
    for x in arg.split(','):
        try:
            out.append(float(x))
        except ValueError:
            pass
    return out


class AssStats:
    def __init__(self):
        self.ignored = collections.Counter()
        self.dropped = collections.Counter()
        self.info = collections.Counter()

    def report(self):
        d = self.dropped
        log('ASS: событий %d, показано после склейки %d' % (self.info['events'], self.info['kept']))
        if self.info['clustered_from']:
            log('  строки надписей собраны в блоки: %d -> %d' % (self.info['clustered_from'], self.info['clustered_to']))
        if self.info['merged_from']:
            log('  покадровые надписи: %d событий склеены в %d статичных'
                % (self.info['merged_from'], self.info['merged_to']))
        parts = [('стили не-реплик', 'not_dialogue_style'), ('надписи/караоке в стиле реплик', 'sign_in_dialogue_style'),
                 ('рисунки \\p', 'drawing'), ('невидимые (alpha FF)', 'invisible'), ('пустые', 'empty'),
                 ('дубликаты', 'duplicate'), ('Comment', 'comment'), ('стиль отфильтрован', 'style'),
                 ('надписи (--ass-signs skip)', 'sign')]
        txt = ', '.join('%s %d' % (label, d[k]) for label, k in parts if d[k])
        if txt:
            log('  пропущено: ' + txt)
        if self.ignored:
            log('  проигнорированы теги: ' + ', '.join(
                '\\%s×%d' % (k, v) for k, v in self.ignored.most_common()))
        if d['no_space']:
            log('  не хватило места на экране: %d блоков (одновременно слишком много текста)' % d['no_space'])
        if d['short']:
            log('  экранов короче --ass-min-duration: %d (поглощены соседними)' % d['short'])
        log('  экранов ARIB: %d' % self.info['screens'])


def parse_ass(path, cs, args):
    raw = open(path, encoding='utf-8-sig', errors='replace').read()
    stats = AssStats()
    section, info, styles, sfmt, efmt, events = None, {}, {}, None, None, []
    legacy = False
    for n, line in enumerate(raw.splitlines()):
        line = line.strip()
        if not line or line.startswith(';'):
            continue
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1].strip().lower()
            continue
        key, _, val = line.partition(':')
        key = key.strip()
        if section == 'script info':
            info[key.lower()] = val.strip()
        elif section in ('v4+ styles', 'v4 styles', 'v4 styles+'):
            legacy = section == 'v4 styles'
            if key == 'Format':
                sfmt = [f.strip().lower() for f in val.split(',')]
            elif key == 'Style' and sfmt:
                d = dict(zip(sfmt, [x.strip() for x in val.split(',', len(sfmt) - 1)]))
                styles[d.get('name', 'Default')] = d
        elif section == 'events':
            if key == 'Format':
                efmt = [f.strip().lower() for f in val.split(',')]
            elif key == 'Dialogue' and efmt:
                d = dict(zip(efmt, val.lstrip().split(',', len(efmt) - 1)))
                d['_order'] = n
                events.append(d)
            elif key == 'Comment':
                stats.dropped['comment'] += 1

    def num(v, default):
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    prx, pry = num(info.get('playresx'), 0), num(info.get('playresy'), 0)
    if not prx and not pry:
        prx, pry = 384, 288
    elif not prx:
        prx = pry * 4 / 3
    elif not pry:
        pry = prx * 3 / 4
    wrapstyle = int(num(info.get('wrapstyle'), 0))
    default_style = styles.get('Default') or (next(iter(styles.values())) if styles else
                                               {'fontsize': str(pry / 14.4), 'primarycolour': '&H00FFFFFF',
                                                'alignment': '2', 'marginl': '10', 'marginr': '10', 'marginv': '10'})
    skip_styles = set(filter(None, (args.ass_skip_styles or '').split(',')))
    only_styles = set(filter(None, (args.ass_only_styles or '').split(',')))
    stats.info['events'] = len(events)

    def style_align(st):
        a = int(num(st.get('alignment'), 2))
        if legacy:                                   # SSA: 1-3 низ, 5-7 верх, 9-11 середина
            a = (a & 3 or 2) + (6 if a & 4 else 3 if a & 8 else 0)
        return a if 1 <= a <= 9 else 2

    items = []
    style_stats, style_samples = collections.defaultdict(collections.Counter), {}
    dialogue_only = getattr(args, 'ass_dialogue_only', False) or getattr(args, 'ass_list_styles', False)
    for ev in events:
        sname = ev.get('style', 'Default').lstrip('*')
        if not dialogue_only and (sname in skip_styles or (only_styles and sname not in only_styles)):
            stats.dropped['style'] += 1
            continue
        st = styles.get(sname, default_style)
        base_rgb = ass_color(st.get('primarycolour', '&H00FFFFFF'))
        rgb, alpha, fs = base_rgb, base_rgb[3], num(st.get('fontsize'), 20)
        an, pos, drawing, q, frz = None, None, False, wrapstyle, None
        feat = set()
        runs, run_fs = [], None
        text = ev.get('text', '')
        i = 0
        while i < len(text):
            if text[i] == '{' and '}' in text[i:]:
                j = text.index('}', i)
                for name, arg in iter_ass_tags(text[i + 1:j]):
                    if name == 'an':
                        v = int(num(arg, 0))
                        if an is None and 1 <= v <= 9:
                            an = v
                    elif name == 'a':
                        v = int(num(arg, 0))
                        if an is None and v:
                            an = (v & 3 or 2) + (6 if v & 4 else 3 if v & 8 else 0)
                    elif name == 'pos':
                        f = _floats(arg)
                        if pos is None and len(f) >= 2:
                            pos = (f[0], f[1])
                    elif name == 'move':
                        f = _floats(arg)
                        if pos is None and len(f) >= 4:
                            pos = (f[0], f[1])
                        feat.add('move')
                        stats.ignored['move'] += 1
                    elif name in ('c', '1c'):
                        rgb = ass_color(arg, base_rgb)[:3] + (alpha,) if arg else base_rgb
                    elif name in ('1a', 'alpha'):
                        alpha = ass_alpha(arg)
                    elif name == 'r':
                        st2 = styles.get(arg, st) if arg else st
                        base_rgb = ass_color(st2.get('primarycolour', '&H00FFFFFF'))
                        rgb, alpha, fs = base_rgb, base_rgb[3], num(st2.get('fontsize'), fs)
                    elif name == 'fs':
                        fs = num(arg, fs) if arg else num(st.get('fontsize'), fs)
                    elif name == 'p':
                        drawing = num(arg, 0) > 0
                        if drawing:
                            feat.add('drawing')
                    elif name == 'q':
                        q = int(num(arg, wrapstyle))
                    else:
                        if name in ('frz', 'fr') and frz is None:
                            frz = num(arg, 0)       # не рисуем, но нужен для порядка строк надписи
                        if name in ('k', 'K', 'kf', 'ko'):
                            feat.add('karaoke')
                        elif name in ('clip', 'iclip'):
                            feat.add('clip')
                        elif name == 'org':
                            feat.add('org')
                        elif name in ('frz', 'fr', 'frx', 'fry') and num(arg, 0) != 0:
                            feat.add('rotation')
                        elif name in ('fax', 'fay') and num(arg, 0) != 0:
                            feat.add('shear')
                        stats.ignored[name] += 1
                i = j + 1
                continue
            j = text.find('{', i + 1) if text[i] == '{' else text.find('{', i)
            j = len(text) if j < 0 else j
            chunk, i = text[i:j], j
            if drawing:
                if chunk.strip():
                    stats.info['drawing_chunks'] += 1
                continue
            if alpha == 255:
                if chunk.strip():
                    stats.info['invisible_chunks'] += 1
                continue
            chunk = chunk.replace('\\N', '\n').replace('\\h', '\u00a0').replace('\\n', '\n' if q == 2 else ' ')
            if chunk:
                runs.append((chunk, rgb_to_arib_on_dark(rgb)))
                if run_fs is None and chunk.strip():
                    run_fs = fs
        # --- признаки «надписи» у события и статистика по стилю ---
        align0 = an or style_align(st)
        if pos is not None:
            ml0, mr0, mv0 = (max(int(num(ev.get(k), 0)) or int(num(st.get(k), 0)), 0) for k in ('marginl', 'marginr', 'marginv'))
            h0, v0 = (align0 - 1) % 3, (align0 - 1) // 3
            dx = ml0 if h0 == 0 else prx - mr0 if h0 == 2 else (prx + ml0 - mr0) / 2
            dy = pry - mv0 if v0 == 0 else mv0 if v0 == 2 else pry / 2
            if abs(pos[0] - dx) > prx * 0.05 or abs(pos[1] - dy) > pry * 0.05:
                feat.add('pos')                          # \pos в точке стиля по умолчанию надписью не считаем
        effect = ev.get('effect', '').strip().lower()
        if effect.startswith(('fx', 'karaoke', 'template', 'code', 'banner', 'scroll')):
            feat.add('effect')
        if ass_name_kind(ev.get('name', '').strip()):
            feat.add('actor')
        cst = style_stats[sname]
        cst['total'] += 1
        for f in feat:
            cst[f] += 1
        if not feat:
            cst['plain'] += 1
            if sname not in style_samples:
                style_samples[sname] = re.sub(r'\{[^}]*\}', '', text).replace('\\N', ' ')
        lines, cur = [], []
        for chunk, col in runs:
            parts = chunk.split('\n')
            for k, part in enumerate(parts):
                if k:
                    lines.append(cur)
                    cur = []
                part = cs.normalize(part)
                if part:
                    cur.append((part, col))
        lines.append(cur)
        for ln in lines:                              # пробелы по краям строки не нужны
            while ln and not ln[0][0].lstrip(' '):
                ln.pop(0)
            if ln:
                ln[0] = (ln[0][0].lstrip(' '), ln[0][1])
            while ln and not ln[-1][0].rstrip(' '):
                ln.pop()
            if ln:
                ln[-1] = (ln[-1][0].rstrip(' '), ln[-1][1])
        while lines and not ''.join(t for t, _ in lines[0]).strip():
            lines.pop(0)
        while lines and not ''.join(t for t, _ in lines[-1]).strip():
            lines.pop()
        if not lines:
            if stats.info['drawing_chunks'] and re.search(r'\\p[1-9]', text):
                stats.dropped['drawing'] += 1
            elif re.search(r'\\(1a|alpha)&?H?FF', text, re.I) or base_rgb[3] == 255:
                stats.dropped['invisible'] += 1
            else:
                stats.dropped['empty'] += 1
            continue
        if pos is not None and args.ass_signs == 'skip' and not dialogue_only:
            stats.dropped['sign'] += 1
            continue
        if pos is not None and args.ass_signs == 'top':
            pos, an = None, 8
        align = an or style_align(st)
        ml, mr, mv = (int(num(ev.get(k), 0)) or int(num(st.get(k), 0)) for k in ('marginl', 'marginr', 'marginv'))
        ml, mr, mv = max(ml, 0), max(mr, 0), max(mv, 0)
        h, v = (align - 1) % 3, (align - 1) // 3        # h: 0 лево 1 центр 2 право; v: 0 низ 1 середина 2 верх
        if pos is None:
            x = ml if h == 0 else prx - mr if h == 2 else (prx + ml - mr) / 2
            y = pry - mv if v == 0 else mv if v == 2 else pry / 2
        else:
            x, y = pos
        size_plane = (run_fs or fs) * 540 / pry
        items.append({
            'start': ass_time(ev.get('start', '0:00:00.00')), 'end': ass_time(ev.get('end', '0:00:00.00')),
            'layer': int(num(ev.get('layer'), 0)), 'style': sname, 'order': ev['_order'],
            'lines': lines, 'h': h, 'v': v, 'positioned': pos is not None,
            'x': x * 960 / prx - AREA_X, 'y': y * 540 / pry - AREA_Y,
            'small': args.ass_small == 'ssz' and size_plane < CHAR_H * 0.75,
            'fsz': size_plane, 'frz': frz or 0.0, 'feat': feat,
        })

    if dialogue_only:
        verdicts = classify_ass_styles(style_stats, only_styles, skip_styles)
        if getattr(args, 'ass_list_styles', False):
            print_ass_styles(style_stats, verdicts, style_samples)
            return None
        kept = []
        for it in items:
            if not verdicts.get(it['style'], (False,))[0]:
                stats.dropped['not_dialogue_style'] += 1
            elif it['feat']:
                stats.dropped['sign_in_dialogue_style'] += 1
            else:
                it['positioned'] = False
                kept.append(it)
        items = kept
        log('ASS, только реплики — стили:')
        print_ass_styles(style_stats, verdicts, style_samples)
    items = [it for it in items if it['end'] > it['start']]
    items = merge_tracked(items, stats)
    items = cluster_signs(items, stats)
    stats.info['kept'] = len(items)
    screens = compose_screens(items, cs, args, stats)
    stats.info['screens'] = len(screens)
    stats.report()
    return screens


def _item_key(it):
    return (it['style'], it['layer'], it['h'], it['v'], it['small'], it['positioned'],
            tuple(tuple(ln) for ln in it['lines']))


def merge_tracked(items, stats):
    """Склеивает покадровые копии (одинаковый текст/стиль, стык по времени)
    в одно событие; позиция — медианная. Убирает точные дубликаты."""
    items.sort(key=lambda it: (it['start'], it['order']))
    open_by_key, out = {}, []
    for it in items:
        key = _item_key(it)
        prev = open_by_key.get(key)
        if prev is not None and it['start'] - prev['end'] <= 0.1 and it['start'] >= prev['start']:
            if it['start'] == prev['start'] and it['end'] == prev['end'] and not prev['_xs'][1:]:
                stats.dropped['duplicate'] += 1           # тот же текст в то же время (например, два слоя)
                continue
            prev['end'] = max(prev['end'], it['end'])
            prev['_xs'].append(it['x'])
            prev['_ys'].append(it['y'])
            prev['_n'] += 1
            continue
        it['_xs'], it['_ys'], it['_n'] = [it['x']], [it['y']], 1
        open_by_key[key] = it
        out.append(it)
    for it in out:
        if it['_n'] > 1:
            stats.info['merged_from'] += it['_n']
            stats.info['merged_to'] += 1
            it['x'] = sorted(it['_xs'])[len(it['_xs']) // 2]
            it['y'] = sorted(it['_ys'])[len(it['_ys']) // 2]
    return out


def _block(it, cs):
    """Событие -> блок: строки, ширины, размер в клетках сетки и якорь."""
    small = it['small']
    unit = 1 if small else 2
    width = (lambda c: 1) if small else cs.width
    lines = []
    for spans in it['lines']:
        lines.extend(ln for ln in wrap_line(spans, cs, small) if ln)
    lines = lines[:GRID_ROWS // unit]
    if not lines:
        return None
    lw = [sum(width(c) for c, _ in ln) for ln in lines]
    w, hgt = max(lw), len(lines) * unit
    c_raw = round(it['x'] / 20 - (0, w / 2, w)[it['h']])
    c0 = min(max(c_raw, 0), GRID_COLS - w)
    r0 = round(it['y'] / 30 - (hgt, hgt / 2, 0)[it['v']])
    if unit == 2:
        r0 -= r0 % 2                     # обычный размер — только на сетке строк 60 точек (для APS)
    return {'it': it, 'lines': lines, 'lw': lw, 'w': w, 'hgt': hgt, 'unit': unit, 'c': c0, 'r': r0,
            'c_raw': c_raw, 'ax': round(it['x'] / 20)}


def _free(grid, r, b):
    return 0 <= r <= GRID_ROWS - b['hgt'] and not any(
        grid[rr][cc] for rr in range(r, r + b['hgt']) for cc in range(b['c'], b['c'] + b['w']))


def _occupy(grid, b, placed):
    for rr in range(b['r'], b['r'] + b['hgt']):
        for cc in range(b['c'], b['c'] + b['w']):
            grid[rr][cc] = True
    for k, ln in enumerate(b['lines']):
        col = b['c'] + (0, (b['w'] - b['lw'][k]) // 2, b['w'] - b['lw'][k])[b['it']['h']]
        placed.append((AREA_X + col * 20, AREA_Y + (b['r'] + k * b['unit'] + b['unit']) * 30 - 1, b['it']['small'], ln))


def cluster_signs(items, stats):
    """Строки одной надписи (часто это отдельные события с \\pos) собираются
    в один блок. Порядок строк — вдоль нормали к повёрнутой (\\frz) строке,
    соседние строки не дальше ~2 межстрочных интервалов."""
    out = [it for it in items if not it['positioned']]
    groups = collections.defaultdict(list)
    for it in items:
        if it['positioned']:
            groups[(it['style'], it['start'], it['end'], it['small'], round(it['frz']))].append(it)
    for its in groups.values():
        th = math.radians(sum(i['frz'] for i in its) / len(its))
        normal = lambda i: i['x'] * math.sin(th) + i['y'] * math.cos(th)
        along = lambda i: i['x'] * math.cos(th) - i['y'] * math.sin(th)
        its.sort(key=lambda i: (normal(i), i['order']))
        clusters = []
        for it in its:
            c = clusters[-1] if clusters else None
            if c and normal(it) - normal(c[-1]) <= 2.2 * max(it['fsz'], c[-1]['fsz']) \
                    and abs(along(it) - along(c[0])) <= 240:
                c.append(it)
            else:
                clusters.append([it])
        for c in clusters:
            if len(c) == 1:
                out.append(c[0])
                continue
            first = c[0]
            merged = dict(first)
            merged['lines'] = [ln for i in c for ln in i['lines']]
            merged['y'] = first['y'] - (first['fsz'], first['fsz'] / 2, 0)[first['v']]
            merged['v'] = 2                            # якорь — верх первой строки
            stats.info['clustered_from'] += len(c)
            stats.info['clustered_to'] += 1
            out.append(merged)
    out.sort(key=lambda it: (it['start'], it['order']))
    return out


def layout_screen(active, cs, stats):
    """Размещает одновременные события в сетке 31x16 без наложений:
    сначала обычные (диалог; одинаково выровненные стопкой, как в libass),
    затем позиционированные надписи — группой, с сохранением их взаимного
    расположения; при конфликте с диалогом группа сдвигается целиком."""
    grid = [[False] * GRID_COLS for _ in range(GRID_ROWS)]
    placed = []
    normal = sorted((it for it in active if not it['positioned']), key=lambda it: (it['start'], it['order']))
    signs = [it for it in active if it['positioned']]
    for it in normal:
        b = _block(it, cs)
        if b is None:
            continue
        r0 = min(max(b['r'], 0), GRID_ROWS - b['hgt'])
        step = (-1 if it['v'] == 0 else 1) * b['unit']   # снизу — стопка вверх, сверху — вниз
        row = next((r for d in range(GRID_ROWS) for r in ((r0 + step * d, r0 - step * d) if d else (r0,))
                    if _free(grid, r, b)), None)
        if row is None:
            stats.dropped['no_space'] += 1
            continue
        b['r'] = row
        _occupy(grid, b, placed)
    blocks = [b for b in (_block(it, cs) for it in signs) if b]
    # соседние надписи с одинаковым выравниванием (например, строки одной
    # карточки) сдвигаем от края экрана вместе, чтобы не рассыпать выравнивание
    for b in blocks:
        cluster = [o for o in blocks if o['it']['h'] == b['it']['h'] and abs(o['ax'] - b['ax']) <= 8]
        over = max(o['c_raw'] + o['w'] - GRID_COLS for o in cluster)
        under = min(o['c_raw'] for o in cluster)
        shift = over if over > 0 else under if under < 0 else 0
        b['c'] = min(max(b['c_raw'] - shift, 0), GRID_COLS - b['w'])
    blocks.sort(key=lambda b: (b['r'], b['c'], -b['it']['layer'], b['it']['order']))
    group = []
    for b in blocks:                                # раздвигаем надписи вниз, не меняя порядок
        while any(g['r'] < b['r'] + b['hgt'] and b['r'] < g['r'] + g['hgt'] and
                  g['c'] < b['c'] + b['w'] and b['c'] < g['c'] + g['w'] for g in group):
            b['r'] += b['unit']
        group.append(b)
    while group:
        top = min(b['r'] for b in group)
        bottom = max(b['r'] + b['hgt'] for b in group)
        if bottom - top <= GRID_ROWS:
            break
        group.pop()                                 # группа выше экрана — жертвуем последними
        stats.dropped['no_space'] += 1
    if group:
        top = min(b['r'] for b in group)
        bottom = max(b['r'] + b['hgt'] for b in group)
        lo, hi = -top, GRID_ROWS - bottom           # допустимые сдвиги всей группы
        base = min(max(0, lo), hi)
        even = any(b['unit'] == 2 for b in group)
        for d in sorted(range(lo, hi + 1), key=lambda d: (abs(d - base), d > base)):
            if even and d % 2:
                continue
            if all(_free(grid, b['r'] + d, b) for b in group):
                for b in group:
                    b['r'] += d
                    _occupy(grid, b, placed)
                group = []
                break
        for b in group:                             # целиком не влезла — по одной
            r0 = min(max(b['r'], 0), GRID_ROWS - b['hgt'])
            u = b['unit']
            row = next((r for d in range(GRID_ROWS) for r in ((r0 - d * u, r0 + d * u) if d else (r0,))
                        if _free(grid, r, b)), None)
            if row is None:
                stats.dropped['no_space'] += 1
                continue
            b['r'] = row
            _occupy(grid, b, placed)
    placed.sort(key=lambda p: (p[1], p[0]))
    return placed


def compose_screens(items, cs, args, stats):
    bounds = sorted({it['start'] for it in items} | {it['end'] for it in items})
    screens, cache = [], {}
    for a, b in zip(bounds, bounds[1:]):
        active = [it for it in items if it['start'] <= a and it['end'] >= b]
        if not active:
            continue
        key = tuple(sorted(id(it) for it in active))
        placed = cache.get(key)
        if placed is None:
            placed = cache[key] = layout_screen(active, cs, stats)
        if not placed:
            continue
        if screens and abs(screens[-1]['end'] - a) < 1e-6 and screens[-1]['placed'] == placed:
            screens[-1]['end'] = b
            continue
        screens.append({'start': a, 'end': b, 'placed': placed})
    # короткие экраны (стыки строк, хвосты надписей) поглощаются предыдущим
    out = []
    for sc in screens:
        if sc['end'] - sc['start'] < args.ass_min_duration:
            stats.dropped['short'] += 1
            if out and abs(out[-1]['end'] - sc['start']) < 1e-6:
                out[-1]['end'] = sc['end']
            continue
        if out and abs(out[-1]['end'] - sc['start']) < 1e-6 and out[-1]['placed'] == sc['placed']:
            out[-1]['end'] = sc['end']
            continue
        out.append(sc)
    return out


# ---------------------------------------------------------------------------
# Управление копированием: digital_copy_control (0xC1) и content_availability (0xDE)
# ---------------------------------------------------------------------------
#
# 0xC1 (ARIB STD-B10): digital_recording_control_data в старших двух битах —
# именно его смотрит приёмник, решая, можно ли писать на D-VHS по i.LINK.
# 0xDE: content_availability — ограничения на выход и «временную» запись.
# Значения переносятся из входного потока как есть; ключи ниже их меняют.
# На реальном i.LINK поверх этого работает шифрование DTCP, и режим на шине
# задаёт передающее устройство, так что биты в потоке — это сигнализация,
# а не сама защита. Для записи, снятой из эфира, они отражают условия вещателя.

# Младшие 4 бита дескриптора 0xC1 в стандарте названы user_defined, но
# эксплуатационные правила ARIB задают их смысл: старшие два — copy_control_type
# (как выдавать наружу), младшие два — APS_control_data (защита аналогового
# выхода). Значение 00 у copy_control_type не определено, и приёмник трактует
# его как самый строгий режим — поэтому «copy free» с нулевым нибблом ведёт
# себя как «копирование запрещено».
CCT_NAMES = {0b00: 'не задан (приёмник считает содержимое защищённым)',
             0b01: 'выход шифруется (DTCP)',
             0b10: 'зарезервировано',
             0b11: 'выход без шифрования'}
CCT_ARG = {'auto': None, 'protected': 0b01, 'free': 0b11, '00': 0b00, '01': 0b01, '10': 0b10, '11': 0b11}

DRC_NAMES = {0b00: 'копирование свободно (制限なし)',
             0b01: 'по усмотрению вещателя',
             0b10: 'одна копия (一世代のみ)',
             0b11: 'копирование запрещено (複製禁止)'}
COPY_ARG = {'free': 0b00, 'broadcaster': 0b01, 'once': 0b10, 'never': 0b11,
            '00': 0b00, '01': 0b01, '10': 0b10, '11': 0b11}


EPN_CONTENT_AVAILABILITY = 0xEE   # как 0xEF у вещателя, но encryption_mode = 0


def apply_epn(a):
    """--epn: «копируй свободно, но выдавай под защитой» (EPN). Одного
    copy_control_type для этого мало: защиту выхода включает бит
    encryption_mode = 0 в дескрипторе 0xDE, и без него приёмник отдаёт
    поток в открытом виде — проверено на JVC HM-DHX1."""
    if not getattr(a, 'epn', False):
        return
    if a.copy is None:
        a.copy = 'free'
    if a.copy_control_type is None:
        a.copy_control_type = 'protected'
    if a.content_availability is None:
        a.content_availability = EPN_CONTENT_AVAILABILITY


def copy_control_requested(a):
    return any(getattr(a, k, None) is not None
               for k in ('copy', 'user_defined', 'content_availability', 'aps'))


def wanted_cct(a):
    """copy_control_type: по умолчанию «без шифрования» для free и «с шифрованием»
    для остальных режимов — так это передаёт вещание."""
    if a.copy_control_type is not None:
        return CCT_ARG[a.copy_control_type]
    if a.copy is None:
        return None
    return 0b11 if COPY_ARG[a.copy] == 0b00 else 0b01


def patch_copy_descriptor(d, a):
    """0xC1/0xDE -> изменённый дескриптор (структура и хвост сохраняются)."""
    if d[0] == 0xC1 and len(d) >= 3:
        v = d[2]
        if a.copy is not None:
            v = (v & 0x3F) | (COPY_ARG[a.copy] << 6)
        cct = wanted_cct(a)
        if cct is not None:
            v = (v & 0xF3) | (cct << 2)
        if a.aps is not None:
            v = (v & 0xFC) | (a.aps & 0x03)
        if a.user_defined is not None:
            v = (v & 0xF0) | (a.user_defined & 0x0F)
        return d[:2] + bytes((v,)) + d[3:]
    if d[0] == 0xDE and len(d) >= 3 and a.content_availability is not None:
        return d[:2] + bytes((a.content_availability & 0xFF,)) + d[3:]
    return d


def apply_copy_control(descs, a, create=False):
    """Меняет 0xC1/0xDE в списке дескрипторов; create — добавить, если их нет."""
    out = [patch_copy_descriptor(d, a) for d in descs]
    have = {d[0] for d in out}
    if create:
        if 0xC1 not in have and (a.copy is not None or a.user_defined is not None
                                 or a.copy_control_type is not None or a.aps is not None):
            v = COPY_ARG[a.copy] << 6 if a.copy is not None else 0
            cct = wanted_cct(a)
            if cct is not None:
                v |= cct << 2
            if a.aps is not None:
                v |= a.aps & 0x03
            if a.user_defined is not None:
                v = (v & 0xF0) | (a.user_defined & 0x0F)
            out.append(bytes((0xC1, 1, v)))
        if 0xDE not in have and a.content_availability is not None:
            out.append(bytes((0xDE, 1, a.content_availability & 0xFF)))
    return out


def copy_control_values(descs):
    """{tag: первый байт полезной нагрузки} для 0xC1/0xDE."""
    out = {}
    for d in descs:
        if d[0] in (0xC1, 0xDE) and len(d) >= 3:
            out.setdefault(d[0], d[2])
    return out


def describe_copy_control(vals, indent='  ', show=print):
    if 0xC1 in vals:
        v = vals[0xC1]
        show('%sdigital_copy_control (0xC1) = 0x%02X (%08s)' % (indent, v, format(v, '08b')))
        show('%s    digital_recording_control_data = %02s  %s' % (indent, format(v >> 6, '02b'), DRC_NAMES[v >> 6]))
        show('%s    maximum_bitrate_flag = %d, component_control_flag = %d'
             % (indent, (v >> 5) & 1, (v >> 4) & 1))
        show('%s    copy_control_type = %02s  %s' % (indent, format((v >> 2) & 3, '02b'), CCT_NAMES[(v >> 2) & 3]))
        show('%s    APS_control_data = %02s%s' % (indent, format(v & 3, '02b'),
                                                 '  (аналоговый выход без ограничений)' if not v & 3 else ''))
    else:
        show('%sdigital_copy_control (0xC1): нет' % indent)
    if 0xDE in vals:
        v = vals[0xDE]
        show('%scontent_availability (0xDE) = 0x%02X (%08s)' % (indent, v, format(v, '08b')))
        show('%s    copy_restriction_mode = %d, image_constraint_token = %d, retention_mode = %d, '
             'retention_state = %03s, encryption_mode = %d'
             % (indent, (v >> 6) & 1, (v >> 5) & 1, (v >> 4) & 1, format((v >> 1) & 7, '03b'), v & 1))
    else:
        show('%scontent_availability (0xDE): нет' % indent)


def patch_pmt_section_inplace(sec, a):
    """Меняет 0xC1/0xDE прямо в секции PMT и пересчитывает CRC. -> (секция, изменённых битов)."""
    buf = bytearray(sec)
    bits = 0

    def walk(start, end):
        nonlocal bits
        q = start
        while q + 2 <= end:
            tag, ln = buf[q], buf[q + 1]
            if tag in (0xC1, 0xDE) and ln >= 1:
                old = bytes(buf[q:q + 2 + ln])
                new = patch_copy_descriptor(old, a)
                if new != old:
                    bits += sum(bin(x ^ y).count('1') for x, y in zip(old, new))
                    buf[q:q + 2 + ln] = new
            q += 2 + ln

    pil = ((buf[10] & 0x0F) << 8) | buf[11]
    walk(12, 12 + pil)
    q, stop = 12 + pil, len(buf) - 4
    while q + 5 <= stop:
        esil = ((buf[q + 3] & 0x0F) << 8) | buf[q + 4]
        walk(q + 5, q + 5 + esil)
        q += 5 + esil
    if bits:
        buf[-4:] = crc32_mpeg(bytes(buf[:-4])).to_bytes(4, 'big')
    return bytes(buf), bits


def iter_records(path):
    """(запись, смещение 188-байтного пакета внутри неё) — включая голову файла
    до первого синхробайта и неполный хвост (у них смещение None)."""
    with open(path, 'rb') as f:
        head = f.read(204 * 8)
        size = start = None
        for sz in (188, 192, 204):
            for off in range(sz):
                tso = off + (4 if sz == 192 else 0)
                if all(tso + k * sz < len(head) and head[tso + k * sz] == 0x47 for k in range(6)):
                    size, start = sz, off
                    break
            if size:
                break
        if size is None:
            raise SystemExit('не найден синхробайт 0x47: это не MPEG-TS?')
        f.seek(0)
        yield f.read(start), None
        tso = 4 if size == 192 else 0
        while True:
            rec = f.read(size)
            if len(rec) < size:
                if rec:
                    yield rec, None
                return
            yield rec, (tso if rec[tso] == 0x47 else None)


def diff_files(a, b):
    """Побайтовое сравнение: сплошные участки различий и номера TS-пакетов."""
    fa, fb = open(a, 'rb'), open(b, 'rb')
    pos, runs, cur, nbits = 0, [], None, 0
    while True:
        x, y = fa.read(1 << 16), fb.read(1 << 16)
        if not x and not y:
            break
        if len(x) != len(y):
            print('файлы разной длины')
        for i in range(min(len(x), len(y))):
            if x[i] != y[i]:
                nbits += bin(x[i] ^ y[i]).count('1')
                if cur is not None and pos + i == cur[1] + 1:
                    cur = (cur[0], pos + i)
                else:
                    if cur:
                        runs.append(cur)
                    cur = (pos + i, pos + i)
        pos += len(x)
    if cur:
        runs.append(cur)
    print('различающихся участков: %d, битов: %d' % (len(runs), nbits))
    for st, en in runs[:6]:
        print('  смещение %d..%d (%d байт, TS-пакет #%d)' % (st, en, en - st + 1, st // TS))
    if len(runs) > 6:
        print('  ... и ещё %d' % (len(runs) - 6))


# ---------------------------------------------------------------------------
# Дескрипторы SIT / DIT
# ---------------------------------------------------------------------------

def partial_ts_descriptor(peak_rate_bps):
    peak = min(0x3FFFFF, -(-peak_rate_bps // 400))
    v = (0x3 << 62) | (peak << 40) | (0x3 << 38) | (0x3FFFFF << 16) | (0x3 << 14) | 0x3FFF
    return b'\x63\x08' + v.to_bytes(8, 'big')


def network_identification_descriptor(network_id, media_type, country=b'JPN'):
    body = country + media_type + network_id.to_bytes(2, 'big')
    return bytes((0xC2, len(body))) + body


def partial_ts_time_descriptor(event, jst, event_version):
    body = bytearray((event_version & 0xFF,))
    if event:
        body += event['start'] + event['duration']
    else:
        body += b'\xff' * 8
    body += b'\x00\x00\x00'                                  # offset
    body.append(0xF8 | (1 if jst else 0))                    # reserved, offset_flag=0, other_descriptor_status=0, JST_time_flag
    if jst:
        body += datetime_to_mjd_bcd(jst)
    return bytes((0xC3, len(body))) + bytes(body)


def caption_groups(tracks):
    """Дорожки, сгруппированные по ES: [(pid, tag, [дорожки])]."""
    out = []
    for tr in tracks:
        for g in out:
            if g[0] == tr.pid:
                g[2].append(tr)
                break
        else:
            out.append((tr.pid, tr.tag, [tr]))
    return out


def set_caption_data_content(descs, tracks):
    """Дескриптор данных (0xC7) на каждую субтитровую дорожку: у заменённых ES
    язык переписывается на язык новой дорожки, недостающие добавляются."""
    groups = {tag: [t.lang for t in trs] for _pid, tag, trs in caption_groups(tracks)}
    out, seen = [], set()
    for d in descs:
        if d[0] == 0xC7 and len(d) > 4 and d[2:4] == b'\x00\x08' and d[4] in groups:
            out.append(data_content_descriptor_caption(d[4], langs=groups[d[4]]))
            seen.add(d[4])
        else:
            out.append(d)
    for tag, langs in groups.items():
        if tag not in seen:
            out.append(data_content_descriptor_caption(tag, langs=langs))
    return out


def data_content_descriptor_caption(tag, dmf=0b0011, lang=b'jpn', langs=None):
    langs = [bytes(lang)] if not langs else [bytes(x) for x in langs]
    sel = bytes((len(langs),))
    for t, lg in enumerate(langs):
        sel += bytes(((t << 5) | 0x10 | dmf,)) + lg
    body = b'\x00\x08' + bytes((tag, len(sel))) + sel + b'\x00' + langs[0] + b'\x00'
    return bytes((0xC7, len(body))) + body


def dit_section(transition=True):
    return bytes((0x7E, 0x70, 0x01, 0xFF if transition else 0x7F))


def media_type_for(network_id):
    if network_id in (0x0004, 0x0006, 0x0007):
        return b'BS'            # BS / широкополосный CS (110°)
    if network_id in (0x0001, 0x0003, 0x000A):
        return b'CS'            # узкополосный CS
    if network_id == 0x000B:
        return b'AB'            # 4K/8K BS
    if network_id == 0x000C:
        return b'AC'            # 4K CS
    if 0x7880 <= network_id <= 0x7FE8:
        return b'TB'            # наземное
    return None


DVHS_MODES = [('HS', 28.2e6), ('STD', 14.1e6)]


# ---------------------------------------------------------------------------
# Полный набор SI, как у BS-вещателя (--si broadcast): NIT, SDT, EIT, TOT, BIT
# ---------------------------------------------------------------------------
#
# Модель — таблицы из японского эфира (ARIB STD-B10): network_name и
# system_management в NIT, service_list и satellite_delivery_system для TS,
# service_descriptor в SDT, EIT[p/f] и базовое расписание EIT (0x50) с
# short_event/component/audio_component/content/data_content, TOT с JST,
# BIT с SI_parameter (периоды повтора) и broadcaster_name. Периоды повтора —
# как объявлено в BIT образца: NIT и BIT 10 с, SDT и EIT[p/f] 3 с.
# Не генерируются: ECM/EMM (условный доступ), SDTT (обновления ПО приёмников),
# CDT (логотипы), карусели данных BML — это не описание потока, а контент.

# Как те же значения называет таблица DVB (EN 300 468). Плееры и MediaInfo
# берут названия оттуда, поэтому «кино» ARIB они покажут как music/ballet/dance.
DVB_GENRE_NAMES = {
    0x0: 'undefined', 0x1: 'Movie/Drama', 0x2: 'News/Current affairs', 0x3: 'Show/Game show',
    0x4: 'Sports', 0x5: "Children's/Youth", 0x6: 'Music/Ballet/Dance', 0x7: 'Arts/Culture',
    0x8: 'Social/Political/Economics', 0x9: 'Education/Science/Factual', 0xA: 'Leisure hobbies',
    0xB: 'Special characteristics', 0xF: 'Other',
}

GENRES = {   # ARIB STD-B10, content_nibble_level_1/level_2
    'news': 0x00, 'sports': 0x10, 'info': 0x20, 'drama': 0x30, 'music': 0x40,
    'variety': 0x50, 'movie': 0x60, 'anime': 0x70, 'anime-foreign': 0x71, 'tokusatsu': 0x72,
    'documentary': 0x80, 'theatre': 0x90, 'hobby': 0xA0, 'welfare': 0xB0, 'other': 0xFF,
}
SI_PERIODS = {'nit': 10, 'bit': 10, 'sdt': 3, 'eit_pf': 3, 'eit_sched': 10, 'tot': 5}
PID_BIT = 0x0024
BS_SATELLITE_DELIVERY = bytes.fromhex('43 0b 01 17 27 48 11 00 e8 02 88 60 08')  # BS 110°E, 11.72748 ГГц — из образца


def section_n(table_id, ext, version, body, sec_num, last_sec, private=True):
    length = 5 + len(body) + 4
    head = bytes((
        table_id, 0x80 | (0x40 if private else 0) | 0x30 | (length >> 8), length & 255,
        ext >> 8, ext & 255, 0xC1 | ((version & 0x1F) << 1), sec_num, last_sec))
    sec = head + body
    return sec + crc32_mpeg(sec).to_bytes(4, 'big')


def _loop(descs):
    d = b''.join(descs)
    return bytes((0xF0 | (len(d) >> 8), len(d) & 255)) + d


def bcd_duration(seconds):
    seconds = max(0, int(round(seconds)))
    h, m, s = seconds // 3600, seconds // 60 % 60, seconds % 60
    bcd = lambda v: ((v // 10) << 4) | (v % 10)
    return bytes((bcd(min(h, 99)), bcd(m), bcd(s)))


def nit_section(network_id, name, tsid, services, media, version, cs):
    descs = []
    if name:
        n = arib_string(name, cs)
        descs.append(bytes((0x40, len(n))) + n)
    if media in (b'BS', b'TB'):
        descs.append(bytes((0xFE, 2, 0x02 if media == b'BS' else 0x03, 0x01)))   # system_management
    sl = b''.join(sid.to_bytes(2, 'big') + bytes((stype,)) for sid, stype in services)
    ts_descs = [bytes((0x41, len(sl))) + sl]
    if media == b'BS':
        ts_descs.append(BS_SATELLITE_DELIVERY)
    ts = tsid.to_bytes(2, 'big') + network_id.to_bytes(2, 'big') + _loop(ts_descs)
    body = _loop(descs) + bytes((0xF0 | (len(ts) >> 8), len(ts) & 255)) + ts
    return section_n(0x40, network_id, version, body, 0, 0)


def sdt_section(tsid, onid, sid, descs, schedule, version):
    d = b''.join(descs)
    body = onid.to_bytes(2, 'big') + b'\xff' + sid.to_bytes(2, 'big')
    body += bytes((0xFC | (2 if schedule else 0) | 1, 0x00 | (len(d) >> 8), len(d) & 255)) + d
    return section_n(0x42, tsid, version, body, 0, 0)


def eit_event_bytes(ev):
    d = b''.join(ev['descs'])
    return (ev['event_id'].to_bytes(2, 'big') + ev['start'] + ev['duration'] +
            bytes(((ev.get('running', 0) << 5) | (len(d) >> 8), len(d) & 255)) + d)


def fit_event_descs(descs, room, warn=log):
    """Обрезает хвост описания (0x4E), чтобы событие влезло в секцию."""
    descs = list(descs)
    while sum(len(d) for d in descs) > room:
        idx = max((i for i, d in enumerate(descs) if d[0] == 0x4E), default=None)
        if idx is None:
            idx = len(descs) - 1
            if idx < 0:
                break
        warn('описание передачи не помещается в секцию EIT — хвост отброшен')
        del descs[idx]
    last = sum(1 for d in descs if d[0] == 0x4E) - 1
    k = 0
    for i, d in enumerate(descs):                 # перенумеровать оставшиеся части
        if d[0] == 0x4E:
            descs[i] = d[:2] + bytes(((k << 4) | last,)) + d[3:]
            k += 1
    return descs


def eit_pf_sections(sid, tsid, onid, present, following, version):
    out = []
    for n, ev in enumerate((present, following)):
        body = tsid.to_bytes(2, 'big') + onid.to_bytes(2, 'big') + bytes((1, 0x4E))
        if ev:
            ev = dict(ev, descs=fit_event_descs(ev['descs'], 4096 - 12 - 5 - len(body) - 12))
            body += eit_event_bytes(ev)
        out.append(section_n(0x4E, sid, version, body, n, 1))
    return out


def eit_schedule_sections(sid, tsid, onid, events, now, version):
    """Базовое расписание (table_id 0x50..): сегменты по 3 часа от полуночи JST."""
    midnight = datetime.datetime(now.year, now.month, now.day)
    segs = collections.defaultdict(list)
    for ev in events:
        st = mjd_bcd_to_datetime(ev['start'])
        if st is None:
            continue
        seg = int((st - midnight).total_seconds() // (3 * 3600))
        if 0 <= seg < 64:
            segs[seg].append(ev)
    if not segs:
        return []
    tables = sorted({0x50 + seg // 32 for seg in segs})
    out = []
    for seg in sorted(segs):
        segs[seg] = [dict(e, descs=fit_event_descs(e['descs'], 3900 // max(1, len(segs[seg]))))
                     for e in segs[seg]]
        tid = 0x50 + seg // 32
        num = (seg % 32) * 8
        last = max((s % 32) * 8 for s in segs if 0x50 + s // 32 == tid)
        body = tsid.to_bytes(2, 'big') + onid.to_bytes(2, 'big') + bytes((num, tables[-1]))
        body += b''.join(eit_event_bytes(ev) for ev in segs[seg])
        out.append(section_n(tid, sid, version, body, num, last))
    return out


def tot_section(jst):
    sec = bytes((0x73, 0x70, 0x0B)) + datetime_to_mjd_bcd(jst) + b'\xf0\x00'
    return sec + crc32_mpeg(sec).to_bytes(4, 'big')


def bit_section(onid, broadcaster_id, broadcaster_name, services, update, version, cs):
    periods = [(0x40, SI_PERIODS['nit']), (0xC4, SI_PERIODS['bit']), (0x42, SI_PERIODS['sdt']),
               (0x4E, SI_PERIODS['eit_pf'])]
    bcd = lambda v: ((v // 10) << 4) | (v % 10)
    sip = bytes((0,)) + datetime_to_mjd_bcd(update)[:2] + b''.join(bytes((t, 1, bcd(v))) for t, v in periods)
    first = bytes((0xD7, len(sip))) + sip
    bdesc = []
    if broadcaster_name:
        n = arib_string(broadcaster_name, cs)
        bdesc.append(bytes((0xD8, len(n))) + n)
    sl = b''.join(sid.to_bytes(2, 'big') + bytes((stype,)) for sid, stype in services)
    bdesc.append(bytes((0x41, len(sl))) + sl)
    bd = b''.join(bdesc)
    body = bytes((0xF0 | (len(first) >> 8), len(first) & 255)) + first
    body += bytes((broadcaster_id, 0xF0 | (len(bd) >> 8), len(bd) & 255)) + bd
    return section_n(0xC4, onid, version, body, 0, 0)


def superimpose_pes(lang=b'jpn'):
    """Асинхронный PES (stream_id 0xBF) только с caption_management_data —
    ровно так вещатель держит «пустой» поток суперимпоза (文字スーパー)."""
    dg = data_group(0x00, bytes((0x3F, 0x01, 0x12)) + lang + b'\x80\x00\x00\x00')
    payload = b'\x81\xff\xf0' + dg
    return b'\x00\x00\x01\xbf' + len(payload).to_bytes(2, 'big') + payload


def parse_video_info(data, stream_type):
    """Разрешение/развёртка/аспект из MPEG-2 sequence header (H.264 — грубо)."""
    info = {}
    if stream_type in (0x01, 0x02):
        i = data.find(b'\x00\x00\x01\xb3')
        if i >= 0 and i + 12 <= len(data):
            b = data[i + 4:i + 8]
            info['w'] = (b[0] << 4) | (b[1] >> 4)
            info['h'] = ((b[1] & 15) << 8) | b[2]
            info['aspect'] = b[3] >> 4                   # 2 = 4:3, 3 = 16:9
            j = data.find(b'\x00\x00\x01\xb5', i)
            if j >= 0 and j + 6 <= len(data) and data[j + 4] >> 4 == 1:
                info['progressive'] = bool(data[j + 5] & 0x08)
    return info


def video_component_type(info):
    h, prog, wide = info.get('h', 0), info.get('progressive', False), info.get('aspect', 3) != 2
    if h >= 1000:
        base, fmt = (0xE0, 0b0000) if prog else (0xB0, 0b0001)
    elif h >= 700:
        base, fmt = 0xC0, 0b0010
    elif h >= 400:
        base, fmt = (0xA0, 0b0011) if prog else (0x00, 0b0100)
    else:
        base, fmt = 0xD0, 0b0101
    return base | (3 if wide else 1), fmt


def parse_audio_info(data, stream_type):
    info = {}
    if stream_type in (0x0F, 0x11):
        i = data.find(b'\xff')
        while 0 <= i < len(data) - 7:
            if data[i + 1] & 0xF6 == 0xF0:              # ADTS
                sf = (data[i + 2] >> 2) & 15
                info['rate'] = [96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000][sf] if sf < 9 else 48000
                info['ch'] = ((data[i + 2] & 1) << 2) | (data[i + 3] >> 6)
                break
            i = data.find(b'\xff', i + 1)
    elif stream_type in (0x03, 0x04):
        i = data.find(b'\xff')
        while 0 <= i < len(data) - 4:
            if data[i + 1] & 0xE0 == 0xE0 and data[i + 2] >> 4 not in (0, 15):
                rates = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000]}.get(data[i + 1] >> 3 & 3, [44100, 48000, 32000])
                info['rate'] = rates[(data[i + 2] >> 2) & 3] if (data[i + 2] >> 2) & 3 < 3 else 48000
                info['ch'] = 1 if data[i + 3] >> 6 == 3 else 2
                break
            i = data.find(b'\xff', i + 1)
    return info


def audio_component_descriptors(pmt_info, audio, audio_langs, names=None, only_tags=None, cs=None):
    """audio_component_descriptor (0xC4) для каждого звукового ES в порядке PMT:
    первый — основной (main_component_flag), язык и название — по дорожкам."""
    descs, n = [], 0
    for es in pmt_info['es']:
        tag = component_tag(es)
        if (es['type'] in AUDIO_TYPES or is_audio_es(es)) and tag is not None:
            if only_tags is None or tag in only_tags:
                a = audio.get(es['pid'], {})
                ch = a.get('ch', 2)
                ctype = {1: 0x01, 2: 0x03}.get(ch, 0x09 if ch >= 6 else 0x03)
                rate_code = {16000: 1, 22050: 2, 24000: 3, 32000: 5, 44100: 6, 48000: 7}.get(a.get('rate', 48000), 7)
                main = 1 if n == 0 else 0
                lang = per_track(audio_langs, n, b'jpn')
                body = bytes((0xF2, ctype, tag, es['type'], 0xFF, (main << 6) | (0b10 << 4) | (rate_code << 1) | 1)) + lang
                name = (names or {}).get(tag)
                if name and cs is not None:
                    body += arib_string(name, cs)[:255 - len(body)]
                descs.append(bytes((0xC4, len(body))) + body)
            n += 1
    return descs


def event_component_descriptors(pmt_info, video, audio, cap_tags, lang, audio_langs, genre, have_superimpose):
    descs = []
    for es in pmt_info['es']:
        tag = component_tag(es)
        if es['type'] in VIDEO_TYPES and tag is not None:
            ctype, _ = video_component_type(video.get(es['pid'], {}))
            content = 0x05 if es['type'] == 0x1B else 0x01
            descs.append(bytes((0x50, 6, 0xF0 | content, ctype, tag)) + b'jpn')
    descs += audio_component_descriptors(pmt_info, audio, audio_langs, AUDIO_NAMES, None, AUDIO_CS)
    descs.append(bytes((0x54, 2, genre, 0xFF)))
    for tag, tlangs in (cap_tags or []):
        descs.append(data_content_descriptor_caption(tag, langs=tlangs))
    return descs


# ---------------------------------------------------------------------------
# Замена звука: WAV -> MPEG-2 AAC-LC в ADTS с CRC, упаковка как у BS-вещателя
# ---------------------------------------------------------------------------
#
# Образец (BS, PID 0x110): ADTS MPEG-2 (ID=1), AAC-LC, 48 кГц, стерео,
# protection_absent=0 (CRC-16 в каждом кадре), ~256 кбит/с. PES фиксированного
# размера 736 байт = ровно 4 TS-пакета, заголовок всегда 7 байт: PTS + 2 байта
# заполнения или 7 байт заполнения, если в PES не начинается ни один кадр;
# PTS — первого кадра, начинающегося в PES. PES приходит за ~0.16 с до PTS.
# Такой ADTS с корректной CRC делает fdkaac (-p 129 -C); встроенный AAC
# ffmpeg CRC не пишет — тогда ставится только ID=1, protection_absent=1.

AUDIO_PES_SIZE = 736
AUDIO_LEAD = 0.16
def per_track(values, n, default=None):
    """Значение для n-й дорожки из списка «a,b,c» (последнее повторяется)."""
    if not values:
        return default
    return values[min(n, len(values) - 1)]


def split_list(text, conv=str):
    return [conv(x.strip()) for x in str(text).split(',') if x.strip()] if text not in (None, '') else []


class TrackAction(argparse.Action):
    """--audio / --audio-wav / --audio-aac пишут в один упорядоченный список."""

    def __call__(self, parser, ns, value, option):
        kind = {'--audio-wav': 'wav', '--audio-aac': 'aac', '--audio-mp2': 'mp2',
                '--audio-pcm': 'pcm', '--audio-ac3': 'ac3'}.get(option)
        if kind is None:
            low = value.lower()
            kind = ('aac' if low.endswith(('.aac', '.adts')) else
                    'ac3file' if low.endswith(('.ac3', '.eac3')) else
                    'mp2file' if low.endswith(('.mp2', '.mpa', '.m2a')) else 'wav')
        elif kind == 'mp2' and value.lower().endswith(('.mp2', '.mpa', '.m2a')):
            kind = 'mp2file'
        elif kind == 'ac3' and value.lower().endswith(('.ac3', '.eac3')):
            kind = 'ac3file'
        lst = list(getattr(ns, self.dest, None) or [])
        lst.append((kind, value))
        setattr(ns, self.dest, lst)


AUDIO_NAMES, AUDIO_CS = {}, None      # component_tag -> название дорожки; кодировщик строк

# Отсчётов задержки кодировщика, измерено на щелчке через полный цикл кодирование->
# декодирование. Для готового файла кодировщик неизвестен: у Layer II задержка задана
# самим форматом (фильтрбанк), поэтому она одна для всех; у AAC зависит от кодировщика,
# и 2048 — самое частое значение (fdkaac, Apple, Nero), у ffmpeg 1024.
AAC_ENCODER_DELAY = {'fdkaac': 2048, 'ffmpeg': 1024, 'file': 2048}
MP2_ENCODER_DELAY = {'libtwolame': 482, 'mp2': 482, 'file': 482}
AC3_ENCODER_DELAY = {'ffmpeg': 256, 'file': 256}                  # измерено на щелчке


def is_audio_es(es):
    if es['type'] in AUDIO_TYPES or es['type'] in (0x82, 0x83, 0x87):
        return True
    if es['type'] == 0x06:
        for d in es['descs']:
            if d[0] in (0x6A, 0x7A, 0x7B, 0x7C) or (d[0] == 0x05 and d[2:6] in (b'AC-3', b'EAC3', b'DTS1')):
                return True
    return False


def adts_extra(head):
    """Поля ADTS, которые проверяет IEC 60774-5: наполнение буфера, профиль, блоки."""
    return {'buffer_fullness': ((head[5] & 0x1F) << 6) | (head[6] >> 2),
            'profile': (head[2] >> 6) + 1,
            'blocks': (head[6] & 3) + 1}


def adts_frames(data):
    """-> список (offset, length) и параметры первого кадра."""
    frames, i, info = [], 0, None
    while i + 7 <= len(data):
        if data[i] != 0xFF or data[i + 1] & 0xF6 != 0xF0:
            j = data.find(b'\xff', i + 1)
            if j < 0:
                break
            i = j
            continue
        length = ((data[i + 3] & 3) << 11) | (data[i + 4] << 3) | (data[i + 5] >> 5)
        if length < 7 or i + length > len(data):
            break
        if info is None:
            sf = (data[i + 2] >> 2) & 15
            info = {'rate': [96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000][sf],
                    'ch': ((data[i + 2] & 1) << 2) | (data[i + 3] >> 6),
                    'mpeg2': bool(data[i + 1] & 0x08), 'crc': not (data[i + 1] & 1),
                    'profile': data[i + 2] >> 6}
        frames.append((i, length))
        i += length
    return frames, info


MPA_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}
MPA_BITRATES = {   # (версия MPEG-1?, слой) -> таблица индексов
    (1, 1): [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448],
    (1, 2): [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384],
    (1, 3): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    (0, 1): [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256],
    (0, 2): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
}


def mpa_frames(data):
    """Кадры MPEG-1/2 Audio (Layer I/II/III) -> [(offset, length)] и параметры."""
    frames, i, info = [], 0, None
    while i + 4 <= len(data):
        if data[i] != 0xFF or (data[i + 1] & 0xE0) != 0xE0:
            j = data.find(b'\xff', i + 1)
            if j < 0:
                break
            i = j
            continue
        ver, layer = (data[i + 1] >> 3) & 3, 4 - ((data[i + 1] >> 1) & 3)
        br_i, sr_i, pad = data[i + 2] >> 4, (data[i + 2] >> 2) & 3, (data[i + 2] >> 1) & 1
        if ver == 1 or layer == 4 or br_i in (0, 15) or sr_i == 3:
            i += 1
            continue
        mpeg1 = ver == 3
        table = MPA_BITRATES.get((1 if mpeg1 else 0, 3 if layer == 3 else layer))
        rate = MPA_RATES[ver if ver in MPA_RATES else 3][sr_i]
        if table is None:
            i += 1
            continue
        kbps = table[br_i]
        if layer == 1:
            length = (12 * kbps * 1000 // rate + pad) * 4
            spf = 384
        else:
            spf = 1152 if (mpeg1 or layer == 2) else 576
            length = (spf // 8) * kbps * 1000 // rate + pad
        if length < 4 or i + length > len(data):
            break
        if info is None:
            mode = (data[i + 3] >> 6) & 3
            info = {'rate': rate, 'ch': 1 if mode == 3 else 2, 'layer': layer, 'mpeg1': mpeg1,
                    'kbps': kbps, 'spf': spf, 'crc': not (data[i + 1] & 1), 'mpeg2': mpeg1, 'profile': 0}
        frames.append((i, length))
        i += length
    return frames, info


def encode_wav_to_mp2(path, encoder, bitrate, channels, warn):
    """WAV -> MPEG-1 Layer II 48 кГц (для дек, которые не понимают AAC)."""
    import os
    import shutil
    import subprocess
    import tempfile
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise SystemExit('для MP2 нужен ffmpeg')
    codec = encoder if encoder != 'auto' else (
        'libtwolame' if 'libtwolame' in subprocess.run([ffmpeg, '-hide_banner', '-encoders'],
                                                       capture_output=True, text=True).stdout else 'mp2')
    ch = channels or (wav_channels(path) or 2)
    if ch > 2:
        warn('%s: Layer II многоканальный звук не несёт — сведено в стерео' % path)
        ch = 2
    limit = 384 if ch == 2 else 192
    if bitrate > limit:
        warn('%s: для MP2 %d кан. максимум %d кбит/с' % (path, ch, limit))
        bitrate = limit
    tmp = tempfile.NamedTemporaryFile(suffix='.mp2', delete=False)
    tmp.close()
    try:
        cmd = [ffmpeg, '-v', 'error', '-y', '-i', path, '-vn', '-ar', '48000', '-ac', str(ch),
               '-c:a', codec, '-b:a', '%dk' % bitrate]
        if codec == 'libtwolame':
            cmd += ['-error_protection', '1']     # IEC 60774-5: CRC обязателен
        cmd += ['-f', 'mp2', tmp.name]
        subprocess.run(cmd, check=True)
        data = bytearray(open(tmp.name, 'rb').read())
    except subprocess.CalledProcessError as e:
        raise SystemExit('кодирование MP2 не удалось: %s' % e)
    finally:
        os.unlink(tmp.name)
    return data, codec


AC3_BITRATES = [32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, 448, 512, 576, 640]
AC3_RATES = {0: 48000, 1: 44100, 2: 32000}
AC3_ACMOD_CH = [2, 1, 2, 3, 3, 4, 4, 5]   # 1+1, 1/0, 2/0, 3/0, 2/1, 3/1, 2/2, 3/2


def ac3_frames(data):
    """Кадры AC-3 (ATSC A/52) -> [(смещение, длина)] и параметры потока."""
    frames, i, info = [], 0, None
    while i + 8 <= len(data):
        if data[i] != 0x0B or data[i + 1] != 0x77:
            j = data.find(b'\x0b\x77', i + 1)
            if j < 0:
                break
            i = j
            continue
        fscod, frmsizecod = data[i + 4] >> 6, data[i + 4] & 0x3F
        if fscod == 3 or frmsizecod >= 38:
            i += 2
            continue
        rate = AC3_RATES[fscod]
        kbps = AC3_BITRATES[frmsizecod >> 1]
        words = {0: kbps * 2, 1: (kbps * 1536 // 44100 + (frmsizecod & 1)) or 1, 2: kbps * 3}[fscod]
        if fscod == 1:                       # 44,1 кГц: размер зависит от бита чётности
            words = (1536 * kbps * 1000 // 44100 // 16 + (frmsizecod & 1))
        length = words * 2
        if length < 8 or i + length > len(data):
            break
        if info is None:
            bsid, bsmod = data[i + 5] >> 3, data[i + 5] & 7
            acmod = data[i + 6] >> 5
            bit = 6 * 8 + 3
            if (acmod & 1) and acmod != 1:
                bit += 2                     # cmixlev
            if acmod & 4:
                bit += 2                     # surmixlev
            if acmod == 2:
                bit += 2                     # dsurmod
            lfeon = (data[bit // 8] >> (7 - bit % 8)) & 1
            info = {'rate': rate, 'kbps': kbps, 'acmod': acmod, 'lfe': lfeon, 'bsid': bsid,
                    'bsmod': bsmod, 'ch': AC3_ACMOD_CH[acmod] + lfeon, 'crc': True,
                    'mpeg1': True, 'mpeg2': True, 'spf': 1536}
        frames.append((i, length))
        i += length
    return frames, info


def encode_wav_to_ac3(path, bitrate, channels, warn):
    """WAV -> Dolby Digital 48 кГц (ATSC A/52), как на лентах D-Theater."""
    import os
    import shutil
    import subprocess
    import tempfile
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise SystemExit('для AC-3 нужен ffmpeg')
    ch = channels or (wav_channels(path) or 2)
    if ch not in (1, 2, 6):
        warn('%s: %d каналов сведены в стерео' % (path, ch))
        ch = 2
    if bitrate > 640:
        warn('%s: D-VHS допускает для AC-3 не больше 640 кбит/с' % path)
        bitrate = 640
    tmp = tempfile.NamedTemporaryFile(suffix='.ac3', delete=False)
    tmp.close()
    try:
        subprocess.run([ffmpeg, '-v', 'error', '-y', '-i', path, '-vn', '-ar', '48000', '-ac', str(ch),
                        '-c:a', 'ac3', '-b:a', '%dk' % bitrate, '-f', 'ac3', tmp.name], check=True)
        data = bytearray(open(tmp.name, 'rb').read())
    except subprocess.CalledProcessError as e:
        raise SystemExit('кодирование AC-3 не удалось: %s' % e)
    finally:
        os.unlink(tmp.name)
    return data, 'ffmpeg'


def wav_channels(path):
    import wave
    try:
        with wave.open(path, 'rb') as w:
            return w.getnchannels()
    except (wave.Error, EOFError, OSError):
        return None


def encode_wav_to_adts(path, encoder, bitrate, channels, warn):
    import os
    import shutil
    import subprocess
    import tempfile
    import wave
    ffmpeg, fdk = shutil.which('ffmpeg'), shutil.which('fdkaac')
    if encoder == 'auto':
        encoder = 'fdkaac' if fdk else 'ffmpeg' if ffmpeg else None
        if encoder is None:
            raise SystemExit('для --audio-wav нужен fdkaac (лучше, с CRC как у вещателя) или ffmpeg')
    rate = ch = None
    try:
        with wave.open(path, 'rb') as w:
            rate, ch = w.getframerate(), w.getnchannels()
    except (wave.Error, EOFError):
        pass
    if channels:
        out_ch = channels
    elif ch in (1, 2, 6):
        out_ch = ch                      # 5.1 сохраняем: ARIB его допускает (3/2+LFE)
    elif ch:
        out_ch = 2
        warn('%s: %d каналов сведены в стерео (ARIB знает 1, 2 и 6)' % (path, ch))
    else:
        out_ch = 2
    if out_ch == 6 and bitrate < 320:
        warn('5.1 на %d кбит/с — маловато; в японском вещании это 384–448' % bitrate)
    tmp = tempfile.NamedTemporaryFile(suffix='.aac', delete=False)
    tmp.close()
    try:
        if encoder == 'fdkaac':
            if not fdk:
                raise SystemExit('fdkaac не найден в PATH')
            base = [fdk, '-p', '129', '-f', '2', '-C', '-m', '0', '-b', str(bitrate * 1000), '-S', '-o', tmp.name]
            if rate == 48000 and ch == out_ch:
                subprocess.run(base + [path], check=True)   # WAV с маской каналов: порядок сохраняется
            else:
                if not ffmpeg:
                    raise SystemExit('WAV не 48 кГц/%d кан.: для пересчёта нужен ffmpeg' % out_ch)
                dec = subprocess.Popen([ffmpeg, '-v', 'error', '-i', path, '-ar', '48000', '-ac', str(out_ch),
                                        '-f', 's16le', '-'], stdout=subprocess.PIPE)
                subprocess.run(base + ['-R', '--raw-channels', str(out_ch), '--raw-rate', '48000',
                                       '--raw-format', 'S16L', '-'], stdin=dec.stdout, check=True)
                dec.stdout.close()
                if dec.wait():
                    raise SystemExit('ffmpeg не смог прочитать %s' % path)
        else:
            if not ffmpeg:
                raise SystemExit('ffmpeg не найден в PATH')
            warn('AAC кодируется ffmpeg: без CRC в ADTS (у вещателя CRC есть; поставьте fdkaac)')
            subprocess.run([ffmpeg, '-v', 'error', '-y', '-i', path, '-ar', '48000', '-ac', str(out_ch),
                            '-c:a', 'aac', '-b:a', '%dk' % bitrate, '-f', 'adts', tmp.name], check=True)
        data = bytearray(open(tmp.name, 'rb').read())
    except subprocess.CalledProcessError as e:
        raise SystemExit('кодирование звука не удалось: %s' % e)
    finally:
        os.unlink(tmp.name)
    return data, encoder


class CaptionTrack:
    """Один субтитровый ES: своя раскладка событий, PID, component_tag и язык."""

    def __init__(self, path, subs, lang):
        self.path, self.subs, self.lang = path, subs, lang
        self.pid = self.tag = None
        self.lang_tag = 0
        self.replaced_pid = None
        self.offset = 0.0
        self.events = []
        self.next_mgmt = 0
        self.mgmt_sent = False
        self.count = {'show': 0, 'clear': 0}
        self.skipped = 0

    def schedule(self, T0, cs, warn):
        ev = []
        off = self.offset
        subs = self.subs
        for i, sub in enumerate(subs):
            t_show = T0 + int(round((sub['start'] + off) * 90000))
            t_end = T0 + int(round((sub['end'] + off) * 90000))
            w = lambda m, i=i: warn('%s, субтитр #%d: %s' % (os.path.basename(self.path), i + 1, m))
            ev.append((t_show, 1, build_statement(sub, cs, w, self.lang_tag), 'show', t_end))
            nxt = subs[i + 1]['start'] + off if i + 1 < len(subs) else None
            if nxt is None or nxt - (sub['end'] + off) >= 0.1:
                ev.append((t_end, 0, build_clear_statement(self.lang_tag), 'clear', t_end))
        ev.sort(key=lambda e: (e[0], e[1]))
        self.events = ev


BIT_REVERSE = [int('{:08b}'.format(i)[::-1], 2) for i in range(256)]
PCM_SAMPLES_PER_PES = 1600        # 33,3 мс — как кадр видео, так делает дека


def pack_smpte302(samples, status_first=True):
    """16-битные стереопары -> SMPTE 302M: 5 байт на пару, по 20 бит на канал.

    Два порядка внутри 20-битного поля:
      status_first=True  — 4 служебных бита, затем 16 бит звука младшим вперёд.
                           Так пишет D-VHS (проверено на записи с деки: корреляция
                           с дорожкой MP2 того же файла 0,98).
      status_first=False — как кодирует ffmpeg: сначала звук, потом служебные.
    """
    out = bytearray()
    for l, r in samples:
        a = (BIT_REVERSE[l & 0xFF] << 8) | BIT_REVERSE[(l >> 8) & 0xFF]
        b = (BIT_REVERSE[r & 0xFF] << 8) | BIT_REVERSE[(r >> 8) & 0xFF]
        if not status_first:
            a <<= 4
            b <<= 4
        out += (((a & 0xFFFFF) << 20) | (b & 0xFFFFF)).to_bytes(5, 'big')
    return bytes(out)


def unpack_smpte302(data, status_first=True):
    out = []
    for i in range(0, len(data) // 5 * 5, 5):
        v = int.from_bytes(data[i:i + 5], 'big')
        pair = []
        for f in ((v >> 20) & 0xFFFFF, v & 0xFFFFF):
            if not status_first:
                f >>= 4
            x = BIT_REVERSE[(f >> 8) & 0xFF] | (BIT_REVERSE[f & 0xFF] << 8)
            pair.append(x - 65536 if x >= 32768 else x)
        out.append(tuple(pair))
    return out


def read_pcm_48k(path, ffmpeg, warn):
    """Любой файл -> список стереопар 16 бит 48 кГц (через ffmpeg)."""
    import struct
    import subprocess
    try:
        res = subprocess.run([ffmpeg, '-v', 'error', '-i', path, '-vn', '-ar', '48000',
                              '-ac', '2', '-f', 's16le', '-'], capture_output=True)
    except OSError:
        raise SystemExit('для PCM нужен ffmpeg (или укажите --ffmpeg)')
    if res.returncode != 0 or not res.stdout:
        raise SystemExit('не удалось прочитать %r:\n%s' % (path, res.stderr.decode(errors='replace')))
    raw = res.stdout
    n = len(raw) // 4
    v = struct.unpack('<%dh' % (n * 2), raw[:n * 4])
    return list(zip(v[0::2], v[1::2]))


class PcmTrack:
    """Линейный PCM по SMPTE 302M — тот самый звук, которым дека пишет в STD
    и который встречается на лентах D-Theater. stream_type 0x83, PES 0xBD."""

    codec = 'pcm'
    stream_type = 0x83
    source = 'pcm'
    delay = 0

    def __init__(self, samples, status_first=True):
        self.samples = samples
        self.status_first = status_first
        self.info = {'rate': 48000, 'ch': 2, 'crc': True, 'kbps': 1536,
                     'mpeg1': True, 'mpeg2': True, 'profile': 2,
                     'buffer_fullness': 0, 'blocks': 1, 'bits': 16}
        self.bitrate = None

    def schedule(self, start_T, first_T):
        step = PCM_SAMPLES_PER_PES
        self.pes_list = []
        pos = 0
        while pos < len(self.samples):
            chunk = self.samples[pos:pos + step]
            self.pes_list.append((pos, chunk))
            pos += step
        # отбрасываем то, что оказалось бы раньше начала видео
        self.pes_list = [(o, c) for o, c in self.pes_list
                         if start_T + o * 90000 // 48000 >= first_T]
        self.start_T = start_T
        self.packets = []                       # (время доставки, PES-индекс)
        self.built = {}
        self.nchunks = len(self.pes_list)
        self.next = 0
        self.pending = []                       # (срок, TS-пакет) — раздаём по одному
        self.duration = len(self.samples) / 48000.0
        self.chunk = step

    def deliver_time(self, j):
        off = self.pes_list[j][0]
        return self.start_T + off * 90000 // 48000 - int(AUDIO_LEAD * 90000)

    def pes(self, j, offset):
        off, chunk = self.pes_list[j]
        body = pack_smpte302(chunk, self.status_first)
        head = bytes((len(body) >> 8, len(body) & 255, 0x00, 0x00))   # SMPTE 302M
        payload = head + body
        pts = self.start_T + off * 90000 // 48000 - offset
        hdr = bytes((0x87, 0x80, 0x0F)) + encode_pts(pts) + b'\xff' * 10   # как у деки
        n = len(hdr) + len(payload)
        return b'\x00\x00\x01\xbd' + bytes((n >> 8, n & 255)) + hdr + payload

    def tail_pes(self, offset):
        return None


class AudioTrack:
    """Один звуковой ES (AAC ADTS или MPEG-1 Layer II) и его нарезка на PES."""

    def __init__(self, data, source, delay, codec='aac'):
        if codec == 'ac3':
            frames, info = ac3_frames(data)
            if not frames or not info:
                raise SystemExit('в звуке не найдено кадров AC-3')
            self.samples_per_frame = info['spf']
            self.stream_type = 0x81
        elif codec == 'mp2':
            frames, info = mpa_frames(data)
            if not frames or not info:
                raise SystemExit('в звуке не найдено кадров MPEG audio')
            if info['layer'] != 2:
                raise SystemExit('нужен MPEG Layer II, а найден Layer %s' % 'I II III'.split()[info['layer'] - 1])
            self.samples_per_frame = info['spf']
            self.stream_type = 0x03 if info['mpeg1'] else 0x04
        else:
            frames, info = adts_frames(data)
            if not frames or not info:
                raise SystemExit('в звуке не найдено кадров ADTS')
            if not info['mpeg2'] and not info['crc']:
                for off, _ in frames:                   # ID=1 (MPEG-2), как в эфире; без CRC это безопасно
                    data[off + 1] |= 0x08
                info['mpeg2'] = True
            self.samples_per_frame = 1024
            self.stream_type = 0x0F
            info.update(adts_extra(data[frames[0][0]:frames[0][0] + 7]))
        covered = sum(n for _, n in frames)
        if covered < 0.5 * len(data) or len(frames) < 2:
            raise SystemExit('%s: файл не похож на поток %s — распознано лишь %d кадров (%d из %d байт)'
                             % ('звук', {'mp2': 'MPEG Layer II', 'ac3': 'AC-3'}.get(codec, 'ADTS AAC'),
                                len(frames), covered, len(data)))
        self.codec = codec
        self.data, self.frames, self.info, self.source, self.delay = data, frames, info, source, delay

    def schedule(self, start_T, first_T):
        """PTS кадров от start_T (T-шкала), отбрасывая кадры до первого PCR."""
        rate = self.info['rate']
        k0 = 0
        pts = [start_T + round((k * self.samples_per_frame - self.delay) * 90000 / rate) for k in range(len(self.frames))]
        while k0 < len(pts) and pts[k0] < first_T:
            k0 += 1
        self.dropped_head = k0
        keep = self.frames[k0:]
        self.pts = pts[k0:]
        base = keep[0][0] if keep else 0
        self.es = bytes(self.data[base:keep[-1][0] + keep[-1][1]]) if keep else b''
        self.starts = [off - base for off, _ in keep]
        self.chunk = AUDIO_PES_SIZE - 9 - 7
        self.nchunks = -(-len(self.es) // self.chunk)
        self.next = 0
        self.duration = len(keep) * self.samples_per_frame / rate

    def deliver_time(self, j):
        import bisect
        k = bisect.bisect_right(self.starts, j * self.chunk) - 1
        return self.pts[max(k, 0)] - int(AUDIO_LEAD * 90000)

    def stream_id(self):
        return 0xBD if self.codec == 'ac3' else 0xC0

    def tail_pes(self, offset):
        """Если отправка остановилась посреди кадра — дослать его до конца (короткий PES)."""
        import bisect
        pos = self.next * self.chunk
        if self.next == 0 or pos >= len(self.es):
            return None
        k = bisect.bisect_right(self.starts, pos) - 1
        end = self.starts[k + 1] if k + 1 < len(self.starts) else len(self.es)
        if self.starts[k] == pos or end <= pos:
            return None
        payload = self.es[pos:end]
        hdr = b'\x80\x00\x07' + b'\xff' * 7
        n = len(hdr) + len(payload)
        return bytes((0x00, 0x00, 0x01, self.stream_id())) + bytes((n >> 8, n & 255)) + hdr + payload

    def pes(self, j, offset):
        import bisect
        lo, hi = j * self.chunk, (j + 1) * self.chunk
        k = bisect.bisect_left(self.starts, lo)
        payload = self.es[lo:hi]
        if k < len(self.starts) and self.starts[k] < hi:
            opt = encode_pts(self.pts[k] - offset) + b'\xff\xff'
            hdr = b'\x80\x80\x07' + opt
        else:
            hdr = b'\x80\x00\x07' + b'\xff' * 7
        n = len(hdr) + len(payload)
        return bytes((0x00, 0x00, 0x01, self.stream_id())) + bytes((n >> 8, n & 255)) + hdr + payload


def pcr_only_packet(pkt):
    """Пакет старого звукового PID, несущий PCR: оставляем только adaptation field."""
    afl = pkt[4]
    af = bytes(pkt[5:5 + afl])
    return bytes((0x47, pkt[1] & 0x1F, pkt[2], 0x20, 183)) + af + b'\xff' * (183 - afl)


# ---------------------------------------------------------------------------
# Предварительный анализ
# ---------------------------------------------------------------------------

class Probe:
    def __init__(self, path, service_id=None, limit=96 * 1024 * 1024):
        self.path = path
        self.pat = None
        self.pmts = {}
        self.nit_id = None
        self.sdt = {}            # sid -> [descriptors]
        self.eit = {}            # sid -> event dict
        self.tot = None          # (datetime, pcr)
        self.has_sit = False
        self.pcr_pid = None
        self.av_pids = []
        self.es_head = {}        # pid -> первые байты ES (для разрешения/каналов)
        self.first_pcr = None
        self.last_pcr = None
        self.first_pts = {}      # pid -> первый PTS (аудио/видео PES)
        self.first_pcr_pid = {}  # pid -> первый PCR
        self.buckets = []        # по 0.5 с: {pid: пакетов}
        self.service_id = service_id
        self._scan(limit)

    def _scan(self, limit):
        asm = {}
        cur_pcr = None
        bucket = None
        bucket_start = None
        for pkt in iter_packets(self.path, limit):
            pid = ((pkt[1] & 0x1F) << 8) | pkt[2]
            pusi = pkt[1] & 0x40
            if pkt[3] & 0x20:
                pcr = read_pcr(pkt)
                if pcr is not None and pid not in self.first_pcr_pid:
                    self.first_pcr_pid[pid] = pcr
            if pusi and pid not in self.first_pts:
                pl = payload_of(pkt)
                if pl is not None and len(pl) > 4 and 0xC0 <= pl[3] <= 0xEF:
                    pts = pes_pts(pl)
                    if pts is not None:
                        self.first_pts[pid] = pts
            if self.pmts and self.pcr_pid is None:
                svc = self.select_service(quiet=True)
                if svc:
                    self.pcr_pid = self.pmts[svc[1]]['pcr_pid']
                    self.av_pids = [e['pid'] for e in self.pmts[svc[1]]['es']
                                    if e['type'] in VIDEO_TYPES or e['type'] in AUDIO_TYPES]
            if pid == self.pcr_pid:
                pcr = read_pcr(pkt)
                if pcr is not None:
                    if self.first_pcr is None:
                        self.first_pcr = self.first_pcr_pid.get(pid, pcr)
                    self.last_pcr = pcr
                    cur_pcr = pcr
                    if bucket_start is None or (pcr - bucket_start) % PTS_WRAP >= 45000:
                        bucket = {}
                        self.buckets.append(bucket)
                        bucket_start = pcr
            if bucket is not None:
                bucket[pid] = bucket.get(pid, 0) + 1
            if pid in self.av_pids and len(self.es_head.get(pid, b'')) < 262144:
                pl = payload_of(pkt)
                if pl is not None and (pid in self.es_head or pusi):
                    self.es_head.setdefault(pid, bytearray()).extend(pl)
            if pid == PID_SIT:
                self.has_sit = True
            watch = pid in (PID_PAT, PID_NIT, PID_SDT, PID_EIT, PID_TOT) or (
                self.pat and pid in [p for n, p in self.pat['programs'] if n])
            if not watch:
                continue
            pl = payload_of(pkt)
            if pl is None:
                continue
            for sec in asm.setdefault(pid, SectionAssembler()).feed(bytes(pl), pusi):
                self._section(pid, sec, cur_pcr)
            if self._done():
                break

    def _section(self, pid, sec, pcr):
        tid = sec[0]
        if pid == PID_PAT and tid == 0x00:
            self.pat = parse_pat(sec)
        elif tid == 0x02:
            info = parse_pmt(sec)
            info['pid'] = pid
            self.pmts[pid] = info
        elif pid == PID_NIT and tid == 0x40:
            self.nit_id = int.from_bytes(sec[3:5], 'big')
        elif pid == PID_SDT and tid == 0x42:
            parse_sdt(sec, self.sdt)
        elif pid == PID_EIT and tid == 0x4E and sec[6] == 0:
            ev = parse_eit_present(sec)
            if ev:
                self.eit[ev['sid']] = ev
        elif pid == PID_TOT and tid in (0x70, 0x73) and pcr is not None:
            dt = mjd_bcd_to_datetime(sec[3:8])
            if dt:
                self.tot = (dt, pcr)

    def _done(self):
        if not (self.pat and self.pcr_pid is not None and all(p in self.first_pts for p in self.av_pids)):
            return False
        if self.first_pcr is None or (self.last_pcr - self.first_pcr) % PTS_WRAP < 90000 * 12:
            return False
        return True

    def duration(self):
        last = None
        for pkt in iter_packets(self.path, from_end=32 * 1024 * 1024):
            if ((pkt[1] & 0x1F) << 8 | pkt[2]) == self.pcr_pid and pkt[3] & 0x20:
                pcr = read_pcr(pkt)
                if pcr is not None:
                    last = pcr
        if last is None or self.first_pcr is None:
            return None
        return ((last - self.first_pcr) % PTS_WRAP) / 90000

    def select_service(self, quiet=False):
        if not self.pat:
            return None
        progs = [(n, p) for n, p in self.pat['programs'] if n]
        if self.service_id is not None:
            for n, p in progs:
                if n == self.service_id and p in self.pmts:
                    return n, p
            return None
        for n, p in progs:
            info = self.pmts.get(p)
            if info and any(e['type'] in VIDEO_TYPES for e in info['es']):
                return n, p
        return None


def parse_sdt(sec, out):
    i = 11
    while i + 5 <= len(sec) - 4:
        sid = int.from_bytes(sec[i:i + 2], 'big')
        n = ((sec[i + 3] & 0x0F) << 8) | sec[i + 4]
        out[sid] = parse_descriptors(sec[i + 5:i + 5 + n])
        i += 5 + n


def parse_eit_present(sec):
    if len(sec) < 14 + 12 + 4:
        return None
    j = 14
    n = ((sec[j + 10] & 0x0F) << 8) | sec[j + 11]
    return {
        'sid': int.from_bytes(sec[3:5], 'big'), 'version': (sec[5] >> 1) & 0x1F,
        'event_id': int.from_bytes(sec[j:j + 2], 'big'),
        'start': bytes(sec[j + 2:j + 7]), 'duration': bytes(sec[j + 7:j + 10]),
        'running': sec[j + 10] >> 5, 'descs': parse_descriptors(sec[j + 12:j + 12 + n]),
        'raw': bytes(sec[8:-4]),
    }


def es_type_name(t):
    return {0x01: 'MPEG-1 video', 0x02: 'MPEG-2 video', 0x1B: 'H.264', 0x24: 'HEVC',
            0x03: 'MPEG-1 audio', 0x04: 'MPEG-2 audio', 0x0F: 'AAC', 0x11: 'AAC-LATM',
            0x81: 'AC-3', 0x06: 'PES private', 0x0D: 'DSM-CC (данные)', 0x0B: 'DSM-CC'}.get(t, '0x%02X' % t)


# ---------------------------------------------------------------------------
# Мультиплексор
# ---------------------------------------------------------------------------

class Muxer:
    def __init__(self, args, probe, subs, cs):
        self.a = args
        self.p = probe
        self.cs = cs
        self.cc = CC()
        self.warnings = []
        svc = probe.select_service()
        if not svc:
            raise SystemExit('сервис не найден (используйте --list и --service-id)')
        self.sid, self.pmt_pid = svc
        self.src_pmt = probe.pmts[self.pmt_pid]
        self.isdb = probe.nit_id is not None and media_type_for(probe.nit_id) is not None
        mode = 'keep' if args.no_partial_ts else args.si
        if mode == 'broadcast' and self.isdb and not args.si_regenerate:
            log('Поток уже японский и с полным SI — таблицы остаются исходными (перегенерировать: --si-regenerate).')
            mode = 'keep'
        self.mode = mode
        self.partial = mode != 'keep'            # фильтруем PID и строим свою PAT
        self.gen_full = mode in ('broadcast', 'both')
        self.out_sid = args.out_service_id if (args.out_service_id and self.partial) else self.sid
        self.tsid = args.ts_id if (args.ts_id is not None and self.partial) else probe.pat['tsid']
        self.pat_version = probe.pat['version']
        self.video_info = {es['pid']: parse_video_info(bytes(probe.es_head.get(es['pid'], b'')), es['type'])
                           for es in self.src_pmt['es'] if es['type'] in VIDEO_TYPES}
        self.audio_info = {es['pid']: parse_audio_info(bytes(probe.es_head.get(es['pid'], b'')), es['type'])
                           for es in self.src_pmt['es'] if es['type'] in AUDIO_TYPES}
        self.audio_langs = [x.strip().lower().encode('ascii')[:3] for x in args.audio_lang.split(',') if x.strip()] or [b'jpn']
        global AUDIO_CS
        AUDIO_CS = cs
        AUDIO_NAMES.clear()
        self.caption_langs = [x.strip().lower().encode('ascii')[:3] for x in args.caption_lang.split(',') if x.strip()] or [b'jpn']
        self.lang = self.caption_langs[0]
        for lg in self.caption_langs:
            if ENCODING == 'utf8':
                continue                 # TCS=1 задаёт схему сам, код языка при этом любой
            if lg in (b'eng', b'tgl'):
                self.warn('язык субтитров %s: по ARIB он включает в приёмнике разбор UTF-8, '
                          'а текст кодируется в JIS — будет мусор. Либо --encoding utf8, '
                          'либо --caption-lang jpn' % lg.decode())
            elif lg in (b'por', b'spa'):
                self.warn('язык субтитров %s: по ARIB он включает латинские наборы ABNT, '
                          'а текст кодируется в JIS. Ставьте --caption-lang jpn' % lg.decode())
        cap_offsets = split_list(args.offset, float)
        self.cap_tracks = [CaptionTrack(path, sub_list, per_track(self.caption_langs, n, b'jpn'))
                           for n, (path, sub_list) in enumerate(subs)]
        for n, tr in enumerate(self.cap_tracks):
            tr.offset = per_track(cap_offsets, n, 0.0)
        self.captions = bool(self.cap_tracks)
        # правка только битов копирования: PMT патчится на месте, остальной файл
        # копируется байт в байт (как делает copyctl.py)
        self.copy_only = (copy_control_requested(args) and not subs and not args.audio_tracks
                          and (args.no_partial_ts or args.si == 'keep'))
        self.copy_bits = 0
        self.copy_before = {}
        self.copy_after = {}
        self._setup_audio()
        self._setup_caption_es()
        self._setup_superimpose()
        self._setup_pid_map()
        self._rebuild_pmt(self.src_pmt)
        # SI для SIT. SDT/EIT/TOT берём только из японского потока: в DVB/ATSC
        # другая кодировка строк и TOT в UTC, а не в JST.
        if not self.isdb and (probe.sdt or probe.eit or probe.tot):
            log('SI в потоке не японские (нет ISDB NIT) — исходные SDT/EIT/TOT не используются.')
        self.sdt_descs = probe.sdt.get(self.sid, []) if self.isdb else []
        self.event = probe.eit.get(self.sid) if self.isdb else None
        self.event_version = 0
        self.tot = probe.tot if self.isdb else None
        if args.jst:
            self.tot = (datetime.datetime.strptime(args.jst, '%Y-%m-%d %H:%M:%S'), probe.first_pcr)
        if args.service_name is not None:
            self.sdt_descs = [d for d in self.sdt_descs if d[0] != 0x48]
            self.sdt_descs.insert(0, service_descriptor(args.service_name, args.provider_name or '', cs))
        self.extra_event_descs = []
        if args.event_name is not None:
            self.extra_event_descs.append(short_event_descriptor(args.event_name, args.event_text or '', cs))
            tail = short_event_text_tail(args.event_name, args.event_text or '', cs)
            if tail:
                self.extra_event_descs += extended_event_descriptors(tail, cs)
            if self.event:
                self.event = dict(self.event, descs=[d for d in self.event['descs'] if d[0] != 0x4D])
        self._setup_generated_si(probe, cs)
        if self.new_audio and self.event:
            new_tags = {t.tag for t in self.new_audio}
            keep_c4 = args.keep_audio and any(d[0] == 0xC4 for d in self.event['descs'])
            ad = audio_component_descriptors(self.pmt_info, self.audio_info, self.audio_langs, AUDIO_NAMES,
                                             new_tags if keep_c4 else None, cs)
            descs = [d for d in self.event['descs'] if d[0] != 0xC4 or (keep_c4 and d[4] not in new_tags)]
            k = max((i + 1 for i, d in enumerate(descs) if d[0] in (0x50, 0xC4)), default=len(descs))
            self.event = dict(self.event, descs=descs[:k] + ad + descs[k:])
        self.network_id = args.network_id if args.network_id is not None else probe.nit_id
        mt = args.media_type.encode('ascii') if args.media_type else (
            media_type_for(self.network_id) if self.network_id is not None else None)
        if self.network_id is None:
            self.network_id = 0x0004
            mt = mt or b'BS'
            (log if self.gen_full else self.warn)(
                'NIT не найдена: network_id=0x0004, media_type=BS (задайте --network-id/--media-type)')
        if mt is None:
            mt = b'BS'
            self.warn('неизвестный network_id 0x%04X, media_type=BS (задайте --media-type)' % self.network_id)
        self.media_type = mt
        self.peak_rate = self._peak_rate()
        self.generate_sit = mode in ('partial', 'both') and not probe.has_sit
        self.si_versions = {}
        self.next_si = {}
        self.sit_version = 0
        self.sit_key = None
        # время
        self.last_raw = None
        self.T = None
        self.offset = 0
        self.T_first = probe.first_pcr
        # «ноль» SRT = самый ранний PTS аудио/видео (так считают ffmpeg/mpv/VLC)
        vp = [probe.first_pts[p] for p in probe.av_pids if p in probe.first_pts]
        if not vp or probe.first_pcr is None:
            raise SystemExit('не найдены PCR/PTS выбранного сервиса')
        if self.new_audio:                         # звук заменён: «ноль» — начало видео
            vp = [probe.first_pts[es['pid']] for es in self.src_pmt['es']
                  if es['type'] in VIDEO_TYPES and es['pid'] in probe.first_pts] or vp
        rel = [((v - probe.first_pcr + PTS_WRAP // 2) % PTS_WRAP) - PTS_WRAP // 2 for v in vp]
        self.T0 = probe.first_pcr + min(rel)
        for tr in self.new_audio:
            tr.schedule(self.T0 + int(round(tr.offset * 90000)), probe.first_pcr)
        for tr in self.cap_tracks:
            tr.schedule(self.T0, cs, self.warn)
        self.lead = int(args.lead * 90000)
        self.next_mgmt = None
        self.next_sit = None
        self.mgmt_sent = False
        self.stats = {}
        self.T_start_out = None
        self.last_pcr_T = None
        self.since_pcr = 0
        self.peak_rate_seen = (0.0, 0.0)
        self.tick_per_pkt = 0.0
        self.bytes_out = 0

    def warn(self, msg):
        if msg not in self.warnings:
            self.warnings.append(msg)
            log('ПРЕДУПРЕЖДЕНИЕ: ' + msg)

    # -- сгенерированные SI ------------------------------------------------
    def _setup_generated_si(self, probe, cs):
        """Сервис, событие и время для потока без японских SI (или --si-regenerate)."""
        a = self.a
        import os
        stem = os.path.splitext(os.path.basename(a.input))[0]
        need = self.gen_full or a.event_name is not None or a.jst
        if not need or (self.isdb and not a.si_regenerate):
            return
        dur = probe.duration() or 0
        if not self.tot:
            mtime = datetime.datetime.utcfromtimestamp(os.path.getmtime(a.input)) + datetime.timedelta(hours=9)
            start = (mtime - datetime.timedelta(seconds=dur)).replace(microsecond=0)
            self.tot = (start, probe.first_pcr)
            log('Время записи не задано: беру из даты файла, начало %s JST (задайте --jst).' % start)
        if self.gen_full and not any(d[0] == 0x48 for d in self.sdt_descs):
            self.sdt_descs.insert(0, service_descriptor(a.service_name or stem[:20], a.provider_name or '', cs))
        if self.isdb and self.event and a.event_name is None:
            return                                   # событие исходного EIT, если не переопределено
        jst0 = self.jst_at(probe.first_pcr)
        minutes = a.event_duration or max(1, -(-int(dur) // 60))
        descs = list(self.extra_event_descs)
        if not descs:
            title = a.event_name or a.service_name or stem[:40]
            descs = [short_event_descriptor(title, a.event_text or '', cs)]
            tail = short_event_text_tail(title, a.event_text or '', cs)
            if tail:
                descs += extended_event_descriptors(tail, cs)
        descs = descs + self.copy_event_descs() + event_component_descriptors(
            self.pmt_info, self.video_info, self.audio_info,
            [(tag, [t.lang for t in trs]) for _p, tag, trs in caption_groups(self.cap_tracks)], self.lang,
            self.audio_langs, GENRES[a.genre], self.sup_pid is not None)
        raw = b''.join(descs) + datetime_to_mjd_bcd(jst0)
        self.event = {'event_id': a.event_id, 'start': datetime_to_mjd_bcd(jst0),
                      'duration': bcd_duration(minutes * 60), 'running': 0, 'descs': descs, 'raw': raw}
        self.extra_event_descs = []

    def copy_event_descs(self):
        """0xC1 (и 0xDE, если задан) для сгенерированного события — как в EIT вещателя."""
        a = self.a
        if not copy_control_requested(a):
            return []
        return apply_copy_control([], a, create=True)

    def pat_section(self):
        progs = ([(0, PID_NIT)] if self.gen_full else []) + [(self.out_sid, self.out_pmt_pid)]
        return build_pat(self.tsid, progs, self.pat_version)

    def _ver(self, kind, key):
        old = self.si_versions.get(kind)
        if old is None:
            self.si_versions[kind] = (0, key)
        elif old[1] != key:
            self.si_versions[kind] = ((old[0] + 1) & 0x1F, key)
        return self.si_versions[kind][0]

    def si_sections(self, kind, T):
        cs, sid, onid = self.cs, self.out_sid, self.network_id
        if kind == 'nit':
            name = self.a.network_name if self.a.network_name is not None else (
                'BS Digital' if self.media_type == b'BS' else '')
            return PID_NIT, [nit_section(onid, name, self.tsid, [(sid, 0x01)], self.media_type, 0, cs)]
        if kind == 'sdt':
            return PID_SDT, [sdt_section(self.tsid, onid, sid, self.sdt_descs, bool(self.event), 0)]
        if kind in ('eit_pf', 'eit_sched'):
            if not self.event:
                return PID_EIT, []
            ev = dict(self.event, descs=apply_copy_control(self.event['descs'], self.a) + self.extra_event_descs,
                      event_id=self.event.get('event_id', 1))
            ev['descs'] = set_caption_data_content(ev['descs'], self.cap_tracks)
            ver = self._ver('eit', ev['raw'])
            if kind == 'eit_pf':
                return PID_EIT, eit_pf_sections(sid, self.tsid, onid, ev, None, ver)
            now = self.jst_at(T) or mjd_bcd_to_datetime(ev['start'])
            return PID_EIT, eit_schedule_sections(sid, self.tsid, onid, [ev], now, ver)
        if kind == 'tot':
            jst = self.jst_at(T)
            return PID_TOT, [tot_section(jst)] if jst else []
        if kind == 'bit':
            name = self.a.provider_name or ''
            upd = self.jst_at(self.T_first) or datetime.datetime(2000, 1, 1)
            return PID_BIT, [bit_section(onid, self.a.broadcaster_id, name, [(sid, 0x01)], upd, 0, cs)]
        raise ValueError(kind)

    def emit_si(self, out, T, kinds=None):
        for kind in kinds or SI_PERIODS:
            pid, secs = self.si_sections(kind, T)
            for sec in secs:
                self.emit(out, pid, section_packets(pid, sec, self.cc))
            self.next_si[kind] = T + SI_PERIODS[kind] * 90000

    def _setup_audio(self):
        """Дорожки AAC из --audio/--audio-wav/--audio-aac в заданном порядке.
        Без --keep-audio исходный звук заменяется, с ним — новые дорожки
        добавляются после исходных. Параметры по дорожкам — списками через запятую."""
        a = self.a
        self.new_audio, self.old_audio_pids = [], set()
        self.pcr_on_old_audio = False
        tracks = a.audio_tracks or []
        if not tracks:
            return
        src_audio = [es for es in self.src_pmt['es'] if is_audio_es(es)]
        keep = a.keep_audio
        if keep:
            bad = [es_type_name(es['type']) for es in src_audio if es['type'] != 0x0F]
            if bad:
                self.warn('оставлен исходный звук не AAC (%s) — японские приёмники его не воспроизведут' % ', '.join(bad))
        else:
            self.old_audio_pids = {es['pid'] for es in src_audio}
        n_keep = len(src_audio) if keep else 0
        used = {es['pid'] for es in self.src_pmt['es']} | {self.pmt_pid, self.src_pmt['pcr_pid']}
        old = [es['pid'] for es in src_audio if es['pid'] != self.src_pmt['pcr_pid']] if not keep else []
        reserved_tags = set()
        if keep:
            untagged = 0
            for es in src_audio:
                t = component_tag(es)
                if t is None:
                    reserved_tags.add(0x10 + untagged)
                    untagged += 1
                else:
                    reserved_tags.add(t)
        reserved_pids = set(range(0x0110, 0x0110 + n_keep)) if (a.arib_pids and self.partial) else set()
        bitrates = split_list(a.audio_bitrate, int)
        chans = split_list(a.audio_channels, int)
        offsets = split_list(a.audio_offset, float)
        delays = split_list(a.audio_delay_samples, int)
        next_tag = 0x10
        for n, (kind, path) in enumerate(tracks):
            want_ch = per_track(chans, n, None)
            bitrate = per_track(bitrates, n, None)
            if bitrate is None:
                src_ch = want_ch or wav_channels(path)
                if kind in ('ac3', 'ac3file'):
                    bitrate = {1: 96, 6: 448}.get(src_ch, 192)  # 448 на 5.1 — как на лентах D-Theater
                elif kind in ('mp2', 'mp2file'):
                    bitrate = 192 if src_ch == 1 else 256      # обычный для DVB Layer II
                else:
                    bitrate = {1: 144, 6: 384}.get(src_ch, 256)
            codec = ('pcm' if kind == 'pcm' else 'ac3' if kind in ('ac3', 'ac3file')
                     else 'mp2' if kind in ('mp2', 'mp2file') else 'aac')
            if kind == 'pcm':
                log('Читаю PCM %s ...' % path)
                tr = PcmTrack(read_pcm_48k(path, a.ffmpeg, self.warn), a.pcm_bit_order == 'dvhs')
                enc = 'pcm'
                data = None
            elif kind == 'ac3':
                log('Кодирую звук %s в AC-3 (%d кбит/с) ...' % (path, bitrate))
                data, enc = encode_wav_to_ac3(path, bitrate, want_ch, self.warn)
            elif kind == 'mp2':
                log('Кодирую звук %s в MP2 (%d кбит/с) ...' % (path, bitrate))
                data, enc = encode_wav_to_mp2(path, a.mp2_encoder, bitrate, want_ch, self.warn)
            elif kind == 'wav':
                log('Кодирую звук %s (%d кбит/с) ...' % (path, bitrate))
                data, enc = encode_wav_to_adts(path, a.aac_encoder, bitrate, want_ch, self.warn)
            else:
                data, enc = bytearray(open(path, 'rb').read()), 'file'
            table = {'mp2': MP2_ENCODER_DELAY, 'ac3': AC3_ENCODER_DELAY}.get(codec, AAC_ENCODER_DELAY)
            given = per_track(delays, n, None)
            delay = 0 if codec == 'pcm' else (table.get(enc, 0) if given is None else given)
            if enc == 'file' and given is None and codec not in ('mp2', 'pcm'):
                log('%s: кодировщик готового файла неизвестен, беру задержку %d отсч. (%.0f мс). '
                    'Если звук уедет — задайте --audio-delay-samples' % (path, delay, delay * 1000 / 48000))
            if codec != 'pcm':
                tr = AudioTrack(data, enc, delay, codec)
            else:
                tr.delay = delay
            if tr.info['rate'] != 48000:
                self.warn('%s: %d Гц (на BS звук 48 кГц)' % (path, tr.info['rate']))
            if codec == 'ac3':
                log('%s: Dolby Digital (AC-3), stream_type 0x81 — такой звук на лентах D-Theater' % path)
            elif codec == 'pcm':
                log('%s: линейный PCM (SMPTE 302M), stream_type 0x83 — как пишет дека в режиме STD; '
                    'порядок бит: %s' % (path, 'D-VHS' if tr.status_first else 'ffmpeg'))
            elif codec == 'mp2':
                log('%s: MPEG-1 Layer II, stream_type 0x%02X — для дек, не понимающих AAC; '
                    'японские приёмники такую дорожку игнорируют' % (path, tr.stream_type))

            if tr.info['ch'] == 6 and codec != 'mp2':
                log('%s: 5.1 (3/2+LFE) — приёмник должен уметь многоканальный AAC; '
                    'на стереовыходе он сведёт сам' % path)
            if codec != 'mp2' and not tr.info['mpeg2']:
                self.warn('%s: MPEG-4 ADTS с CRC — бит ID не меняю (сломался бы CRC); как в эфире будет из WAV '
                          'или из fdkaac -p 129' % path)
            if a.arib_pids and self.partial:
                pid = 0x0110 + n_keep + n
            elif n < len(old):
                pid = old[n]
            else:
                pid = 0x0110 + n_keep + n
            taken = (used - set(old)) | reserved_pids | {t.pid for t in self.new_audio}
            while pid in taken:
                pid += 1
            while next_tag in reserved_tags or next_tag in {t.tag for t in self.new_audio}:
                next_tag += 1
            if next_tag > 0x2F:
                raise SystemExit('слишком много звуковых дорожек (component_tag 0x10–0x2F)')
            tr.pid, tr.tag, tr.path, tr.kind = pid, next_tag, path, kind
            tr.offset = per_track(offsets, n, 0.0)
            tr.name = a.audio_name[n] if a.audio_name and n < len(a.audio_name) else None
            tr.bitrate = bitrate if kind == 'wav' else None
            self.check_dvhs_audio(tr, path)
            self.audio_info[pid] = {'rate': tr.info['rate'], 'ch': tr.info['ch']}
            if tr.name:
                AUDIO_NAMES[tr.tag] = tr.name
            self.new_audio.append(tr)
        self.pcr_on_old_audio = self.src_pmt['pcr_pid'] in self.old_audio_pids

    def _setup_pid_map(self):
        """--arib-pids: PMT 0x01F0, видео 0x0100.., звук 0x0110.., отдельный PCR 0x01FF — как на BS."""
        self.pid_map = {}
        if not (self.a.arib_pids and self.partial):
            self.out_pmt_pid = self.pmt_pid
            return
        src = self.src_pmt
        taken = {t.pid for t in self.cap_tracks} | {self.sup_pid} | {t.pid for t in self.new_audio}
        want = {self.pmt_pid: 0x01F0}
        nv, na = 0x0100, 0x0110
        for es in src['es']:
            if es['type'] in VIDEO_TYPES:
                want[es['pid']], nv = nv, nv + 1
            elif es['type'] in AUDIO_TYPES and es['pid'] not in self.old_audio_pids:
                want[es['pid']], na = na, na + 1
        if src['pcr_pid'] not in want:
            want[src['pcr_pid']] = 0x01FF
        unmapped = {es['pid'] for es in src['es']} - set(want) - self.old_audio_pids
        for old, new in want.items():
            if new not in taken and new not in unmapped:
                self.pid_map[old] = new
                taken.add(new)
        self.out_pmt_pid = self.pid_map.get(self.pmt_pid, self.pmt_pid)

    def check_dvhs_audio(self, tr, path):
        """Требования IEC 60774-5 (D-VHS), приложение A.2.8 — то, чего ждёт дека."""
        i = tr.info
        if tr.codec == 'pcm':
            if i['rate'] != 48000 or i['ch'] != 2:
                self.warn('%s: D-VHS требует для PCM ровно 48 кГц и два канала' % path)
            return
        if tr.codec == 'ac3':
            if i['rate'] != 48000:
                self.warn('%s: %d Гц; D-VHS требует для AC-3 48 кГц' % (path, i['rate']))
            if i['kbps'] > 640:
                self.warn('%s: %d кбит/с — выше предела 640 для AC-3' % (path, i['kbps']))
            if i['acmod'] == 0:
                self.warn('%s: режим 1+1 стандартом D-VHS запрещён' % path)
            return
        if i['rate'] not in (32000, 44100, 48000):
            self.warn('%s: частота %d Гц; D-VHS допускает 32, 44,1 и 48 кГц' % (path, i['rate']))
        if not i['crc']:
            self.warn('%s: в потоке нет CRC, а D-VHS его требует' % path)
        if tr.codec == 'mp2':
            limit = 384 if i['ch'] > 1 else 384
            if i['kbps'] > limit:
                self.warn('%s: %d кбит/с для Layer II выше предела D-VHS без расширения' % (path, i['kbps']))
            return
        if i.get('profile') != 2:
            self.warn('%s: профиль AAC не LC, а D-VHS требует именно его' % path)
        if i.get('buffer_fullness') == 0x7FF:
            self.warn('%s: adts_buffer_fullness = 0x7FF (переменный битрейт); '
                      'D-VHS это запрещает — кодируйте fdkaac или задайте постоянный битрейт' % path)
        if i.get('blocks', 1) != 1:
            self.warn('%s: в кадре ADTS больше одного raw_data_block, D-VHS требует один' % path)
        if tr.bitrate and i['ch'] and tr.bitrate > 288 * i['ch']:
            self.warn('%s: %d кбит/с — больше 288 на канал, предел D-VHS для AAC' % (path, tr.bitrate))

    def _setup_superimpose(self):
        self.sup_pid = None
        if not self.gen_full or self.a.no_superimpose:
            return
        es_list = self.src_pmt['es']
        if any(e['type'] == 0x06 and (component_tag(e) or 0) in range(0x38, 0x40) for e in es_list):
            return
        used = {e['pid'] for e in es_list} | {t.pid for t in self.cap_tracks} | {self.pmt_pid, self.src_pmt['pcr_pid']}
        used |= {t.pid for t in self.new_audio}
        pid = (self.cap_pid or 0x0130) + 8
        while pid in used:
            pid += 1
        self.sup_pid = pid

    # -- PMT ----------------------------------------------------------------
    def _setup_caption_es(self):
        """PID и component_tag каждой дорожке: 0x30.. — субтитры (字幕1, 字幕2...)."""
        self.replaced_pid = None
        if not self.captions:                  # только перемукс: исходные субтитры (если есть) остаются
            self.cap_pid = self.cap_tag = None
            return
        existing = [e for e in self.src_pmt['es'] if is_caption_es(e)]
        used_tags = {component_tag(e) for e in self.src_pmt['es']}
        used_pids = {e['pid'] for e in self.src_pmt['es']} | {self.src_pmt['pcr_pid'], self.pmt_pid}
        used_pids |= {t.pid for t in self.new_audio}
        want_pids = split_list(self.a.caption_pid, lambda v: int(v, 0))
        replacing = existing and self.a.existing == 'replace'
        if replacing:
            log('В потоке уже есть субтитры ARIB (%s) — заменяю их своими.'
                % ', '.join('PID 0x%04X' % e['pid'] for e in existing[:len(self.cap_tracks)]))
        elif existing:
            log('Субтитры уже есть (PID 0x%04X) — добавляю свои отдельными ES.' % existing[0]['pid'])
        free_tags = [t for t in range(0x30, 0x38) if t not in used_tags]
        if self.a.caption_multi == 'lang' and len(self.cap_tracks) > 1:
            # ARIB: несколько языков живут в одном ES, различаясь data_group_id
            if len(self.cap_tracks) > 2:
                self.warn('в одном ES ARIB несёт не больше двух языков (字幕1 и 字幕2); '
                          'лишние дорожки отброшены — либо используйте --caption-multi es')
                self.cap_tracks = self.cap_tracks[:2]
            head = self.cap_tracks[0]
            old = existing[0] if replacing else None
            if old is not None:
                head.replaced_pid = old['pid']
                head.tag = component_tag(old) or 0x30
                head.pid = per_track(want_pids, 0, None) or old['pid']
            else:
                head.tag = free_tags.pop(0)
                pid = per_track(want_pids, 0, None) or (0x0100 + head.tag)
                while pid in used_pids:
                    pid += 1
                head.pid = pid
            for n, tr in enumerate(self.cap_tracks):
                tr.pid, tr.tag, tr.lang_tag = head.pid, head.tag, n
                if n:
                    tr.replaced_pid = None
            self.replaced_pid = head.replaced_pid
            self.cap_pid, self.cap_tag = head.pid, head.tag
            return
        for n, tr in enumerate(self.cap_tracks):
            old = existing[n] if (replacing and n < len(existing)) else None
            if old is not None:
                tr.replaced_pid = old['pid']
                tr.tag = component_tag(old) or 0x30
                tr.pid = per_track(want_pids, n, None) or old['pid']
            else:
                if not free_tags:
                    raise SystemExit('больше 8 субтитровых ES ARIB не допускает (component_tag 0x30–0x37)')
                tr.tag = free_tags.pop(0)
                pid = per_track(want_pids, n, None) or (0x0100 + tr.tag)
                while pid in used_pids | {t.pid for t in self.cap_tracks[:n]}:
                    pid += 1
                tr.pid = pid
            used_tags.add(tr.tag)
        self.replaced_pid = self.cap_tracks[0].replaced_pid
        self.cap_pid, self.cap_tag = self.cap_tracks[0].pid, self.cap_tracks[0].tag

    def _rebuild_pmt(self, src):
        info = {'program': self.out_sid, 'pcr_pid': src['pcr_pid'],
                'descs': apply_copy_control(src['descs'], self.a, create=True), 'es': []}
        strip_ca = self.partial and not self.a.keep_ca
        if strip_ca:
            info['descs'] = [d for d in info['descs'] if d[0] != 0x09]
        seen_cap = set()
        cap_es = []
        for tr in self.cap_tracks:
            if tr.pid in seen_cap:
                continue
            seen_cap.add(tr.pid)
            cap_es.append({'type': 0x06, 'pid': tr.pid,
                           'descs': [bytes((0x52, 1, tr.tag)), b'\xfd\x03\x00\x08\x3d']})
        replaced = {tr.replaced_pid: es for tr, es in zip(self.cap_tracks, cap_es) if tr.replaced_pid is not None}
        next_tag = {'v': 0x00, 'a': 0x10}
        inserted = False
        drop_types = {0x0D, 0x0B} if self.a.drop_data else set()
        audio_done = False
        new_audio_es = [{'type': t.stream_type, 'pid': t.pid, 'descs': [bytes((0x52, 1, t.tag))]}
                        for t in self.new_audio]
        for es in src['es']:
            if es['type'] in drop_types:
                continue
            if es['pid'] in self.old_audio_pids:
                if not audio_done:
                    info['es'].extend(new_audio_es)
                    audio_done = True
                continue
            if es['pid'] in replaced:
                info['es'].append(replaced[es['pid']])
                inserted = True
                continue
            descs = apply_copy_control([d for d in es['descs'] if not (strip_ca and d[0] == 0x09)], self.a)
            vi = self.video_info.get(es['pid'])
            if self.partial and es['type'] == 0x02 and vi and 'h' in vi and not any(d[0] == 0xC8 for d in descs):
                fmt = video_component_type(vi)[1]         # video_decode_control_descriptor, как на BS
                descs.append(bytes((0xC8, 1, 0x40 | (fmt << 2) | 3)))
            if self.partial and component_tag(es) is None:
                kind = 'v' if es['type'] in VIDEO_TYPES else 'a' if es['type'] in AUDIO_TYPES else None
                if kind:
                    descs.insert(0, bytes((0x52, 1, next_tag[kind])))
                    next_tag[kind] += 1
            info['es'].append({'type': es['type'], 'pid': es['pid'], 'descs': descs})
        if new_audio_es and not audio_done:
            pos = max((i + 1 for i, e in enumerate(info['es']) if is_audio_es(e)), default=0) or \
                max((i + 1 for i, e in enumerate(info['es']) if e['type'] in VIDEO_TYPES), default=0)
            info['es'][pos:pos] = new_audio_es
        if self.a.audio_lang_pmt and self.partial:        # ISO_639_language_descriptor — для плееров
            n = 0
            for es in info['es']:
                if is_audio_es(es):
                    if not any(d[0] == 0x0A for d in es['descs']):
                        es['descs'] = list(es['descs']) + [b'\x0a\x04' + per_track(self.audio_langs, n, b'jpn') + b'\x00']
                    n += 1
        if self.captions:
            rest = [e for e in cap_es if e not in info['es']]
        else:
            rest = []
        if rest:
            pos = 0
            for i, es in enumerate(info['es']):
                if es['type'] in VIDEO_TYPES or es['type'] in AUDIO_TYPES or is_caption_es(es):
                    pos = i + 1
            info['es'][pos:pos] = rest
        if getattr(self, 'sup_pid', None):
            k = max((i + 1 for i, e in enumerate(info['es']) if e['pid'] in {t.pid for t in self.cap_tracks}),
                    default=len(info['es'])) - 1
            info['es'].insert(k + 1, {'type': 0x06, 'pid': self.sup_pid,
                                      'descs': [bytes((0x52, 1, 0x38)), b'\xfd\x03\x00\x08\x3c']})
        self.pmt_info = info
        pm = getattr(self, 'pid_map', {})
        mapped = dict(info, pcr_pid=pm.get(info['pcr_pid'], info['pcr_pid']),
                      es=[dict(es, pid=pm.get(es['pid'], es['pid'])) for es in info['es']])
        self.pmt_section = build_pmt(mapped, (src['version'] + 1) & 0x1F)
        self.keep_pids = {PID_PAT, self.pmt_pid, info['pcr_pid'], PID_DIT, PID_SIT}
        cap_pids = {t.pid for t in self.cap_tracks} | {t.replaced_pid for t in self.cap_tracks}
        self.keep_pids |= {es['pid'] for es in info['es']
                           if es['pid'] not in cap_pids and es['pid'] != getattr(self, 'sup_pid', None)}
        self.keep_pids -= {t.pid for t in self.new_audio}
        self.src_pmt_version = src['version']

    # -- расписание субтитров ---------------------------------------------
    def _peak_rate(self):
        if self.a.peak_rate:
            return int(self.a.peak_rate * 1e6)
        best = 0
        for b in self.p.buckets[1:-1] or self.p.buckets:
            n = sum(c for pid, c in b.items() if pid in self.keep_pids or not self.partial)
            best = max(best, n * 188 * 8 * 2)
        return int(best * 1.05) or 30_000_000

    # -- SIT ----------------------------------------------------------------
    def jst_at(self, T):
        if not self.tot:
            return None
        dt, pcr_then = self.tot
        return dt + datetime.timedelta(seconds=(T - pcr_then) / 90000)

    def build_sit(self, T):
        tinfo = partial_ts_descriptor(self.peak_rate) + network_identification_descriptor(self.network_id, self.media_type)
        body_descs = apply_copy_control(self.sdt_descs, self.a) + self.extra_event_descs
        running = 0
        if self.event:
            body_descs += apply_copy_control(self.event['descs'], self.a)
            running = self.event['running']
        if self.cap_tracks:
            body_descs = set_caption_data_content(body_descs, self.cap_tracks)
        key = (tinfo, self.event['raw'] if self.event else None, tuple(body_descs))
        if key != self.sit_key:
            if self.sit_key is not None:
                self.sit_version = (self.sit_version + 1) & 0x1F
                if self.event and key[1] != self.sit_key[1]:
                    self.event_version = (self.event_version + 1) & 0xFF
            self.sit_key = key
        jst = self.jst_at(T)
        head = [partial_ts_time_descriptor(self.event, jst, self.event_version)] if (self.event or jst) else []
        while True:
            sdesc = b''.join(head + body_descs)
            body = bytes((0xF0 | (len(tinfo) >> 8), len(tinfo) & 255)) + tinfo
            body += self.out_sid.to_bytes(2, 'big') + bytes((0x80 | (running << 4) | (len(sdesc) >> 8), len(sdesc) & 255)) + sdesc
            if len(body) + 12 <= 4096:
                break
            idx = max((i for i, d in enumerate(body_descs) if d[0] == 0x4E), default=None)
            if idx is None:
                idx = len(body_descs) - 1
            del body_descs[idx]
            self.warn('SIT больше 4096 байт: часть дескрипторов события отброшена')
        return long_section(0x7F, 0xFFFF, self.sit_version, body, private=True)

    # -- вывод --------------------------------------------------------------
    def emit(self, out, pid, data):
        out += data
        self.stats[pid] = self.stats.get(pid, 0) + len(data) // TS

    def emit_psi(self, out, T):
        if self.partial:
            self.emit(out, PID_PAT, section_packets(PID_PAT, self.pat_section(), self.cc))
        self.emit(out, self.out_pmt_pid, section_packets(self.out_pmt_pid, self.pmt_section, self.cc))
        if self.generate_sit and T is not None:
            self.emit(out, PID_SIT, section_packets(PID_SIT, self.build_sit(T), self.cc))
        if self.gen_full and T is not None:
            self.emit_si(out, T)

    def on_pcr(self, raw, out):
        if self.last_raw is None:
            self.T = raw
        else:
            d = (raw - self.last_raw) % PTS_WRAP
            if d <= 90000 * 10:
                self.T += d
            else:
                self.T += 3000
                self.warn('разрыв PCR — вставлена DIT; тайминг субтитров отсчитывается по непрерывному времени')
                if self.partial:
                    self.emit(out, PID_DIT, section_packets(PID_DIT, dit_section(True), self.cc))
                self.emit_psi(out, self.T)
        if self.last_pcr_T is not None and self.since_pcr:
            dT = self.T - self.last_pcr_T
            if 0 < dT <= 90000:                        # тиков на один пакет
                self.tick_per_pkt = dT / self.since_pcr
                rate = self.since_pcr * TS * 8 / (dT / 90000.0)
                if rate > self.peak_rate_seen[0]:
                    self.peak_rate_seen = (rate, (self.last_pcr_T - (self.T_first or 0)) / 90000.0)
        self.last_pcr_T = self.T
        self.since_pcr = 0
        self.last_raw = raw
        self.offset = self.T - raw

    def schedule(self, out, T=None):
        """Отправка того, чей срок подошёл. Вызывается на каждом выходном пакете
        с временем, интерполированным между PCR, и за один вызов отправляет не
        больше одного PES на поток — иначе на ленту уходит всплеск, который
        дека не успевает записать (предел HS — 28,2 Мбит/с)."""
        if T is None:
            T = self.T
        if self.T_start_out is None:
            self.T_start_out = T
            self.next_mgmt = T
            self.next_sit = T + int(self.a.sit_interval * 90000)
            # субтитры, закончившиеся до начала файла, пропускаем
            for tr in self.cap_tracks:
                tr.skipped = sum(1 for e in tr.events if e[3] == 'show' and e[4] <= T)
                tr.events = [e for e in tr.events if e[4] > T]
                tr.next_mgmt = T
        self.T_last = T
        if self.generate_sit and T >= self.next_sit:
            self.emit(out, PID_SIT, section_packets(PID_SIT, self.build_sit(T), self.cc))
            self.next_sit = T + int(self.a.sit_interval * 90000)
        if self.gen_full:
            due = [k for k in SI_PERIODS if T >= self.next_si.get(k, 0)]
            if due:
                self.emit_si(out, T, due[:1])          # по одной таблице за раз
        for tr in self.new_audio:
            if tr.codec == 'pcm':
                # PES линейного PCM — это ~44 пакета; раздаём их равномерно
                # по длительности куска, как делает дека (у неё максимум 2 подряд)
                if not tr.pending and tr.next < tr.nchunks and tr.deliver_time(tr.next) <= T:
                    data = pes_packets(tr.pid, tr.pes(tr.next, self.offset), self.cc)
                    pkts = [data[i:i + TS] for i in range(0, len(data), TS)]
                    span = PCM_SAMPLES_PER_PES * 90000 // 48000
                    tr.pending = [(T + span * k // max(1, len(pkts)), q) for k, q in enumerate(pkts)]
                    tr.next += 1
                if tr.pending and tr.pending[0][0] <= T:
                    self.emit(out, tr.pid, tr.pending.pop(0)[1])
                continue
            if tr.next < tr.nchunks and tr.deliver_time(tr.next) <= T:
                self.emit(out, tr.pid, pes_packets(tr.pid, tr.pes(tr.next, self.offset), self.cc))
                tr.next += 1
        if self.sup_pid and T >= getattr(self, 'next_sup', 0):
            self.emit(out, self.sup_pid, pes_packets(self.sup_pid, superimpose_pes(self.lang), self.cc))
            self.next_sup = T + 90000
        for pid, _tag, trs in caption_groups(self.cap_tracks):
            head = trs[0]
            if T >= head.next_mgmt:
                pts = T + self.lead
                self.emit(out, pid, pes_packets(pid, caption_pes(
                    caption_management_data([t.lang for t in trs]), pts - self.offset,
                    not self.a.simple_pes), self.cc))
                for t in trs:
                    t.next_mgmt = T + int(self.a.mgmt_interval * 90000)
                    t.mgmt_sent = True
        for tr in self.cap_tracks:
            if tr.events and tr.mgmt_sent and tr.events[0][0] - self.lead <= T:
                t, _, dg, kind, _end = tr.events.pop(0)
                pts = max(t, T + 9000)
                self.emit(out, tr.pid, pes_packets(tr.pid, caption_pes(dg, pts - self.offset, not self.a.simple_pes), self.cc))
                tr.count[kind] += 1

    def run_copy_only(self, out_path):
        """Меняем только 0xC1/0xDE в PMT, всё остальное копируем байт в байт."""
        split = 0
        with open(out_path, 'wb') as fo:
            chunk = bytearray()
            for rec, k in iter_records(self.a.input):
                if k is not None and ((rec[k + 1] & 0x1F) << 8 | rec[k + 2]) == self.pmt_pid:
                    new = self._patch_pmt_packet(memoryview(rec)[k:k + 188])
                    if new is None and rec[k + 1] & 0x40:
                        split += 1
                    elif new is not None:
                        rec = bytes(rec[:k]) + new + bytes(rec[k + 188:])
                        self.stats[self.pmt_pid] = self.stats.get(self.pmt_pid, 0) + 1
                chunk += rec
                if len(chunk) >= 16 * 1024 * 1024:
                    fo.write(chunk)
                    self.bytes_out += len(chunk)
                    chunk = bytearray()
            fo.write(chunk)
            self.bytes_out += len(chunk)
        if split:
            self.warn('%d секций PMT занимают несколько пакетов и оставлены без изменений' % split)

    def run(self, out_path):
        a = self.a
        asm = {}
        cap_pids = {t.pid for t in self.cap_tracks} | {t.replaced_pid for t in self.cap_tracks}
        watch = {PID_EIT, PID_SDT, PID_TOT, self.pmt_pid}
        out = bytearray()
        fo = open(out_path, 'wb')
        self.emit_psi(out, self.T_first)
        pcr_pid = self.pmt_info['pcr_pid']
        for pkt in iter_packets(a.input):
            pid = ((pkt[1] & 0x1F) << 8) | pkt[2]
            pcr = None
            if pid == pcr_pid and pkt[3] & 0x20:
                pcr = read_pcr(pkt)
                if pcr is not None:
                    self.on_pcr(pcr, out)       # время; при разрыве — DIT перед пакетом
            if pid in watch:
                pl = payload_of(pkt)
                if pl is not None:
                    for sec in asm.setdefault(pid, SectionAssembler()).feed(bytes(pl), pkt[1] & 0x40):
                        self._on_section(pid, sec)
            keep = True
            if pid == PID_PAT:
                if self.partial:
                    keep = False
                    if pkt[1] & 0x40:
                        self.emit(out, PID_PAT, section_packets(PID_PAT, self.pat_section(), self.cc))
            elif pid == self.pmt_pid and self.copy_only:
                sec = self._patch_pmt_packet(pkt)
                if sec is not None:
                    out += sec
                    self.stats[pid] = self.stats.get(pid, 0) + 1
                    keep = False
                    pkt = None
            elif pid == self.pmt_pid:
                keep = False
                if pkt[1] & 0x40:
                    self.emit(out, self.out_pmt_pid, section_packets(self.out_pmt_pid, self.pmt_section, self.cc))
            elif pid in self.old_audio_pids:
                keep = False
                if pid == self.pmt_info['pcr_pid'] and read_pcr(pkt) is not None:
                    np = self.pid_map.get(pid, pid)
                    q = pcr_only_packet(pkt)
                    out += bytes((0x47, np >> 8, np & 255)) + q[3:]
                    self.stats[np] = self.stats.get(np, 0) + 1
            elif pid in cap_pids or pid == self.sup_pid:
                keep = False
            elif self.partial and (pid not in self.keep_pids or (pid == PID_SIT and self.generate_sit)):
                keep = False
            if keep:
                np = self.pid_map.get(pid)
                if np is not None:
                    out += bytes((0x47, (pkt[1] & 0xE0) | (np >> 8), np & 255))
                    out += pkt[3:]
                    pid = np
                else:
                    out += pkt
                self.stats[pid] = self.stats.get(pid, 0) + 1
            self.since_pcr += 1
            if self.T is not None:
                self.schedule(out, self.T + int(self.since_pcr * self.tick_per_pkt))
            if len(out) >= 16 * 1024 * 1024:
                fo.write(out)
                self.bytes_out += len(out)
                out = bytearray()
        for tr in self.new_audio:                    # последний кадр звука — целиком
            tail = tr.tail_pes(self.offset)
            if tail:
                self.emit(out, tr.pid, pes_packets(tr.pid, tail, self.cc))
        # хвост: оставшиеся «очистки» экрана
        if self.T is not None:
            for tr in self.cap_tracks:
                while tr.events:
                    t, _, dg, kind, _end = tr.events.pop(0)
                    if kind == 'clear' and t - self.lead <= self.T + 90000 * 2:
                        self.emit(out, tr.pid, pes_packets(tr.pid, caption_pes(dg, t - self.offset, not a.simple_pes), self.cc))
                        tr.count[kind] += 1
                    elif kind == 'show':
                        tr.skipped += 1
        fo.write(out)
        self.bytes_out += len(out)
        fo.close()

    def _patch_pmt_packet(self, pkt):
        """Секция PMT целиком в одном пакете -> патчим на месте, иначе None."""
        if not pkt[1] & 0x40:
            return None
        pl = payload_of(pkt)
        if pl is None or not pl:
            return None
        off = 188 - len(pl) + 1 + pl[0]
        sec_start = 1 + pl[0]
        if sec_start >= len(pl) or pl[sec_start] != 0x02:
            return None
        n = 3 + (((pl[sec_start + 1] & 0x0F) << 8) | pl[sec_start + 2])
        if sec_start + n > len(pl):
            self.warn('секция PMT не помещается в один пакет — биты копирования в ней не изменены')
            return None
        sec = bytes(pl[sec_start:sec_start + n])
        self.copy_before.update({k: v for k, v in copy_control_values(parse_pmt(sec)['descs']).items()
                                 if k not in self.copy_before})
        new, bits = patch_pmt_section_inplace(sec, self.a)
        self.copy_bits += bits
        self.copy_after = copy_control_values(parse_pmt(new)['descs'])
        return bytes(pkt[:off]) + new + bytes(pkt[off + n:])

    def _on_section(self, pid, sec):
        tid = sec[0]
        if pid == self.pmt_pid and tid == 0x02:
            info = parse_pmt(sec)
            if info['version'] != self.src_pmt_version:
                self.src_pmt = info
                self._rebuild_pmt(info)
        elif not self.isdb:
            return
        elif pid == PID_EIT and tid == 0x4E and sec[6] == 0 and int.from_bytes(sec[3:5], 'big') == self.sid:
            ev = parse_eit_present(sec)
            if ev:
                ev['event_id'] = int.from_bytes(sec[14:16], 'big')
            if ev and self.a.event_name is not None:
                ev['descs'] = [d for d in ev['descs'] if d[0] != 0x4D]
            if ev and (not self.event or ev['raw'] != self.event['raw']):
                self.event = ev
        elif pid == PID_SDT and tid == 0x42 and self.a.service_name is None:
            d = {}
            parse_sdt(sec, d)
            if self.sid in d:
                self.sdt_descs = d[self.sid]
        elif pid == PID_TOT and tid in (0x70, 0x73) and self.T is not None and not self.a.jst:
            dt = mjd_bcd_to_datetime(sec[3:8])
            if dt:
                self.tot = (dt, self.T)

    def warn_output_protection(self, vals):
        """«Свободно + выход под защитой» задаётся не в 0xC1, а битом
        encryption_mode дескриптора 0xDE."""
        c1 = vals.get(0xC1)
        if c1 is None or (c1 >> 6) != 0 or ((c1 >> 2) & 3) != 0b01:
            return
        de = vals.get(0xDE)
        if de is None or de & 1:
            self.warn('copy_control_type = 01 при «копирование свободно» сам по себе выход не защищает: '
                      'нужен дескриптор 0xDE с encryption_mode = 0. Проще всего ключом --epn')

    def report(self):
        if self.copy_only:
            log('Правка битов копирования, PMT PID 0x%04X: %d секций, изменено битов %d' % (
                self.pmt_pid, self.stats.get(self.pmt_pid, 0), self.copy_bits))
            log('Биты копирования (было):')
            describe_copy_control(self.copy_before, '  ', log)
            log('Биты копирования (стало):')
            describe_copy_control(self.copy_after, '  ', log)
            self.warn_output_protection(self.copy_after)
            log('Остальные байты файла скопированы без изменений.')
            return
        dur = (self.T_last - self.T_start_out) / 90000 if self.T_start_out is not None else 0
        log('')
        if not self.cap_tracks:
            log('Готово: без новых субтитров')
        for n, tr in enumerate(self.cap_tracks):
            log('Готово, субтитры %d (%s, %s): %s, %s%s' % (
                n + 1, os.path.basename(tr.path), tr.lang.decode(),
                plural(tr.count['show'], 'фраза', 'фразы', 'фраз'),
                plural(tr.count['clear'], 'очистка', 'очистки', 'очисток') + ' экрана',
                (', пропущено (вне видео): %d' % tr.skipped) if tr.skipped else ''))
        log('Сервис %d%s, PMT PID 0x%04X, %s' % (
            self.out_sid, (' (во входе %d)' % self.sid) if self.out_sid != self.sid else '', self.out_pmt_pid,
            ('субтитры: %s; %s; область %dx%d+%d+%d, до %d знаков в строке; позиционирование %s' % (
                '; '.join('PID 0x%04X tag 0x%02X: %s' % (pid, tag, ', '.join(
                    '%s%s%s' % (('字幕%d ' % (t.lang_tag + 1)) if len(trs) > 1 else '', t.lang.decode(),
                                ' (сдвиг %+.2f с)' % t.offset if t.offset else '') for t in trs))
                    for pid, tag, trs in caption_groups(self.cap_tracks)),
                'наборы ARIB (JIS)' if ENCODING == 'jis' else 'UCS/UTF-8 (TCS=1)',
                AREA_W, AREA_H, AREA_X, AREA_Y, MAX_HALF, POSITIONING.upper()))
            if self.captions else 'без новых субтитров (перемукс)'))
        for tr in self.new_audio:
            i = tr.info
            left = tr.nchunks - tr.next
            n = self.new_audio.index(tr)
            n_keep = len([e for e in self.src_pmt['es'] if is_audio_es(e)]) if self.a.keep_audio else 0
            lang = per_track(self.audio_langs, n + n_keep, b'jpn')
            fmt = ('Dolby Digital %d кбит/с%s' % (i['kbps'], ' (5.1)' if i.get('lfe') and i['ch'] == 6 else '')
                   if tr.codec == 'ac3' else
                   'линейный PCM 16 бит (SMPTE 302M)' if tr.codec == 'pcm' else
                   ('MPEG-%d Layer II %d кбит/с' % (1 if i['mpeg1'] else 2, i['kbps'])) if tr.codec == 'mp2' else (
                '%s AAC-LC' % ('MPEG-2' if i['mpeg2'] else 'MPEG-4')))
            log('Звук %d: %s → PID 0x%04X, tag 0x%02X, %s%s%s: %s %d Гц %d кан., %s, кодер %s (задержка %d отсч.), '
                '%.1f с%s' % (n + 1, tr.path, self.pid_map.get(tr.pid, tr.pid), tr.tag, lang.decode(),
                              (' «%s»' % tr.name) if tr.name else '', (', сдвиг %+.3f с' % tr.offset) if tr.offset else '',
                              fmt, i['rate'], i['ch'],
                              'CRC' if i['crc'] else 'без CRC', tr.source, tr.delay, tr.duration,
                              ('; не вошло в видео: %.1f с' % (left * tr.chunk / 48000.0
                                                               if tr.codec == 'pcm' else
                                                               left * tr.chunk / max(1, len(tr.es)) * tr.duration))
                              if left > 2 else ''))
        before = self.copy_before or copy_control_values(self.src_pmt['descs'])
        after = self.copy_after or copy_control_values(self.pmt_info['descs'])
        self.warn_output_protection(after)
        if copy_control_requested(self.a):
            log('Биты копирования (было):')
            describe_copy_control(before, '  ', log)
            log('Биты копирования (стало):')
            describe_copy_control(after, '  ', log)
            if self.copy_only:
                log('  изменено битов: %d; остальной файл скопирован байт в байт' % self.copy_bits)
        elif before:
            log('Биты копирования (без изменений): 0xC1 = %s, 0xDE = %s%s' % (
                ('0x%02X — %s' % (before[0xC1], DRC_NAMES[before[0xC1] >> 6])) if 0xC1 in before else 'нет',
                ('0x%02X' % before[0xDE]) if 0xDE in before else 'нет',
                '' if 0xC1 not in before else ''))
        if self.pid_map:
            log('PID переназначены: ' + ', '.join('0x%04X→0x%04X' % kv for kv in sorted(self.pid_map.items()) if kv[0] != kv[1]))
        log('Режим SI: %s' % {'partial': 'partial TS для D-VHS (PAT/PMT/SIT/DIT)',
                              'broadcast': 'как в эфире (PAT/PMT/NIT/SDT/EIT/TOT/BIT)',
                              'both': 'эфирные таблицы + SIT', 'keep': 'исходный поток без изменений'}[self.mode])
        if self.gen_full and self.event:
            g = GENRES[self.a.genre] >> 4
            dvb = DVB_GENRE_NAMES.get(g)
            if dvb:
                log('Жанр: %s (ARIB, content_nibble %d). Плееры и MediaInfo берут названия из таблицы DVB '
                    'и назовут его «%s» — в файле значение верное, различаются только таблицы.'
                    % (self.a.genre, g, dvb))
        if self.gen_full:
            log('  NIT %d с, SDT %d с, EIT[p/f] %d с, расписание EIT %d с, TOT %d с, BIT %d с%s' % (
                SI_PERIODS['nit'], SI_PERIODS['sdt'], SI_PERIODS['eit_pf'], SI_PERIODS['eit_sched'],
                SI_PERIODS['tot'], SI_PERIODS['bit'],
                ('; суперимпоз PID 0x%04X' % self.sup_pid) if self.sup_pid else ''))
        if self.generate_sit:
            log('SIT: network_id 0x%04X, media_type %s, peak_rate %.2f Мбит/с' % (
                self.network_id, self.media_type.decode(), self.peak_rate / 1e6))
        if dur > 0:
            total = self.bytes_out * 8 / dur
            log('Длительность %.1f с, средний битрейт выхода %.2f Мбит/с' % (dur, total / 1e6))
            for pid in sorted(self.stats):
                log('   PID 0x%04X: %8.3f Мбит/с' % (pid, self.stats[pid] * TS * 8 / dur / 1e6))
            types = {es['type'] for es in self.pmt_info['es']}
            if not types & {0x02}:
                log('Внимание: видео не MPEG-2 — D-VHS пишет только MPEG-2 TS.')
            if types & AUDIO_TYPES and not types & {0x0F}:
                log('Внимание: звук не AAC — встроенный BS-декодер японских дек его не воспроизведёт '
                    '(запись битстрима при этом возможна).')
            peak, at = self.peak_rate_seen
            if peak:
                log('Пиковая мгновенная скорость (между соседними PCR): %.1f Мбит/с на %.1f с' % (peak / 1e6, at))
                over = [name for name, lim in DVHS_MODES if peak > lim]
                if over:
                    self.warn('пик %.1f Мбит/с выше предела %s — дека может запнуться в этом месте. '
                              'Обычно это всплеск самого видео: снизьте его битрейт или maxrate'
                              % (peak / 1e6, '/'.join(over)))
            fits = [name for name, rate in DVHS_MODES if self.peak_rate <= rate]
            log('D-VHS: ' + ('помещается в режим ' + '/'.join(fits) if fits else
                             'пиковый битрейт выше 28.2 Мбит/с — даже HS не потянет'))


def plural(n, one, few, many):
    if n % 10 == 1 and n % 100 != 11:
        w = one
    elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        w = few
    else:
        w = many
    return '%d %s' % (n, w)


def list_streams(probe):
    if not probe.pat:
        raise SystemExit('PAT не найдена')
    print('transport_stream_id: 0x%04X, network_id: %s' % (
        probe.pat['tsid'], '0x%04X' % probe.nit_id if probe.nit_id is not None else '—'))
    for num, pid in probe.pat['programs']:
        if num == 0:
            print('  NIT PID 0x%04X' % pid)
            continue
        info = probe.pmts.get(pid)
        print('  service %d (PMT 0x%04X)%s' % (num, pid, '' if info else ' — PMT не найдена'))
        if info:
            print('    PCR PID 0x%04X' % info['pcr_pid'])
            for es in info['es']:
                tag = component_tag(es)
                print('    PID 0x%04X  %-16s tag %s%s' % (
                    es['pid'], es_type_name(es['type']), '0x%02X' % tag if tag is not None else '—',
                    '  [субтитры ARIB]' if is_caption_es(es) else ''))
    for num, pid in probe.pat['programs']:
        info = probe.pmts.get(pid)
        if num and info:
            vals = copy_control_values(info['descs'])
            if vals:
                print('  управление копированием сервиса %d:' % num)
                describe_copy_control(vals, '    ')
    print('SIT в потоке: %s, EIT[p/f]: %s, TOT: %s' % (
        'есть' if probe.has_sit else 'нет', ', '.join(map(str, probe.eit)) or 'нет',
        probe.tot[0].strftime('%Y-%m-%d %H:%M:%S JST') if probe.tot else 'нет'))


def main():
    ap = argparse.ArgumentParser(description='Субтитры ARIB STD-B24 + partial TS (ARIB STD-B21) для D-VHS')
    ap.add_argument('input', help='входной MPEG-TS (.m2t/.ts)')
    ap.add_argument('subs', nargs='*', help='субтитры .srt или .ass/.ssa (UTF-8); можно несколько файлов — '
                                            'каждый станет отдельным ES (字幕1, 字幕2...)')
    ap.add_argument('-o', '--output', help='выходной файл')
    ap.add_argument('--list', action='store_true', help='показать сервисы и потоки и выйти')
    ap.add_argument('--service-id', type=lambda s: int(s, 0), help='service_id (по умолчанию первый с видео)')
    ap.add_argument('--caption-pid', help='PID субтитров (по умолчанию 0x0130, 0x0131...); по дорожкам: 0x130,0x131')
    ap.add_argument('--existing', choices=['replace', 'keep'], default='replace',
                    help='если в потоке уже есть субтитры: заменить (по умолчанию) или добавить второй ES')
    ap.add_argument('--offset', default='0', help='сдвиг субтитров, с; по дорожкам: 0,-0.5')
    ap.add_argument('--lead', type=float, default=0.8, help='на сколько секунд PES опережает свой PTS (как на BS: 0.8)')
    ap.add_argument('--mgmt-interval', type=float, default=0.5, help='период caption_management_data, с')
    ap.add_argument('--sit-interval', type=float, default=1.0, help='период SIT, с (ARIB: не больше 3)')
    ap.add_argument('--network-id', type=lambda s: int(s, 0), help='network_id для SIT, если нет NIT')
    ap.add_argument('--media-type', choices=['BS', 'CS', 'TB', 'AB', 'AC'], help='media_type для SIT')
    ap.add_argument('--peak-rate', type=float, help='peak_rate для SIT, Мбит/с (по умолчанию измеряется)')
    ap.add_argument('--service-name', help='название канала для SIT (service_descriptor)')
    ap.add_argument('--provider-name', help='название вещателя для SIT')
    ap.add_argument('--event-name', help='название передачи для SIT (short_event_descriptor)')
    ap.add_argument('--event-text', help='описание передачи для SIT')
    ap.add_argument('--jst', help='время начала записи "ГГГГ-ММ-ДД ЧЧ:ММ:СС" (JST), если в потоке нет TOT')
    ap.add_argument('--si', choices=['partial', 'broadcast', 'both', 'keep'], default='partial',
                    help='служебные таблицы: partial — partial TS для D-VHS (по умолчанию); broadcast — как в эфире '
                         '(NIT/SDT/EIT/TOT/BIT); both — оба набора; keep — не трогать исходный поток')
    ap.add_argument('--si-regenerate', action='store_true', help='перестроить SI даже у японского потока')
    ap.add_argument('--network-name', help='название сети в NIT (по умолчанию для BS: "BS Digital")')
    ap.add_argument('--ts-id', type=lambda s: int(s, 0), help='transport_stream_id на выходе')
    ap.add_argument('--out-service-id', type=lambda s: int(s, 0), help='service_id на выходе (например 171)')
    ap.add_argument('--broadcaster-id', type=lambda s: int(s, 0), default=1, help='broadcaster_id в BIT')
    ap.add_argument('--event-id', type=lambda s: int(s, 0), default=1, help='event_id передачи')
    ap.add_argument('--event-duration', type=int, help='длительность передачи в EIT, минуты (по умолчанию — по файлу)')
    ap.add_argument('--genre', choices=sorted(GENRES), default='anime', help='жанр в EIT (content_descriptor)')
    ap.add_argument('--caption-multi', choices=['lang', 'es'], default='lang',
                    help='несколько дорожек субтитров: lang — один ES, языки различаются внутри '
                         '(字幕1/字幕2, так делает вещание); es — отдельный ES на дорожку')
    ap.add_argument('--caption-lang', default='jpn', help='ISO 639-2 языки субтитров по дорожкам: rus,jpn')
    ap.add_argument('--audio-lang', default='jpn', help='ISO 639-2 языки звуковых ES по порядку PMT: jpn,rus')
    ap.add_argument('--no-superimpose', action='store_true', help='не добавлять служебный поток суперимпоза')
    ap.add_argument('--positioning', choices=['aps', 'acps'], default='aps',
                    help='позиция строк: aps — строка/столбец (по умолчанию; так понимают реальные деки), '
                         'acps — точки, как BS-вещатель')
    ap.add_argument('--audio', action=TrackAction, dest='audio_tracks', metavar='FILE',
                    help='звуковая дорожка AAC: WAV/FLAC (кодируется) или готовый .aac; повторяйте для нескольких')
    ap.add_argument('--audio-wav', action=TrackAction, dest='audio_tracks', metavar='WAV',
                    help='дорожка из WAV -> MPEG-2 AAC-LC 48 кГц (можно несколько раз)')
    ap.add_argument('--audio-aac', action=TrackAction, dest='audio_tracks', metavar='AAC', help='дорожка из готового ADTS AAC')
    ap.add_argument('--audio-mp2', action=TrackAction, dest='audio_tracks', metavar='WAV|MP2',
                    help='дорожка MPEG-1 Layer II (stream_type 0x03) — её ждут деки, не понимающие AAC')
    ap.add_argument('--mp2-encoder', choices=['auto', 'libtwolame', 'mp2'], default='auto',
                    help='кодировщик MP2 (по умолчанию libtwolame, если он есть в ffmpeg)')
    ap.add_argument('--audio-ac3', action=TrackAction, dest='audio_tracks', metavar='WAV|AC3',
                    help='дорожка Dolby Digital (AC-3, stream_type 0x81) — такой звук на лентах D-Theater; '
                         '48 кГц, до 640 кбит/с')
    ap.add_argument('--audio-pcm', action=TrackAction, dest='audio_tracks', metavar='WAV',
                    help='дорожка линейного PCM (SMPTE 302M, stream_type 0x83) — такой звук дека пишет '
                         'в режиме STD, встречается и на лентах D-Theater; всегда 48 кГц, 16 бит, стерео')
    ap.add_argument('--ffmpeg', default='ffmpeg', help='путь к ffmpeg')
    ap.add_argument('--pcm-bit-order', choices=['dvhs', 'ffmpeg'], default='dvhs',
                    help='порядок бит в 20-битном поле 302M: dvhs — как у деки (по умолчанию), '
                         'ffmpeg — как кодирует ffmpeg')
    ap.add_argument('--keep-audio', action='store_true', help='оставить исходный звук и добавить дорожки после него')
    ap.add_argument('--audio-name', action='append', metavar='NAME',
                    help='название новой дорожки в EIT/SIT (по порядку), например "日本語" или "Русский"')
    ap.add_argument('--audio-lang-pmt', action='store_true',
                    help='добавить ISO_639_language_descriptor в PMT (плееры покажут языки; у BS его нет)')
    ap.add_argument('--aac-encoder', choices=['auto', 'fdkaac', 'ffmpeg'], default='auto',
                    help='кодер AAC: fdkaac (ADTS с CRC, как у вещателя) или встроенный в ffmpeg (без CRC)')
    ap.add_argument('--audio-channels', metavar='N', help='каналы AAC: 1, 2 или 6 (5.1); по дорожкам: 6,2. '
                                                         'По умолчанию как в WAV')
    ap.add_argument('--audio-bitrate', help='битрейт AAC, кбит/с; по дорожкам: 384,192 '
                                            '(по умолчанию 256, для 5.1 — 384, для моно — 144)')
    ap.add_argument('--audio-offset', default='0', help='сдвиг звука относительно начала видео, с; по дорожкам: 0,-0.12')
    ap.add_argument('--audio-delay-samples', help='задержка кодера в отсчётах; по дорожкам через запятую')
    ap.add_argument('--arib-pids', action='store_true',
                    help='эфирная нумерация PID: PMT 0x01F0, видео 0x0100, звук 0x0110, отдельный PCR 0x01FF')
    ap.add_argument('--no-partial-ts', action='store_true', help='то же, что --si keep')
    ap.add_argument('--copy', choices=sorted(COPY_ARG), metavar='РЕЖИМ',
                    help='digital_recording_control_data: free | once | never | broadcaster '
                         '(или биты напрямую: 00 01 10 11)')
    ap.add_argument('--epn', action='store_true',
                    help='копирование свободно, но выход под защитой DTCP (EPN): включает --copy free, '
                         'copy_control_type 01 и encryption_mode 0 в дескрипторе 0xDE')
    ap.add_argument('--copy-control-type', choices=sorted(CCT_ARG), metavar='РЕЖИМ',
                    help='copy_control_type: free — выход без шифрования, protected — выход через DTCP, '
                         'auto (по умолчанию) — free для --copy free, protected для остальных')
    ap.add_argument('--aps', type=lambda v: int(v, 0), metavar='БИТЫ',
                    help='APS_control_data: защита аналогового выхода (0 — без ограничений)')
    ap.add_argument('--user-defined', type=lambda v: int(v, 0),
                    help='весь младший полубайт 0xC1 сразу (перекрывает --copy-control-type и --aps)')
    ap.add_argument('--content-availability', type=lambda v: int(v, 0), metavar='БАЙТ',
                    help='байт дескриптора 0xDE целиком (в образце 0xEF)')
    ap.add_argument('--diff', metavar='ФАЙЛ', help='сравнить input с этим файлом побайтно и выйти')
    ap.add_argument('--keep-ca', action='store_true', help='не удалять CA_descriptor из PMT')
    ap.add_argument('--drop-data', action='store_true', help='выбросить потоки данных (DSM-CC), чтобы влезть в STD')
    ap.add_argument('--simple-pes', action='store_true', help='минимальный PES-заголовок вместо «вещательного»')
    ap.add_argument('--ass-signs', choices=['place', 'top', 'skip'], default='place',
                    help='ASS: позиционированные надписи (\\pos/\\move) — на своём месте (place), '
                         'вверху экрана (top) или не показывать (skip)')
    ap.add_argument('--ass-dialogue-only', action='store_true',
                    help='ASS: только реплики — стили надписей, песен/OP/ED/караоке, примечаний и титров '
                         '(по имени и по содержимому) и события с \\pos/\\move/\\k/\\clip/поворотом/рисунком отбрасываются')
    ap.add_argument('--ass-list-styles', action='store_true',
                    help='ASS: показать, какие стили считаются репликами, и выйти')
    ap.add_argument('--ass-skip-styles', metavar='A,B', help='ASS: не показывать эти стили')
    ap.add_argument('--ass-only-styles', metavar='A,B', help='ASS: показывать только эти стили')
    ap.add_argument('--ass-small', choices=['ssz', 'normal'], default='ssz',
                    help='ASS: мелкий текст — малым размером ARIB SSZ (по умолчанию) или обычным. '
                         'Внимание: libaribcaption/ffmpeg в текстовом режиме считают SSZ фуриганой и не выводят')
    ap.add_argument('--ass-min-duration', type=float, default=0.3,
                    help='ASS: экраны короче этого (с) поглощаются предыдущим')
    ap.add_argument('--encoding', choices=['jis', 'utf8'], default='jis',
                    help='кодирование текста субтитров: jis — наборы ARIB (как в японском вещании); '
                         'utf8 — UCS/TCS=1, нужно для --caption-lang eng, снимает ограничения набора знаков')
    ap.add_argument('--area', metavar='ШxВ+X+Y',
                    help='область субтитров в плоскости 960x540 (по умолчанию 620x480+170+30, как на BS). '
                         'Шире область — больше знаков в строке: 880x480+40+30 даёт 44 вместо 31')
    ap.add_argument('--cyrillic', choices=['full', 'half'], default='full',
                    help='кириллица/греческий: full — в полной клетке (15 букв в строке), '
                         'half — вполширины через MSZ (30 букв, приёмник сжимает глифы)')
    ap.add_argument('--drcs-font', metavar='TTF|auto',
                    help='рисовать знаки вне наборов ARIB (і ї є ґ ў « » …) как DRCS этим шрифтом; нужен Pillow')
    a = ap.parse_args()

    apply_epn(a)
    if a.diff:
        diff_files(a.input, a.diff)
        return
    if a.ass_list_styles:
        names = [f for f in a.subs if f.lower().endswith(('.ass', '.ssa'))]
        if not names:
            ap.error('--ass-list-styles нужен файл .ass/.ssa')
        for f in names:
            parse_ass(f, AribCharset(), a)
        return
    probe = Probe(a.input, a.service_id)
    if a.list:
        list_streams(probe)
        return
    if not a.output:
        ap.error('нужен -o/--output (или --list); без subs — только перемукс')
    if not copy_control_requested(a) and not a.subs and not a.audio_tracks \
            and (a.si == 'keep' or a.no_partial_ts):
        ap.error('нечего делать: нет ни субтитров, ни звука, ни изменений SI или битов копирования')
    if a.sit_interval > 3:
        ap.error('--sit-interval не может быть больше 3 с')
    cs = AribCharset(half_letters=a.cyrillic == 'half', drcs=DrcsFont(a.drcs_font) if a.drcs_font else None)
    global POSITIONING, ENCODING
    POSITIONING = a.positioning
    ENCODING = a.encoding
    if a.area:
        set_area(a.area)
    subs = []
    for path in a.subs:
        if path.lower().endswith(('.ass', '.ssa')):
            lst = parse_ass(path, cs, a)
        else:
            lst = parse_srt(path, cs)
        if not lst:
            raise SystemExit('в %s не найдено ни одного субтитра' % path)
        subs.append((path, lst))
    mux = Muxer(a, probe, subs, cs)
    if mux.copy_only:
        mux.run_copy_only(a.output)
    else:
        mux.run(a.output)
    mux.report()


if __name__ == '__main__':
    main()
