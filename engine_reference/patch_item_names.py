"""Resolve short, save-compatible name IDs into full Korean names at display.

The original magic-definition name slot is 32 bytes (next field at +0x20).
Do not enlarge item/save structures or copy long UTF-8 names into this slot.
"""
import hashlib,struct
from inspect_le_text import LE
from stage_utf8_game import assemble,fixups

START=0xadb00
LIMIT=0xadd00
SITES={0x3f44d:'three',0x3f50c:'four',0x3f59b:'three',
       0x3f6d2:'two',0x3f805:'three',0x3f878:'two',0x3f8ca:'one',0x3f7ab:'one'}

def patch(data,count,ui_patch_offset=None):
    assert hashlib.sha256(data).hexdigest()=='0f9821310b442dbcc4ae6104c06d175bd957726f00d845a0c6925210fab0dad5'
    le=LE(data);before=fixups(le)
    source=f'''
startup:
pushad
call startup_pc
startup_pc:
pop edi
sub edi,startup_pc
lea eax,[edi+filename]
xor edx,edx
call 0x3ad8
mov [edi+pool_pointer],eax
UI_POINTER_PATCH
popad
jmp 0x4152f
resolve:
push ebx
push ecx
push edx
push edi
cmp word ptr [eax],0x4b7e
jne resolved
cmp byte ptr [eax+6],0
jne resolved
mov ebx,eax
xor edx,edx
mov ecx,2
digit:
movzx eax,byte ptr [ebx+ecx]
sub eax,48
cmp eax,9
jbe digit_ok
sub eax,7
digit_ok:
cmp eax,15
ja invalid
shl edx,4
or edx,eax
inc ecx
cmp ecx,6
jb digit
cmp edx,{count}
jae invalid
call resolve_pc
resolve_pc:
pop edi
sub edi,resolve_pc
mov edi,[edi+pool_pointer]
test edi,edi
jz invalid
mov eax,[edi+edx*4+4]
add eax,edi
jmp resolved
invalid:
mov eax,ebx
resolved:
pop edi
pop edx
pop ecx
pop ebx
ret
'''
    ui_asm=''
    if ui_patch_offset is not None:
        ui_asm=f'''
mov ebx,eax
lea esi,[eax+{ui_patch_offset}]
mov ecx,[esi]
add esi,4
mov edx,[edi+0x3993]
sub edx,114720
test ecx,ecx
jz ui_done
ui_loop:
mov eax,[esi]
test eax,0x80000000
jz ui_data
and eax,0x7fffffff
add eax,edi
jmp ui_write
ui_data:
add eax,edx
ui_write:
mov ebp,[esi+4]
add ebp,ebx
mov [eax],ebp
add esi,8
dec ecx
jnz ui_loop
ui_done:
'''
    source=source.replace('UI_POINTER_PATCH',ui_asm)
    for kind,magic in [('two',16),('three',20),('four',24)]:
        source+=f'''
{kind}:
pushad
mov eax,[esp+{32+magic-4}]
call resolve
mov [esp+{32+magic-4}],eax
mov eax,[esp+{32+magic}]
cmp word ptr [eax],0x4b7e
jne {kind}_done
call resolve
'''
        if kind=='two':
            source+='mov edx,[esp+44]; mov [esp+44],eax; mov [esp+48],edx\n'
        elif kind=='three':
            source+='mov edx,[esp+44]; mov ecx,[esp+48]; mov [esp+44],eax; mov [esp+48],edx; mov [esp+52],ecx\n'
        else:
            source+='mov edx,[esp+48]; mov ecx,[esp+52]; mov [esp+48],eax; mov [esp+52],edx; mov [esp+56],ecx\n'
        source+=f'{kind}_done:\npopad\njmp 0x5fcc0\n'
    source+='one: pushad; mov eax,[esp+44]; call resolve; mov [esp+44],eax; popad; jmp 0x5fcc0\n'
    # Assemble a call-prefix to retrieve label addresses without guessing lengths.
    names=['startup','resolve','two','three','four','one']
    prefix='; '.join('call '+n for n in names)+'; '
    length=len(names)*5
    full=assemble(prefix+source+'pool_pointer: .long 0; filename: .ascii "GAMEDATA\\\\KRNAMES.DAT"; .byte 0',START-length)
    labels={n:START-length+i*5+5+struct.unpack_from('<i',full,i*5+1)[0]
            for i,n in enumerate(names)}
    body=full[length:]
    assert START+len(body)<=LIMIT,(len(body),hex(START+len(body)))
    assert not any(data[le.page_start+START:le.page_start+START+len(body)])
    assert not any(f['object']==1 and START<=f['offset']<START+len(body) for f in before)
    out=bytearray(data)
    out[le.page_start+START:le.page_start+START+len(body)]=body
    sites={0x86a:('startup',0x4152f),**{s:(k,0x5fcc0) for s,k in SITES.items()}}
    for at,(label,original) in sites.items():
        assert data[le.page_start+at:le.page_start+at+5]==assemble(f'call {original}',at)
        out[le.page_start+at:le.page_start+at+5]=assemble(f'call {labels[label]}',at)
    assert fixups(LE(bytes(out)))==before
    changed={i-le.page_start for i,(a,b) in enumerate(zip(data,out)) if a!=b}
    allowed=set(range(START,START+len(body)))|{s+i for s in sites for i in range(5)}
    assert changed<=allowed
    return bytes(out),dict(labels=labels,sites={hex(s):v[0] for s,v in sites.items()},
        payload_bytes=len(body),changed_bytes=len(changed),relocations_preserved=len(before),
        source_sha256=hashlib.sha256(data).hexdigest(),output_sha256=hashlib.sha256(out).hexdigest(),
        name_count=count,name_slot_bytes=32,lookup_token_bytes=6,
        ui_patch_table_offset=ui_patch_offset,
        save_structure_unchanged=True,runtime_game_verified=False)
