import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import configure_windows as config
from instance_lock import InstanceLock

class Compatibility(unittest.TestCase):
    def test_posix_lock_exclusive_and_release(self):
        if os.name=='nt': self.skipTest('POSIX branch')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bot.lock'
            a=InstanceLock(path)
            with self.assertRaises(OSError): InstanceLock(path)
            a.close(); b=InstanceLock(path); b.close()

    def test_windows_branch_lock_unlock(self):
        calls=[]
        fake=types.SimpleNamespace(LK_NBLCK=2,LK_UNLCK=0,locking=lambda fd,mode,n:calls.append((mode,n)))
        with tempfile.TemporaryDirectory() as folder,patch.dict(sys.modules,{'msvcrt':fake}):
            lock=InstanceLock(Path(folder)/'bot.lock',platform='nt'); lock.close()
            self.assertEqual(calls,[(2,1),(0,1)])

    def test_windows_branch_failed_lock_closes_file(self):
        fake=types.SimpleNamespace(LK_NBLCK=2,locking=lambda *args:(_ for _ in ()).throw(OSError('locked')))
        with tempfile.TemporaryDirectory() as folder,patch.dict(sys.modules,{'msvcrt':fake}):
            with self.assertRaises(OSError): InstanceLock(Path(folder)/'bot.lock',platform='nt')

    def test_timezone_fallback_in_separate_process(self):
        code="from unittest.mock import patch; from zoneinfo import ZoneInfoNotFoundError; from datetime import datetime; exec(\"with patch('zoneinfo.ZoneInfo', side_effect=ZoneInfoNotFoundError()):\\n import engine\\n print(datetime(2026,11,4,tzinfo=engine.TZ).utcoffset().total_seconds())\")"
        result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,check=True)
        self.assertEqual(result.stdout.strip(),'18000.0')

    def test_config_read_utf8_bom(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'.env';path.write_text('BOT_TOKEN=abc\n',encoding='utf-8-sig')
            self.assertEqual(config.read_values(path)['BOT_TOKEN'],'abc')

    def test_wizard_saves_without_exposing_token(self):
        class Fake:
            def __init__(self,token): pass
            def call(self,method,**kwargs):
                if method=='getMe': return {'id':444,'username':'roy_test_bot'}
                if method=='getWebhookInfo': return {}
                if method=='getUpdates':return [{'message':{'from':{'id':1,'first_name':'Иван'},'chat':{'id':-100,'title':'Медовый поток'}}}]
                if method=='getChat':return {'title':'Медовый поток'}
                if method=='getChatMember':return {'status':'administrator' if kwargs['user_id']==444 else 'creator'}
                raise AssertionError(method)
        token='123456:TEST_NOT_REAL'
        with tempfile.TemporaryDirectory() as folder,patch.object(config,'BASE',Path(folder)),patch.object(config.os,'chdir'),patch.object(config,'Telegram',Fake),patch.object(config.getpass,'getpass',return_value=token),patch('builtins.input',side_effect=['','','','да']):
            output=io.StringIO()
            with contextlib.redirect_stdout(output): self.assertEqual(config.main(),0)
            self.assertNotIn(token,output.getvalue())
            values=config.read_values(Path(folder)/'.env')
            self.assertEqual(values['ADMIN_IDS'],'1'); self.assertEqual(values['TAVERN_CHAT_ID'],'-100')
            self.assertEqual(values['BOT_TOKEN'],token)

if __name__=='__main__': unittest.main()
