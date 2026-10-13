import json,struct,tempfile,unittest,zipfile
from pathlib import Path
from unittest import mock
import bsdiff4
import patcher
from patcher import Bundle,Installer,PatchError,Archive,sha,safe_path

def archive(values):
    header=struct.pack('<HH',len(values),0x100);body=b'';directory=b''
    for name,value in values:
        body+=value;directory+=struct.pack('<12sHI',name.encode().ljust(12,b'\0'),0,len(value))
    return header+body+directory

class InstallerTests(unittest.TestCase):
    def setUp(self):
        # Windows runners can return an 8.3 temp path. Canonicalize it exactly
        # as Installer does, so fault injection targets the actual game file.
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();self.game=self.root/'game';self.game.mkdir()
        self.old={'GAME.EXE':b'original executable','GAMEDATA/TEXT.RSC':b'original text'}
        self.new={'GAME.EXE':b'patched executable','GAMEDATA/TEXT.RSC':'한국어'.encode(),'START_KOREAN.bat':b'new launcher'}
        records=[];blobs={}
        for index,(name,value) in enumerate(self.new.items()):
            before=self.old.get(name);payload=f'p/{index}';data=value if before is None else bsdiff4.diff(before,value)
            blobs[payload]=data;records.append(dict(path=name,source_sha256=sha(before) if before is not None else None,
                target_sha256=sha(value),mode='new' if before is None else 'bsdiff',payload=payload,payload_sha256=sha(data)))
        self.manifest=dict(schema=1,version='test',bundle_id='test-id',files=records)
        self.bundle_path=self.root/'bundle.zip';self.write_bundle(blobs)
        for name,value in self.old.items():
            p=self.game/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(value)
        self.installer=Installer(self.game,Bundle(self.bundle_path))
    def tearDown(self):self.tmp.cleanup()
    def write_bundle(self,blobs):
        with zipfile.ZipFile(self.bundle_path,'w') as z:
            z.writestr('manifest.json',json.dumps(self.manifest))
            for name,value in blobs.items():z.writestr(name,value)
    def assert_original(self):
        for name,value in self.old.items():self.assertEqual((self.game/name).read_bytes(),value)
        self.assertFalse((self.game/'START_KOREAN.bat').exists())
    def test_install_and_exact_restore(self):
        self.assertEqual(self.installer.check(),'original');self.installer.apply()
        for name,value in self.new.items():self.assertEqual((self.game/name).read_bytes(),value)
        self.assertEqual(self.installer.check(),'installed');self.installer.restore();self.assert_original()
        self.assertTrue((self.installer.backup/'original/GAME.EXE').exists())
    def test_install_is_idempotent(self):
        self.installer.apply();self.assertEqual(self.installer.apply(),'already_installed')
        self.assertEqual((self.installer.backup/'original/GAME.EXE').read_bytes(),self.old['GAME.EXE'])
    def test_incompatible_original_rejected_before_game_writes(self):
        (self.game/'GAME.EXE').write_bytes(b'other version')
        with self.assertRaises(PatchError):self.installer.apply()
        self.assertEqual((self.game/'GAMEDATA/TEXT.RSC').read_bytes(),self.old['GAMEDATA/TEXT.RSC'])
        self.assertFalse((self.game/'START_KOREAN.bat').exists())
    def test_payload_corruption_rejected_before_game_writes(self):
        self.write_bundle({'p/0':b'wrong','p/1':b'wrong','p/2':b'wrong'})
        with self.assertRaises(PatchError):self.installer.apply()
        self.assert_original()
    def test_restore_does_not_overwrite_post_install_changes(self):
        self.installer.apply();(self.game/'GAME.EXE').write_bytes(b'new mod')
        with self.assertRaises(PatchError):self.installer.restore()
        self.assertEqual((self.game/'GAME.EXE').read_bytes(),b'new mod')
    def test_corrupt_backup_rejected_before_restore_writes(self):
        self.installer.apply();(self.installer.backup/'original/GAME.EXE').write_bytes(b'bad backup')
        with self.assertRaises(PatchError):self.installer.restore()
        self.assertEqual((self.game/'GAME.EXE').read_bytes(),self.new['GAME.EXE'])
    def test_failed_install_rolls_back_written_files(self):
        original_write=patcher.atomic_write
        def failing(path,value):
            if path==self.game/'GAMEDATA/TEXT.RSC' and value==self.new['GAMEDATA/TEXT.RSC']:raise OSError('simulated disk failure')
            original_write(path,value)
        with mock.patch.object(patcher,'atomic_write',side_effect=failing):
            with self.assertRaises(OSError):self.installer.apply()
        self.assert_original()
    def test_repeat_install_after_restore(self):
        self.installer.apply();self.installer.restore();self.installer.apply()
        self.assertEqual(self.installer.check(),'installed')
    def test_partial_install_rejected(self):
        (self.game/'GAME.EXE').write_bytes(self.new['GAME.EXE'])
        with self.assertRaises(PatchError):self.installer.apply()
    def upgrade_fixture(self):
        self.installer.apply();old=json.loads(json.dumps(self.manifest))
        with zipfile.ZipFile(self.bundle_path) as z:blobs={n:z.read(n) for n in z.namelist() if n!='manifest.json'}
        cfg=self.game/'DOSBox-0.73/bs.conf';cfg.parent.mkdir();cfg.write_bytes(b'old config')
        delta=bsdiff4.diff(b'old config',b'Steam-compatible config');blobs['steam']=delta
        self.manifest.update(version='next',bundle_id='next-id',upgrade_from=dict(version=old['version'],bundle_id=old['bundle_id'],files=old['files']))
        self.manifest['files'].append(dict(path='DOSBox-0.73/bs.conf',source_sha256=sha(b'old config'),target_sha256=sha(b'Steam-compatible config'),mode='bsdiff',payload='steam',payload_sha256=sha(delta)))
        self.write_bundle(blobs);return Installer(self.game,Bundle(self.bundle_path))
    def test_verified_upgrade_keeps_clean_original_backup_and_restores_it(self):
        installer=self.upgrade_fixture();self.assertEqual(installer.check(),'upgrade_available');installer.apply()
        self.assertEqual((self.game/'DOSBox-0.73/bs.conf').read_bytes(),b'Steam-compatible config')
        installer.restore();self.assert_original()
        self.assertEqual((self.game/'DOSBox-0.73/bs.conf').read_bytes(),b'old config')
    def test_upgrade_accepts_changed_compiled_exe_only_with_verified_old_backup(self):
        self.upgrade_fixture()
        revised=b'new UTF-8 compiled executable with legacy RSC control handling'
        with zipfile.ZipFile(self.bundle_path) as z:
            blobs={name:z.read(name) for name in z.namelist() if name!='manifest.json'}
        entry=next(e for e in self.manifest['files'] if e['path']=='GAME.EXE')
        patch=bsdiff4.diff(self.old['GAME.EXE'],revised)
        blobs[entry['payload']]=patch
        entry['payload_sha256']=sha(patch)
        entry['target_sha256']=sha(revised)
        self.write_bundle(blobs)
        upgraded=Installer(self.game,Bundle(self.bundle_path))
        self.assertEqual(upgraded.check(),'upgrade_available')
        upgraded.apply()
        self.assertEqual((self.game/'GAME.EXE').read_bytes(),revised)
        upgraded.restore()
        self.assert_original()
        self.assertEqual((self.game/'DOSBox-0.73/bs.conf').read_bytes(),b'old config')
    def test_upgrade_rejects_damaged_original_backup(self):
        installer=self.upgrade_fixture();(self.installer.backup/'original/GAME.EXE').write_bytes(b'bad')
        with self.assertRaises(PatchError):installer.apply()
        self.assertEqual((self.game/'GAME.EXE').read_bytes(),self.new['GAME.EXE'])
        self.assertEqual((self.game/'DOSBox-0.73/bs.conf').read_bytes(),b'old config')
    def test_traversal_and_absolute_paths_rejected(self):
        for name in ['../GAME.EXE','/GAME.EXE','C:/GAME.EXE','a\\GAME.EXE','a/../../outside']:
            with self.subTest(name=name),self.assertRaises(PatchError):safe_path(self.game,name)
    def test_symlink_escape_rejected(self):
        outside=self.root/'outside';outside.mkdir()
        try:(self.game/'link').symlink_to(outside,target_is_directory=True)
        except OSError:self.skipTest('symlink permission unavailable')
        with self.assertRaises(PatchError):safe_path(self.game,'link/file')
    def test_named_archive_member_delta_roundtrip(self):
        old=archive([('A.TXT',b'unchanged'),('B.TXT',b'old text')])
        new=archive([('A.TXT',b'unchanged'),('B.TXT','한글 본문'.encode())])
        a=Archive(old);self.assertEqual(a.raw(a.entries[0]),b'unchanged')
        delta=bsdiff4.diff(b'old text','한글 본문'.encode())
        entry=dict(path='GAMEDATA/TXT.BSA',mode='bsa',source_sha256=sha(old),target_sha256=sha(new),
            members=[dict(index=1,source_mode='raw',source_sha256=sha(b'old text'),target_sha256=sha('한글 본문'.encode()),
                target_flag=0,payload='delta',payload_sha256=sha(delta))])
        self.manifest['files']=[entry];self.write_bundle({'delta':delta})
        self.assertEqual(Bundle(self.bundle_path).rebuild(entry,old),new)

if __name__=='__main__':unittest.main()
