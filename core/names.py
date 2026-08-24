"""ПІБ → ім'я + кличний відмінок. Ніколи не звертаємось на прізвище.

first_name("Петренко Оксана Іванівна") -> "Оксана"
vocative("Оксана") -> "Оксано"; невідоме ім'я -> "" (звертаємось без імені).
"""
from __future__ import annotations

import re

SURNAME_SUFFIX = re.compile(r"(енко|єнко|ук|юк|чук|ський|ська|цький|цька|зький|зька|ов|ова|ев|єв|єва|ін|іна|ич|ич|ко|ишин|ишина|ець|ак|як)$", re.IGNORECASE)
PATRONYMIC = re.compile(r"(івна|ївна|овна|ович|йович|евич|євич|ич)$", re.IGNORECASE)
MALE_A = {"микола", "ілля", "сава", "лука", "кузьма", "хома", "микита", "данило", "кирило", "михайло", "павло", "петро", "дмитро"}

VOCATIVE_EXCEPTIONS = {
    "федір": "Федоре", "яків": "Якове", "лев": "Леве", "антін": "Антоне", "прокіп": "Прокопе", "сидір": "Сидоре",
    "ігор": "Ігорю", "олег": "Олегу", "любов": "Любов", "нінель": "Нінель", "ілля": "Ілле", "микола": "Миколо",
    "сава": "Саво", "лука": "Луко", "кузьма": "Кузьмо", "хома": "Хомо", "микита": "Микито",
}


FIRST_NAMES = set("""
оксана олена ольга наталія наталя тетяна ірина світлана людмила галина марія маріна марина валентина юлія анна ганна катерина
вікторія віка надія лариса алла любов ніна віра лідія зоя інна алла леся дарина дар'я софія соломія христина злата поліна аліна
вероніка діана яна жанна інга ілона ельвіра лілія лариса руслана мирослава ярослава богдана роксолана орися уляна олеся василина
євгенія валерія маргарита анастасія настя таїсія тамара раїса євдокія емма єва антоніна ангеліна
тарас олег олександр сашко андрій сергій дмитро максим іван микола василь петро павло володимир вова володя юрій роман богдан
ярослав станіслав владислав влад віталій валерій віктор ігор євген артем денис антон кирило данило назар остап орест
михайло мирослав леонід григорій геннадій анатолій костянтин руслан вадим едуард тимур марк матвій захар лев арсен
святослав ростислав вячеслав степан семен федір яків ілля лука сава кузьма хома микита олексій льоша
""".split())


def _is_first(tok: str) -> bool:
    return tok.lower().replace("’", "'") in FIRST_NAMES


def split_pib(full: str | None, hint_first: str | None = None) -> tuple[str, str, str]:
    """(прізвище, ім'я, по батькові) — з евристикою порядку."""
    if not full:
        return "", "", ""
    parts = [p for p in re.split(r"\s+", full.strip()) if p]
    if len(parts) >= 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        a, b = parts
        if hint_first and a.lower() == hint_first.lower():
            return b, a, ""
        if hint_first and b.lower() == hint_first.lower():
            return a, b, ""
        if _is_first(a) and not _is_first(b):
            return b, a, ""                       # «Тарас Левчик»
        if _is_first(b) and not _is_first(a):
            return a, b, ""                       # «Левчик Тарас»
        if PATRONYMIC.search(b) and not SURNAME_SUFFIX.search(b):
            return "", a, b                       # «Оксана Іванівна»
        if SURNAME_SUFFIX.search(a) and not SURNAME_SUFFIX.search(b):
            return a, b, ""                       # «Петренко Оксана»
        if SURNAME_SUFFIX.search(b) and not SURNAME_SUFFIX.search(a):
            return b, a, ""                       # «Оксана Петренко»
        return a, b, ""                           # за замовчуванням: Прізвище Ім'я
    return "", parts[0], ""


def first_name(full: str | None, hint_first: str | None = None) -> str:
    return split_pib(full, hint_first)[1]


def vocative(name: str) -> str:
    n = (name or "").strip()
    if not n or not re.fullmatch(r"[А-ЯІЇЄҐа-яіїєґ'’\-]+", n):
        return ""
    low = n.lower()
    if low in VOCATIVE_EXCEPTIONS:
        return VOCATIVE_EXCEPTIONS[low]
    if low.endswith("ія") or low.endswith("ея"):
        return n[:-1] + "є"                       # Марія → Маріє
    if low.endswith("а"):
        return n[:-1] + "о"                       # Оксана → Оксано, Микола → Миколо
    if low.endswith("я"):
        return n[:-1] + "ю"                       # Наталя → Наталю
    if low.endswith(("ь", "й")):
        return n[:-1] + "ю"                       # Василь → Василю, Андрій → Андрію
    if low.endswith("о"):
        return n[:-1] + "е"                       # Петро → Петре
    if low.endswith(("г", "к", "х")):
        return n + "у"                            # Олег → Олегу
    if re.search(r"[бвджзлмнпрстфцчшщ]$", low):
        return n + "е"                            # Іван → Іване
    return n


def address(full: str | None, hint_first: str | None = None) -> str:
    """Кличний відмінок імені з ПІБ або '' — для підстановки «{addr}, …»."""
    return vocative(first_name(full, hint_first))


def clean_np(desc: str | None) -> str:
    """«Відділення №12 (до 30 кг на одне місце): вул. Шевченка, 5» → «відділення №12, вул. Шевченка, 5»."""
    if not desc:
        return ""
    d = re.sub(r"\s*\([^)]*кг[^)]*\)", "", desc)
    d = d.replace("Відділення", "відділення").replace("Поштомат \"Нова Пошта\"", "поштомат").replace("Поштомат", "поштомат")
    d = re.sub(r":\s*", ", ", d, count=1)
    return re.sub(r"\s+", " ", d).strip()


def plural_steps(n: int) -> str:
    if n == 1:
        return "1 крок"
    if 2 <= n <= 4:
        return f"{n} кроки"
    return f"{n} кроків"


def steps_left_phrase(n: int) -> str:
    """«Лишився один крок» / «Лишилося 3 кроки» — узгоджено."""
    if n == 1:
        return "Лишився один крок"
    return f"Лишилося {plural_steps(n)}"
