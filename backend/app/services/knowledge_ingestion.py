"""Bounded local extraction; documents cannot run macros or fetch remote resources."""
import base64
import hashlib
from io import BytesIO
from pathlib import PurePath
import re
from xml.etree import ElementTree
from zipfile import ZipFile

MAX_FILE = 3 * 1024 * 1024
MAX_TEXT = 80000


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def extract(filename: str, encoded: str) -> tuple[list[tuple[str, str]], str]:
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception:
        raise ValueError('文件编码不正确。') from None
    if not raw or len(raw) > MAX_FILE:
        raise ValueError('文件为空或超过 3MB。')
    suffix = PurePath(filename.lower()).suffix
    try:
        if suffix in {'.txt', '.md'}:
            pages = [('正文', raw.decode('utf-8-sig'))]
        elif suffix == '.docx':
            with ZipFile(BytesIO(raw)) as archive:
                infos = archive.infolist()
                if len(infos) > 500 or sum(i.file_size for i in infos) > 8 * 1024 * 1024:
                    raise ValueError('Word 文件解压体积过大。')
                if any('vbaProject' in i.filename or i.flag_bits & 1 for i in infos):
                    raise ValueError('不支持带宏或加密的 Word 文件。')
                xml = archive.read('word/document.xml')
                if b'<!DOCTYPE' in xml or b'<!ENTITY' in xml:
                    raise ValueError('Word 文件包含不支持的 XML 声明。')
                tree = ElementTree.fromstring(xml)
                namespace = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                text = '\n'.join(''.join(p.itertext()) for p in tree.findall('.//w:p', namespace))
                pages = [('Word 段落', text)]
        elif suffix == '.pdf':
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(raw), strict=True)
            if reader.is_encrypted or len(reader.pages) > 80:
                raise ValueError('不支持加密或超过 80 页的 PDF。')
            pages = []
            total = 0
            for number, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ''
                total += len(text)
                if total > MAX_TEXT:
                    raise ValueError('提取文字超过 80000 字，请拆分资料。')
                pages.append((f'PDF 第 {number} 页', text))
        else:
            raise ValueError('仅支持 UTF-8 TXT、Markdown、DOCX 和文本型 PDF。')
    except ValueError:
        raise
    except Exception:
        raise ValueError('无法提取文件，请检查格式；扫描件需先完成文字识别。') from None
    pages = [(anchor, text.replace('\x00', '').strip()) for anchor, text in pages if text.strip()]
    if sum(len(text) for _, text in pages) > MAX_TEXT:
        raise ValueError('提取文字超过 80000 字，请拆分资料。')
    if sum(len(text) for _, text in pages) < 20:
        raise ValueError('未提取到足够文字；扫描件需先识别，不能发布空资料。')
    return pages, suffix.lstrip('.')


def chunks(pages: list[tuple[str, str]]) -> list[tuple[str, str]]:
    result = []
    for anchor, text in pages:
        text = re.sub(r'\n{3,}', '\n\n', text)
        for offset in range(0, len(text), 600):
            part = text[offset:offset + 700].strip()
            if part:
                result.append((f'{anchor} · 段 {offset // 600 + 1}', part))
    return result
