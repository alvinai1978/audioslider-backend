import re

NARRATOR_NAMES = ("Blessica", "Angelo", "Narrator", "Commentator")


def remove_narrator_labels(text: str) -> str:
    """Remove narrator labels only, without removing useful labels like Phase 1: or Monthly Plan:."""
    cleaned = []
    for line in (text or "").splitlines():
        line = re.sub(r"^\s*(Blessica|Angelo|Narrator|Commentator)\s*:\s*", "", line, flags=re.I).strip()
        if line:
            cleaned.append(line)
    return "\n".join(cleaned)


def normalize_for_speech(input_text: str) -> str:
    """Normalize symbols, peso amounts, ranges, percentages, and common plan words for Tagalog TTS."""
    text = remove_narrator_labels(input_text or "")

    # Specific commercial pricing pattern requested by user.
    text = re.sub(r"Trial\s*/\s*Demo\s*:\s*free\s*,\s*limited", "Trial o Demo: libre, pero limitado ang paggamit.", text, flags=re.I)
    text = re.sub(r"\b1\s*month\s*:\s*₱([\d,]+(?:\.\d{2})?)\s*[–—-]\s*₱([\d,]+(?:\.\d{2})?)", lambda m: f"Isang buwan: mula {money_to_tagalog_pesos(m.group(1), noun='pesos')} hanggang {money_to_tagalog_pesos(m.group(2), noun='pesos')}.", text, flags=re.I)
    text = re.sub(r"\b1\s*year\s*:\s*₱([\d,]+(?:\.\d{2})?)\s*[–—-]\s*₱([\d,]+(?:\.\d{2})?)", lambda m: f"Isang taon: mula {money_to_tagalog_pesos(m.group(1), noun='pesos')} hanggang {money_to_tagalog_pesos(m.group(2), noun='pesos')}.", text, flags=re.I)
    text = re.sub(r"\bLifetime\s*:\s*₱([\d,]+(?:\.\d{2})?)\s*[–—-]\s*₱([\d,]+(?:\.\d{2})?)", lambda m: f"Lifetime access: mula {money_to_tagalog_pesos(m.group(1), noun='pesos')} hanggang {money_to_tagalog_pesos(m.group(2), noun='pesos')}.", text, flags=re.I)

    # Peso amounts written as: 10,000,000.00 Pesos, 1,000,000 Pesos, PHP 2,999, etc.
    text = re.sub(r"\bPHP\s*([\d,]+(?:\.\d{2})?)\b", lambda m: money_to_tagalog_pesos(m.group(1)), text, flags=re.I)
    text = re.sub(r"\b([\d,]+(?:\.\d{2})?)\s*(?:pesos?|piso)\b", lambda m: money_to_tagalog_pesos(m.group(1)), text, flags=re.I)

    # Currency ranges before single currency.
    text = re.sub(r"₱([\d,]+(?:\.\d{2})?)\s*[–—-]\s*₱([\d,]+(?:\.\d{2})?)", lambda m: f"mula {money_to_tagalog_pesos(m.group(1), noun='pesos')} hanggang {money_to_tagalog_pesos(m.group(2), noun='pesos')}", text)
    text = re.sub(r"\$([\d,]+(?:\.\d{2})?)\s*[–—-]\s*\$([\d,]+(?:\.\d{2})?)", lambda m: f"mula {money_to_tagalog_dollars(m.group(1))} hanggang {money_to_tagalog_dollars(m.group(2))}", text)

    # Percentages and numeric ranges.
    text = re.sub(r"(\d+(?:\.\d+)?)\s*%", lambda m: f"{decimal_to_tagalog(m.group(1))} porsiyento", text)
    text = re.sub(r"\b(\d+)\s*[–—-]\s*(\d+)\b", lambda m: f"{number_to_tagalog(int(m.group(1)))} hanggang {number_to_tagalog(int(m.group(2)))}", text)

    # Single currency symbols.
    text = re.sub(r"₱([\d,]+(?:\.\d{2})?)", lambda m: money_to_tagalog_pesos(m.group(1), noun='pesos'), text)
    text = re.sub(r"\$([\d,]+(?:\.\d{2})?)", lambda m: money_to_tagalog_dollars(m.group(1)), text)

    # Time/plans.
    text = re.sub(r"\b1\s*month\b", "isang buwan", text, flags=re.I)
    text = re.sub(r"\b1\s*year\b", "isang taon", text, flags=re.I)
    text = re.sub(r"\b(\d+)\s*months?\b", lambda m: f"{number_to_tagalog(int(m.group(1)))} buwan", text, flags=re.I)
    text = re.sub(r"\b(\d+)\s*years?\b", lambda m: f"{number_to_tagalog(int(m.group(1)))} taon", text, flags=re.I)

    # General symbols.
    text = text.replace(" / ", " o ")
    text = text.replace("&", " at ")
    text = text.replace("+", " plus ")
    text = text.replace("=", " katumbas ng ")
    text = text.replace("@", " at ")
    text = text.replace("#", " number ")
    text = text.replace("✓", "check ")
    text = text.replace("•", " ")
    text = text.replace("–", "-").replace("—", "-")

    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([.,:;!?])", r"\1", text)
    return text.strip()


def _num(value: str) -> int:
    return int(str(value).replace(",", "").split(".", 1)[0])


def _parse_money(value: str) -> tuple[int, int]:
    raw = str(value).replace(",", "")
    if "." in raw:
        whole, cents = raw.split(".", 1)
        cents = (cents + "00")[:2]
        return int(whole or 0), int(cents or 0)
    return int(raw or 0), 0


def money_to_tagalog_pesos(value: str, noun: str = "piso") -> str:
    pesos, cents = _parse_money(value)
    if cents:
        return f"{amount_number_to_tagalog(pesos, noun=noun)} {noun} at {number_to_tagalog(cents)} sentimos"
    return f"{amount_number_to_tagalog(pesos, noun=noun)} {noun}"


def money_to_tagalog_dollars(value: str) -> str:
    dollars, cents = _parse_money(value)
    if cents:
        return f"{number_to_tagalog(dollars)} dollars at {number_to_tagalog(cents)} cents"
    return f"{number_to_tagalog(dollars)} dollars"


def amount_number_to_tagalog(n: int, noun: str = "piso") -> str:
    """Natural amount form before piso/pesos: e.g., 10,000,000 -> sampung milyong."""
    if n == 1_000_000:
        return "isang milyong"
    if n > 0 and n % 1_000_000 == 0:
        return f"{linker_number_to_tagalog(n // 1_000_000)} milyong"
    if n == 1000 and noun == "piso":
        return "isang libong"
    return number_to_tagalog(n)


def linker_number_to_tagalog(n: int) -> str:
    """Number phrase with Filipino linker before a following noun when helpful."""
    base = number_to_tagalog(n)
    irregular = {
        "isa": "isang",
        "dalawa": "dalawang",
        "tatlo": "tatlong",
        "apat": "apat na",
        "lima": "limang",
        "anim": "anim na",
        "pito": "pitong",
        "walo": "walong",
        "siyam": "siyam na",
        "sampu": "sampung",
        "dalawampu": "dalawampung",
        "tatlumpu": "tatlumpung",
        "apatnapu": "apatnapung",
        "limampu": "limampung",
        "animnapu": "animnapung",
        "pitumpu": "pitumpung",
        "walumpu": "walumpung",
        "siyamnapu": "siyamnapung",
    }
    return irregular.get(base, base)


def decimal_to_tagalog(value: str) -> str:
    if "." not in value:
        return number_to_tagalog(int(value))
    whole, dec = value.split(".", 1)
    return f"{number_to_tagalog(int(whole))} point {' '.join(number_to_tagalog(int(d)) for d in dec)}"


def number_to_tagalog(n: int) -> str:
    if n == 0:
        return "zero"
    ones = ["", "isa", "dalawa", "tatlo", "apat", "lima", "anim", "pito", "walo", "siyam"]
    teens = {
        10: "sampu", 11: "labing isa", 12: "labing dalawa", 13: "labing tatlo", 14: "labing apat",
        15: "labing lima", 16: "labing anim", 17: "labing pito", 18: "labing walo", 19: "labing siyam",
    }
    tens = {20: "dalawampu", 30: "tatlumpu", 40: "apatnapu", 50: "limampu", 60: "animnapu", 70: "pitumpu", 80: "walumpu", 90: "siyamnapu"}

    def under100(x: int) -> str:
        if x < 10:
            return ones[x]
        if x < 20:
            return teens[x]
        t = (x // 10) * 10
        r = x % 10
        return f"{tens[t]}’t {ones[r]}" if r else tens[t]

    hundred_names = {
        1: "isang daan", 2: "dalawang daan", 3: "tatlong daan", 4: "apat na raan",
        5: "limang daan", 6: "anim na raan", 7: "pitong daan", 8: "walong daan", 9: "siyam na raan",
    }
    thousand_names = {
        1: "isang libo", 2: "dalawang libo", 3: "tatlong libo", 4: "apat na libo",
        5: "limang libo", 6: "anim na libo", 7: "pitong libo", 8: "walong libo", 9: "siyam na libo",
    }

    def under1000(x: int) -> str:
        if x < 100:
            return under100(x)
        h = x // 100
        r = x % 100
        h_text = hundred_names[h]
        return f"{h_text} {under100(r)}" if r else h_text

    if n < 1000:
        return under1000(n)
    if n < 1_000_000:
        th = n // 1000
        r = n % 1000
        th_text = thousand_names.get(th, f"{under1000(th)} libo")
        return f"{th_text} {under1000(r)}" if r else th_text
    m = n // 1_000_000
    r = n % 1_000_000
    m_text = "isang milyon" if m == 1 else f"{number_to_tagalog(m)} milyon"
    return f"{m_text} {number_to_tagalog(r)}" if r else m_text
