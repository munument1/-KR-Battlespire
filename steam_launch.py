"""Adjust only runtime settings shared by Steam's existing launch entries."""
import re

def configure(data):
    text=data.decode('ascii');section='';found=set();out=[]
    desired={('sdl','output'):'surface',('dosbox','memsize'):'63',('cpu','core'):'dynamic',('cpu','cycles'):'max'}
    for line in text.splitlines(keepends=True):
        heading=re.fullmatch(r'\s*\[([^\]]+)\]\s*',line.strip())
        if heading:section=heading[1].lower()
        setting=re.match(r'^(\s*)([A-Za-z0-9_]+)\s*=.*?(\r?\n)?$',line)
        key=(section,setting[2].lower()) if setting else None
        if key in desired:
            if key in found:raise ValueError('Duplicate DOSBox setting: '+str(key))
            found.add(key);line=setting[1]+setting[2]+'='+desired[key]+(setting[3] or '')
        out.append(line)
    if found!=set(desired):raise ValueError('Missing expected DOSBox sections/settings')
    return ''.join(out).encode('ascii')
