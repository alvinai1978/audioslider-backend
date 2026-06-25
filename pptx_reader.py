import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Any

A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def extract_slides_from_pptx(path: str | Path) -> List[Dict[str, Any]]:
    """Extract all readable/editable text from PPTX slide XML.

    Reads every a:t text node in slide XML. This catches text boxes, bullets,
    tables, grouped shapes, and many chart labels. It cannot read text that is
    flattened into images/screenshots.
    """
    p = Path(path)
    slides = []
    with zipfile.ZipFile(p, "r") as z:
        names = sorted(
            [n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)],
            key=lambda n: int(re.search(r"slide(\d+)\.xml", n).group(1)),
        )
        for idx, name in enumerate(names, start=1):
            xml = z.read(name)
            lines = _extract_text_nodes(xml)
            lines = _clean_lines(lines)
            title = _choose_title(lines, idx)
            slides.append({"num": idx, "title": title, "lines": lines})
    return slides


def _extract_text_nodes(xml_bytes: bytes) -> list[str]:
    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return []
    texts = []
    for elem in root.iter():
        if elem.tag.endswith("}t") and elem.text:
            texts.append(elem.text)
    return texts


def _clean_lines(lines: list[str]) -> list[str]:
    out = []
    last = None
    for raw in lines:
        line = re.sub(r"\s+", " ", raw or "").strip()
        if not line:
            continue
        if line == last:
            continue
        out.append(line)
        last = line
    return out


def _choose_title(lines: list[str], idx: int) -> str:
    for line in lines[:8]:
        if not re.fullmatch(r"\d+", line.strip()) and len(line.strip()) > 1:
            return line.strip()
    return f"Slide {idx}"


def generate_commentary(slides: list[dict], narrator: str = "female", style: str = "professional", output_language: str = "tagalog") -> str:
    if (output_language or "tagalog").lower().startswith("en"):
        return generate_english_commentary(slides, narrator=narrator, style=style)
    return generate_tagalog_commentary(slides, narrator=narrator, style=style)


def _narrator_name(narrator: str) -> str:
    if (narrator or "female").lower() == "male":
        return "Angelo"
    return "Blessica"


def generate_tagalog_commentary(slides: list[dict], narrator: str = "female", style: str = "professional") -> str:
    narrator_name = _narrator_name(narrator)
    blocks = [
        f"{narrator_name}: Magandang araw. Narito ang malinaw na Tagalog commentary para sa presentasyong ito. Babasahin natin ang bawat slide at bibigyan ng maayos na paliwanag ang lahat ng mahahalagang detalye."
    ]
    for slide in slides:
        num = slide.get("num")
        lines = slide.get("lines") or []
        title = slide.get("title") or f"Slide {num}"
        details = [x for x in lines if x.strip() and x.strip() != title]
        block = [f"SLIDE {num} – {title}", f"{narrator_name}: Sa slide {num}, ang pangunahing paksa ay {title}."]
        block.extend(_details_to_tagalog_commentary(details))
        blocks.append("\n".join(block))
    blocks.append(f"{narrator_name}: Iyan ang kabuuang paliwanag ng presentation. Maaari pang i-edit ang script para mas tumugma sa eksaktong tono, audience, at timing ng presentasyon. Maraming salamat.")
    return "\n\n".join(blocks).replace("\n\n\n", "\n\n")


def generate_english_commentary(slides: list[dict], narrator: str = "female", style: str = "professional") -> str:
    narrator_name = _narrator_name(narrator)
    blocks = [
        f"{narrator_name}: Welcome. Here is a clear English commentary for this presentation. We will go through each slide and explain all important details in a professional narration style."
    ]
    for slide in slides:
        num = slide.get("num")
        lines = slide.get("lines") or []
        title = slide.get("title") or f"Slide {num}"
        details = [x for x in lines if x.strip() and x.strip() != title]
        block = [f"SLIDE {num} – {title}", f"{narrator_name}: On slide {num}, the main topic is {title}."]
        block.extend(_details_to_english_commentary(details))
        blocks.append("\n".join(block))
    blocks.append(f"{narrator_name}: That completes the presentation commentary. You may still edit this script to better match your timing, audience, and exact delivery style. Thank you.")
    return "\n\n".join(blocks).replace("\n\n\n", "\n\n")


def _details_to_tagalog_commentary(details: list[str]) -> list[str]:
    if not details:
        return ["Walang karagdagang readable text sa slide na ito. Kung may details na nasa larawan, kailangan itong i-type o gamitan ng OCR sa susunod na version."]
    commentary = []
    pending_header = None
    for raw in details:
        item = re.sub(r"^[•\-–—✓!xX]+\s*", "", raw).strip()
        if not item:
            continue
        lower = item.lower()
        if _looks_like_footer(item):
            commentary.append(f"Mahalagang paalala rin dito: {item}.")
            continue
        if _looks_like_short_header(item):
            pending_header = item
            commentary.append(f"May bahagi rin dito tungkol sa {item}.")
            continue
        if re.search(r"phase\s*\d+", item, flags=re.I):
            commentary.append(f"Makikita rin ang {item}, na bahagi ng step-by-step na execution plan.")
        elif re.search(r"months?\s*\d+", lower):
            commentary.append(f"Ang timeline na binanggit ay {item}.")
        elif re.search(r"₱|\$|\d+(?:\.\d+)?\s*%|\d{1,3},\d{3}", item):
            commentary.append(f"Mahalagang bilang o halaga rito ang {item}.")
        elif pending_header:
            commentary.append(f"Sa ilalim ng {pending_header}, kasama ang {item}.")
        else:
            commentary.append(f"Kasama rin sa detalye ang {item}.")
    return commentary


def _details_to_english_commentary(details: list[str]) -> list[str]:
    if not details:
        return ["There is no additional readable text on this slide. If some details are inside an image, they may need to be typed manually or processed with OCR later."]
    commentary = []
    pending_header = None
    for raw in details:
        item = re.sub(r"^[•\-–—✓!xX]+\s*", "", raw).strip()
        if not item:
            continue
        lower = item.lower()
        if _looks_like_footer(item):
            commentary.append(f"An important note here is: {item}.")
            continue
        if _looks_like_short_header(item):
            pending_header = item
            commentary.append(f"This slide also includes a section on {item}.")
            continue
        if re.search(r"phase\s*\d+", item, flags=re.I):
            commentary.append(f"It also shows {item}, which is part of the step-by-step execution plan.")
        elif re.search(r"months?\s*\d+", lower):
            commentary.append(f"The timeline mentioned here is {item}.")
        elif re.search(r"₱|\$|\d+(?:\.\d+)?\s*%|\d{1,3},\d{3}", item):
            commentary.append(f"A key number or amount on this slide is {item}.")
        elif pending_header:
            commentary.append(f"Under {pending_header}, the slide includes {item}.")
        else:
            commentary.append(f"Another detail included here is {item}.")
    return commentary


def _looks_like_short_header(item: str) -> bool:
    return len(item) <= 38 and not item.endswith(".") and not re.search(r"[,:;]", item) and not re.search(r"₱|\$|%", item)


def _looks_like_footer(item: str) -> bool:
    return any(key in item.lower() for key in ["critical path", "key conclusion", "final position", "go / no-go", "interpretation", "assumption"])


def split_script_by_slide(script: str, slide_count: int) -> dict[int, str]:
    """Return {slide_number: script_block}. Keeps matching SLIDE n blocks.
    If no markers exist, split text roughly across slides.
    """
    text = script or ""
    matches = list(re.finditer(r"(?im)^\s*SLIDE\s+(\d+)\b[^\n]*", text))
    mapping: dict[int, str] = {}
    if matches:
        for i, m in enumerate(matches):
            n = int(m.group(1))
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            mapping[n] = text[start:end].strip()
    else:
        words = text.split()
        chunk = max(1, len(words) // max(slide_count, 1))
        for n in range(1, slide_count + 1):
            mapping[n] = " ".join(words[(n - 1) * chunk : n * chunk]).strip() or text
    for n in range(1, slide_count + 1):
        mapping.setdefault(n, f"Sa slide {n}, ipagpatuloy natin ang presentation.")
    return mapping
