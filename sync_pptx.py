import csv
import io
import re
import tempfile
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Dict, List

# Namespaces
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P14 = "http://schemas.microsoft.com/office/powerpoint/2010/main"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

ET.register_namespace("p", P)
ET.register_namespace("a", A)
ET.register_namespace("r", R)
ET.register_namespace("p14", P14)


def create_timing_manifest_csv(slide_audio: dict[int, dict], out_path: Path) -> None:
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["slide", "audio_file", "duration_seconds", "engine", "voice"])
        for n, meta in sorted(slide_audio.items()):
            writer.writerow([n, meta.get("filename"), round(float(meta.get("duration", 0)), 2), meta.get("engine"), meta.get("voice")])


def build_cloud_synced_pptx(input_pptx: Path, output_pptx: Path, slide_audio_files: dict[int, Path], durations: dict[int, float]) -> None:
    """Experimental direct-PPTX sync exporter.

    Adds each slide's MP3 into ppt/media, adds relationships, inserts a small audio
    picture shape, and sets slide advance timing. This avoids PowerPoint desktop
    automation, so it can run on Linux cloud hosts. PowerPoint XML media timelines
    are complicated, so test in Microsoft PowerPoint Desktop after export.
    """
    output_pptx.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(input_pptx, "r") as zin:
        existing = {info.filename: zin.read(info.filename) for info in zin.infolist()}

    # Add mp3 content type.
    existing["[Content_Types].xml"] = _ensure_content_type_mp3(existing.get("[Content_Types].xml", b""))

    # Add a tiny PNG audio placeholder icon in media.
    icon_path = "ppt/media/slidenarrate_audio_icon.png"
    if icon_path not in existing:
        existing[icon_path] = _tiny_png()

    for slide_num, audio_file in slide_audio_files.items():
        slide_path = f"ppt/slides/slide{slide_num}.xml"
        if slide_path not in existing:
            continue
        media_name = f"ppt/media/slidenarrate_slide_{slide_num:03d}.mp3"
        existing[media_name] = audio_file.read_bytes()
        slide_xml, rels_xml = _patch_slide_with_audio(
            existing[slide_path],
            existing.get(f"ppt/slides/_rels/slide{slide_num}.xml.rels"),
            slide_num,
            f"../media/slidenarrate_slide_{slide_num:03d}.mp3",
            "../media/slidenarrate_audio_icon.png",
            int((durations.get(slide_num, 3.0) + 0.8) * 1000),
        )
        existing[slide_path] = slide_xml
        existing[f"ppt/slides/_rels/slide{slide_num}.xml.rels"] = rels_xml

    with zipfile.ZipFile(output_pptx, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for name, data in existing.items():
            zout.writestr(name, data)


def _ensure_content_type_mp3(xml_bytes: bytes) -> bytes:
    if not xml_bytes:
        return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
    root = ET.fromstring(xml_bytes)
    ns = "{http://schemas.openxmlformats.org/package/2006/content-types}"
    for child in root:
        if child.tag == ns + "Default" and child.attrib.get("Extension") == "mp3":
            return ET.tostring(root, encoding="utf-8", xml_declaration=True)
    ET.SubElement(root, ns + "Default", {"Extension": "mp3", "ContentType": "audio/mpeg"})
    ET.SubElement(root, ns + "Default", {"Extension": "png", "ContentType": "image/png"}) if not any(c.tag == ns + "Default" and c.attrib.get("Extension") == "png" for c in root) else None
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _patch_slide_with_audio(slide_xml_bytes: bytes, rels_xml_bytes: bytes | None, slide_num: int, audio_target: str, icon_target: str, adv_ms: int):
    slide_root = ET.fromstring(slide_xml_bytes)
    rels_root = _load_rels(rels_xml_bytes)

    audio_rid = _next_rid(rels_root)
    ET.SubElement(rels_root, f"{{{PKG_REL}}}Relationship", {
        "Id": audio_rid,
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/audio",
        "Target": audio_target,
    })
    media_rid = _next_rid(rels_root)
    ET.SubElement(rels_root, f"{{{PKG_REL}}}Relationship", {
        "Id": media_rid,
        "Type": "http://schemas.microsoft.com/office/2007/relationships/media",
        "Target": audio_target,
    })
    icon_rid = _next_rid(rels_root)
    ET.SubElement(rels_root, f"{{{PKG_REL}}}Relationship", {
        "Id": icon_rid,
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
        "Target": icon_target,
    })

    shape_id = _next_shape_id(slide_root)
    _append_audio_pic(slide_root, shape_id, audio_rid, media_rid, icon_rid)
    _set_transition_advance(slide_root, adv_ms)
    _set_timing_auto_audio(slide_root, shape_id)

    return ET.tostring(slide_root, encoding="utf-8", xml_declaration=True), ET.tostring(rels_root, encoding="utf-8", xml_declaration=True)


def _load_rels(xml_bytes: bytes | None):
    if xml_bytes:
        return ET.fromstring(xml_bytes)
    return ET.Element(f"{{{PKG_REL}}}Relationships")


def _next_rid(root) -> str:
    nums = []
    for rel in root:
        rid = rel.attrib.get("Id", "")
        m = re.match(r"rId(\d+)$", rid)
        if m:
            nums.append(int(m.group(1)))
    return f"rId{(max(nums) if nums else 0) + 1}"


def _next_shape_id(slide_root) -> int:
    ids = []
    for elem in slide_root.iter():
        if elem.tag.endswith("}cNvPr") and "id" in elem.attrib:
            try:
                ids.append(int(elem.attrib["id"]))
            except Exception:
                pass
    return (max(ids) if ids else 1000) + 1


def _append_audio_pic(slide_root, shape_id: int, audio_rid: str, media_rid: str, icon_rid: str) -> None:
    sp_tree = slide_root.find(f".//{{{P}}}spTree")
    if sp_tree is None:
        return
    pic = ET.fromstring(f'''
    <p:pic xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}" xmlns:p14="{P14}">
      <p:nvPicPr>
        <p:cNvPr id="{shape_id}" name="SlideNarrate audio {shape_id}">
          <a:hlinkClick r:id="" action="ppaction://media"/>
        </p:cNvPr>
        <p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr>
        <p:nvPr>
          <a:audioFile r:link="{audio_rid}"/>
          <p:extLst>
            <p:ext uri="{{DAA4B4D4-6D71-4841-9C94-3DE7FCFB9230}}">
              <p14:media r:embed="{media_rid}"/>
            </p:ext>
          </p:extLst>
        </p:nvPr>
      </p:nvPicPr>
      <p:blipFill>
        <a:blip r:embed="{icon_rid}"/>
        <a:stretch><a:fillRect/></a:stretch>
      </p:blipFill>
      <p:spPr>
        <a:xfrm><a:off x="32000" y="32000"/><a:ext cx="280000" cy="280000"/></a:xfrm>
        <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
      </p:spPr>
    </p:pic>
    ''')
    sp_tree.append(pic)


def _set_transition_advance(slide_root, adv_ms: int) -> None:
    # Remove existing transition? Keep type but ensure auto advance timing.
    transition = slide_root.find(f"{{{P}}}transition")
    if transition is None:
        # p:transition should appear before p:timing if possible.
        transition = ET.Element(f"{{{P}}}transition")
        # append near end is accepted by many PowerPoint versions.
        slide_root.append(transition)
    transition.set("advClick", "0")
    transition.set("advTm", str(max(1000, adv_ms)))


def _set_timing_auto_audio(slide_root, shape_id: int) -> None:
    # Replace existing timing with a simple automatic audio timeline.
    for child in list(slide_root):
        if child.tag == f"{{{P}}}timing":
            slide_root.remove(child)
    timing = ET.fromstring(f'''
    <p:timing xmlns:p="{P}">
      <p:tnLst>
        <p:par>
          <p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot">
            <p:childTnLst>
              <p:seq concurrent="1" nextAc="seek">
                <p:cTn id="2" dur="indefinite" nodeType="mainSeq">
                  <p:childTnLst>
                    <p:par>
                      <p:cTn id="3" fill="hold">
                        <p:stCondLst><p:cond delay="indefinite"/></p:stCondLst>
                        <p:childTnLst>
                          <p:par>
                            <p:cTn id="4" fill="hold">
                              <p:stCondLst><p:cond delay="0"/></p:stCondLst>
                              <p:childTnLst>
                                <p:audio isNarration="1">
                                  <p:cMediaNode vol="80000">
                                    <p:cTn id="5" fill="hold" display="0">
                                      <p:stCondLst><p:cond delay="0"/></p:stCondLst>
                                    </p:cTn>
                                    <p:tgtEl><p:spTgt spid="{shape_id}"/></p:tgtEl>
                                  </p:cMediaNode>
                                </p:audio>
                              </p:childTnLst>
                            </p:cTn>
                          </p:par>
                        </p:childTnLst>
                      </p:cTn>
                    </p:par>
                  </p:childTnLst>
                </p:cTn>
                <p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>
                <p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst>
              </p:seq>
            </p:childTnLst>
          </p:cTn>
        </p:par>
      </p:tnLst>
    </p:timing>
    ''')
    slide_root.append(timing)


def _tiny_png() -> bytes:
    # 1x1 transparent png. PowerPoint just needs an image placeholder relationship.
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6360000002000100ffff03000006000557bfab0000000049454e44ae426082"
    )
