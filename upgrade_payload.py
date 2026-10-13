"""Add Steam's shared DOSBox configuration and verified Preview 1 migration."""
import argparse,json,zipfile
from pathlib import Path
import bsdiff4
from patcher import VERSION,sha
from steam_launch import configure

def build(previous,config,output):
    assert not output.exists()
    with zipfile.ZipFile(previous) as z:
        old=json.loads(z.read('manifest.json'));blobs={n:z.read(n) for n in z.namelist() if n!='manifest.json'}
    before=config.read_bytes();after=configure(before);data=bsdiff4.diff(before,after)
    manifest=dict(old);manifest.pop('bundle_id');manifest['version']=VERSION
    manifest['upgrade_from']=dict(version=old['version'],bundle_id=old['bundle_id'],
        files=[{k:e[k] for k in ['path','source_sha256','target_sha256']} for e in old['files']])
    manifest['files']=old['files']+[dict(path='DOSBox-0.73/bs.conf',source_sha256=sha(before),target_sha256=sha(after),
        source_bytes=len(before),target_bytes=len(after),mode='bsdiff',payload='patches/steam-config.dat',payload_sha256=sha(data))]
    manifest['steam_default_launch_supported']=True
    manifest['bundle_id']=sha(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode())
    blobs['patches/steam-config.dat']=data
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        for name,value in blobs.items():z.writestr(name,value)
    assert bsdiff4.patch(before,data)==after
    print(json.dumps(dict(files=len(manifest['files']),version=VERSION,config_sha256=sha(after))))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--previous',type=Path,required=True);p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();build(a.previous,a.config,a.output)
