"""Battlespire Korean patch installer. Exact-version, backed-up, reversible."""
from __future__ import annotations
import argparse,contextlib,hashlib,json,os,queue,shutil,struct,sys,tempfile,threading,zipfile
from pathlib import Path,PurePosixPath
import bsdiff4

VERSION='0.1.0-preview1'
ASSETS=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))/'assets/korean-patch.zip'

class PatchError(Exception):pass
def sha(data):return hashlib.sha256(data).hexdigest()

def safe_path(root,name):
    part=PurePosixPath(name)
    if not part.parts or part.is_absolute() or any(p in ('..','.') or ':' in p or '\\' in p for p in part.parts):
        raise PatchError('안전하지 않은 파일 경로입니다: '+name)
    root=root.resolve();dest=root.joinpath(*part.parts)
    if not dest.resolve().is_relative_to(root):raise PatchError('게임 폴더 밖의 경로입니다: '+name)
    if dest.is_symlink():raise PatchError('심볼릭 링크 파일은 수정하지 않습니다: '+name)
    return dest

class Archive:
    def __init__(self,data):
        self.data=data;self.count,self.kind=struct.unpack_from('<HH',data)
        if self.kind!=0x100:raise PatchError('지원하지 않는 BSA 형식입니다.')
        self.directory=len(data)-18*self.count;self.entries=[];pos=4
        for index in range(self.count):
            row=data[self.directory+index*18:self.directory+(index+1)*18]
            name,flag,size=struct.unpack('<12sHI',row)
            if flag not in (0,0x100) or pos+size>self.directory:raise PatchError('손상된 BSA입니다.')
            self.entries.append(dict(index=index,name=name,flag=flag,size=size,start=pos,directory=row));pos+=size
        if pos!=self.directory:raise PatchError('BSA 경계가 일치하지 않습니다.')
    def stored(self,e):return self.data[e['start']:e['start']+e['size']]
    def raw(self,e):
        data=self.stored(e)
        if not e['flag']:return data
        window=bytearray(b' '*4078+b'\0'*18);out=bytearray();cursor=4078;pos=0
        def emit(byte):
            nonlocal cursor
            if len(out)>32*1024*1024:raise PatchError('BSA 압축 해제 제한을 초과했습니다.')
            out.append(byte);window[cursor]=byte;cursor=(cursor+1)&4095
        while pos<len(data):
            flags=data[pos];pos+=1
            for bit in range(8):
                if pos>=len(data):break
                if flags&(1<<bit):emit(data[pos]);pos+=1
                else:
                    if pos+2>len(data):raise PatchError('잘린 BSA 압축 데이터입니다.')
                    lo,hi=data[pos:pos+2];pos+=2;at=lo|((hi&240)<<4)
                    for i in range((hi&15)+3):emit(window[(at+i)&4095])
        return bytes(out)

class Bundle:
    def __init__(self,path=ASSETS):
        self.path=Path(path)
        with zipfile.ZipFile(self.path) as z:self.manifest=json.loads(z.read('manifest.json'))
        if self.manifest.get('schema')!=1:raise PatchError('패치 형식을 지원하지 않습니다.')
        paths=[e['path'] for e in self.manifest['files']]
        if len(paths)!=len(set(paths)):raise PatchError('패치에 중복 경로가 있습니다.')
        for name in paths:safe_path(Path.cwd(),name)
    def payload(self,entry):
        with zipfile.ZipFile(self.path) as z:data=z.read(entry['payload'])
        if sha(data)!=entry['payload_sha256']:raise PatchError('패치 데이터가 손상되었습니다.')
        return data
    def rebuild(self,entry,before):
        if entry['mode']=='new':result=self.payload(entry)
        elif entry['mode']=='bsdiff':result=bsdiff4.patch(before,self.payload(entry))
        elif entry['mode']=='bsa':
            archive=Archive(before);changes={r['index']:r for r in entry['members']}
            result=bytearray(before[:4]);directory=bytearray()
            for member in archive.entries:
                record=bytearray(member['directory']);change=changes.get(member['index'])
                if change:
                    source=archive.raw(member) if change['source_mode']=='raw' else archive.stored(member)
                    if sha(source)!=change['source_sha256']:raise PatchError('BSA 항목 원본이 다릅니다.')
                    value=bsdiff4.patch(source,self.payload(change))
                    if sha(value)!=change['target_sha256']:raise PatchError('BSA 항목 결과가 다릅니다.')
                    struct.pack_into('<HI',record,12,change['target_flag'],len(value))
                else:value=archive.stored(member)
                result.extend(value);directory.extend(record)
            result=bytes(result+directory);Archive(result)
        else:raise PatchError('알 수 없는 패치 방식입니다.')
        if sha(result)!=entry['target_sha256']:raise PatchError('패치 결과 해시가 다릅니다: '+entry['path'])
        return result

def atomic_write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.bsk-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

@contextlib.contextmanager
def game_lock(root):
    path=root/'_Battlespire_Korean_Backup/installer.lock';path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as handle:
        handle.seek(0);handle.write(b'0');handle.flush();handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as e:raise PatchError('다른 패처가 이 폴더에서 작업 중입니다.') from e
        try:yield
        finally:
            handle.seek(0)
            if os.name=='nt':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle,fcntl.LOCK_UN)

class Installer:
    def __init__(self,game,bundle=None,progress=lambda message:None):
        self.root=Path(game).resolve();self.bundle=bundle or Bundle();self.progress=progress
        self.entries=self.bundle.manifest['files']
        self.backup=self.root/'_Battlespire_Korean_Backup'/self.bundle.manifest['version']
        # Version is a path component, too; reject malicious bundle metadata.
        safe_path(self.root,'_Battlespire_Korean_Backup/'+self.bundle.manifest['version']+'/state.json')
    def check(self):
        if not self.root.is_dir():raise PatchError('게임 폴더가 없습니다.')
        status=[]
        for entry in self.entries:
            target=safe_path(self.root,entry['path']);value=target.read_bytes() if target.exists() else None
            digest=sha(value) if value is not None else None
            if digest==entry['target_sha256']:state='installed'
            elif digest==entry['source_sha256']:state='original'
            else:raise PatchError('지원하는 원본과 다르거나 다른 패치가 적용돼 있습니다: '+entry['path'])
            status.append(state)
        if all(s=='installed' for s in status):return 'installed'
        if any(s=='installed' for s in status):raise PatchError('일부 파일만 패치되어 있습니다. 백업 복원 후 다시 설치하세요.')
        return 'original'
    def _state(self):
        path=self.backup/'state.json'
        if not path.exists():raise PatchError('이 패치의 백업 기록이 없습니다.')
        state=json.loads(path.read_text(encoding='utf-8'))
        if state['bundle_id']!=self.bundle.manifest['bundle_id']:raise PatchError('백업과 패치 버전이 다릅니다.')
        return state
    def _restore_bytes(self):
        restored={}
        for e in self.entries:
            if e['source_sha256'] is None:restored[e['path']]=None;continue
            value=safe_path(self.backup/'original',e['path']).read_bytes()
            if sha(value)!=e['source_sha256']:raise PatchError('백업 파일이 손상되었습니다: '+e['path'])
            restored[e['path']]=value
        return restored
    def apply(self):
        with game_lock(self.root):
            if self.check()=='installed':self.progress('이미 같은 패치가 설치되어 있습니다.');return 'already_installed'
            self.progress('원본 확인 완료. 적용할 파일을 만드는 중...');prepared={};originals={}
            for e in self.entries:
                path=safe_path(self.root,e['path']);before=path.read_bytes() if path.exists() else None
                # Revalidate after preflight; do not silently patch a moving file.
                if (sha(before) if before is not None else None)!=e['source_sha256']:raise PatchError('검사 후 파일이 바뀌었습니다: '+e['path'])
                originals[e['path']]=before;prepared[e['path']]=self.bundle.rebuild(e,before)
                self.progress('준비: '+e['path'])
            self.backup.mkdir(parents=True,exist_ok=True)
            if (self.backup/'state.json').exists():self._state()
            for e in self.entries:
                before=originals[e['path']]
                if before is None:continue
                target=safe_path(self.backup/'original',e['path'])
                if target.exists():
                    if sha(target.read_bytes())!=e['source_sha256']:raise PatchError('다른 백업을 덮어쓰지 않습니다.')
                else:atomic_write(target,before)
            self._restore_bytes() # Verify every backup before the first game write.
            state=dict(bundle_id=self.bundle.manifest['bundle_id'],version=self.bundle.manifest['version'],status='prepared')
            atomic_write(self.backup/'state.json',(json.dumps(state,indent=2)+'\n').encode())
            written=[]
            try:
                for name,value in prepared.items():
                    path=safe_path(self.root,name);current=path.read_bytes() if path.exists() else None
                    if current!=originals[name]:raise PatchError('설치 중 파일이 바뀌었습니다: '+name)
                    atomic_write(path,value);written.append(name);self.progress('적용: '+name)
                state['status']='installed';atomic_write(self.backup/'state.json',json.dumps(state,indent=2).encode())
            except Exception:
                for name in reversed(written):
                    path=safe_path(self.root,name);before=originals[name]
                    if before is None:path.unlink()
                    else:atomic_write(path,before)
                state['status']='rolled_back';atomic_write(self.backup/'state.json',json.dumps(state,indent=2).encode());raise
            self.progress('설치 완료. 게임 폴더의 START_KOREAN.bat로 실행하세요.');return 'installed'
    def restore(self):
        with game_lock(self.root):
            state=self._state();originals=self._restore_bytes()
            for e in self.entries:
                path=safe_path(self.root,e['path']);current=sha(path.read_bytes()) if path.exists() else None
                if current not in (e['target_sha256'],e['source_sha256']):
                    raise PatchError('설치 후 바뀐 파일을 덮어쓰지 않습니다: '+e['path'])
            for name,value in originals.items():
                path=safe_path(self.root,name)
                if value is None:
                    if path.exists():path.unlink()
                else:atomic_write(path,value)
                self.progress('복원: '+name)
            state['status']='restored';atomic_write(self.backup/'state.json',json.dumps(state,indent=2).encode())
            self.progress('원본 복원 완료. 백업은 보관했습니다.');return 'restored'

def gui():
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    root=tk.Tk();root.title('배틀스파이어 한국어 패처 '+VERSION);root.geometry('680x430');root.minsize(620,380)
    frame=ttk.Frame(root,padding=18);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='배틀스파이어 한국어 패처',font=('맑은 고딕',17,'bold')).pack(anchor='w')
    ttk.Label(frame,text='Steam 1.5 원본용 · 대사/서적/UI/EXE/직업/기술/메시지 포함\n실제 게임 전체 분기 검증 전인 시험 배포판입니다. 게임을 종료하고 적용하세요.').pack(anchor='w',pady=(8,14))
    path=tk.StringVar();line=ttk.Frame(frame);line.pack(fill='x')
    ttk.Entry(line,textvariable=path).pack(side='left',fill='x',expand=True)
    ttk.Button(line,text='게임 폴더 선택',command=lambda:path.set(filedialog.askdirectory() or path.get())).pack(side='right',padx=(8,0))
    if (Path.cwd()/'GAME.EXE').exists():path.set(str(Path.cwd()))
    else:
        guess=Path(os.environ.get('ProgramFiles(x86)',r'C:\Program Files (x86)'))/'Steam/steamapps/common/An Elder Scrolls Legend Battlespire'
        if guess.exists():path.set(str(guess))
    actions=ttk.Frame(frame);actions.pack(fill='x',pady=14);events=queue.Queue();buttons=[];busy=[False]
    output=tk.Text(frame,height=12,wrap='word',state='disabled');output.pack(fill='both',expand=True)
    def run(action):
        if busy[0]:return
        if not path.get():messagebox.showinfo('게임 폴더','GAME.EXE가 있는 폴더를 선택하세요.');return
        busy[0]=True
        for button in buttons:button.configure(state='disabled')
        game=path.get()
        def worker():
            try:
                installer=Installer(game,progress=lambda m:events.put(('log',m)))
                if action=='check':events.put(('log','호환 원본입니다.' if installer.check()=='original' else '이미 설치되어 있습니다.'))
                else:getattr(installer,action)()
            except Exception as error:events.put(('error',str(error)))
            finally:events.put(('done',''))
        threading.Thread(target=worker,daemon=True).start()
    for label,action in [('원본 검사','check'),('한국어 패치 적용','apply'),('원본 복원','restore')]:
        button=ttk.Button(actions,text=label,command=lambda a=action:run(a));button.pack(side='left',padx=(0,8));buttons.append(button)
    def poll():
        while not events.empty():
            kind,message=events.get()
            if kind=='done':
                busy[0]=False
                for button in buttons:button.configure(state='normal')
            else:
                output.configure(state='normal');output.insert('end',message+'\n');output.see('end');output.configure(state='disabled')
                if kind=='error':messagebox.showerror('패처',message)
        root.after(100,poll)
    def closing():
        if busy[0]:messagebox.showinfo('작업 중','파일 작업이 끝난 뒤 닫아 주세요.')
        else:root.destroy()
    root.protocol('WM_DELETE_WINDOW',closing);poll();root.mainloop()

def main():
    p=argparse.ArgumentParser(description='Battlespire Korean patch installer')
    p.add_argument('--game',type=Path);p.add_argument('--bundle',type=Path,default=ASSETS)
    group=p.add_mutually_exclusive_group();group.add_argument('--check',action='store_true');group.add_argument('--apply',action='store_true');group.add_argument('--restore',action='store_true')
    a=p.parse_args()
    if not any([a.check,a.apply,a.restore]):gui();return 0
    if not a.game:p.error('--game is required for command-line use')
    try:
        installer=Installer(a.game,Bundle(a.bundle),print)
        result=installer.check() if a.check else installer.apply() if a.apply else installer.restore()
        print(json.dumps(dict(status=result),ensure_ascii=False));return 0
    except Exception as error:
        print(str(error),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
