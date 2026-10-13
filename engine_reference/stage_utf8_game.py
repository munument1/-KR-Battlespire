"""Build a version-locked UTF-8 trial in an independent game copy.

Uses zero padding in the final code page, PIC stubs and existing relocated
operands. No new relocation entries. Trial overlay is intentionally enabled.
"""
import argparse
import hashlib
import json
import re
import shutil
import struct
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'local/runtime_deps'))
from bs_kor import FNT
from inspect_le_text import LE

EXPECTED='a07299044a65d3294450ada6312908c90d26a6b265d13806010dd16527e0ee3e'
CAVE=0xad900
DECODER=CAVE
GLYPH=CAVE+0x100
DRAW=CAVE+0x180
WIDTH=CAVE+0x400
HEIGHT=CAVE+0x500
SAMPLE=CAVE+0x600
DEMO='한국어 UTF-8 시험'


def fixups(le):
    """Strict subset sufficient for this exact version; reject other encodings."""
    records=[]
    table=le.header+le.u32(0x68);base=le.header+le.u32(0x6c)
    for page in range(le.pages):
        start,end=struct.unpack_from('<II',le.data,table+page*4)
        at=base+start;stop=base+end
        obj=next(o for o in le.objects if o['first_page']-1<=page<o['first_page']-1+o['page_count'])
        while at<stop:
            source,flags=le.data[at:at+2]
            if source not in (2,7) or flags not in (0,0x10):
                raise ValueError(f'Unsupported fixup {source:x}/{flags:x} at {at:x}')
            off=struct.unpack_from('<h',le.data,at+2)[0]
            target=le.data[at+4]
            size=0 if source==2 else (4 if flags&0x10 else 2)
            value=int.from_bytes(le.data[at+5:at+5+size],'little')
            records.append(dict(source_type=source,object=obj['index'],offset=(page-obj['first_page']+1)*4096+off,
                target_object=target,target_offset=value))
            at+=5+size
        if at!=stop:raise ValueError('Fixup table boundary mismatch')
    return records


def assemble(source,address):
    from keystone import Ks,KS_ARCH_X86,KS_MODE_32
    return bytes(Ks(KS_ARCH_X86,KS_MODE_32).asm(source,address)[0])


def payload(overlay=True,fast_height=False):
    decoder=(ROOT/'tools/utf8_decode_x86.asm').read_text(encoding='utf-8')
    decoder='\n'.join(line.split(';')[0] for line in decoder.splitlines())
    glyph='''
cmp eax,33
jb blank
cmp eax,127
jb ascii_slot
cmp eax,0xac00
jb fallback
cmp eax,0xd7a3
ja fallback
sub eax,0xac00
add eax,241
cmp eax,dword ptr [esi]
jae fallback
ret
ascii_slot:
sub eax,33
ret
fallback:
mov eax,30
ret
blank:
mov eax,0xffffffff
ret
'''
    draw=f'''
call get_base
get_base:
pop ebp
sub ebp,{DRAW+5}
push ebx
push esi
push edi
lea ebx,[ebp+{SAMPLE}]
mov eax,dword ptr [ebp+0x3983]
mov edi,dword ptr [eax+120]
mov eax,dword ptr [ebp+0x398d]
add edi,dword ptr [eax]
add edi,80
call render_text
pop edi
pop esi
pop ebx
mov eax,dword ptr [ebp+0x39b0]
mov dword ptr [eax],0
call render_text
jmp 0x39be
render_text:
call {DECODER}
test eax,eax
jz text_done
call {GLYPH}
cmp eax,-1
je blank_glyph
push ebx
push esi
push edi
movzx edx,word ptr [esi+eax*4+4]
mov ebx,dword ptr [ebp+0x39ce]
mov dword ptr [ebx],edx
movzx ecx,word ptr [esi+eax*4+6]
add eax,dword ptr [esi]
mov eax,dword ptr [esi+eax*4+4]
add esi,eax
push ebp
mov ebp,2
call 0x3a0b
pop ebp
pop edi
pop esi
pop ebx
jmp advance
blank_glyph:
mov eax,dword ptr [ebp+0x39ce]
mov dword ptr [eax],4
advance:
mov eax,dword ptr [ebp+0x39ce]
mov eax,dword ptr [eax]
mov edx,dword ptr [ebp+0x39b0]
add dword ptr [edx],eax
lea edi,[edi+eax*2+2]
jmp render_text
text_done:
ret
'''
    if not overlay:
        start=draw.index('push ebx\npush esi\npush edi\nlea ebx')
        end=draw.index('call render_text\njmp 0x39be',start)
        draw=draw[:start]+draw[end:]
    width=f'''
push ebx
push ecx
push edx
push esi
push edi
push ebp
mov ebx,eax
call get_base
get_base:
pop ebp
sub ebp,{WIDTH+13}
mov esi,dword ptr [ebp+0x3993]
mov esi,dword ptr [esi]
xor edi,edi
next_char:
call {DECODER}
test eax,eax
jz width_done
call {GLYPH}
cmp eax,-1
je blank_width
movzx eax,word ptr [esi+eax*4+4]
inc eax
add edi,eax
jmp next_char
blank_width:
add edi,5
jmp next_char
width_done:
mov eax,edi
pop ebp
pop edi
pop esi
pop edx
pop ecx
pop ebx
ret
'''
    segments=[(DECODER,assemble(decoder,DECODER)),(GLYPH,assemble(glyph,GLYPH)),
              (DRAW,assemble(draw,DRAW)),(WIDTH,assemble(width,WIDTH)),
              (SAMPLE,DEMO.encode('utf-8')+b'\0')]
    sources=dict(draw=draw,width=width,glyph=glyph)
    if fast_height:
        height=f'''
push edx
call height_base
height_base:
pop edx
sub edx,{HEIGHT+6}
mov eax,dword ptr [edx+0x3993]
mov eax,dword ptr [eax]
movzx eax,word ptr [eax+966]
pop edx
ret
'''
        segments.append((HEIGHT,assemble(height,HEIGHT)))
        sources['height']=height
        segments.sort()
    for i,(addr,body) in enumerate(segments):
        limit=segments[i+1][0] if i+1<len(segments) else 0xae000
        if addr+len(body)>limit:raise ValueError('Code cave segment overflow')
    return segments,sources


def patch_exe(data,overlay=True,fast_height=False):
    if hashlib.sha256(data).hexdigest()!=EXPECTED:raise ValueError('Unsupported GAME.EXE hash')
    le=LE(data);relocs=fixups(le);out=bytearray(data)
    # Final code-page physical padding exists but is outside the old virtual size.
    end=next(m for m in le.mappings if m['object']==1 and m['address']==0xbd000)
    file_cave=end['offset']+0x900
    if any(data[file_cave:file_cave+0x700]):raise ValueError('Cave is not zero filled')
    ranges=[(0x3998,6),(0x3a81,5),(CAVE,0x700)]
    if fast_height:ranges.append((0x3ab1,5))
    for r in relocs:
        if r['object']==1 and any(a-3<=r['offset']<a+n for a,n in ranges):
            raise ValueError('Relocation overlaps patch range')
    if data[le.page_start+0x3998:le.page_start+0x399e]!=bytes.fromhex('8a0384c07420'):
        raise ValueError('Draw entry mismatch')
    if data[le.page_start+0x3a81:le.page_start+0x3a86]!=bytes.fromhex('56525331db'):
        raise ValueError('Width entry mismatch')
    segments,sources=payload(overlay,fast_height)
    for addr,body in segments:
        out[file_cave+addr-CAVE:file_cave+addr-CAVE+len(body)]=body
    detours=[(0x3998,DRAW,6),(0x3a81,WIDTH,5)]
    if fast_height:
        if data[le.page_start+0x3ab1:le.page_start+0x3ab6]!=bytes.fromhex('56515331db'):
            raise ValueError('Height entry mismatch')
        detours.append((0x3ab1,HEIGHT,5))
    for source,target,size in detours:
        code=assemble(f'jmp {target}',source)
        if len(code)!=5:raise ValueError('Unexpected detour size')
        out[le.page_start+source:le.page_start+source+size]=code+b'\x90'*(size-5)
    struct.pack_into('<I',out,le.header+le.u32(0x40),0xae000)
    parsed=LE(bytes(out))
    if fixups(parsed)!=relocs:raise ValueError('Fixup records changed')
    return bytes(out),sources,dict(relocations=len(relocs),cave_offset=file_cave,
        payload_bytes=sum(len(b) for _,b in segments),code_size_before=0xad900,code_size_after=0xae000,
        overlay=overlay,fast_height=fast_height)


def cache_font_height(data):
    """Unused slot 240 holds maximum height in its height field (offset 966)."""
    font=FNT(data,max_count=65535)
    height=max(h for w,h in font.dimensions)
    count=font.count;offset=4+count*8;dims=bytearray();ptrs=bytearray();pixels=bytearray()
    for i,(w,h) in enumerate(font.dimensions):
        if i==240:w,h,p=1,height,bytes(height*2)
        else:
            p=data[font.offsets[i]:font.offsets[i]+w*h*2]
            if len(p)!=w*h*2:raise ValueError('Expected allocated sparse font')
        dims.extend(struct.pack('<HH',w,h));ptrs.extend(struct.pack('<I',offset));pixels.extend(p);offset+=len(p)
    result=bytes(struct.pack('<HH',count,0)+dims+ptrs+pixels)
    FNT(result,max_count=65535)
    return result


def sparse_font(original,chars):
    from PIL import Image,ImageDraw,ImageFont
    base=FNT(original);face=ImageFont.truetype('C:/Windows/Fonts/malgun.ttf',14)
    glyphs=[]
    for i in range(base.count):
        if base.offsets[i]==len(original):glyphs.append((1,1,b'\0\0'))
        else:
            w,h=base.dimensions[i];at=base.offsets[i]
            glyphs.append((w,h,original[at:at+w*h*2]))
    for cp in range(0xac00,0xd7a4):
        if chr(cp) not in chars:glyphs.append((1,1,b'\0\0'));continue
        mask=Image.new('L',(16,16));d=ImageDraw.Draw(mask);l,t,r,b=face.getbbox(chr(cp))
        d.text(((16-r+l)//2-l,(16-b+t)//2-t),chr(cp),font=face,fill=255)
        values=mask.get_flattened_data() if hasattr(mask,'get_flattened_data') else mask.getdata()
        bitmap=struct.pack('<256H',*[0x7fff if x>75 else 0 for x in values])
        glyphs.append((16,16,bitmap))
    count=len(glyphs);offset=4+count*8;dims=bytearray();ptrs=bytearray();pixels=bytearray()
    for w,h,p in glyphs:
        dims.extend(struct.pack('<HH',w,h));ptrs.extend(struct.pack('<I',offset));pixels.extend(p);offset+=len(p)
    result=bytes(struct.pack('<HH',count,0)+dims+ptrs+pixels)
    FNT(result,max_count=65535)
    return result


def stage(game,dest,font_dir=None,overlay=True,fast_height=False,cpu_core='normal'):
    if dest.exists():raise ValueError('Output exists; choose a new directory')
    if game.resolve()==dest.resolve() or game.resolve() in dest.resolve().parents:
        raise ValueError('Trial must be outside source game')
    exe,sources,report=patch_exe((game/'GAME.EXE').read_bytes(),overlay,fast_height)
    # Make a complete independent copy; no hardlinks to writable game files.
    shutil.copytree(game,dest/'game')
    trial=dest/'game';(trial/'GAME.EXE').write_bytes(exe)
    sizes=[]
    for number in range(1,11):
        name=f'FONT{number:04d}.FNT'
        data=(font_dir/name).read_bytes() if font_dir else sparse_font((game/'GAMEDATA'/name).read_bytes(),set(DEMO))
        if fast_height:data=cache_font_height(data)
        FNT(data,max_count=65535)
        (trial/'GAMEDATA'/name).write_bytes(data);sizes.append(len(data))
    for name,source in sources.items():(dest/f'{name}.asm').write_text(source,encoding='utf-8')
    report.update(original_sha256=EXPECTED,patched_sha256=hashlib.sha256(exe).hexdigest(),
                  font_bytes=sizes,demo=DEMO,runtime_tested=False,
                  note='Sparse trial fonts contain selected Hangul only; not a full Korean release.')
    if font_dir:
        report['font_source']=str(font_dir)
        if (font_dir/'manifest.json').exists():
            shutil.copy2(font_dir/'manifest.json',dest/'font_manifest.json')
        if (font_dir/'LICENSE_Galmuri.txt').exists():
            shutil.copy2(font_dir/'LICENSE_Galmuri.txt',dest/'LICENSE_Galmuri.txt')
    (dest/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    config=trial/'DOSBox-0.73/utf8_trial.conf'
    config.write_text(f'[sdl]\nfullscreen=false\noutput=surface\n[dosbox]\nmemsize=63\n[cpu]\ncore={cpu_core}\ncycles=max\n[autoexec]\n@echo off\nmount C: .. -freesize 1024\nimgmount D: "../battlespire.ins" -t iso\nC:\nspire.bat\nexit\n',encoding='ascii')
    report['cpu_core']=cpu_core
    report['staged_font_sha256']={f'FONT{n:04d}.FNT':hashlib.sha256((trial/'GAMEDATA'/f'FONT{n:04d}.FNT').read_bytes()).hexdigest() for n in range(1,11)}
    (dest/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (dest/'START_UTF8_TRIAL.bat').write_text('@echo off\r\ncd /d "%~dp0game\\DOSBox-0.73"\r\nstart "" dosbox.exe -noconsole -conf bs.conf -conf utf8_trial.conf\r\n',encoding='ascii')
    print(json.dumps(report,ensure_ascii=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--font-dir',type=Path,help='Prebuilt trial FNT directory')
    parser.add_argument('--no-overlay',action='store_true')
    parser.add_argument('--fast-height',action='store_true')
    parser.add_argument('--cpu-core',choices=('normal','dynamic','auto'),default='normal')
    args=parser.parse_args();stage(args.game,args.output,args.font_dir,not args.no_overlay,args.fast_height,args.cpu_core)
