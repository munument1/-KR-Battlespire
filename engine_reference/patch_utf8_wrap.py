"""Version-locked Hangul byte-width routing for three legacy wrapping loops.

Copying remains byte-for-byte. A Hangul syllable contributes its full width on
its final UTF-8 byte, so overflow decisions happen at character boundaries.
"""
import hashlib
from stage_utf8_game import assemble, CAVE, DECODER, fixups
from inspect_le_text import LE

EXPECTED='b3de96f981fdbb7b343234f10d139fe6bba04b04dbfa7ece8032a878f0a04e58'
HELPER=CAVE+0x540
COPY=CAVE+0x680
SCAN=CAVE+0x698


def patch(data):
    if hashlib.sha256(data).hexdigest()!=EXPECTED:
        raise ValueError('Requires fast-height UTF-8 executable without overlay')
    le=LE(data);before=fixups(le)
    helper=f'''
push ebx
push ecx
push edx
push esi
movzx ecx,byte ptr [ebx]
cmp ecx,0x80
jb legacy
cmp ecx,0xc0
jae leading
movzx eax,byte ptr [ebx-1]
cmp eax,0x80
jb legacy
cmp eax,0xc0
jae middle
sub ebx,2
call {DECODER}
cmp eax,0xac00
jb legacy
cmp eax,0xd7a3
ja legacy
sub eax,0xac00
add eax,241
call font_base
font_base:
pop esi
sub esi,FONT_BASE_RETURN
mov esi,dword ptr [esi+0x3993]
mov esi,dword ptr [esi]
movzx eax,word ptr [esi+eax*4+4]
inc eax
jmp finished
middle:
dec ebx
jmp test_hangul
leading:
test_hangul:
call {DECODER}
cmp eax,0xac00
jb legacy
cmp eax,0xd7a3
ja legacy
xor eax,eax
jmp finished
legacy:
mov eax,ecx
call 0x3a65
finished:
pop esi
pop edx
pop ecx
pop ebx
ret
'''
    # The return address is determined from assembled code, not a guessed
    # instruction size; the immediate's width does not affect that prefix.
    provisional=assemble(helper.replace('FONT_BASE_RETURN','0x12345678'),HELPER)
    at=provisional.index(b'\xe8', provisional.index(b'\x05\xf1\x00\x00\x00')+5)
    return_at=HELPER+at+5
    body=assemble(helper.replace('FONT_BASE_RETURN',str(return_at)),HELPER)
    copy=assemble(f'push ebx; mov ebx,[ebp-0x28]; dec ebx; call {HELPER}; pop ebx; ret',COPY)
    scan=assemble(f'push ebx; mov ebx,[ebp-0x24]; call {HELPER}; pop ebx; ret',SCAN)
    segments=[(HELPER,body),(COPY,copy),(SCAN,scan)]
    assert HELPER+len(body)<=COPY and COPY+len(copy)<=SCAN and SCAN+len(scan)<=CAVE+0x700
    out=bytearray(data);sites=[(0x2c58a,COPY),(0x2cbbc,SCAN),(0x49824,SCAN)]
    for start,target in sites:
        original=assemble('call 0x3a65',start)
        assert data[le.page_start+start:le.page_start+start+5]==original
        out[le.page_start+start:le.page_start+start+5]=assemble(f'call {target}',start)
    for addr,code in segments:
        out[le.page_start+addr:le.page_start+addr+len(code)]=code
    changed={i-le.page_start for i,(a,b) in enumerate(zip(data,out)) if a!=b}
    allowed={i for start,_ in sites for i in range(start,start+5)}|{i for addr,code in segments for i in range(addr,addr+len(code))}
    assert changed<=allowed
    assert fixups(LE(bytes(out)))==before
    return bytes(out),dict(sites=[hex(start) for start,_ in sites],payload_bytes=sum(len(code) for _,code in segments),
        changed_bytes=len(changed),relocations_preserved=len(before),
        input_sha256=EXPECTED,output_sha256=hashlib.sha256(out).hexdigest())
