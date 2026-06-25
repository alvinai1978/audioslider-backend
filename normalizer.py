import re

NARRATOR_NAMES = ("Blessica", "Angelo", "Narrator", "Commentator")


def remove_narrator_labels(text: str) -> str:
    cleaned = []
    for line in (text or "").splitlines():
        line = re.sub(r"^\s*(Blessica|Angelo|Narrator|Commentator)\s*:\s*", "", line, flags=re.I).strip()
        if line:
            cleaned.append(line)
    return "\n".join(cleaned)


def normalize_for_speech(input_text: str) -> str:
    """Normalize symbols, currency, ranges, and common English plan words for Tagalog TTS."""
    text = remove_narrator_labels(input_text or "")

    # Specific commercial pricing pattern requested by user.
    text = re.sub(r"Trial\s*/\s*Demo\s*:\s*free\s*,\s*limited", "Trial o Demo: libre, pero limitado ang paggamit.", text, flags=re.I)
    text = re.sub(r"\b1\s*month\s*:\s*₱([\d,]+)\s*[–—-]\s*₱([\d,]+)", lambda m: f"Isang buwan: mula {number_to_tagalog(_num(m.group(1)))} pesos hanggang {number_to_tagalog(_num(m.group(2)))} pesos.", text, flags=re.I)
    text = re.sub(r"\b1\s*year\s*:\s*₱([\d,]+)\s*[–—-]\s*₱([\d,]+)", lambda m: f"Isang taon: mula {number_to_tagalog(_num(m.group(1)))} pesos hanggang {number_to_tagalog(_num(m.group(2)))} pesos.", text, flags=re.I)
    text = re.sub(r"\bLifetime\s*:\s*₱([\d,]+)\s*[–—-]\s*₱([\d,]+)", lambda m: f"Lifetime access: mula {number_to_tagalog(_num(m.group(1)))} pesos hanggang {number_to_tagalog(_num(m.group(2)))} pesos.", text, flags=re.I)

    # Currency ranges before single currency.
    text = re.sub(r"₱([\d,]+)\s*[–—-]\s*₱([\d,]+)", lambda m: f"mula {number_to_tagalog(_num(m.group(1)))} pesos hanggang {number_to_tagalog(_num(m.group(2)))} pesos", text)
    text = re.sub(r"\$([\d,]+)\s*[–—-]\s*\$([\d,]+)", lambda m: f"mula {number_to_tagalog(_num(m.group(1)))} dollars hanggang {number_to_tagalog(_num(m.group(2)))} dollars", text)

    # Percentages and numeric ranges.
    text = re.sub(r"(\d+(?:\.\d+)?)\s*%", lambda m: f"{decimal_to_tagalog(m.group(1))} porsiyento", text)
    text = re.sub(r"\b(\d+)\s*[–—-]\s*(\d+)\b", lambda m: f"{number_to_tagalog(int(m.group(1)))} hanggang {number_to_tagalog(int(m.group(2)))}", text)

    # Single currency.
    text = re.sub(r"₱([\d,]+)", lambda m: f"{number_to_tagalog(_num(m.group(1)))} pesos", text)
    text = re.sub(r"\$([\d,]+)", lambda m: f"{number_to_tagalog(_num(m.group(1)))} dollars", text)

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
    return int(value.replace(",", ""))


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
    m_text = "isang milyon" if m == 1 else f"{under1000(m)} milyon"
    return f"{m_text} {number_to_tagalog(r)}" if r else m_text
