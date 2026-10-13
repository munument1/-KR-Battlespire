"""Build changes-only payload from user-owned original and translated games."""
import argparse,hashlib,json,struct,zipfile
from pathlib import Path
import bsdiff4
from patcher import Archive,Bundle,VERSION,sha

LAUNCHER=b'@echo off\r\ncd /d "%~dp0DOSBox-0.73"\r\nstart "" dosbox.exe -noconsole -conf bs.conf -conf korean.conf\r\n'
CONFIG=b'[sdl]\r\nfullscreen=false\r\noutput=surface\r\n[dosbox]\r\nmemsize=63\r\n[cpu]\r\ncore=dynamic\r\ncycles=max\r\n[autoexec]\r\n@echo off\r\nmount C: .. -freesize 1024\r\nimgmount D: "../battlespire.ins" -t iso\r\nC:\r\nspire.bat\r\nexit\r\n'

def build(original,translated,output):
    assert not output.exists();output.parent.mkdir(parents=True,exist_ok=True)
    stage=json.loads((translated.parent/'manifest.json').read_text(encoding='utf-8'))
    paths=sorted(set(stage['changed_files']+stage['new_files']+['GAMEDATA/BSI.BSA']))
    new={'START_KOREAN.bat':LAUNCHER,'DOSBox-0.73/korean.conf':CONFIG}
    paths+=list(new);records=[];payloads={};serial=0
    def add(data):
        nonlocal serial
        name=f'patches/{serial:04d}.dat';serial+=1;payloads[name]=data
        return dict(payload=name,payload_sha256=sha(data))
    for name in paths:
        source=original/name;target=translated/name
        before=source.read_bytes() if source.exists() else None
        after=new[name] if name in new else target.read_bytes()
        if before==after:continue
        entry=dict(path=name,source_sha256=sha(before) if before is not None else None,
            target_sha256=sha(after),source_bytes=len(before) if before is not None else None,target_bytes=len(after))
        if before is None:entry.update(mode='new',**add(after))
        elif name.upper().endswith('.BSA'):
            a,b=Archive(before),Archive(after);assert a.count==b.count and a.kind==b.kind
            members=[]
            for x,y in zip(a.entries,b.entries):
                assert x['name']==y['name']
                if a.stored(x)==b.stored(y) and x['flag']==y['flag']:continue
                mode='raw' if y['flag']==0 else 'stored'
                old=a.raw(x) if mode=='raw' else a.stored(x);value=b.stored(y)
                diff=bsdiff4.diff(old,value);assert bsdiff4.patch(old,diff)==value
                members.append(dict(index=x['index'],source_mode=mode,source_sha256=sha(old),
                    target_sha256=sha(value),target_flag=y['flag'],**add(diff)))
            entry.update(mode='bsa',members=members)
        else:
            delta=bsdiff4.diff(before,after);assert bsdiff4.patch(before,delta)==after
            entry.update(mode='bsdiff',**add(delta))
        records.append(entry)
        print(name,entry['mode'],len(entry.get('members',[])))
    manifest=dict(schema=1,version=VERSION,game='Battlespire Steam 1.5',files=records,
        translations=dict(dialogue_fields=2275,books=59,rsc_prose=204,rsc_placeholder_labels=68,
            item_name_fields=463,spire_fields=143,exe_ui_strings=628,exe_inline_names=90,class_templates=18,level_names=17),
        runtime_game_fully_verified=False,original_game_files_included=False)
    manifest['bundle_id']=sha(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode())
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        for name,data in payloads.items():z.writestr(name,data)
    # Independently reconstruct EVERY declared output using the public installer.
    bundle=Bundle(output)
    for entry in manifest['files']:
        path=original/entry['path'];data=path.read_bytes() if path.exists() else None
        assert sha(bundle.rebuild(entry,data))==entry['target_sha256'],entry['path']
    print(json.dumps(dict(files=len(records),patch_blocks=len(payloads),payload_bytes=output.stat().st_size,
        all_outputs_reconstructed=True,bundle_id=manifest['bundle_id'])))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--original-game',type=Path,required=True)
    p.add_argument('--translated-game',type=Path,required=True);p.add_argument('--output',type=Path,default=Path('assets/korean-patch.zip'))
    a=p.parse_args();build(a.original_game,a.translated_game,a.output)
