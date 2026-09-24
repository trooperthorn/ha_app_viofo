import asyncio
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "viofo_workbench"))
from aiohttp import web, FormData
from aiohttp.test_utils import TestClient, TestServer
from app.core import State, local_address
from app.camera import recording_time, within_dates, CameraClient, parse_listing, remote_path, states, settings_for
from app.server import create_app, execute_job
from app import media


class ProtocolTests(unittest.TestCase):
    def test_recording_dates(self):
        self.assertEqual(recording_time('2025_0621_192620_001F.MP4'), '2025-06-21T19:26:20')
        self.assertEqual(recording_time('recording (3).mp4'), '')
        self.assertEqual(recording_time('unknown.mp4','2025/06/21 19:26:20'), '2025-06-21T19:26:20')
        self.assertTrue(within_dates({'name':'2025_0621_192620_F.MP4'},'2025-06-21','2025-06-21'))
        self.assertFalse(within_dates({'name':'2025_0622_192620_F.MP4'},'2025-06-21','2025-06-21'))
        with self.assertRaises(ValueError):
            within_dates({'name':'unknown'},'2025-06-22','2025-06-21')

    def test_embedded_sensor_rows(self):
        points = media.parse_accelerometer('0,0.1 0.2 0.3\n1,0.2 -1 0\n2,nan 0 0\nnot a sample\n-1,0 0 1')
        self.assertEqual(len(points),2)
        self.assertEqual(points[1]['y'],-1)

    def test_private_camera_addresses_only(self):
        self.assertEqual(local_address("192.168.1.10"), "http://192.168.1.10")
        for bad in ("127.0.0.1", "http://example.com", "http://192.168.1.1@evil.com", "http://192.168.1.1/secret", "169.254.169.254", "8.8.8.8", "http://user:pass@192.168.1.1"):
            with self.assertRaises(ValueError): local_address(bad)

    def test_file_paths_and_xml(self):
        for bad in ("/DCIM/../secrets.MP4", "/DCIM/%2e%2e/secrets.MP4", "http://evil/DCIM/a.MP4", "/etc/passwd", "/DCIM/a.MP4?cmd=3010"):
            with self.assertRaises(ValueError): remote_path(bad)
        xml = '<LIST><File><FPATH>A:\\DCIM\\Movie\\RO\\a.MP4</FPATH><SIZE>123</SIZE><ATTR>33</ATTR></File></LIST>'
        self.assertEqual(parse_listing(xml)[0]["category"], "locked")
        with self.assertRaises(ValueError): parse_listing('<!DOCTYPE x><LIST/>')

    def test_current_state_and_ambiguous_options(self):
        data = states('<Cmd>2001</Cmd><Status>1</Status><Cmd>2007</Cmd><Status>0</Status>')
        self.assertEqual(data[2001], 1)
        settings = settings_for("A119 Mini 2", "F", data)
        audio = next(s for s in settings if s["command"] == 2007)
        self.assertTrue(audio["ambiguous"])
        self.assertFalse(audio["writable"])

    def test_gps_synthetic_atom(self):
        # Known synthetic N/E fix validates binary offsets, not real camera compatibility.
        payload = struct.pack('<IIIIII', 12, 30, 0, 26, 9, 24) + b'ANE\0' + struct.pack('<ffff', 4000.0, 7500.0, 10.0, 90.0)
        atom = struct.pack('>I4s4s', len(payload)+12, b'free', b'GPS ') + payload
        table = struct.pack('>I4s', 24, b'gps ') + b'\0'*8 + struct.pack('>II', 0, len(atom))
        moov = struct.pack('>I4s', len(table)+8, b'moov') + table
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'test.mp4'; path.write_bytes(atom+moov)
            track = media.gps(path)
            self.assertEqual(len(track['points']),1)
            self.assertAlmostEqual(track['points'][0]['lat'],40)
            self.assertAlmostEqual(track['points'][0]['speed_kmh'],18.519984)
            self.assertIn(b'trkpt',media.gpx(track))
            path.write_bytes(b'\0\0\0\x01moov'+b'\xff'*8)
            self.assertEqual(media.gps(path)['points'],[])


class WebTests(unittest.IsolatedAsyncioTestCase):
    async def test_original_name_and_bulk_pause(self):
        from urllib.parse import unquote
        path=self.state.storage/'recordings'/'internal.mp4';path.write_bytes(b'original')
        name='2025_0621_192620_001F.MP4'
        cid=self.state.register(path,'a229pro',name)
        response=await self.client.get(f'/api/clips/{cid}/download')
        self.assertIn(name,unquote(response.headers['Content-Disposition']))
        self.assertEqual(await response.read(),b'original')
        jid=self.state.add_job('download',{'camera':'a229pro','record':{'name':name}})
        response=await self.client.post('/api/downloads/pause',json={},headers={'X-Viofo-Request':'1'})
        self.assertEqual(response.status,200)
        self.assertEqual(self.state.job(jid)['state'],'paused')
        self.assertFalse(self.state.camera('a229pro')['auto_sync'])

    async def test_live_failure_preserves_error_and_releases_slot(self):
        self.state.camera('a229pro')['address'] = 'http://192.168.1.20'
        class Process:
            returncode = 1
            stdout = asyncio.StreamReader()
            stderr = asyncio.StreamReader()
            wait = AsyncMock(return_value=1)
        proc = Process()
        proc.stdout.feed_eof()
        proc.stderr.feed_data(b'Cannot open rtsp://192.168.1.20/: unsupported transport\n')
        proc.stderr.feed_eof()
        with patch('app.server.asyncio.create_subprocess_exec', AsyncMock(return_value=proc)) as spawn:
            response = await self.client.get('/api/live/a229pro')
            self.assertEqual(response.status, 400)
            self.assertIn('failed to start', (await response.json())['error'])
            self.assertIn('-timeout', spawn.call_args.args)
            self.assertNotIn('-rw_timeout', spawn.call_args.args)
        self.assertEqual(self.client.app['live_count'], 0)
        response = await self.client.get('/api/diagnostics')
        with zipfile.ZipFile(io.BytesIO(await response.read())) as bundle:
            logs = bundle.read('debug.log').decode()
        self.assertIn('unsupported transport', logs)
        self.assertNotIn('192.168.1.20', logs)

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = State(self.temp.name)
        self.client = TestClient(TestServer(create_app(self.state,background=False)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.state.close()
        self.temp.cleanup()

    async def post(self,path,body):
        return await self.client.post(path,json=body,headers={'X-Viofo-Request':'1'})

    async def test_status_and_csrf(self):
        r=await self.client.get('/api/status'); self.assertEqual(r.status,200)
        self.assertEqual(len((await r.json())['cameras']),2)
        r=await self.client.post('/api/exports',json={});self.assertEqual(r.status,403)
        r=await self.client.get('/');self.assertEqual(r.status,200)
        self.assertIn('VIOFO Workbench',await r.text())

    async def test_export_filename_cannot_inject_headers(self):
        r=await self.post('/api/exports',{'filename':'bad\r\nHeader: value/../../secret.mp4','segments':[]})
        jid=(await r.json())['job']
        filename=json.loads(self.state.job(jid)['payload'])['filename']
        self.assertNotIn('\r',filename);self.assertNotIn('\n',filename);self.assertNotIn('/',filename)

    async def test_ingress_rejects_direct_and_spoofed_requests(self):
        with patch.dict(os.environ,{'VIOFO_HA':'1'}):
            r=await self.client.get('/api/status',headers={'X-Forwarded-For':'172.30.32.2'})
            self.assertEqual(r.status,403)

    async def test_token_api(self):
        self.state.options['api_token']='secret-test-token'
        client=TestClient(TestServer(create_app(self.state,integration=True,background=False)))
        await client.start_server()
        try:
            r=await client.get('/api/status');self.assertEqual(r.status,401)
            r=await client.get('/api/status',headers={'Authorization':'Bearer secret-test-token'});self.assertEqual(r.status,200)
            self.assertNotIn('secret-test-token',await r.text())
        finally:await client.close()

    async def test_diagnostics_redaction(self):
        self.state.options['api_token']='super-secret-token'
        self.state.log.debug('token=super-secret-token camera=192.168.1.20 password=abc')
        r=await self.client.get('/api/diagnostics')
        z=zipfile.ZipFile(io.BytesIO(await r.read()))
        content=b' '.join(z.read(n) for n in z.namelist())
        for secret in (b'super-secret-token',b'192.168.1.20',b'password=abc'):
            self.assertNotIn(secret,content)

    async def test_job_control_and_persistence(self):
        jid=self.state.add_job('snapshot',{'clip':'none','seconds':0})
        self.assertEqual(jid,self.state.add_job('snapshot',{'clip':'none','seconds':0}))
        await self.post('/api/jobs/'+jid,{'action':'pause'})
        self.assertEqual(self.state.job(jid)['state'],'paused')
        await self.post('/api/jobs/'+jid,{'action':'retry'})
        self.assertEqual(self.state.job(jid)['state'],'queued')

    async def test_protected_delete_and_range(self):
        path=self.state.storage/'recordings'/'a.mp4';path.write_bytes(b'0123456789')
        cid=self.state.register(path,'mini2','a_F.mp4',category='locked')
        r=await self.post(f'/api/clips/{cid}/delete',{'confirm':cid});self.assertEqual(r.status,400)
        self.assertTrue(path.exists())
        r=await self.client.get(f'/api/clips/{cid}/media',headers={'Range':'bytes=2-4'})
        self.assertEqual(r.status,206);self.assertEqual(await r.read(),b'234')
        r=await self.client.get(f'/api/clips/{cid}/delete');self.assertEqual(r.status,405)

    async def test_settings_write_requires_readback(self):
        c=self.state.camera('mini2');c.update(address='http://192.168.1.10',writes=True)
        client=self.client.app['camera']
        client.request=AsyncMock(side_effect=['<Cmd>2001</Cmd><Status>0</Status>','<Cmd>2001</Cmd><Status>0</Status>','<Cmd>2001</Cmd><Status>1</Status>'])
        self.assertTrue((await client.write('mini2',2001,1))['verified'])
        c['writes']=False
        with self.assertRaises(ValueError):await client.write('mini2',2001,0)

    async def test_truncated_download_is_not_committed(self):
        async def camera(request):
            if request.method=='HEAD':return web.Response(headers={'Content-Length':'10'})
            return web.Response(body=b'123')
        app=web.Application();app.router.add_route('*','/DCIM/Movie/a.MP4',camera)
        cam=TestServer(app);await cam.start_server()
        self.state.camera('mini2')['address']=str(cam.make_url('')).rstrip('/')
        target=Path(self.temp.name)/'a.part'
        try:
            with self.assertRaises(ValueError):
                await self.client.app['camera'].download('mini2',{'path':'/DCIM/Movie/a.MP4'},target,AsyncMock())
        finally:await cam.close()


@unittest.skipUnless(__import__('shutil').which(media.FFMPEG) and __import__('shutil').which(media.FFPROBE),'FFmpeg and ffprobe required')
class MediaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.state=State(self.temp.name)
        self.source=self.state.storage/'recordings'/'sample.mp4'
        await media.process([media.FFMPEG,'-v','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=30:duration=2','-f','lavfi','-i','sine=frequency=440:duration=2','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(self.source)])
        self.cid=self.state.register(self.source,'a229pro','2026_0924_120000_F.MP4',metadata=await media.probe(self.source))

    async def asyncTearDown(self):
        self.state.close();self.temp.cleanup()

    async def test_snapshot_and_multisegment_export_with_title(self):
        target=self.state.storage/'exports'/'frame.jpg'
        await media.screenshot(self.source,target,.5);self.assertGreater(target.stat().st_size,100)
        payload={'segments':[{'clips':[self.cid],'start':0,'end':.5},{'clips':[self.cid],'start':1,'end':1.5}],'height':720,'layout':'single','title':'Test title 100%'}
        jid=self.state.add_job('export',payload)
        result=await media.render_export(self.state,self.state.job(jid),AsyncMock())
        info=await media.probe(self.state.storage/'exports'/result)
        self.assertAlmostEqual(info['duration'],4,delta=.2)
        self.assertTrue(self.source.exists())

    async def test_three_camera_grid(self):
        payload={'segments':[{'clips':[self.cid]*3,'start':0,'end':.5}],'height':720,'layout':'grid'}
        jid=self.state.add_job('export',payload)
        result=await media.render_export(self.state,self.state.job(jid),AsyncMock())
        info=await media.probe(self.state.storage/'exports'/result)
        video=next(s for s in info['streams'] if s['codec_type']=='video')
        self.assertEqual((video['width'],video['height']),(1280,720))

    async def test_invalid_export_preserves_original(self):
        jid=self.state.add_job('export',{'segments':[{'clips':[self.cid],'start':0,'end':50}]})
        with self.assertRaises(ValueError):await media.render_export(self.state,self.state.job(jid),AsyncMock())
        self.assertTrue(self.source.exists())
        self.assertFalse((self.state.storage/'exports'/(jid+'.mp4')).exists())


if __name__=='__main__':unittest.main()
