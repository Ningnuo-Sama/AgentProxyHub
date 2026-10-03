"""官方契约mock回归：绝不访问网络或真实金库。"""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

from core import mineru_ocr as m


class MinerUTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.file = self.root / 'input.jpg'
        self.file.write_bytes(b'JPEG mock')
        self.root_patch = patch.object(m, 'ROOT', self.root)
        self.root_patch.start()
        self.net = patch.object(m, '_request')
        self.request = self.net.start()
        self.token = patch.object(m, '_token', return_value='SECRET_TOKEN')
        self.token.start()
        self.addCleanup(self.token.stop)
        self.addCleanup(self.net.stop)
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.temp.cleanup)

    def submit(self, api='precise'):
        data = {'batch_id': 'batch-1', 'file_urls': ['https://mineru.oss-cn-shanghai.aliyuncs.com/a?signature=PRIVATE']} if api == 'precise' else {'task_id': 'task-1', 'file_url': 'https://oss-mineru.openxlab.org.cn/a?signature=PRIVATE'}
        self.request.side_effect = [json.dumps({'code': 0, 'data': data}).encode(), b'']
        return m.run({'action': 'submit', 'api': api, 'file_path': str(self.file)})

    def test_dry_run(self):
        r = m.run({'file_path': str(self.file)})
        self.assertTrue(r['ok']); self.assertFalse(r['executed'])
        self.assertEqual(r['status'], 'not_submitted')
        self.request.assert_not_called()

    def test_endpoint_and_env_cannot_override(self):
        for extra in ({'endpoint': 'https://evil.test'}, {'mode': 'execute'}, {'token': 'PRIVATE'}):
            self.assertFalse(m.run(dict(file_path=str(self.file), **extra))['ok'])
        with patch.dict('os.environ', {'APHUB_OCR_ALLOWED_ROOT': str(self.root.parent)}):
            self.assertFalse(m.run({'file_path': str(self.root.parent / 'else.jpg')})['ok'])
        self.request.assert_not_called()

    def test_escape_ads_and_relative(self):
        for path in ('../input.jpg', str(self.root / '..' / 'else.jpg'), str(self.file)+':ads'):
            self.assertFalse(m.run({'file_path': path})['ok'])
        self.request.assert_not_called()

    def test_size(self):
        self.file.write_bytes(b'')
        self.assertEqual(m.run({'file_path': str(self.file)})['code'], 'ocr_file_too_large')

    def test_precise_upload_success_and_no_leak(self):
        r = self.submit()
        self.assertEqual(r['status'], 'submitted')
        self.assertEqual(self.request.call_args_list[0].args[:2], ('POST', m.API+'/api/v4/file-urls/batch'))
        upload = self.request.call_args_list[1]
        self.assertEqual(upload.args[0], 'PUT')
        self.assertNotIn('Authorization', upload.kwargs['headers'])
        self.assertNotIn('SECRET', json.dumps(r)); self.assertNotIn('PRIVATE', json.dumps(r))
        self.assertNotIn('http', json.dumps(r))
        self.assertEqual(len(list((self.root/'mineru-jobs').glob('*.json'))), 1)

    def test_agent_no_auth(self):
        self.assertTrue(self.submit('agent')['ok'])
        self.assertNotIn('Authorization', self.request.call_args_list[0].kwargs['headers'])

    def test_upload_failure_not_submitted(self):
        self.submit()
        self.request.side_effect = [b'{"code":0,"data":{"batch_id":"b","file_urls":["https://mineru.oss-cn-shanghai.aliyuncs.com/a"]}}', m.OcrError('mineru_http_error', http_status=403)]
        r=m.run({'action':'submit','file_path':str(self.file)})
        self.assertFalse(r['ok']); self.assertNotEqual(r.get('status'), 'submitted')
        self.assertEqual(r['stage'], 'upload'); self.assertFalse(r['executed'])

    def test_error_code_and_secret_message_filtered(self):
        self.request.side_effect = None
        self.request.return_value = b'{"code":-30001,"msg":"SECRET_TOKEN https://evil?signature=PRIVATE"}'
        r=m.run({'action':'submit','file_path':str(self.file)})
        self.assertEqual(r['provider_code'], -30001)
        self.assertNotIn('SECRET', json.dumps(r)); self.assertEqual(r['stage'], 'allocate_upload')

    def test_url_allowlist(self):
        for url in ('http://oss-mineru.openxlab.org.cn/a', 'https://oss-mineru.openxlab.org.cn.evil/a', 'https://user@oss-mineru.openxlab.org.cn/a', 'https://127.0.0.1/a', 'https://oss-mineru.openxlab.org.cn:444/a'):
            with self.assertRaises(m.OcrError): m._url(url, m.UPLOAD_HOSTS)

    def status(self, state, api='agent', extra=None):
        r=self.submit(api)
        data=dict(state=state, **(extra or {}))
        if api == 'precise': data={'extract_result':[data]}
        self.request.reset_mock()
        self.request.side_effect=[json.dumps({'code':0,'data':data}).encode()]
        return m.run({'action':'status','job_id':r['job_id']})

    def test_pending_single_get(self):
        for state in ('waiting-file','pending','running','converting','uploading'):
            r=self.status(state)
            self.assertTrue(r['ok']); self.assertEqual(r['status'],state)
            self.assertEqual(self.request.call_count,1)

    def test_failed_and_unknown_state(self):
        r=self.status('failed',extra={'err_code':-30003,'err_msg':'SECRET'})
        self.assertEqual(r['provider_code'],-30003); self.assertNotIn('SECRET',json.dumps(r))
        self.assertFalse(self.status('evil state')['ok'])

    def test_done_markdown_hash(self):
        r=self.submit('agent'); self.request.side_effect=[b'{"code":0,"data":{"state":"done","markdown_url":"https://cdn-mineru.openxlab.org.cn/a?signature=PRIVATE"}}',b'# hello']
        r=m.run({'action':'status','job_id':r['job_id']})
        self.assertTrue(r['ok']); self.assertEqual(r['confidence'],'unknown')
        a=r['artifacts'][0]; self.assertEqual(Path(a['path']).read_bytes(),b'# hello')
        self.assertEqual(a['sha256'],m.hashlib.sha256(b'# hello').hexdigest())
        self.assertNotIn('PRIVATE',json.dumps(r)); self.assertNotIn('headers',self.request.call_args.kwargs)

    def test_zip_safe_and_unsafe(self):
        for name,success in [('full.md',True),('../evil.md',False),('C:/evil.md',False),('CON.md',False),('foo\\evil.md',False)]:
            b=io.BytesIO()
            with zipfile.ZipFile(b,'w') as z:z.writestr(name,'hello')
            archive_bytes = b.getvalue()
            if '\\' in name:
                archive_bytes = archive_bytes.replace(name.replace('\\', '/').encode(), name.encode())
            self.request.side_effect=None; self.request.return_value=archive_bytes
            if success:
                self.assertTrue(m._results({'full_zip_url':'https://cdn-mineru.openxlab.org.cn/a'},'precise', 'abc'))
            else:
                with self.subTest(name=name):
                    with self.assertRaises(m.OcrError):m._results({'full_zip_url':'https://cdn-mineru.openxlab.org.cn/a'},'precise','abc')

    def test_redirect_refused(self):
        with self.assertRaises(m.OcrError):m._NoRedirect().redirect_request(None,None,302,'',{},'https://evil')

    def test_http_error_sanitized_transport(self):
        self.net.stop()
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=urllib.error.HTTPError('https://PRIVATE',403,'SECRET',{},None)
            with self.assertRaises(m.OcrError) as error:m._request('GET',m.API)
            self.assertEqual(error.exception.details,{'http_status':403})
            self.assertNotIn('SECRET',str(error.exception))
        self.net.start()


if __name__ == '__main__':
    unittest.main()
