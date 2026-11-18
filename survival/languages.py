"""나라별로 표지판·간판에 쓰이는 언어 (장면 이미지용).

이미지 모델은 지시문에 섞인 글자를 그림 속 표지판에 그대로 흉내 내는 경향이 있다. 그래서 그림 지시문에는
한글을 넣지 않고, 표지판이 나온다면 그 나라에서 실제로 쓰는 언어로 쓰도록 지정한다.
"""

# 국가 코드 → 표지판에 주로 쓰이는 언어(영어 이름)
SIGN_LANGUAGE = {
    # 오세아니아 · 북미 · 영어권
    "au": "English", "nz": "English", "us": "English", "ca": "English and French", "gb": "English",
    "ie": "English", "fj": "English", "pg": "English", "gy": "English", "jm": "English",
    "za": "English", "ng": "English", "gh": "English", "ke": "English and Swahili", "ug": "English",
    "zm": "English", "zw": "English", "bw": "English", "na": "English", "mw": "English",
    "sl": "English", "lr": "English", "ss": "English", "sg": "English and Chinese",
    "ph": "English and Filipino", "in": "Hindi and English", "pk": "Urdu and English",
    "bd": "Bengali", "lk": "Sinhala, Tamil and English", "np": "Nepali (Devanagari script)",
    "mv": "Dhivehi and English",
    # 중남미
    "mx": "Spanish", "gt": "Spanish", "hn": "Spanish", "ni": "Spanish", "sv": "Spanish", "cr": "Spanish",
    "pa": "Spanish", "cu": "Spanish", "do": "Spanish", "co": "Spanish", "ve": "Spanish", "ec": "Spanish",
    "pe": "Spanish", "bo": "Spanish", "cl": "Spanish", "ar": "Spanish", "py": "Spanish", "uy": "Spanish",
    "br": "Portuguese", "sr": "Dutch", "gf": "French", "ht": "French and Haitian Creole",
    # 유럽
    "fr": "French", "be": "French and Dutch", "ch": "German and French", "de": "German", "at": "German",
    "nl": "Dutch", "es": "Spanish", "pt": "Portuguese", "it": "Italian", "gr": "Greek (Greek alphabet)",
    "dk": "Danish", "no": "Norwegian", "se": "Swedish", "fi": "Finnish", "is": "Icelandic",
    "pl": "Polish", "cz": "Czech", "sk": "Slovak", "hu": "Hungarian", "ro": "Romanian",
    "bg": "Bulgarian (Cyrillic)", "rs": "Serbian (Cyrillic and Latin)", "hr": "Croatian", "si": "Slovenian",
    "ua": "Ukrainian (Cyrillic)", "by": "Belarusian and Russian (Cyrillic)", "lt": "Lithuanian",
    "lv": "Latvian", "ee": "Estonian", "ru": "Russian (Cyrillic)", "gl": "Greenlandic and Danish",
    # 중동 · 북아프리카
    "eg": "Arabic", "ly": "Arabic", "tn": "Arabic and French", "dz": "Arabic and French",
    "ma": "Arabic and French", "mr": "Arabic", "sd": "Arabic", "sa": "Arabic", "ae": "Arabic and English",
    "om": "Arabic", "qa": "Arabic", "kw": "Arabic", "iq": "Arabic", "ye": "Arabic", "jo": "Arabic",
    "lb": "Arabic", "sy": "Arabic", "il": "Hebrew", "ir": "Persian (Arabic script)", "tr": "Turkish",
    "af": "Dari and Pashto (Arabic script)",
    # 아프리카 (프랑스어권 등)
    "ml": "French", "ne": "French", "td": "French and Arabic", "sn": "French", "ci": "French",
    "bf": "French", "gn": "French", "bj": "French", "tg": "French", "cm": "French", "cf": "French",
    "ga": "French", "cg": "French", "cd": "French", "mg": "Malagasy and French", "rw": "Kinyarwanda and English",
    "et": "Amharic (Ge'ez script)", "er": "Tigrinya", "so": "Somali", "dj": "French and Arabic",
    "tz": "Swahili", "ao": "Portuguese", "mz": "Portuguese",
    # 아시아
    "cn": "Simplified Chinese", "hk": "Traditional Chinese and English", "tw": "Traditional Chinese",
    "jp": "Japanese", "mn": "Mongolian (Cyrillic)", "kz": "Kazakh and Russian (Cyrillic)",
    "uz": "Uzbek (Latin)", "kg": "Kyrgyz and Russian (Cyrillic)", "tj": "Tajik (Cyrillic)",
    "tm": "Turkmen (Latin)", "az": "Azerbaijani (Latin)", "ge": "Georgian script", "am": "Armenian script",
    "th": "Thai", "vn": "Vietnamese", "la": "Lao", "kh": "Khmer", "mm": "Burmese", "my": "Malay",
    "id": "Indonesian", "tl": "Portuguese and Tetum", "bn": "Malay", "bt": "Dzongkha",
}


def sign_language(country_code, country_en=""):
    """그 나라 표지판에 쓰일 언어. 목록에 없으면 '그 나라의 현지 언어'."""
    lang = SIGN_LANGUAGE.get((country_code or "").lower())
    if lang:
        return lang
    return f"the local language of {country_en}" if country_en else "the local language"


def sign_rule(country_code, country_en=""):
    """그림 지시문에 넣는 글자 규칙."""
    lang = sign_language(country_code, country_en)
    return (f"Keep visible text to a minimum. Any signs, labels or shop names that do appear must be written "
            f"in {lang}, as they really are in this country. Never use Korean letters (Hangul). ")
