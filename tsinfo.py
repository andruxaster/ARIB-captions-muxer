#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tsinfo.py — инвентаризация вещательного транспортного потока MPEG-2 TS.

Ориентирован на ARIB/ISDB (японское вещание, захваты с D-VHS по i.LINK),
но понимает и обычный DVB. Внешних зависимостей нет, Python 3.8+.

Что выводит:
  * контейнер: размер пакета (188/192/204/208), смещение синхронизации,
    источниковые метки времени (source packet header) для .m2t с i.LINK
  * карта PID: трафик, ошибки continuity_counter, скремблирование, PCR, битрейт
  * PAT / CAT / PMT / SDT / NIT / EIT / TOT / BIT / SDTT / CDT
  * все дескрипторы, включая ARIB (0xC0–0xFE) с расшифровкой
  * субтитры: сигнализация в PMT + реальные data group в PES (0x80/0x81),
    языки и формат из caption management data
  * карусели данных: DSM-CC секции, DII/DSI/DDB, число и размер модулей
  * copy control: digital_copy_control (включая copy_control_type и APS),
    content_availability, DTCP_descriptor (0x88), CA_descriptor,
    состояние transport_scrambling_control по каждому PID
  * звук: разбор самих элементарных потоков — AAC (ADTS), MPEG Layer II,
    AC-3, линейный PCM (SMPTE 302M) — и проверка по IEC 60774-5 (D-VHS)
  * пригодность для записи на ленту: пиковая мгновенная скорость между
    соседними PCR и запас до пределов режимов HS/STD, длинные пачки пакетов,
    интервал PCR, признаки partial TS (SIT/DIT, registration MTRM)

Использование:
    python3 tsinfo.py stream.m2t
    python3 tsinfo.py stream.ts --max-mb 64 --events 10
    python3 tsinfo.py stream.ts --json > report.json
"""

import argparse
import json
import os
import sys
from collections import OrderedDict, defaultdict

# ---------------------------------------------------------------------------
# CRC-32/MPEG-2
# ---------------------------------------------------------------------------


def _mk_crc_table():
    tbl = []
    for i in range(256):
        c = i << 24
        for _ in range(8):
            if c & 0x80000000:
                c = ((c << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                c = (c << 1) & 0xFFFFFFFF
        tbl.append(c)
    return tbl


_CRC_TABLE = _mk_crc_table()


def crc32_mpeg(data):
    crc = 0xFFFFFFFF
    for b in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _CRC_TABLE[((crc >> 24) ^ b) & 0xFF]
    return crc


# ---------------------------------------------------------------------------
# Декодирование текста: ARIB STD-B24 (8-битный набор) и DVB
# ---------------------------------------------------------------------------

_HIRA_EXTRA = {0x77: "ゝ", 0x78: "ゞ", 0x79: "ー", 0x7A: "。",
               0x7B: "「", 0x7C: "」", 0x7D: "、", 0x7E: "・"}
_KATA_EXTRA = {0x77: "ヽ", 0x78: "ヾ", 0x79: "ー", 0x7A: "。",
               0x7B: "「", 0x7C: "」", 0x7D: "、", 0x7E: "・"}

# финальные байты escape-последовательностей -> имя набора
_FINAL_1B = {0x4A: "ALNUM", 0x30: "HIRA", 0x31: "KATA", 0x49: "JISX0201K",
             0x36: "ALNUM", 0x37: "HIRA", 0x38: "KATA",
             0x32: "MOSAIC", 0x33: "MOSAIC", 0x34: "MOSAIC", 0x35: "MOSAIC",
             0x20: "DRCS"}
_FINAL_2B = {0x42: "KANJI", 0x39: "KANJI", 0x3A: "KANJI", 0x3B: "GAIJI",
             0x20: "DRCS2"}

# C0/C1: сколько байт параметров пропустить после кода
_C0_PARAM = {0x16: 1, 0x1C: 2, 0x1F: 1}
_C1_PARAM = {0x8B: 1, 0x90: 1, 0x91: 1, 0x92: 1, 0x93: 1,
             0x94: 1, 0x97: 1, 0x98: 1, 0x9D: 2}


def _jis2(b1, b2):
    try:
        return bytes([b1 | 0x80, b2 | 0x80]).decode("euc_jp")
    except Exception:
        return "〓"


def decode_arib(data):
    """Грубый, но практичный декодер 8-битного набора ARIB STD-B24."""
    g = ["KANJI", "ALNUM", "HIRA", "KATA"]
    gl, gr = 0, 2
    out = []
    i, n = 0, len(data)
    while i < n:
        b = data[i]
        if b == 0x1B:  # ESC
            i += 1
            if i >= n:
                break
            e = data[i]
            i += 1
            if e == 0x24:  # 2-байтовые наборы
                if i < n and data[i] in (0x28, 0x29, 0x2A, 0x2B):
                    slot = data[i] - 0x28
                    i += 1
                    if i < n and data[i] == 0x20:
                        i += 1
                    if i < n:
                        g[slot] = _FINAL_2B.get(data[i], "KANJI")
                        i += 1
                elif i < n:
                    g[0] = _FINAL_2B.get(data[i], "KANJI")
                    i += 1
            elif e in (0x28, 0x29, 0x2A, 0x2B):  # 1-байтовые наборы
                slot = e - 0x28
                if i < n and data[i] == 0x20:  # DRCS
                    i += 1
                    if i < n:
                        i += 1
                    g[slot] = "DRCS"
                elif i < n:
                    g[slot] = _FINAL_1B.get(data[i], "ALNUM")
                    i += 1
            elif e == 0x6E:
                gl = 2
            elif e == 0x6F:
                gl = 3
            elif e == 0x7E:
                gr = 1
            elif e == 0x7D:
                gr = 2
            elif e == 0x7C:
                gr = 3
            continue
        if b == 0x0F:
            gl = 0
            i += 1
            continue
        if b == 0x0E:
            gl = 1
            i += 1
            continue
        if b in (0x19, 0x1D):  # SS2 / SS3
            slot = 2 if b == 0x19 else 3
            i += 1
            if i < n:
                s, used = _char(g[slot], data, i)
                out.append(s)
                i += used
            continue
        if b < 0x20:
            if b in (0x0A, 0x0D):
                out.append("\n")
            i += 1 + _C0_PARAM.get(b, 0)
            continue
        if b == 0x20:
            out.append(" ")
            i += 1
            continue
        if b == 0x7F:
            i += 1
            continue
        if b < 0x7F:
            s, used = _char(g[gl], data, i)
            out.append(s)
            i += used
            continue
        if b == 0xA0 or b == 0xFF:
            out.append(" ")
            i += 1
            continue
        if 0x80 <= b <= 0x9F:
            i += 1 + _C1_PARAM.get(b, 0)
            continue
        s, used = _char(g[gr], data, i, high=True)
        out.append(s)
        i += used
    return "".join(out)


def _char(setname, data, i, high=False):
    b = data[i] & 0x7F
    if setname in ("KANJI", "GAIJI", "DRCS2"):
        if i + 1 >= len(data):
            return ("", 1)
        b2 = data[i + 1] & 0x7F
        if setname == "KANJI":
            return (_jis2(b, b2), 2)
        return ("〓", 2)
    if setname == "HIRA":
        if b in _HIRA_EXTRA:
            return (_HIRA_EXTRA[b], 1)
        return (_jis2(0x24, b), 1)
    if setname == "KATA":
        if b in _KATA_EXTRA:
            return (_KATA_EXTRA[b], 1)
        return (_jis2(0x25, b), 1)
    if setname == "JISX0201K":
        return (chr(0xFF61 + (b - 0x21)) if 0x21 <= b <= 0x5F else "", 1)
    if setname == "DRCS":
        return ("□", 1)
    if setname == "MOSAIC":
        return ("▨", 1)
    if b == 0x5C:
        return ("¥", 1)
    return (chr(b) if 0x20 <= b < 0x7F else "", 1)


_DVB_CHARSETS = {0x01: "iso8859_5", 0x02: "iso8859_6", 0x03: "iso8859_7",
                 0x04: "iso8859_8", 0x05: "iso8859_9", 0x06: "iso8859_10",
                 0x07: "iso8859_11", 0x09: "iso8859_13", 0x0A: "iso8859_14",
                 0x0B: "iso8859_15", 0x11: "utf-16-be", 0x15: "utf-8"}


def decode_dvb(data):
    if not data:
        return ""
    enc = "iso8859_1"
    if data[0] < 0x20:
        if data[0] == 0x10 and len(data) >= 3:
            enc = "iso8859_%d" % data[2]
            data = data[3:]
        else:
            enc = _DVB_CHARSETS.get(data[0], "iso8859_1")
            data = data[1:]
    try:
        return data.decode(enc, "replace")
    except Exception:
        return data.decode("iso8859_1", "replace")


def decode_text(data, charset="auto"):
    """auto = сначала ARIB (инструмент нацелен на ISDB).

    7-битный диапазон ARIB неотличим от ASCII: по умолчанию G0=KANJI, поэтому
    латинские названия из DVB-потока в режиме auto превратятся в кандзи-мусор.
    Для DVB укажите --charset dvb, для чистого ASCII --charset ascii.
    """
    if not data:
        return ""
    if charset == "dvb":
        return decode_dvb(data)
    if charset == "ascii":
        return data.decode("ascii", "replace")
    txt = decode_arib(data)
    if charset == "arib":
        return txt
    if not txt.strip() or txt.count("〓") > max(1, len(txt) // 3):
        if all(0x20 <= b < 0x7F for b in data):
            return data.decode("ascii")
        return decode_dvb(data)
    return txt


# ---------------------------------------------------------------------------
# Справочники
# ---------------------------------------------------------------------------

STREAM_TYPES = {
    0x01: "MPEG-1 Video", 0x02: "MPEG-2 Video", 0x03: "MPEG-1 Audio",
    0x04: "MPEG-2 Audio", 0x05: "private sections", 0x06: "PES private data",
    0x07: "MHEG", 0x08: "DSM-CC", 0x09: "H.222.1", 0x0A: "DSM-CC type A",
    0x0B: "DSM-CC type B (U-N messages)", 0x0C: "DSM-CC type C",
    0x0D: "DSM-CC type D (data carousel)", 0x0F: "AAC (ADTS)",
    0x10: "MPEG-4 Video", 0x11: "AAC (LATM)", 0x1B: "H.264/AVC",
    0x24: "H.265/HEVC", 0x42: "AVS", 0x80: "MPEG-2 Video (private)",
    0x81: "AC-3 (Dolby Digital)", 0x82: "DTS", 0x83: "Linear PCM (SMPTE 302M)",
    0x86: "SCTE-35", 0x87: "E-AC-3",
}

DESC_NAMES = {
    0x02: "video_stream", 0x03: "audio_stream", 0x05: "registration",
    0x06: "data_stream_alignment", 0x09: "CA", 0x0A: "ISO_639_language",
    0x0B: "system_clock", 0x0E: "maximum_bitrate", 0x10: "smoothing_buffer",
    0x11: "STD", 0x13: "carousel_identifier", 0x14: "association_tag",
    0x15: "deferred_association_tags", 0x1C: "MPEG-4 audio", 0x28: "AVC_video",
    0x2A: "AVC_timing_and_HRD", 0x40: "network_name", 0x41: "service_list",
    0x42: "stuffing", 0x43: "satellite_delivery_system",
    0x44: "cable_delivery_system", 0x47: "bouquet_name", 0x48: "service",
    0x49: "country_availability", 0x4A: "linkage", 0x4C: "time_shifted_service",
    0x4D: "short_event", 0x4E: "extended_event", 0x50: "component",
    0x52: "stream_identifier", 0x53: "CA_identifier", 0x54: "content",
    0x55: "parental_rating", 0x56: "teletext", 0x58: "local_time_offset",
    0x59: "subtitling", 0x5A: "terrestrial_delivery_system",
    0x63: "partial_transport_stream", 0x66: "data_broadcast_id",
    0x6A: "AC-3", 0x7A: "enhanced_AC-3",
    # --- ARIB STD-B10 ---
    0x88: "DTCP", 0xC0: "hierarchical_transmission", 0xC1: "digital_copy_control",
    0xC2: "network_identification", 0xC3: "partial_TS_time",
    0xC4: "audio_component", 0xC5: "hyperlink", 0xC6: "target_region",
    0xC7: "data_contents", 0xC8: "video_decode_control",
    0xC9: "download_content", 0xCA: "CA_EMM_TS", 0xCB: "CA_contract_info",
    0xCC: "CA_service", 0xCD: "TS_information", 0xCE: "extended_broadcaster",
    0xCF: "logo_transmission", 0xD0: "basic_local_event", 0xD1: "reference",
    0xD2: "node_relation", 0xD3: "short_node_information",
    0xD4: "STC_reference", 0xD5: "series", 0xD6: "event_group",
    0xD7: "SI_parameter", 0xD8: "broadcaster_name", 0xD9: "component_group",
    0xDA: "SI_prime_TS", 0xDB: "board_information", 0xDC: "LDT_linkage",
    0xDD: "connected_transmission", 0xDE: "content_availability",
    0xDF: "extension", 0xE0: "service_group",
    0xF6: "access_control", 0xF7: "carousel_compatible_composite",
    0xF8: "conditional_playback", 0xF9: "cable_TS_division",
    0xFA: "terrestrial_delivery_system", 0xFB: "partial_reception",
    0xFC: "emergency_information", 0xFD: "data_component",
    0xFE: "system_management",
}

DATA_COMPONENT_ID = {
    0x0007: "данные (BS/CS, BML)",
    0x0008: "субтитры /文字スーパー (ARIB STD-B24)",
    0x000C: "данные (наземное ЦТВ, BML)",
    0x000D: "накопительное/загружаемое вещание",
    0x000E: "мультимедиа-загрузка",
}

COPY_CONTROL = {0: "copy free (свободное копирование)",
                1: "определяется другими средствами",
                2: "copy once (одна копия)",
                3: "copy never (копирование запрещено)"}

APS_CONTROL = {0: "APS выкл.", 1: "APS тип 1", 2: "APS тип 2", 3: "APS тип 3"}

# Младшие 4 бита дескриптора 0xC1: эксплуатационные правила ARIB задают им смысл.
# Значение 00 у copy_control_type не определено, и приёмник трактует содержимое
# как защищённое — «копирование свободно» с нулевым нибблом ведёт себя как запрет.
COPY_CONTROL_TYPE = {0: "не задан (приёмник считает содержимое защищённым)",
                     1: "выход шифруется (DTCP)",
                     2: "зарезервировано",
                     3: "выход без шифрования"}
DTCP_CCI = {0: "copy free", 1: "no more copies", 2: "copy one generation", 3: "copy never"}

SERVICE_TYPES = {0x01: "цифровое ТВ", 0x02: "цифровое радио",
                 0x0C: "передача данных", 0xA1: "спец. видео",
                 0xA2: "спец. аудио", 0xA3: "спец. данные",
                 0xA4: "инженерный сервис", 0xA5: "промо-видео",
                 0xA6: "промо-аудио", 0xA7: "промо-данные",
                 0xAD: "суперHD (4K)"}

TABLE_NAMES = {0x00: "PAT", 0x01: "CAT", 0x02: "PMT", 0x03: "TSDT",
               0x3A: "DSM-CC MPE", 0x3B: "DSM-CC UN (DII/DSI)",
               0x3C: "DSM-CC DDB", 0x3D: "DSM-CC stream descr",
               0x3E: "DSM-CC private", 0x40: "NIT actual", 0x41: "NIT other",
               0x42: "SDT actual", 0x46: "SDT other", 0x4A: "BAT",
               0x4E: "EIT p/f actual", 0x4F: "EIT p/f other",
               0x70: "TDT", 0x71: "RST", 0x72: "ST", 0x73: "TOT",
               0x7E: "DIT", 0x7F: "SIT",
               0xC3: "SDTT", 0xC4: "BIT", 0xC5: "NBIT (body)",
               0xC6: "NBIT (ref)", 0xC7: "LDT", 0xC8: "CDT"}

WELL_KNOWN_PIDS = {
    0x0000: "PAT", 0x0001: "CAT", 0x0002: "TSDT", 0x0010: "NIT",
    0x0011: "SDT/BAT", 0x0012: "EIT", 0x0013: "RST", 0x0014: "TDT/TOT",
    0x0016: "网 (RNT)", 0x0017: "DCT", 0x001E: "DIT", 0x001F: "SIT",
    0x0020: "SDTT (одноsegment)", 0x0023: "SDTT", 0x0024: "BIT",
    0x0025: "NBIT/LDT", 0x0026: "EIT (H-EIT)", 0x0027: "EIT (одноsegment)",
    0x0029: "CDT", 0x1FFF: "NULL (заполнение)",
}


# ---------------------------------------------------------------------------
# Сборка секций из TS-пакетов
# ---------------------------------------------------------------------------


class SectionAssembler:
    def __init__(self):
        self.buf = b""

    def push(self, payload, pusi):
        out = []
        if not payload:
            return out
        if pusi:
            ptr = payload[0]
            head, rest = payload[1:1 + ptr], payload[1 + ptr:]
            if self.buf and head:
                self.buf += head
                out += self._drain()
            self.buf = rest
        else:
            if not self.buf:
                return out
            self.buf += payload
        out += self._drain()
        return out

    def _drain(self):
        out = []
        while len(self.buf) >= 3:
            if self.buf[0] == 0xFF:
                self.buf = b""
                break
            length = ((self.buf[1] & 0x0F) << 8) | self.buf[2]
            total = length + 3
            if len(self.buf) < total:
                break
            out.append(self.buf[:total])
            self.buf = self.buf[total:]
        return out


# ---------------------------------------------------------------------------
# Дескрипторы
# ---------------------------------------------------------------------------


def parse_descriptors(data, charset="auto"):
    res = []
    i = 0
    while i + 2 <= len(data):
        tag, length = data[i], data[i + 1]
        body = data[i + 2:i + 2 + length]
        if len(body) < length:
            break
        d = {"tag": tag, "name": DESC_NAMES.get(tag, "unknown_0x%02X" % tag),
             "len": length, "raw": body.hex()}
        try:
            _parse_one(d, tag, body, charset)
        except Exception as exc:  # дескриптор битый — не роняем разбор
            d["error"] = "%s: %s" % (type(exc).__name__, exc)
        res.append(d)
        i += 2 + length
    return res


def _parse_one(d, tag, b, charset):
    if tag == 0x05:
        d["format_identifier"] = b[:4].decode("ascii", "replace")
    elif tag == 0x09:
        d["ca_system_id"] = (b[0] << 8) | b[1]
        d["ca_pid"] = ((b[2] & 0x1F) << 8) | b[3]
        d["private"] = b[4:].hex()
    elif tag == 0x0A:
        d["languages"] = [{"lang": b[i:i + 3].decode("ascii", "replace"),
                           "audio_type": b[i + 3]} for i in range(0, len(b) - 3, 4)]
    elif tag == 0x0E:
        d["max_bitrate_bps"] = (((b[0] & 0x3F) << 16) | (b[1] << 8) | b[2]) * 400
    elif tag == 0x13:
        d["carousel_id"] = int.from_bytes(b[:4], "big")
        if len(b) > 4:
            d["format_id"] = b[4]
    elif tag == 0x14:
        d["association_tag"] = (b[0] << 8) | b[1]
        d["use"] = (b[2] << 8) | b[3]
    elif tag == 0x28:
        d["profile_idc"] = b[0]
        d["level_idc"] = b[2]
    elif tag == 0x40:
        d["network_name"] = decode_text(b, charset)
    elif tag == 0x41:
        d["services"] = [{"service_id": (b[i] << 8) | b[i + 1],
                          "type": b[i + 2]} for i in range(0, len(b) - 2, 3)]
    elif tag == 0x48:
        st = b[0]
        pl = b[1]
        prov = b[2:2 + pl]
        nl = b[2 + pl]
        name = b[3 + pl:3 + pl + nl]
        d["service_type"] = st
        d["service_type_str"] = SERVICE_TYPES.get(st, "0x%02X" % st)
        d["provider"] = decode_text(prov, charset)
        d["service_name"] = decode_text(name, charset)
    elif tag == 0x4D:
        d["lang"] = b[:3].decode("ascii", "replace")
        nl = b[3]
        d["event_name"] = decode_text(b[4:4 + nl], charset)
        tl = b[4 + nl]
        d["text"] = decode_text(b[5 + nl:5 + nl + tl], charset)
    elif tag == 0x50:
        d["stream_content"] = b[0] & 0x0F
        d["component_type"] = b[1]
        d["component_tag"] = b[2]
        d["lang"] = b[3:6].decode("ascii", "replace")
        d["text"] = decode_text(b[6:], charset)
    elif tag == 0x52:
        d["component_tag"] = b[0]
    elif tag == 0x54:
        d["genres"] = [{"nibble1": b[i] >> 4, "nibble2": b[i] & 0x0F}
                       for i in range(0, len(b) - 1, 2)]
    elif tag == 0x56:
        d["teletext"] = [{"lang": b[i:i + 3].decode("ascii", "replace"),
                          "type": b[i + 3] >> 3,
                          "magazine": b[i + 3] & 0x07,
                          "page": b[i + 4]} for i in range(0, len(b) - 4, 5)]
    elif tag == 0x59:
        d["subtitles"] = [{"lang": b[i:i + 3].decode("ascii", "replace"),
                           "subtitling_type": b[i + 3],
                           "composition_page": (b[i + 4] << 8) | b[i + 5],
                           "ancillary_page": (b[i + 6] << 8) | b[i + 7]}
                          for i in range(0, len(b) - 7, 8)]
    elif tag == 0x88 and len(b) >= 2:
        d["CA_System_ID"] = (b[0] << 8) | b[1]
        d["is_DTLA"] = d["CA_System_ID"] == 0x0FFF
        if len(b) >= 3:
            v = b[2]
            d["EPN"] = (v >> 6) & 1
            d["DTCP_CCI"] = (v >> 4) & 3
            d["DTCP_CCI_str"] = DTCP_CCI[(v >> 4) & 3]
            d["Image_Constraint_Token"] = (v >> 2) & 1
            d["APS"] = v & 3
            d["APS_str"] = APS_CONTROL[v & 3]
        d["raw"] = b.hex()
    elif tag == 0xC0:
        d["quality_level"] = (b[0] >> 4) & 1
        d["reference_pid"] = ((b[1] & 0x1F) << 8) | b[2]
    elif tag == 0xC1:
        d["digital_recording_control"] = b[0] >> 6
        d["copy_control_str"] = COPY_CONTROL[b[0] >> 6]
        d["maximum_bitrate_flag"] = (b[0] >> 5) & 1
        d["component_control_flag"] = (b[0] >> 4) & 1
        d["copy_control_type"] = (b[0] >> 2) & 3
        d["copy_control_type_str"] = COPY_CONTROL_TYPE[(b[0] >> 2) & 3]
        d["APS_control_data"] = b[0] & 3
        d["APS_str"] = APS_CONTROL[b[0] & 3]
        idx = 1
        if d["maximum_bitrate_flag"]:
            d["maximum_bitrate_kbps"] = b[idx] * 250
            idx += 1
        if d["component_control_flag"] and idx < len(b):
            n = b[idx]
            idx += 1
            comps = []
            end = idx + n
            while idx + 1 < min(end + 1, len(b)):
                tagv = b[idx]
                flags = b[idx + 1]
                c = {"component_tag": tagv,
                     "digital_recording_control": flags >> 6,
                     "copy_control_str": COPY_CONTROL[flags >> 6],
                     "maximum_bitrate_flag": (flags >> 5) & 1,
                     "copy_control_type": (flags >> 2) & 3,
                     "copy_control_type_str": COPY_CONTROL_TYPE[(flags >> 2) & 3],
                     "APS_control_data": flags & 3}
                idx += 2
                if c["maximum_bitrate_flag"] and idx < len(b):
                    c["maximum_bitrate_kbps"] = b[idx] * 250
                    idx += 1
                comps.append(c)
            d["components"] = comps
    elif tag == 0xC4:
        d["stream_content"] = b[0] & 0x0F
        d["component_type"] = b[1]
        d["component_tag"] = b[2]
        d["stream_type"] = b[3]
        d["simulcast_group_tag"] = b[4]
        d["ES_multi_lingual_flag"] = (b[5] >> 7) & 1
        d["main_component_flag"] = (b[5] >> 6) & 1
        d["quality_indicator"] = (b[5] >> 4) & 3
        d["sampling_rate"] = (b[5] >> 1) & 7
        d["lang"] = b[6:9].decode("ascii", "replace")
        idx = 9
        if d["ES_multi_lingual_flag"]:
            d["lang2"] = b[9:12].decode("ascii", "replace")
            idx = 12
        d["text"] = decode_text(b[idx:], charset)
    elif tag == 0xC7:
        d["data_component_id"] = (b[0] << 8) | b[1]
        d["entry_component"] = b[2]
        sl = b[3]
        d["selector"] = b[4:4 + sl].hex()
    elif tag == 0xC8:
        d["still_picture_flag"] = (b[0] >> 7) & 1
        d["sequence_end_code_flag"] = (b[0] >> 6) & 1
        d["video_encode_format"] = (b[0] >> 2) & 0x0F
    elif tag == 0xCD:
        d["remote_control_key_id"] = b[0]
        ln = b[1] >> 2
        d["ts_name"] = decode_text(b[2:2 + ln], charset)
    elif tag == 0xCF:
        d["logo_transmission_type"] = b[0]
    elif tag == 0xD5:
        d["series_id"] = (b[0] << 8) | b[1]
        d["repeat_label"] = b[2] >> 4
        d["episode_number"] = ((b[3] & 0x0F) << 8) | b[4]
    elif tag == 0xD9:
        d["component_group_type"] = b[0] >> 5
        d["num_groups"] = b[0] & 0x0F
    elif tag == 0xDE:
        d["copy_restriction_mode"] = (b[0] >> 6) & 1
        d["image_constraint_token"] = (b[0] >> 5) & 1
        d["retention_mode"] = (b[0] >> 4) & 1
        d["retention_state"] = (b[0] >> 1) & 7
        d["encryption_mode"] = b[0] & 1
        d["encryption_str"] = ("шифрование не требуется" if b[0] & 1
                               else "требуется шифрование при выводе")
    elif tag == 0xFA:
        d["area_code"] = (b[0] << 4) | (b[1] >> 4)
        d["guard_interval"] = (b[1] >> 2) & 3
        d["transmission_mode"] = b[1] & 3
        d["frequencies_mhz"] = [round((((b[i] << 8) | b[i + 1]) / 7.0), 4)
                                for i in range(2, len(b) - 1, 2)]
    elif tag == 0xFB:
        d["partial_reception_service_ids"] = [(b[i] << 8) | b[i + 1]
                                              for i in range(0, len(b) - 1, 2)]
    elif tag == 0xFC:
        d["emergency"] = True
        if len(b) >= 4:
            d["service_id"] = (b[0] << 8) | b[1]
            d["start_end_flag"] = (b[2] >> 7) & 1
            d["signal_level"] = (b[2] >> 6) & 1
    elif tag == 0xFD:
        dcid = ((b[0] & 0x0F) << 8) | b[1]
        d["data_component_id"] = dcid
        d["data_component_str"] = DATA_COMPONENT_ID.get(dcid, "0x%04X" % dcid)
        extra = b[2:]
        d["additional_info"] = extra.hex()
        if dcid == 0x0008:
            d.update(_parse_caption_component_info(extra))
    elif tag == 0xFE:
        d["broadcasting_flag"] = b[0] >> 6
        d["broadcasting_identifier"] = b[0] & 0x3F
        d["additional_id"] = b[1] if len(b) > 1 else None


def _parse_caption_component_info(b):
    """additional_arib_caption_info (ARIB STD-B24). Сырые байты тоже сохранены."""
    out = {}
    if not b:
        return out
    try:
        n = b[0]
        langs = []
        i = 1
        for _ in range(n):
            tag = b[i] >> 5
            dmf = b[i] & 0x0F
            i += 1
            entry = {"language_tag": tag, "DMF": "0b" + format(dmf, "04b")}
            if dmf in (0x0C, 0x0D, 0x0E):
                entry["DC"] = b[i]
                i += 1
            entry["lang"] = b[i:i + 3].decode("ascii", "replace")
            i += 3
            fmt = b[i]
            entry["format"] = fmt >> 4
            entry["TCS"] = (fmt >> 2) & 3
            entry["rollup_mode"] = fmt & 3
            i += 1
            langs.append(entry)
        out["caption_languages"] = langs
    except Exception:
        out["caption_languages_note"] = "не разобрано, см. additional_info"
    return out


# ---------------------------------------------------------------------------
# Время
# ---------------------------------------------------------------------------


def mjd_bcd_to_str(b):
    if len(b) < 5:
        return None
    mjd = (b[0] << 8) | b[1]
    if mjd == 0xFFFF:
        return None
    yp = int((mjd - 15078.2) / 365.25)
    mp = int((mjd - 14956.1 - int(yp * 365.25)) / 30.6001)
    day = mjd - 14956 - int(yp * 365.25) - int(mp * 30.6001)
    k = 1 if mp in (14, 15) else 0
    year = yp + k + 1900
    month = mp - 1 - k * 12
    hh, mm, ss = (b[2] >> 4) * 10 + (b[2] & 0xF), (b[3] >> 4) * 10 + (b[3] & 0xF), \
                 (b[4] >> 4) * 10 + (b[4] & 0xF)
    return "%04d-%02d-%02d %02d:%02d:%02d" % (year, month, day, hh, mm, ss)


def bcd_duration(b):
    return "%02d:%02d:%02d" % ((b[0] >> 4) * 10 + (b[0] & 0xF),
                               (b[1] >> 4) * 10 + (b[1] & 0xF),
                               (b[2] >> 4) * 10 + (b[2] & 0xF))


# ---------------------------------------------------------------------------
# Анализатор
# ---------------------------------------------------------------------------

BASE_PSI_PIDS = {0x0000, 0x0001, 0x0010, 0x0011, 0x0012, 0x0013, 0x0014,
                 0x001E, 0x001F, 0x0020, 0x0023, 0x0024, 0x0025, 0x0026,
                 0x0027, 0x0029, 0x002F}


# ---------------------------------------------------------------------------
# Разбор звуковых элементарных потоков и проверка их по IEC 60774-5 (D-VHS)
# ---------------------------------------------------------------------------

_REV8 = [int("{:08b}".format(i)[::-1], 2) for i in range(256)]
MPA_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}
MPA_BR = {
    (1, 1): [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448],
    (1, 2): [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384],
    (1, 3): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    (0, 1): [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256],
    (0, 2): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
}
AAC_RATES = [96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050, 16000, 12000, 11025, 8000]
AC3_BR = [32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, 448, 512, 576, 640]
AC3_ACMOD_CH = [2, 1, 2, 3, 3, 4, 4, 5]
AC3_ACMOD_STR = ["1+1", "1/0 моно", "2/0 стерео", "3/0", "2/1", "3/1", "2/2", "3/2"]


def probe_aac(es):
    i = es.find(b"\xff")
    while 0 <= i < len(es) - 7:
        if es[i + 1] & 0xF6 == 0xF0:
            h = es[i:i + 7]
            n = ((h[3] & 3) << 11) | (h[4] << 3) | (h[5] >> 5)
            frames = 0
            j = i
            while j + 7 <= len(es) and es[j] == 0xFF and es[j + 1] & 0xF6 == 0xF0:
                ln = ((es[j + 3] & 3) << 11) | (es[j + 4] << 3) | (es[j + 5] >> 5)
                if ln < 7:
                    break
                j += ln
                frames += 1
            if frames < 3:
                i = es.find(b"\xff", i + 1)
                continue
            sf = (h[2] >> 2) & 0xF
            ch = ((h[2] & 1) << 2) | (h[3] >> 6)
            return {"кодек": "AAC", "версия": "MPEG-2" if (h[1] >> 3) & 1 else "MPEG-4",
                    "профиль": ["Main", "LC", "SSR", "LTP"][(h[2] >> 6) & 3],
                    "частота": AAC_RATES[sf] if sf < len(AAC_RATES) else 0, "каналов": ch,
                    "CRC": not (h[1] & 1), "adts_buffer_fullness": ((h[5] & 0x1F) << 6) | (h[6] >> 2),
                    "raw_data_blocks": (h[6] & 3) + 1,
                    "кбит/с": round(n * 8 * (AAC_RATES[sf] if sf < len(AAC_RATES) else 48000) / 1024 / 1000),
                    "кадров": frames}
        i = es.find(b"\xff", i + 1)
    return None


def probe_mpa(es):
    i = es.find(b"\xff")
    while 0 <= i < len(es) - 4:
        b1, b2 = es[i + 1], es[i + 2]
        ver, layer = (b1 >> 3) & 3, 4 - ((b1 >> 1) & 3)
        br_i, sr_i, pad = b2 >> 4, (b2 >> 2) & 3, (b2 >> 1) & 1
        if b1 & 0xE0 == 0xE0 and ver != 1 and layer != 4 and br_i not in (0, 15) and sr_i != 3:
            mpeg1 = ver == 3
            tab = MPA_BR.get((1 if mpeg1 else 0, 3 if layer == 3 else layer))
            rate = MPA_RATES[ver if ver in MPA_RATES else 3][sr_i]
            if tab:
                kbps = tab[br_i]
                spf = 384 if layer == 1 else (1152 if (mpeg1 or layer == 2) else 576)
                return {"кодек": "MPEG Audio", "версия": "MPEG-1" if mpeg1 else "MPEG-2",
                        "слой": "I II III".split()[layer - 1], "частота": rate, "кбит/с": kbps,
                        "каналов": 1 if (es[i + 3] >> 6) == 3 else 2, "CRC": not (b1 & 1),
                        "отсч./кадр": spf}
        i = es.find(b"\xff", i + 1)
    return None


def probe_ac3(es):
    i = es.find(b"\x0b\x77")
    while 0 <= i < len(es) - 8:
        fscod, frm = es[i + 4] >> 6, es[i + 4] & 0x3F
        if fscod != 3 and frm < 38:
            acmod = es[i + 6] >> 5
            bit = 6 * 8 + 3
            if (acmod & 1) and acmod != 1:
                bit += 2
            if acmod & 4:
                bit += 2
            if acmod == 2:
                bit += 2
            lfe = (es[bit // 8] >> (7 - bit % 8)) & 1 if bit // 8 < len(es) else 0
            return {"кодек": "AC-3", "частота": {0: 48000, 1: 44100, 2: 32000}[fscod],
                    "кбит/с": AC3_BR[frm >> 1], "режим": AC3_ACMOD_STR[acmod],
                    "LFE": bool(lfe), "каналов": AC3_ACMOD_CH[acmod] + lfe,
                    "bsid": es[i + 5] >> 3}
        i = es.find(b"\x0b\x77", i + 1)
    return None


def probe_pcm(es):
    """SMPTE 302M. Порядок бит в 20-битном поле определяем по данным: у D-VHS
    служебные биты идут первыми, у ffmpeg — последними."""
    if len(es) < 64:
        return None
    size = (es[0] << 8) | es[1]
    nch, bps = (es[2] >> 6) & 3, (es[3] >> 4) & 3
    body = es[4:4 + max(0, size)]
    if len(body) < 500:
        return None
    def smooth(status_first):
        prev = None
        acc = n = 0
        rms = 0
        for k in range(0, min(len(body) // 5 * 5, 5000), 5):
            v = int.from_bytes(body[k:k + 5], "big")
            f = (v >> 20) & 0xFFFFF
            if not status_first:
                f >>= 4
            x = _REV8[(f >> 8) & 0xFF] | (_REV8[f & 0xFF] << 8)
            x = x - 65536 if x >= 32768 else x
            rms += x * x
            if prev is not None:
                acc += abs(x - prev)
                n += 1
            prev = x
        rms = (rms / max(1, n)) ** 0.5
        return acc / max(1, n) / (rms + 1e-9)
    a, b = smooth(True), smooth(False)
    if max(a, b) < 0.02 or abs(a - b) < 0.05:
        order = "не определить (сигнал слишком тихий или ровный)"
    else:
        order = "D-VHS" if a < b else "ffmpeg"
    return {"кодек": "Linear PCM (SMPTE 302M)", "частота": 48000,
            "каналов": [2, 4, 6, 8][nch], "бит": [16, 20, 24, 0][bps],
            "размер кадра": size, "порядок бит": order,
            "оценка гладкости": "%.2f / %.2f" % (a, b)}


def probe_audio(stype, es):
    if stype == 0x0F or stype == 0x11:
        return probe_aac(es)
    if stype in (0x03, 0x04):
        return probe_mpa(es)
    if stype == 0x81:
        return probe_ac3(es)
    if stype == 0x83:
        return probe_pcm(es)
    return None


def check_dvhs_audio(stype, info):
    """Требования IEC 60774-5, приложение A.2.8."""
    out = []
    if not info:
        return ["не удалось разобрать поток"]
    rate = info.get("частота")
    if stype in (0x0F, 0x11):
        if rate not in (32000, 44100, 48000):
            out.append("частота %s — допустимы 32, 44,1 и 48 кГц" % rate)
        if info.get("профиль") != "LC":
            out.append("профиль %s — требуется LC" % info.get("профиль"))
        if not info.get("CRC"):
            out.append("нет CRC в ADTS, стандарт его требует")
        if info.get("adts_buffer_fullness") == 0x7FF:
            out.append("adts_buffer_fullness = 0x7FF (VBR) — стандарт запрещает")
        if info.get("raw_data_blocks") != 1:
            out.append("raw_data_block на кадр: %d, требуется 1" % info.get("raw_data_blocks"))
        if info.get("каналов") and info.get("кбит/с", 0) > 288 * info["каналов"]:
            out.append("%d кбит/с — больше 288 на канал" % info["кбит/с"])
    elif stype in (0x03, 0x04):
        if info.get("слой") != "II":
            out.append("слой %s — D-VHS описывает Layer II" % info.get("слой"))
        if not info.get("CRC"):
            out.append("нет CRC, стандарт его требует")
    elif stype == 0x81:
        if rate != 48000:
            out.append("частота %s — для AC-3 требуется 48 кГц" % rate)
        if info.get("кбит/с", 0) > 640:
            out.append("%d кбит/с — выше предела 640" % info["кбит/с"])
        if info.get("режим") == "1+1":
            out.append("режим 1+1 стандартом запрещён")
    elif stype == 0x83:
        if info.get("каналов") != 2 or info.get("бит") != 16:
            out.append("D-VHS требует ровно 2 канала по 16 бит")
    return out


class PidStat:
    __slots__ = ("pid", "packets", "cc_errors", "scrambled", "last_cc",
                 "pcr_first", "pcr_last", "pcr_count", "pkt_first", "pkt_last",
                 "pes_count", "pes_stream_id", "pes_sample", "afc_only",
                 "tei_errors")

    def __init__(self, pid):
        self.pid = pid
        self.packets = 0
        self.cc_errors = 0
        self.scrambled = 0
        self.last_cc = None
        self.pcr_first = None
        self.pcr_last = None
        self.pcr_count = 0
        self.pkt_first = None
        self.pkt_last = None
        self.pes_count = 0
        self.pes_stream_id = None
        self.pes_sample = None
        self.afc_only = 0
        self.tei_errors = 0


class TSAnalyzer:
    def __init__(self, path, charset="auto", max_bytes=None, max_events=5):
        self.path = path
        self.charset = charset
        self.max_bytes = max_bytes
        self.max_events = max_events

        self.pkt_size = 188
        self.head_len = 0
        self.offset = 0
        self.packets = 0

        self.pids = {}
        self.es_bytes = {}          # pid -> начало элементарного потока
        self.pts_lead = {}          # pid -> [мин, макс] PTS-PCR, секунды
        self.run_max = {}           # pid -> самая длинная пачка подряд
        self._run_pid = None
        self._run_len = 0
        self._pcr_pkt = {}          # pid -> (номер пакета, PCR) предыдущей метки
        self.peak_rate = {}         # pid -> (Мбит/с, секунда) самого быстрого участка
        self.pcr_gap = {}           # pid -> самый долгий интервал между PCR
        self.assemblers = {}
        self.psi_pids = set(BASE_PSI_PIDS)
        self.es_pids = set()        # PID элементарных потоков — секциями не разбираем
        self.pmt_pids = {}          # pid -> program_number
        self.carousel_pids = set()
        self.caption_pids = {}      # pid -> "caption"/"superimpose"
        self.caption_sig = set()    # PID, объявленные субтитровыми в PMT
        self.audio_sig = set()      # PID звука — их PES трогать нельзя

        self.pat = OrderedDict()
        self.cat_descs = []
        self.programs = OrderedDict()
        self.services = OrderedDict()
        self.nit = None
        self.events = []
        self.table_counts = defaultdict(int)
        self.crc_errors = 0
        self.time_tdt = None
        self.time_tot = None
        self.tot_descs = []
        self.dsmcc = defaultdict(int)
        self.carousels = OrderedDict()
        self.caption_groups = defaultdict(int)
        self.caption_mgmt = OrderedDict()
        self.src_ts_first = None
        self.src_ts_last = None
        self.src_cpi = defaultdict(int)
        self.emergency = []
        self._event_keys = set()

    # -- определение упаковки -------------------------------------------------

    def detect_packing(self):
        with open(self.path, "rb") as f:
            head = f.read(1024 * 1024)
        best = None
        for size, hlen in ((188, 0), (192, 4), (204, 0), (208, 4), (192, 0)):
            for off in range(0, min(size * 2, len(head))):
                hits = 0
                p = off + hlen
                while p < len(head) and hits < 200:
                    if head[p] != 0x47:
                        break
                    hits += 1
                    p += size
                if hits >= 10 and (best is None or hits > best[0]):
                    best = (hits, size, hlen, off)
                if hits >= 200:
                    break
            if best and best[0] >= 200 and best[1] == size:
                break
        if not best:
            raise SystemExit("Не найден синхробайт 0x47 — это не TS?")
        _, self.pkt_size, self.head_len, self.offset = best
        return best

    # -- основной проход ------------------------------------------------------

    def run(self):
        self.detect_packing()
        size = self.pkt_size
        hlen = self.head_len
        limit = self.max_bytes
        with open(self.path, "rb") as f:
            f.seek(self.offset)
            read = 0
            chunk_pkts = 4096
            while True:
                want = size * chunk_pkts
                if limit is not None:
                    want = min(want, max(0, limit - read))
                    if want == 0:
                        break
                    want = max(size, (want // size) * size)
                data = f.read(want)
                if not data:
                    break
                read += len(data)
                for i in range(0, len(data) - size + 1, size):
                    pkt = data[i:i + size]
                    if hlen:
                        self._source_header(pkt[:hlen])
                    if pkt[hlen] != 0x47:
                        continue
                    self._packet(pkt[hlen:hlen + 188])
                if limit and read >= limit:
                    break
        return self

    def _source_header(self, h):
        v = int.from_bytes(h, "big")
        if self.src_ts_first is None:
            self.src_ts_first = v
        self.src_ts_last = v
        self.src_cpi[v >> 30] += 1

    def _packet(self, p):
        if len(p) < 188:
            return
        self.packets += 1
        _pid = ((p[1] & 0x1F) << 8) | p[2]
        if _pid == self._run_pid:
            self._run_len += 1
        else:
            if self._run_pid is not None:
                if self._run_len > self.run_max.get(self._run_pid, 0):
                    self.run_max[self._run_pid] = self._run_len
            self._run_pid, self._run_len = _pid, 1
        tei = (p[1] >> 7) & 1
        pusi = (p[1] >> 6) & 1
        pid = ((p[1] & 0x1F) << 8) | p[2]
        tsc = (p[3] >> 6) & 3
        afc = (p[3] >> 4) & 3
        cc = p[3] & 0x0F

        st = self.pids.get(pid)
        if st is None:
            st = self.pids[pid] = PidStat(pid)
            st.pkt_first = self.packets
        st.packets += 1
        st.pkt_last = self.packets
        if tei:
            st.tei_errors += 1
        if tsc:
            st.scrambled += 1

        payload = b""
        if afc in (2, 3):
            af_len = p[4]
            if afc == 2:
                st.afc_only += 1
            if af_len >= 7 and len(p) > 5 and (p[5] & 0x10):
                base = (p[6] << 25) | (p[7] << 17) | (p[8] << 9) | \
                       (p[9] << 1) | (p[10] >> 7)
                ext = ((p[10] & 0x01) << 8) | p[11]
                pcr = base * 300 + ext
                if st.pcr_first is None:
                    st.pcr_first = (pcr, self.packets)
                st.pcr_last = (pcr, self.packets)
                st.pcr_count += 1
                prev = self._pcr_pkt.get(pid)
                if prev is not None:
                    n0, t0 = prev
                    dt = (pcr - t0) / 27e6                  # PCR здесь в единицах 27 МГц
                    if 0 < dt <= 10:
                        rate = (self.packets - n0) * 188 * 8 / dt / 1e6
                        cur = self.peak_rate.get(pid, (0.0, 0.0))
                        if rate > cur[0]:
                            self.peak_rate[pid] = (rate, (t0 - st.pcr_first[0]) / 27e6)
                        if dt > self.pcr_gap.get(pid, 0.0):
                            self.pcr_gap[pid] = dt
                self._pcr_pkt[pid] = (self.packets, pcr)
            if afc == 3:
                payload = p[5 + af_len:]
        elif afc == 1:
            payload = p[4:]

        # continuity_counter: инкремент только при наличии payload
        if afc in (1, 3):
            if st.last_cc is not None:
                if cc != (st.last_cc + 1) & 0x0F:
                    st.cc_errors += 1
            st.last_cc = cc
        elif afc == 2:
            if st.last_cc is not None and cc != st.last_cc:
                st.cc_errors += 1
            st.last_cc = cc

        if not payload or tsc or pid == 0x1FFF:
            return
        if pid not in self.psi_pids and pid not in self.pmt_pids and pid not in self.carousel_pids:
            buf = self.es_bytes.get(pid)
            if pusi and payload[:3] == b"\x00\x00\x01" and len(payload) > 8:
                if buf is None:
                    buf = self.es_bytes[pid] = bytearray()   # начинаем строго с начала PES
                if len(buf) < 96 * 1024:
                    buf += payload[9 + payload[8]:]
            elif buf is not None and len(buf) < 96 * 1024:
                buf += payload

        if pid in self.psi_pids or pid in self.pmt_pids or pid in self.carousel_pids:
            asm = self.assemblers.get(pid)
            if asm is None:
                asm = self.assemblers[pid] = SectionAssembler()
            for sec in asm.push(payload, pusi):
                self._section(pid, sec)
        elif pusi and payload[:3] == b"\x00\x00\x01":
            self._pes(st, payload)

    # -- PES ------------------------------------------------------------------

    def _pes(self, st, payload):
        st.pes_count += 1
        sid = payload[3]
        st.pes_stream_id = sid
        if len(payload) < 9:
            return
        hdr_len = payload[8]
        body = payload[9 + hdr_len:]
        if st.pes_sample is None:
            st.pes_sample = body[:24].hex()
        # AC-3, DTS и линейный PCM тоже идут через stream_id 0xBD, а их куски
        # могут случайно начинаться с 0x80/0x81 — опираемся на сигнализацию в PMT
        if sid == 0xBD and body and body[0] in (0x80, 0x81) and st.pid not in self.audio_sig \
                and (st.pid in self.caption_sig or not self.caption_sig):
            self._caption_pes(st.pid, body)

    def _caption_pes(self, pid, body):
        kind = "caption" if body[0] == 0x80 else "superimpose"
        self.caption_pids.setdefault(pid, kind)
        try:
            hlen = body[2] & 0x0F
            q = body[3 + hlen:]
            if len(q) < 5:
                return
            gid = q[0] >> 2
            size = (q[3] << 8) | q[4]
            grp = q[5:5 + size]
            if gid in (0x00, 0x20):
                self.caption_groups["management(0x%02X)" % gid] += 1
                if pid not in self.caption_mgmt:
                    info = self._caption_mgmt(grp)
                    if info:
                        self.caption_mgmt[pid] = info
            else:
                # data_group_id 1..8 — это 字幕1..字幕8 (группа A), 0x21.. — группа B
                lang_no = (gid - 0x21 if gid >= 0x21 else gid - 1) + 1
                self.caption_groups["statement(0x%02X) = 字幕%d%s" %
                                    (gid, lang_no, " группа B" if gid >= 0x21 else "")] += 1
        except Exception:
            pass

    @staticmethod
    def _caption_mgmt(b):
        if not b:
            return None
        tmd = b[0] >> 6
        i = 1
        if tmd == 0b10:
            return {"TMD": tmd, "note": "TMD=offset time, языки не разобраны"}
        n = b[i]
        i += 1
        langs = []
        for _ in range(n):
            tag = b[i] >> 5
            dmf = b[i] & 0x0F
            i += 1
            e = {"language_tag": tag, "DMF": "0b" + format(dmf, "04b")}
            if dmf in (0x0C, 0x0D, 0x0E):
                e["DC"] = b[i]
                i += 1
            e["lang"] = b[i:i + 3].decode("ascii", "replace")
            i += 3
            f = b[i]
            i += 1
            e["format"] = f >> 4
            e["TCS"] = (f >> 2) & 3
            e["rollup_mode"] = f & 3
            langs.append(e)
        return {"TMD": tmd, "languages": langs}

    # -- секции ---------------------------------------------------------------

    def _section(self, pid, sec):
        # В D-VHS и D-Theater PMT лежит на низких PID (0x0010), а элементарные
        # потоки — на 0x0011 и далее. Поэтому принадлежность к программе важнее
        # привычных номеров PID: иначе PMT разбирается как NIT, а видео — как SI.
        if pid in self.es_pids:
            return
        tid = sec[0]
        syntax = (sec[1] >> 7) & 1
        self.table_counts["0x%02X %s" % (tid, TABLE_NAMES.get(tid, ""))] += 1
        if syntax and len(sec) >= 12 and tid not in (0x3B, 0x3C, 0x3A):
            if crc32_mpeg(sec) != 0:
                self.crc_errors += 1
                return
        try:
            if tid == 0x00:
                self._pat(sec)
            elif tid == 0x01:
                self.cat_descs = parse_descriptors(sec[8:-4], self.charset)
            elif tid == 0x02 and pid in self.pmt_pids:
                self._pmt(pid, sec)
            elif pid in self.pmt_pids:
                return                        # чужие таблицы на PID программы игнорируем
            elif tid in (0x42, 0x46):
                self._sdt(sec)
            elif tid in (0x40, 0x41):
                self._nit(sec, tid)
            elif 0x4E <= tid <= 0x6F:
                self._eit(sec, tid)
            elif tid == 0x70:
                self.time_tdt = mjd_bcd_to_str(sec[3:8])
            elif tid == 0x73:
                self.time_tot = mjd_bcd_to_str(sec[3:8])
                dl = ((sec[8] & 0x0F) << 8) | sec[9]
                self.tot_descs = parse_descriptors(sec[10:10 + dl], self.charset)
            elif tid in (0x3B, 0x3C, 0x3A):
                self._dsmcc(pid, tid, sec)
        except Exception:
            pass

    def _note_pmt_pid(self, pid):
        self.psi_pids.discard(pid)

    def _pat(self, sec):
        body = sec[8:-4]
        for i in range(0, len(body) - 3, 4):
            prog = (body[i] << 8) | body[i + 1]
            pid = ((body[i + 2] & 0x1F) << 8) | body[i + 3]
            if prog == 0:
                self.pat["NIT"] = pid
                self.psi_pids.add(pid)
            else:
                self.pat[prog] = pid
                self.pmt_pids[pid] = prog
                self._note_pmt_pid(pid)

    def _pmt(self, pid, sec):
        prog = (sec[3] << 8) | sec[4]
        version = (sec[5] >> 1) & 0x1F
        pcr_pid = ((sec[8] & 0x1F) << 8) | sec[9]
        pil = ((sec[10] & 0x0F) << 8) | sec[11]
        prog_descs = parse_descriptors(sec[12:12 + pil], self.charset)
        es = []
        i = 12 + pil
        end = len(sec) - 4
        while i + 5 <= end:
            stype = sec[i]
            epid = ((sec[i + 1] & 0x1F) << 8) | sec[i + 2]
            esil = ((sec[i + 3] & 0x0F) << 8) | sec[i + 4]
            descs = parse_descriptors(sec[i + 5:i + 5 + esil], self.charset)
            es.append({"stream_type": stype,
                       "stream_type_str": STREAM_TYPES.get(stype, "0x%02X" % stype),
                       "pid": epid, "descriptors": descs})
            if stype in (0x0B, 0x0D, 0x08, 0x0A, 0x0C):
                self.carousel_pids.add(epid)
            self.es_pids.add(epid)
            self.psi_pids.discard(epid)
            if stype in (0x03, 0x04, 0x0F, 0x11, 0x81, 0x82, 0x83, 0x87):
                self.audio_sig.add(epid)
            elif stype == 0x06 and any(d["tag"] == 0xFD and d.get("data_component_id") == 0x0008
                                       for d in descs):
                self.caption_sig.add(epid)
            i += 5 + esil
        prev = self.programs.get(prog)
        if prev and prev.get("version") == version:
            return
        self.programs[prog] = {"program_number": prog, "pmt_pid": pid,
                               "version": version, "pcr_pid": pcr_pid,
                               "descriptors": prog_descs, "es": es}
        for d in prog_descs:
            if d["tag"] == 0xFC:
                self.emergency.append({"program": prog, "descriptor": d})

    def _sdt(self, sec):
        onid = (sec[8] << 8) | sec[9]
        i = 11
        end = len(sec) - 4
        while i + 5 <= end:
            sid = (sec[i] << 8) | sec[i + 1]
            eit_sched = (sec[i + 2] >> 1) & 1
            eit_pf = sec[i + 2] & 1
            running = sec[i + 3] >> 5
            free_ca = (sec[i + 3] >> 4) & 1
            dl = ((sec[i + 3] & 0x0F) << 8) | sec[i + 4]
            descs = parse_descriptors(sec[i + 5:i + 5 + dl], self.charset)
            name = provider = stype = None
            for d in descs:
                if d["tag"] == 0x48:
                    name = d.get("service_name")
                    provider = d.get("provider")
                    stype = d.get("service_type_str")
            self.services[sid] = {"service_id": sid, "original_network_id": onid,
                                  "name": name, "provider": provider,
                                  "service_type": stype, "free_CA_mode": free_ca,
                                  "running_status": running,
                                  "EIT_schedule": eit_sched, "EIT_pf": eit_pf,
                                  "descriptors": descs}
            i += 5 + dl

    def _nit(self, sec, tid):
        if self.nit is not None:
            return
        nid = (sec[3] << 8) | sec[4]
        ndl = ((sec[8] & 0x0F) << 8) | sec[9]
        ndescs = parse_descriptors(sec[10:10 + ndl], self.charset)
        i = 10 + ndl
        tsl = ((sec[i] & 0x0F) << 8) | sec[i + 1]
        i += 2
        end = min(i + tsl, len(sec) - 4)
        streams = []
        while i + 6 <= end:
            tsid = (sec[i] << 8) | sec[i + 1]
            onid = (sec[i + 2] << 8) | sec[i + 3]
            dl = ((sec[i + 4] & 0x0F) << 8) | sec[i + 5]
            streams.append({"transport_stream_id": tsid, "original_network_id": onid,
                            "descriptors": parse_descriptors(sec[i + 6:i + 6 + dl],
                                                             self.charset)})
            i += 6 + dl
        self.nit = {"network_id": nid, "table": TABLE_NAMES.get(tid),
                    "descriptors": ndescs, "transport_streams": streams}

    def _eit(self, sec, tid):
        if len(self.events) >= self.max_events:
            return
        seen = self._event_keys
        sid = (sec[3] << 8) | sec[4]
        i = 14
        end = len(sec) - 4
        while i + 12 <= end and len(self.events) < self.max_events:
            eid = (sec[i] << 8) | sec[i + 1]
            if (tid, sid, eid) in seen:
                i += 12 + (((sec[i + 10] & 0x0F) << 8) | sec[i + 11])
                continue
            seen.add((tid, sid, eid))
            start = mjd_bcd_to_str(sec[i + 2:i + 7])
            dur = bcd_duration(sec[i + 7:i + 10])
            dl = ((sec[i + 10] & 0x0F) << 8) | sec[i + 11]
            descs = parse_descriptors(sec[i + 12:i + 12 + dl], self.charset)
            title = text = None
            copy_ctl = None
            for d in descs:
                if d["tag"] == 0x4D:
                    title = d.get("event_name")
                    text = d.get("text")
                elif d["tag"] == 0xC1:
                    copy_ctl = d.get("copy_control_str")
            self.events.append({"table": TABLE_NAMES.get(tid, "EIT 0x%02X" % tid),
                                "service_id": sid, "event_id": eid,
                                "start": start, "duration": dur,
                                "title": title, "text": text,
                                "copy_control": copy_ctl,
                                "descriptor_tags": sorted({d["tag"] for d in descs})})
            i += 12 + dl

    def _dsmcc(self, pid, tid, sec):
        self.dsmcc["pid 0x%04X tid 0x%02X" % (pid, tid)] += 1
        if tid != 0x3B:
            return
        try:
            i = 8
            if sec[i] != 0x11:
                return
            msg_id = (sec[i + 2] << 8) | sec[i + 3]
            tx_id = int.from_bytes(sec[i + 4:i + 8], "big")
            adapt = sec[i + 9]
            j = i + 12 + adapt
            entry = self.carousels.setdefault(pid, {"pid": pid, "transactions": {}})
            if msg_id == 0x1002:  # DII
                download_id = int.from_bytes(sec[j:j + 4], "big")
                block_size = (sec[j + 4] << 8) | sec[j + 5]
                # windowSize(1) ackPeriod(1) tCDownloadWindow(4) tCDownloadScenario(4)
                k = j + 6 + 1 + 1 + 4 + 4
                cdl = (sec[k] << 8) | sec[k + 1]
                k += 2 + cdl
                nmod = (sec[k] << 8) | sec[k + 1]
                k += 2
                mods = []
                total = 0
                for _ in range(nmod):
                    mid = (sec[k] << 8) | sec[k + 1]
                    msize = int.from_bytes(sec[k + 2:k + 6], "big")
                    mver = sec[k + 6]
                    mil = sec[k + 7]
                    k += 8 + mil
                    total += msize
                    mods.append({"module_id": mid, "size": msize, "version": mver})
                entry["transactions"]["0x%08X" % tx_id] = {
                    "type": "DII", "download_id": "0x%08X" % download_id,
                    "block_size": block_size, "modules": len(mods),
                    "total_bytes": total, "module_list": mods[:16]}
            elif msg_id == 0x1006:
                entry["transactions"]["0x%08X" % tx_id] = {"type": "DSI"}
        except Exception:
            pass

    # -- сводка ---------------------------------------------------------------

    def bitrate(self):
        best = None
        for st in self.pids.values():
            if st.pcr_count >= 2:
                if best is None or st.pcr_count > best.pcr_count:
                    best = st
        if not best:
            return None
        p0, i0 = best.pcr_first
        p1, i1 = best.pcr_last
        if p1 < p0:
            p1 += 2 ** 33 * 300
        dt = (p1 - p0) / 27000000.0
        if dt <= 0:
            return None
        pkts = i1 - i0
        return {"pcr_pid": best.pid, "duration_s": dt,
                "bitrate_bps": pkts * 188 * 8 / dt,
                "pcr_count": best.pcr_count}

    def es_role(self, stype, descs):
        tags = {d["tag"] for d in descs}
        ctag = next((d.get("component_tag") for d in descs if d["tag"] == 0x52), None)
        if stype == 0x06:
            for d in descs:
                if d["tag"] == 0xFD and d.get("data_component_id") == 0x0008:
                    if ctag is not None and 0x38 <= ctag <= 0x3F:
                        return "文字スーパー / superimpose (ARIB)"
                    return "субтитры ARIB STD-B24"
                if d["tag"] == 0x59:
                    return "субтитры DVB"
                if d["tag"] == 0x56:
                    return "телетекст"
                if d["tag"] == 0xFD:
                    return "данные (%s)" % d.get("data_component_str", "?")
            if ctag is not None and 0x30 <= ctag <= 0x37:
                return "субтитры ARIB (по component_tag)"
            if ctag is not None and 0x38 <= ctag <= 0x3F:
                return "文字スーパー / superimpose (по component_tag)"
            return "приватные данные"
        if stype in (0x0B, 0x0D, 0x08, 0x0A, 0x0C):
            return "карусель данных / DSM-CC"
        if stype in (0x01, 0x02, 0x10, 0x1B, 0x24, 0x80):
            return "видео"
        if stype in (0x03, 0x04, 0x0F, 0x11, 0x81, 0x82, 0x83, 0x87):
            return "аудио"
        if 0x09 in tags:
            return "условный доступ"
        return "прочее"

    def to_dict(self):
        br = self.bitrate()
        d = OrderedDict()
        d["file"] = {"path": self.path, "size": os.path.getsize(self.path),
                     "packet_size": self.pkt_size, "header_len": self.head_len,
                     "sync_offset": self.offset, "packets": self.packets}
        if self.head_len:
            d["source_packets"] = {
                "first_header": self.src_ts_first, "last_header": self.src_ts_last,
                "cpi_distribution": {("0b" + format(k, "02b")): v
                                     for k, v in sorted(self.src_cpi.items())}}
        d["bitrate"] = br
        d["tables"] = dict(self.table_counts)
        d["crc_errors"] = self.crc_errors
        d["pat"] = {str(k): v for k, v in self.pat.items()}
        d["cat"] = self.cat_descs
        d["programs"] = list(self.programs.values())
        d["services"] = list(self.services.values())
        d["nit"] = self.nit
        d["time"] = {"TDT": self.time_tdt, "TOT": self.time_tot,
                     "TOT_descriptors": self.tot_descs}
        d["events"] = self.events
        d["dsmcc_sections"] = dict(self.dsmcc)
        d["carousels"] = list(self.carousels.values())
        d["caption_data_groups"] = dict(self.caption_groups)
        d["caption_management"] = {("0x%04X" % k): v
                                   for k, v in self.caption_mgmt.items()}
        d["emergency"] = self.emergency
        d["pids"] = [{"pid": s.pid, "packets": s.packets, "cc_errors": s.cc_errors,
                      "scrambled_packets": s.scrambled, "tei_errors": s.tei_errors,
                      "pcr_count": s.pcr_count, "pes_packets": s.pes_count,
                      "pes_stream_id": s.pes_stream_id,
                      "pes_first_bytes": s.pes_sample}
                     for s in sorted(self.pids.values(), key=lambda x: x.pid)]
        return d


# ---------------------------------------------------------------------------
# Отчёт
# ---------------------------------------------------------------------------


def h(title):
    return "\n" + "=" * 78 + "\n" + title + "\n" + "=" * 78


def fmt_size(n):
    for u in ("Б", "КиБ", "МиБ", "ГиБ"):
        if n < 1024:
            return "%.1f %s" % (n, u)
        n /= 1024.0
    return "%.1f ТиБ" % n


def report(a):
    o = []
    p = o.append
    size = os.path.getsize(a.path)

    p(h("1. КОНТЕЙНЕР"))
    p("Файл:            %s (%s)" % (a.path, fmt_size(size)))
    p("Размер пакета:   %d байт (%s)" % (
        a.pkt_size,
        {188: "чистый TS", 192: "source packet, 4-байтовый заголовок (i.LINK/M2TS)",
         204: "TS + 16 байт Reed-Solomon",
         208: "4 + 188 + 16"}.get(a.pkt_size, "нестандартно")))
    p("Смещение синхр.: %d байт" % a.offset)
    p("Пакетов:         %d" % a.packets)
    if a.head_len:
        p("Заголовки источниковых пакетов:")
        p("  первый: 0x%08X   последний: 0x%08X" % (a.src_ts_first or 0,
                                                    a.src_ts_last or 0))
        p("  старшие 2 бита (CPI/copy permission у M2TS): " +
          ", ".join("0b%s×%d" % (format(k, "02b"), v)
                    for k, v in sorted(a.src_cpi.items())))
        p("  ! DTCP-статус линка i.LINK (EMI) в TS не хранится — он живёт")
        p("    в CIP-заголовке изохронных пакетов 1394 и здесь не виден.")
    br = a.bitrate()
    if br:
        p("PCR PID:         0x%04X (%d меток)" % (br["pcr_pid"], br["pcr_count"]))
        p("Длительность:    %.2f c (%02d:%02d:%05.2f)" % (
            br["duration_s"], int(br["duration_s"] // 3600),
            int(br["duration_s"] % 3600 // 60), br["duration_s"] % 60))
        p("Битрейт:         %.3f Мбит/с (по TS-полезной нагрузке)" %
          (br["bitrate_bps"] / 1e6))
    else:
        p("PCR не найден — длительность и битрейт не вычислить.")

    p(h("2. ТАБЛИЦЫ PSI/SI"))
    if a.table_counts:
        for k, v in sorted(a.table_counts.items()):
            p("  %-28s секций: %d" % (k, v))
    else:
        p("  таблиц не найдено")
    p("Ошибок CRC: %d" % a.crc_errors)

    p(h("3. PAT / ПРОГРАММЫ"))
    for k, v in a.pat.items():
        p("  program %-6s -> PMT PID 0x%04X" % (k, v))
    for prog in a.programs.values():
        svc = a.services.get(prog["program_number"], {})
        p("\n--- Программа %d (PMT 0x%04X, версия %d) ---" %
          (prog["program_number"], prog["pmt_pid"], prog["version"]))
        if svc:
            p("    Сервис: %s / %s [%s]" % (svc.get("name"), svc.get("provider"),
                                            svc.get("service_type")))
            p("    free_CA_mode: %s" % ("да (открытый)" if not svc["free_CA_mode"]
                                        else "нет (сервис под CA)"))
        p("    PCR PID: 0x%04X" % prog["pcr_pid"])
        if prog["descriptors"]:
            p("    Дескрипторы программы:")
            for d in prog["descriptors"]:
                p("      " + desc_line(d))
        p("    Элементарные потоки:")
        for es in prog["es"]:
            st = a.pids.get(es["pid"])
            role = a.es_role(es["stream_type"], es["descriptors"])
            p("      PID 0x%04X  type 0x%02X %-26s %s" %
              (es["pid"], es["stream_type"], es["stream_type_str"], role))
            if st:
                p("        пакетов: %d, PES: %d, скремблировано: %d, CC-ошибок: %d"
                  % (st.packets, st.pes_count, st.scrambled, st.cc_errors))
                if st.pes_sample:
                    p("        первые байты PES: %s" % st.pes_sample)
            for d in es["descriptors"]:
                p("        " + desc_line(d))

    p(h("4. СУБТИТРЫ"))
    found = []
    for prog in a.programs.values():
        for es in prog["es"]:
            role = a.es_role(es["stream_type"], es["descriptors"])
            if "убтитр" in role or "superimpose" in role or "елетекст" in role:
                found.append((prog["program_number"], es, role))
    if not found:
        p("  В PMT субтитровые ES не объявлены.")
    for prognum, es, role in found:
        st = a.pids.get(es["pid"])
        ctag = next((d.get("component_tag") for d in es["descriptors"]
                     if d["tag"] == 0x52), None)
        p("  программа %d, PID 0x%04X — %s" % (prognum, es["pid"], role))
        p("    component_tag: %s" % ("0x%02X" % ctag if ctag is not None else "нет"))
        for d in es["descriptors"]:
            if d["tag"] == 0xFD:
                p("    data_component: %s (id 0x%04X)" %
                  (d.get("data_component_str"), d.get("data_component_id", 0)))
                p("    additional_arib_caption_info: %s" % d.get("additional_info"))
                for lang in d.get("caption_languages", []):
                    p("      lang=%s tag=%d DMF=%s format=%s TCS=%s rollup=%s" %
                      (lang.get("lang"), lang.get("language_tag"), lang.get("DMF"),
                       lang.get("format"), lang.get("TCS"), lang.get("rollup_mode")))
        if st:
            p("    трафик: %d TS-пакетов, %d PES-пакетов" % (st.packets, st.pes_count))
            if st.packets and not st.pes_count:
                if st.scrambled:
                    p("    ! PES не разобрать: пакеты скремблированы (%d шт.)" %
                      st.scrambled)
                else:
                    p("    ! PID объявлен, но PES-пакеты не найдены — поток пустой")
            if not st.packets:
                p("    ! PID объявлен в PMT, но трафика по нему нет вообще")
    if a.caption_groups:
        p("\n  Реально принятые data group (из PES):")
        for k, v in sorted(a.caption_groups.items()):
            p("    %-22s %d" % (k, v))
    else:
        p("\n  Data group субтитров в PES не обнаружено.")
    for pid, mg in a.caption_mgmt.items():
        p("  caption management data, PID 0x%04X: TMD=%s" % (pid, mg.get("TMD")))
        for lang in mg.get("languages", []):
            p("    lang=%s tag=%d DMF=%s format=%s TCS=%s rollup=%s" %
              (lang.get("lang"), lang.get("language_tag"), lang.get("DMF"),
               lang.get("format"), lang.get("TCS"), lang.get("rollup_mode")))

    p(h("5. КАРУСЕЛИ ДАННЫХ / DSM-CC"))
    if not a.dsmcc:
        p("  DSM-CC секций не найдено.")
    for k, v in sorted(a.dsmcc.items()):
        p("  %s: %d секций" % (k, v))
    for c in a.carousels.values():
        p("  PID 0x%04X:" % c["pid"])
        for txid, tx in c["transactions"].items():
            if tx["type"] == "DII":
                p("    DII transaction %s, download_id %s, block %d Б, модулей %d, "
                  "суммарно %s" % (txid, tx["download_id"], tx["block_size"],
                                   tx["modules"], fmt_size(tx["total_bytes"])))
                for m in tx["module_list"]:
                    p("      module 0x%04X  %8d Б  v%d" %
                      (m["module_id"], m["size"], m["version"]))
            else:
                p("    DSI transaction %s" % txid)
    for prog in a.programs.values():
        for es in prog["es"]:
            for d in es["descriptors"]:
                if d["tag"] == 0x13:
                    p("  carousel_identifier на PID 0x%04X: id=%d" %
                      (es["pid"], d.get("carousel_id")))
                if d["tag"] == 0x14:
                    p("  association_tag на PID 0x%04X: 0x%04X" %
                      (es["pid"], d.get("association_tag", 0)))

    p(h("6. УПРАВЛЕНИЕ КОПИРОВАНИЕМ И ЗАЩИТА"))
    any_cc = False
    for prog in a.programs.values():
        for d in prog["descriptors"]:
            if d["tag"] == 0xC1:
                any_cc = True
                p("  [программа %d] digital_copy_control: %s, APS: %s" %
                  (prog["program_number"], d.get("copy_control_str"), d.get("APS_str")))
                if "maximum_bitrate_kbps" in d:
                    p("      максимальный битрейт: %d кбит/с" %
                      d["maximum_bitrate_kbps"])
                for c in d.get("components", []):
                    p("      component_tag 0x%02X: %s" %
                      (c["component_tag"], c["copy_control_str"]))
            if d["tag"] == 0xDE:
                any_cc = True
                p("  [программа %d] content_availability: %s; "
                  "copy_restriction_mode=%d, image_constraint_token=%d, "
                  "retention_mode=%d, retention_state=%d" %
                  (prog["program_number"], d.get("encryption_str"),
                   d.get("copy_restriction_mode", 0), d.get("image_constraint_token", 0),
                   d.get("retention_mode", 0), d.get("retention_state", 0)))
        for es in prog["es"]:
            for d in es["descriptors"]:
                if d["tag"] in (0xC1, 0xDE):
                    any_cc = True
                    p("  [PID 0x%04X] %s: %s" % (es["pid"], d["name"],
                                                 d.get("copy_control_str") or
                                                 d.get("encryption_str")))
                if d["tag"] == 0x09:
                    p("  [PID 0x%04X] CA_descriptor: CA_system_id 0x%04X, "
                      "ECM PID 0x%04X" % (es["pid"], d.get("ca_system_id", 0),
                                          d.get("ca_pid", 0)))
    for ev in a.events:
        if ev.get("copy_control"):
            p("  [EIT, событие 0x%04X] digital_copy_control: %s" %
              (ev["event_id"], ev["copy_control"]))
    if a.cat_descs:
        p("  CAT:")
        for d in a.cat_descs:
            if d["tag"] == 0x09:
                p("    CA_system_id 0x%04X, EMM PID 0x%04X" %
                  (d.get("ca_system_id", 0), d.get("ca_pid", 0)))
            else:
                p("    " + desc_line(d))
    if not any_cc and not a.cat_descs:
        p("  Дескрипторов управления копированием и CA не найдено.")

    scrambled = [s for s in a.pids.values() if s.scrambled]
    p("\n  Скремблирование (transport_scrambling_control):")
    if scrambled:
        for s in sorted(scrambled, key=lambda x: -x.scrambled):
            p("    PID 0x%04X: %d из %d пакетов помечены как скремблированные" %
              (s.pid, s.scrambled, s.packets))
        p("    -> поток закрыт CA (B-CAS/CAS); ES не разобрать без дескремблирования.")
    else:
        p("    ни один пакет не помечен — поток открытый (или уже дескремблирован).")

    p(h("7. КАРТА PID"))
    p("  %-8s %10s %7s %8s %6s %8s  %s" %
      ("PID", "пакетов", "доля", "скрембл", "CC-err", "PES", "назначение"))
    es_map = {}
    for prog in a.programs.values():
        es_map[prog["pcr_pid"]] = es_map.get(prog["pcr_pid"], "PCR")
        es_map[prog["pmt_pid"]] = "PMT prog %d" % prog["program_number"]
        for es in prog["es"]:
            es_map[es["pid"]] = "%s / %s" % (es["stream_type_str"],
                                             a.es_role(es["stream_type"],
                                                       es["descriptors"]))
    for s in sorted(a.pids.values(), key=lambda x: -x.packets):
        role = es_map.get(s.pid) or WELL_KNOWN_PIDS.get(s.pid, "?")
        p("  0x%04X %10d %6.2f%% %8d %6d %8d  %s" %
          (s.pid, s.packets, 100.0 * s.packets / max(1, a.packets),
           s.scrambled, s.cc_errors, s.pes_count, role))

    p(h("8. СЕТЬ / ВРЕМЯ / EPG"))
    if a.nit:
        p("  NIT: network_id %d (%s)" % (a.nit["network_id"], a.nit["table"]))
        for d in a.nit["descriptors"]:
            p("    " + desc_line(d))
        for ts in a.nit["transport_streams"]:
            p("    TS 0x%04X (onid 0x%04X)" % (ts["transport_stream_id"],
                                               ts["original_network_id"]))
            for d in ts["descriptors"]:
                p("      " + desc_line(d))
    else:
        p("  NIT не найдена.")
    p("  TDT: %s" % (a.time_tdt or "нет"))
    p("  TOT: %s" % (a.time_tot or "нет"))
    for d in a.tot_descs:
        p("    " + desc_line(d))
    if a.events:
        p("\n  События EPG (%d, уникальные по event_id):" % len(a.events))
        for e in a.events:
            p("    [%s] sid 0x%04X eid 0x%04X %s +%s  %s" %
              (e["table"], e["service_id"], e["event_id"], e["start"],
               e["duration"], e["title"] or ""))
            if e["text"]:
                p("        %s" % e["text"][:110])
    else:
        p("\n  EIT не найдена.")
    if a.emergency:
        p("\n  !!! Обнаружен emergency_information_descriptor (緊急警報放送)")

    p(h("9. ЗВУК: ФОРМАТЫ И СООТВЕТСТВИЕ D-VHS"))
    audio_found = False
    for prog in a.programs.values():
        for es in prog["es"]:
            if a.es_role(es["stream_type"], es["descriptors"]) != "аудио":
                continue
            audio_found = True
            ctag = next((d.get("component_tag") for d in es["descriptors"] if d["tag"] == 0x52), None)
            lang = next((d.get("language") or d.get("ISO_639_language_code")
                         for d in es["descriptors"] if d["tag"] == 0x0A), None)
            p("  PID 0x%04X  stream_type 0x%02X %s%s%s" % (
                es["pid"], es["stream_type"], STREAM_TYPES.get(es["stream_type"], ""),
                "  tag 0x%02X" % ctag if ctag is not None else "",
                "  язык %s" % lang if lang else ""))
            info = probe_audio(es["stream_type"], bytes(a.es_bytes.get(es["pid"], b"")))
            if info:
                p("    " + ", ".join("%s=%s" % (k, v) for k, v in info.items()))
            else:
                p("    поток не разобран (мало данных или чужой формат)")
            for msg in check_dvhs_audio(es["stream_type"], info):
                p("    ! " + msg)
    if not audio_found:
        p("  звуковых ES не найдено")

    p(h("10. ПРИГОДНОСТЬ ДЛЯ ЗАПИСИ НА D-VHS"))
    pcr_pid = max(a.peak_rate, key=lambda k: a.pids[k].pcr_count) if a.peak_rate else None
    if pcr_pid is not None:
        peak, at = a.peak_rate[pcr_pid]
        p("Пиковая мгновенная скорость: %.1f Мбит/с (на %.1f с, между соседними PCR)" % (peak, at))
        for name, lim in (("HS", 28.2), ("STD", 14.1)):
            p("  режим %-3s (%4.1f Мбит/с): %s" % (name, lim, "проходит" if peak <= lim else
                                                   "ПРЕВЫШЕН — дека может запнуться"))
        gap = a.pcr_gap.get(pcr_pid, 0)
        p("Самый долгий интервал между PCR: %.1f мс (предел ARIB 100)%s" % (
            gap * 1000, "" if gap <= 0.1 else "  ! превышен"))
    else:
        p("PCR не найден — оценить скорость нельзя")
    video_pids = {es["pid"] for prog in a.programs.values() for es in prog["es"]
                  if a.es_role(es["stream_type"], es["descriptors"]) == "видео"}
    bursts = sorted(((v, k) for k, v in a.run_max.items()
                     if v >= 16 and k != 0x1FFF and k not in video_pids), reverse=True)
    if bursts:
        p("Длинные пачки пакетов одного PID — создают всплеск скорости:")
        for v, k in bursts[:6]:
            p("  PID 0x%04X: %d подряд" % (k, v))
    else:
        others = [v for k, v in a.run_max.items() if k != 0x1FFF and k not in video_pids]
        p("Пачек нет: вне видео максимум %d пакетов подряд" % (max(others) if others else 0))
    for k in sorted(video_pids):
        if a.run_max.get(k, 0) >= 16:
            p("  (видео PID 0x%04X идёт по %d пакетов подряд — для видео это норма)"
              % (k, a.run_max[k]))
    tabs = set(a.table_counts)
    has = lambda name: any(name in t for t in tabs)
    p("SIT: %s, DIT: %s" % ("есть" if has("SIT") else "нет", "есть" if has("DIT") else "нет"))
    extra = [t for t in ("NIT", "SDT", "EIT", "TOT", "BIT") if has(t)]
    p("Эфирные таблицы в потоке: %s" % (", ".join(extra) if extra else "нет"))
    if has("SIT") and not extra:
        p("  -> похоже на partial TS, как его отдаёт тюнер по i.LINK")
    elif extra and not has("SIT"):
        p("  -> похоже на полный эфирный поток, не partial TS")
    mtrm = any(d.get("format_identifier") == "MTRM"
               for prog in a.programs.values() for d in prog["descriptors"] if d["tag"] == 0x05)
    p("registration MTRM (флаг D-VHS-совместимости): %s" % ("есть" if mtrm else "нет"))
    dtcp = [d for prog in a.programs.values() for d in prog["descriptors"] if d["tag"] == 0x88]
    if dtcp:
        d = dtcp[0]
        p("DTCP_descriptor: CCI=%s, EPN=%d, ICT=%d, APS=%s" % (
            d.get("DTCP_CCI_str"), d.get("EPN", 0), d.get("Image_Constraint_Token", 0), d.get("APS_str")))
    else:
        p("DTCP_descriptor (0x88): нет")

    p(h("11. ЗАМЕЧАНИЯ"))
    warn = []
    total_cc = sum(s.cc_errors for s in a.pids.values())
    if total_cc:
        warn.append("Ошибок continuity_counter: %d (обрывы/потери пакетов)" % total_cc)
    tei = sum(s.tei_errors for s in a.pids.values())
    if tei:
        warn.append("transport_error_indicator взведён у %d пакетов" % tei)
    if a.crc_errors:
        warn.append("Секций с битым CRC: %d" % a.crc_errors)
    null = a.pids.get(0x1FFF)
    if null:
        warn.append("Нулевых пакетов (PID 0x1FFF): %d — %.1f%% потока" %
                    (null.packets, 100.0 * null.packets / max(1, a.packets)))
    if not a.programs:
        warn.append("PMT не разобрана — PAT не найдена или поток скремблирован")
    for prog in a.programs.values():
        tags = [d.get("component_tag") for es in prog["es"] for d in es["descriptors"]
                if d["tag"] == 0x52]
        if len(tags) != len(set(tags)):
            warn.append("Программа %d: повторяющиеся component_tag %s" %
                        (prog["program_number"], tags))
        if not any(d["tag"] == 0xC1 for d in prog["descriptors"]):
            warn.append("Программа %d: нет digital_copy_control_descriptor "
                        "(ARIC требует его в PMT для вещательного потока)" %
                        prog["program_number"])
    if a.caption_pids and not a.caption_groups:
        warn.append("Найдены PES с data_identifier 0x80/0x81, но data group не разобраны")
    if scrambled:
        warn.append("Скремблировано PID'ов: %d — часть анализа недоступна без "
                    "дескремблирования" % len(scrambled))
    cap_es = [es for prog in a.programs.values() for es in prog["es"]
              if "убтитр" in a.es_role(es["stream_type"], es["descriptors"])]
    if cap_es and not a.caption_groups and not scrambled:
        warn.append("Субтитровый ES объявлен, но ни одной caption data group "
                    "не принято — проверьте PES (data_identifier 0x80) и PTS")
    if not warn:
        p("  Ничего подозрительного.")
    for w in warn:
        p("  * " + w)
    return "\n".join(o)


def signature(a):
    """Детерминированный дамп сигнализации без счётчиков трафика.

    Годится для сравнения эталонного вещательного потока со своим муксом:
        diff <(tsinfo.py --sig ref.ts) <(tsinfo.py --sig mine.ts)
    """
    o = []
    p = o.append
    p("CONTAINER packet_size=%d header_len=%d" % (a.pkt_size, a.head_len))
    for k, v in a.pat.items():
        p("PAT %s -> 0x%04X" % (k, v))
    for d in a.cat_descs:
        p("CAT desc 0x%02X %s raw=%s" % (d["tag"], d["name"], d["raw"]))
    for prog in a.programs.values():
        n = prog["program_number"]
        p("PMT %d pid=0x%04X pcr=0x%04X" % (n, prog["pmt_pid"], prog["pcr_pid"]))
        for d in prog["descriptors"]:
            p("PMT %d desc 0x%02X %-24s raw=%s" % (n, d["tag"], d["name"], d["raw"]))
        for es in prog["es"]:
            ctag = next((d.get("component_tag") for d in es["descriptors"]
                         if d["tag"] == 0x52), None)
            p("ES  %d pid=0x%04X type=0x%02X tag=%s %s" %
              (n, es["pid"], es["stream_type"],
               ("0x%02X" % ctag) if ctag is not None else "--",
               a.es_role(es["stream_type"], es["descriptors"])))
            for d in es["descriptors"]:
                p("ES  %d pid=0x%04X desc 0x%02X %-24s raw=%s" %
                  (n, es["pid"], d["tag"], d["name"], d["raw"]))
    for sid, svc in a.services.items():
        p("SDT 0x%04X name=%s provider=%s type=%s free_CA=%d" %
          (sid, svc.get("name"), svc.get("provider"), svc.get("service_type"),
           svc.get("free_CA_mode", 0)))
    for pid, kind in sorted(a.caption_pids.items()):
        p("CAPTION pid=0x%04X pes_data_identifier=%s" %
          (pid, "0x80 (subtitle)" if kind == "caption" else "0x81 (superimpose)"))
    for k, v in sorted(a.caption_groups.items()):
        p("CAPTION data_group %s" % k)
    for pid, mg in a.caption_mgmt.items():
        for lang in mg.get("languages", []):
            p("CAPTION mgmt pid=0x%04X lang=%s tag=%s DMF=%s format=%s TCS=%s "
              "rollup=%s" % (pid, lang.get("lang"), lang.get("language_tag"),
                             lang.get("DMF"), lang.get("format"), lang.get("TCS"),
                             lang.get("rollup_mode")))
    for c in a.carousels.values():
        for txid, tx in sorted(c["transactions"].items()):
            p("CAROUSEL pid=0x%04X tx=%s %s" % (c["pid"], txid, tx["type"]))
    for s in sorted(a.pids.values(), key=lambda x: x.pid):
        if s.scrambled:
            p("SCRAMBLED pid=0x%04X" % s.pid)
    return "\n".join(o)


def desc_line(d):
    skip = {"tag", "name", "len", "raw"}
    parts = []
    for k, v in d.items():
        if k in skip or v is None:
            continue
        if isinstance(v, (list, dict)):
            v = json.dumps(v, ensure_ascii=False)
            if len(v) > 160:
                v = v[:157] + "..."
        parts.append("%s=%s" % (k, v))
    tail = ", ".join(parts) if parts else "raw=" + d["raw"]
    return "0x%02X %-28s %s" % (d["tag"], d["name"], tail)


# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(
        description="Инвентаризация вещательного TS (ARIB/ISDB и DVB)")
    ap.add_argument("path", help="файл .ts / .m2t / .m2ts")
    ap.add_argument("--json", action="store_true", help="вывести JSON вместо отчёта")
    ap.add_argument("--sig", action="store_true",
                    help="дамп сигнализации без счётчиков — удобно для diff "
                         "эталонного потока со своим муксом")
    ap.add_argument("--max-mb", type=float, default=None,
                    help="читать только первые N МиБ")
    ap.add_argument("--events", type=int, default=5,
                    help="сколько событий EPG показать (по умолчанию 5)")
    ap.add_argument("--charset", choices=("auto", "arib", "dvb", "ascii"), default="auto",
                    help="кодировка текстовых полей SI")
    args = ap.parse_args()

    if not os.path.isfile(args.path):
        sys.exit("Нет такого файла: %s" % args.path)

    a = TSAnalyzer(args.path, charset=args.charset,
                   max_bytes=int(args.max_mb * 1024 * 1024) if args.max_mb else None,
                   max_events=args.events)
    a.run()
    if args.json:
        json.dump(a.to_dict(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    elif args.sig:
        print(signature(a))
    else:
        print(report(a))


if __name__ == "__main__":
    main()
