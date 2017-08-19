from __future__ import unicode_literals

import os
import time
import psutil
import requests
import tornado.gen
from threading import Thread, Lock
from subprocess import Popen, PIPE, STDOUT
from six.moves.urllib.parse import urlencode, urljoin
from tornado.web import HTTPError
from tornado.httpclient import AsyncHTTPClient
from gramex.config import app_log, variables
from gramex.http import OK, GATEWAY_TIMEOUT, BAD_GATEWAY, CLIENT_TIMEOUT
from .basehandler import BaseHandler


class Capture(object):
    default_port = 9900         # Default port to run CaptureJS at
    check_interval = 0.05       # Frequency (seconds) to check if self.started

    '''
    Create a proxy for capture.js. Typical usage::

        capture = Capture()
        with open('screenshot.png', 'wb') as handle:
            handle.write(capture.png('https://gramener.com/'))
        with open('screenshot.pdf', 'wb') as handle:
            handle.write(capture.pdf('https://gramener.com/'))

    The constructor accepts these optional parameters:

    :arg int port: port where capture.js is running. Default: 9900
    :arg string url: URL:port where PhantomJS is running with capture.js.
        Default: ``http://localhost:<port>/``
    :arg string cmd: Command to run PhantomJS with capture.js at the specified
        port. Default: ``phantomjs $GRAMEXPATH/apps/capture/capture.js --port=<port>``
    :arg int timeout: Seconds to wait for PhantomJS to timeout. Default: 10

    The constructor runs :meth:`Capture.start` in a new thread, which checks if
    capture.js is running at ``url``. If not, it runs ``cmd`` and checks again.
    Until capture.js is detected, all capture methods will fail.
    '''
    def __init__(self, port=None, url=None, cmd=None, timeout=10):
        # Set default values for port, url and cmd
        port = self.default_port if port is None else port
        if url is None:
            url = 'http://localhost:%d/' % port
            if cmd is None:
                cmd = 'phantomjs --ssl-protocol=any %s --port=%d' % (
                    os.path.join(variables.GRAMEXPATH, 'apps', 'capture', 'capture.js'), port)
        self.url = url
        self.cmd = cmd
        self.timeout = timeout
        self.browser = AsyncHTTPClient()
        self.lock = Lock()
        self.start()

    def start(self):
        '''
        Starts a thread and check if PhantomJS is already running at ``url``. If
        not, start ``cmd`` and check again. Print logs from ``cmd``.

        This method is thread-safe. It may be called as often as required.
        :class:`CaptureHandler` calls this method if ``?start`` is passed.
        '''
        with self.lock:
            thread = Thread(target=self._start)
            thread.daemon = True
            thread.start()

    def _start(self):
        '''
        Check if PhantomJS is already running at ``url``. If not, start ``cmd``
        and check again. Print logs from ``cmd``.
        '''
        self.started = False
        try:
            # Check if capture.js is at the url specified
            app_log.info('Pinging capture.js at %s', self.url)
            r = requests.get(self.url, timeout=self.timeout)
            self._validate_server(r)
            self.started = True
        except requests.ReadTimeout:
            # If capture.js doesn't respond immediately, we haven't started
            app_log.error('url: %s timed out', self.url)
        except requests.ConnectionError:
            # Try starting the process again
            app_log.info('Starting capture.js via %s', self.cmd)
            self.close()
            self.proc = Popen(self.cmd, shell=True, stdout=PIPE, stderr=STDOUT)
            self.proc.poll()
            # TODO: what if readline() does not return quickly?
            line = self.proc.stdout.readline().strip()
            if b'PhantomJS' not in line or b'capture.js' not in line:
                return app_log.error('cmd: %s invalid. Returned "%s"', self.cmd, line)
            app_log.info('Pinging capture.js at %s', self.url)
            try:
                r = requests.get(self.url, timeout=self.timeout)
                self._validate_server(r)
                pid = self.proc.pid
                app_log.info('capture.js live at %s (pid=%d)', self.url, pid)
                self.started = True
                # Keep logging capture.js output until proc ends
                while True:
                    line = self.proc.stdout.readline().strip()
                    if len(line) == 0:
                        app_log.info('capture.js terminated: pid=%d', pid)
                        self.started = False
                        break
                    app_log.info(line.decode('utf-8'))
            except Exception:
                app_log.exception('Ran %s. But capture.js not at %s', self.cmd, self.url)

    def close(self):
        '''Stop capture.js if it has been started by this object'''
        if hasattr(self, 'proc'):
            process = psutil.Process(self.proc.pid)
            for proc in process.children(recursive=True):
                proc.kill()
            process.kill()
            delattr(self, 'proc')

    def _validate_server(self, response):
        # Make sure that the response we got is from capture.js
        server = response.headers.get('Server', '')
        if not server.startswith('Capture/') or server < 'Capture/1.':
            raise RuntimeError('Server: %s at %s is not capture.js' % (server, self.url))

    @tornado.gen.coroutine
    def capture_async(self, **kwargs):
        '''
        '''
        # If ?start is provided, start server and wait until timeout
        if 'start' in kwargs:
            self.start()
            end_time = time.time() + self.timeout
            while not self.started and time.time() < end_time:
                yield tornado.gen.sleep(self.check_interval)
        if not self.started:
            raise RuntimeError('capture.js not started. See logs')
        r = yield self.browser.fetch(
            self.url, method='POST', body=urlencode(kwargs), raise_error=False,
            connect_timeout=self.timeout, request_timeout=self.timeout)
        if r.code == OK:
            self._validate_server(r)
        raise tornado.gen.Return(r)

    def capture(self, url, **kwargs):
        '''
        Return a screenshot of the URL.

        :arg str url: URL to take a screenshot of
        :arg str ext: format of output. Can be pdf, png, gif or jpg
        :arg str selector: Restrict screenshot to (optional) CSS selector in URL
        :arg int delay: milliseconds to wait for before taking a screenshot
        :arg str format: A3, A4, A5, Legal, Letter or Tabloid. Defaults to A4. For PDF
        :arg str orientation: portrait or landscape. Defaults to portrait. For PDF
        :arg str header: header for the page. For PDF
        :arg str footer: footer for the page. For PDF
        :arg int width: screen width. Default: 1200. For PNG/GIF/JPG
        :arg int height: screen height. Default: 768. For PNG/GIF/JPG
        :arg float scale: zooms the screen by a factor. For PNG/GIF/JPG
        :return: a bytestring with the binary contents of the screenshot
        :rtype: bytes
        :raises RuntimeError: if capture.js is not running or fails
        '''
        # Ensure that we're connecting to the right version of capture.js
        if not self.started:
            end_time = time.time() + self.timeout
            while not self.started and time.time() < end_time:
                time.sleep(self.check_interval)
            if not self.started:
                raise RuntimeError('capture.js not started. See logs')
        kwargs['url'] = url
        r = requests.post(self.url, data=kwargs, timeout=self.timeout)
        if r.status_code == OK:
            self._validate_server(r)
            return r.content
        else:
            raise RuntimeError('capture.js error: %s' % r.content)

    def pdf(self, url, **kwargs):
        '''An alias for :meth:`Capture.capture` with ``ext='pdf'``.'''
        kwargs['ext'] = 'pdf'
        return self.capture(url, **kwargs)

    def png(self, url, **kwargs):
        '''An alias for :meth:`Capture.capture` with ``ext='png'``.'''
        kwargs['ext'] = 'png'
        return self.capture(url, **kwargs)

    def jpg(self, url, **kwargs):
        '''An alias for :meth:`Capture.capture` with ``ext='jpg'``.'''
        kwargs['ext'] = 'jpg'
        return self.capture(url, **kwargs)

    def gif(self, url, **kwargs):
        '''An alias for :meth:`Capture.capture` with ``ext='gif'``.'''
        kwargs['ext'] = 'gif'
        return self.capture(url, **kwargs)


class CaptureHandler(BaseHandler):
    '''
    Renders a web page as a PDF or as an image. It accepts the same arguments as
    :class:`Capture`.

    The page is called with the same args as :meth:`Capture.capture`. It also
    accepts a ``?start`` parameter that restarts capture.js if required.
    '''
    captures = {}

    @classmethod
    def setup(cls, port=None, url=None, cmd=None, **kwargs):
        super(CaptureHandler, cls).setup(**kwargs)
        if cls.name in cls.captures:
            cls.captures[cls.name].close()
        capture_kwargs = {}
        for kwarg in ('timeout', ):
            if kwarg in kwargs:
                capture_kwargs[kwarg] = kwargs.pop(kwarg)
        cls.capture = Capture(port=port, url=url, cmd=cmd, **capture_kwargs)
        cls.captures[cls.name] = cls.capture
        cls.ext = {
            'pdf': dict(mime='application/pdf'),
            'png': dict(mime='image/png'),
            'jpg': dict(mime='image/jpeg'),
            'jpeg': dict(mime='image/jpeg'),
            'gif': dict(mime='image/gif'),
        }

    @tornado.gen.coroutine
    def get(self):
        args = self.argparse(
            url={'default': self.request.headers.get('Referer', None)},
            ext={'choices': self.ext, 'default': 'pdf'},
            file={'default': 'screenshot'},
            selector={},
            delay={'type': int},
            width={'type': int},
            height={'type': int},
            scale={'type': float},
            format={'choices': ['A3', 'A4', 'A5', 'Legal', 'Letter', 'Tabloid'], 'default': 'A4'},
            orientation={'choices': ['portrait', 'landscape'], 'default': 'portrait'},
            start={},
        )
        if args['url'] is None:
            self.write('Missing ?url=')
            raise tornado.gen.Return()

        # If the URL is a relative URL, treat it relative to the called path
        args['url'] = urljoin(self.request.full_url(), args['url'])

        cookie = self.request.headers.get('Cookie', None)
        if cookie is not None:
            args['cookie'] = cookie
        info = self.ext[args.ext]
        try:
            response = yield self.capture.capture_async(**args)
        except RuntimeError as e:
            # capture.js could not fetch the response
            raise HTTPError(BAD_GATEWAY, reason=e.args[0])

        if response.code == OK:
            self.set_header('Content-Type', info['mime'])
            self.set_header('Content-Disposition',
                            'attachment; filename="{file}.{ext}"'.format(**args))
            self.write(response.body)
        elif response.code == CLIENT_TIMEOUT:
            self.set_status(GATEWAY_TIMEOUT, reason='capture.js is busy')
            self.set_header('Content-Type', 'application/json')
            self.write({'status': 'fail', 'msg': [
                'capture.js did not respond within timeout: %ds' % self.capture.timeout]})
        else:
            self.set_status(response.code, reason='capture.js error')
            self.set_header('Content-Type', 'application/json')
            self.write(response.body)