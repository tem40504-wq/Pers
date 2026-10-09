"""Validate the entire PNG before accepting an ADB screenshot."""
import io
import struct
import zlib


class PNGError(ValueError):
    pass


def validate_png(data: bytes) -> tuple[int, int]:
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise PNGError('Нет сигнатуры PNG')
    offset = 8
    size = None
    has_image = False
    while offset < len(data):
        if len(data) - offset < 12:
            raise PNGError('Оборван заголовок PNG chunk')
        length = struct.unpack('>I', data[offset:offset + 4])[0]
        end = offset + 12 + length
        if end > len(data):
            raise PNGError('Неполный PNG chunk')
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        checksum = struct.unpack('>I', data[end - 4:end])[0]
        if zlib.crc32(kind + payload) & 0xffffffff != checksum:
            raise PNGError('Не совпадает CRC PNG chunk')
        if size is None:
            if kind != b'IHDR' or length != 13:
                raise PNGError('Нет IHDR PNG')
            size = struct.unpack('>II', payload[:8])
            if min(size) == 0 or size[0] * size[1] > 64_000_000:
                raise PNGError('Недопустимый размер скриншота')
        if kind == b'IDAT':
            has_image = True
        if kind == b'IEND':
            if length or end != len(data) or not has_image:
                raise PNGError('Некорректное завершение PNG')
            # Correct framing/CRC is insufficient if compressed pixels are invalid.
            from PIL import Image
            try:
                with Image.open(io.BytesIO(data)) as image:
                    image.load()
                    if image.format != 'PNG' or image.size != size:
                        raise PNGError('Некорректные пиксели PNG')
            except (OSError, ValueError, SyntaxError) as exc:
                raise PNGError('Не удалось прочитать пиксели PNG') from exc
            return size
        offset = end
    raise PNGError('Нет IEND: PNG передан не полностью')
