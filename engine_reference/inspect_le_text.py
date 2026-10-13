"""Read-only LE mapping and text-renderer candidate inspection.

Requires capstone. Does not patch the input or apply runtime relocations.
Structure reference: Open Watcom bld/watcom/h/exeflat.h.
"""
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path


class LE:
    def __init__(self, data):
        self.data = data
        if data[:2] != b'MZ':
            raise ValueError('Expected MZ')
        self.header = struct.unpack_from('<I', data, 0x3c)[0]
        if data[self.header:self.header + 4] != b'LE\0\0':
            raise ValueError('Expected little-endian LE')
        self.pages = self.u32(0x14)
        self.page_size = self.u32(0x28)
        self.last_size = self.u32(0x2c) or self.page_size
        self.page_start = self.u32(0x80)
        if self.page_size != 4096 or self.last_size > self.page_size:
            raise ValueError('Unsupported page sizes')
        self.objects = []
        for i in range(self.u32(0x44)):
            size, base, flags, first, count, reserved = struct.unpack_from(
                '<6I', data, self.header + self.u32(0x40) + i * 24)
            self.objects.append(dict(index=i+1, size=size, base=base,
                                     flags=flags, first_page=first, page_count=count))
        self.mappings = []
        for obj in self.objects:
            for i in range(obj['page_count']):
                mapoff = self.header + self.u32(0x48) + (obj['first_page']-1+i)*4
                entry = data[mapoff:mapoff+4]
                if len(entry) != 4:
                    raise ValueError('Truncated page map')
                page = int.from_bytes(entry[:3], 'big')
                if entry[3] == 3:
                    continue
                if entry[3] != 0 or not 1 <= page <= self.pages:
                    raise ValueError('Unsupported LE page encoding')
                offset = self.page_start + (page-1)*self.page_size
                length = self.last_size if page == self.pages else self.page_size
                length = min(length, obj['size']-i*self.page_size)
                if length < 0 or offset+length > len(data):
                    raise ValueError('Invalid page bounds')
                self.mappings.append(dict(object=obj['index'], offset=offset,
                    address=obj['base']+i*self.page_size, length=length))

    def u32(self, offset):
        return struct.unpack_from('<I', self.data, self.header+offset)[0]

    def address(self, offset):
        for m in self.mappings:
            if m['offset'] <= offset < m['offset']+m['length']:
                return m['address']+offset-m['offset'], m['object']
        return None, None

    def image(self, obj):
        # Only stored pages; do not allocate the large uninitialized BSS tail.
        chunks = [m for m in self.mappings if m['object']==obj['index']]
        end = max((m['address']+m['length']-obj['base'] for m in chunks), default=0)
        image = bytearray(end)
        for m in chunks:
            start = m['address']-obj['base']
            image[start:start+m['length']] = self.data[m['offset']:m['offset']+m['length']]
        return bytes(image)


def inspect(path, output):
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    from capstone.x86 import X86_OP_IMM
    data = path.read_bytes()
    le = LE(data)
    if output.exists():
        raise ValueError('Output exists; choose a new directory')
    if output.resolve() == path.parent.resolve() or path.parent.resolve() in output.resolve().parents:
        raise ValueError('Output must be outside the original game directory')
    strings = []
    for match in re.finditer(rb'[ -~]{4,}', data):
        if re.search(rb'font|\.fnt|text\.rsc|book[0-9]|glyph', match[0], re.I):
            addr, obj = le.address(match.start())
            strings.append(dict(file_offset=match.start(), address=addr,
                                object=obj, text=match[0].decode('ascii')))
    dis = Cs(CS_ARCH_X86, CS_MODE_32)
    dis.detail = True
    dis.skipdata = True
    candidates = []
    contexts = []
    for obj in le.objects:
        if not obj['flags'] & 4:
            continue
        instructions = list(dis.disasm(le.image(obj), obj['base']))
        for i, ins in enumerate(instructions):
            if ins.id == 0:
                continue
            immediates = [op.imm for op in ins.operands if op.type==X86_OP_IMM]
            reasons = []
            if ins.mnemonic in ('sub', 'add', 'cmp') and any(x in (33,-33,223,241,968,1932) for x in immediates):
                reasons.append('glyph-related constant (heuristic)')
            if ins.mnemonic == 'lea' and '- 0x21]' in ins.op_str:
                reasons.append('possible code-minus-33 normalization')
            if not reasons:
                continue
            row = dict(object=obj['index'], address=ins.address,
                       instruction=f'{ins.mnemonic} {ins.op_str}', reasons=reasons)
            candidates.append(row)
            contexts.append('\nCandidate '+hex(ins.address)+' '+', '.join(reasons)+'\n' +
                '\n'.join(f'{x.address:08x}  {x.bytes.hex():22} {x.mnemonic} {x.op_str}'
                          for x in instructions[max(0,i-14):i+19]))
    report = dict(source_sha256=hashlib.sha256(data).hexdigest(),
        le_header=le.header, page_size=le.page_size, pages=le.pages,
        entry_object=le.u32(0x18), entry_offset=le.u32(0x1c),
        objects=le.objects, mappings=le.mappings, strings=strings,
        candidates=candidates,
        limitations=['Static candidate search only; constants also occur in unrelated code.',
                    'LE fixups are not applied: absolute addresses in operands may be object-relative.',
                    'Linear disassembly may misinterpret embedded data; confirm control flow before patching.'])
    output.mkdir(parents=True)
    (output/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    (output/'candidate_contexts.txt').write_text('\n'.join(contexts),encoding='utf-8')
    print(json.dumps(dict(objects=len(le.objects),strings=len(strings),candidates=len(candidates),
                         output=str(output)),ensure_ascii=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    inspect(args.exe,args.output)
