"""
Copyright (c) 2004, CherryPy Team (team@cherrypy.org)
All rights reserved.

Redistribution and use in source and binary forms, with or without modification, 
are permitted provided that the following conditions are met:

    * Redistributions of source code must retain the above copyright notice, 
      this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright notice, 
      this list of conditions and the following disclaimer in the documentation 
      and/or other materials provided with the distribution.
    * Neither the name of the CherryPy Team nor the names of its contributors 
      may be used to endorse or promote products derived from this software 
      without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND 
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED 
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE 
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE 
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL 
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR 
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER 
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, 
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE 
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

"""Extensions to unittest for web frameworks.

Use the WebCase.getPage method to request a page from your HTTP server.

Framework Integration
=====================

If you have control over your server process, you can handle errors
in the server-side of the HTTP conversation a bit better. You must run
both the client (your WebCase tests) and the server in the same process
(but in separate threads, obviously).

When an error occurs in the framework, call server_error. It will print
the traceback to stdout, and keep any assertions you have from running
(the assumption is that, if the server errors, the page output won't be
of further significance to your tests).
"""

import os, sys, time
import types
import socket
import httplib
import traceback

from unittest import *
from unittest import _TextTestResult


class TerseTestResult(_TextTestResult):
    
    def printErrors(self):
        # Overridden to avoid unnecessary empty line
        if self.errors or self.failures:
            if self.dots or self.showAll:
                self.stream.writeln()
            self.printErrorList('ERROR', self.errors)
            self.printErrorList('FAIL', self.failures)


class TerseTestRunner(TextTestRunner):
    """A test runner class that displays results in textual form."""
    
    def _makeResult(self):
        return TerseTestResult(self.stream, self.descriptions, self.verbosity)
    
    def run(self, test):
        "Run the given test case or test suite."
        # Overridden to remove unnecessary empty lines and separators
        result = self._makeResult()
        startTime = time.time()
        test(result)
        timeTaken = float(time.time() - startTime)
        result.printErrors()
        if not result.wasSuccessful():
            self.stream.write("FAILED (")
            failed, errored = map(len, (result.failures, result.errors))
            if failed:
                self.stream.write("failures=%d" % failed)
            if errored:
                if failed: self.stream.write(", ")
                self.stream.write("errors=%d" % errored)
            self.stream.writeln(")")
        return result


class ReloadingTestLoader(TestLoader):
    
    def loadTestsFromName(self, name, module=None):
        """Return a suite of all tests cases given a string specifier.

        The name may resolve either to a module, a test case class, a
        test method within a test case class, or a callable object which
        returns a TestCase or TestSuite instance.

        The method optionally resolves the names relative to a given module.
        """
        parts = name.split('.')
        if module is None:
            if not parts:
                raise ValueError, "incomplete test name: %s" % name
            else:
                parts_copy = parts[:]
                while parts_copy:
                    target = ".".join(parts_copy)
                    if target in sys.modules:
                        module = reload(sys.modules[target])
                        break
                    else:
                        try:
                            module = __import__(target)
                            break
                        except ImportError:
                            del parts_copy[-1]
                            if not parts_copy: raise
                parts = parts[1:]
        obj = module
        for part in parts:
            obj = getattr(obj, part)
        
        if type(obj) == types.ModuleType:
            return self.loadTestsFromModule(obj)
        elif (isinstance(obj, (type, types.ClassType)) and
              issubclass(obj, TestCase)):
            return self.loadTestsFromTestCase(obj)
        elif type(obj) == types.UnboundMethodType:
            return obj.im_class(obj.__name__)
        elif callable(obj):
            test = obj()
            if not isinstance(test, TestCase) and \
               not isinstance(test, TestSuite):
                raise ValueError, \
                      "calling %s returned %s, not a test" % (obj,test)
            return test
        else:
            raise ValueError, "don't know how to make test from: %s" % obj


class WebCase(TestCase):
    
    HOST = "127.0.0.1"
    PORT = 8000
    
    def getPage(self, url, headers=None, method="GET", body=None):
        ServerError.on = False
        
        result = openURL(url, headers, method, body, self.HOST, self.PORT)
        self.status, self.headers, self.body = result
        
        if ServerError.on:
            raise ServerError
        return result
    
    def assertStatus(self, status, msg=None):
        """Fail if self.status != status."""
        if not self.status == status:
            raise self.failureException, \
                  (msg or 'Status (%s) != %s' % (`self.status`, `status`))
    
    def assertHeader(self, key, value=None, msg=None):
        """Fail if (key, [value]) not in self.headers."""
        lowkey = key.lower()
        for k, v in self.headers:
            if k.lower() == lowkey:
                if value is None or value == v:
                    return
        
        if value is None:
            raise self.failureException, msg or '%s not in headers' % `key`
        else:
            raise self.failureException, \
                  (msg or '%s:%s not in headers' % (`key`, `value`))
    
    def assertBody(self, value, msg=None):
        """Fail if value != self.body."""
        if value != self.body:
            if msg is None:
                msg = 'expected body:\n%s\n\nactual body:\n%s' % (`value`, `self.body`)
            raise self.failureException, msg
    
    def assertInBody(self, value, msg=None):
        """Fail if value not in self.body."""
        if value not in self.body:
            raise self.failureException, msg or '%s not in body' % `value`
    
    def assertNotInBody(self, value, msg=None):
        """Fail if value in self.body."""
        if value in self.body:
            raise self.failureException, msg or '%s found in body' % `value`



def cleanHeaders(headers, method, body):
    if headers is None:
        headers = []
    
    if method in ("POST", "PUT"):
        # Stick in default type and length headers if not present
        found = False
        for k, v in headers:
            if k.lower() == 'content-type':
                found = True
                break
        if not found:
            headers.append(("Content-Type", "application/x-www-form-urlencoded"))
            headers.append(("Content-Length", str(len(body or ""))))
    
    return headers


def openURL(url, headers=None, method="GET", body=None,
            host="127.0.0.1", port=8000):
    
    headers = cleanHeaders(headers, method, body)
    
    # Trying 10 times is simply in case of socket errors.
    # Normal case--it should run once.
    trial = 0
    while trial < 10:
        try:
            conn = httplib.HTTPConnection('%s:%s' % (host, port))
            conn.putrequest(method.upper(), url)
            
            for key, value in headers:
                conn.putheader(key, value)
            conn.endheaders()
            
            if body is not None:
                conn.send(body)
            
            # Handle response
            response = conn.getresponse()
            
            status = "%s %s" % (response.status, response.reason)
            
            outheaders = []
            for line in response.msg.headers:
                key, value = line.split(":", 1)
                outheaders.append((key.strip(), value.strip()))
            
            outbody = response.read()
            
            conn.close()
            return status, outheaders, outbody
        except socket.error:
            trial += 1
            if trial >= 10:
                raise
            else:
                time.sleep(0.5)


# Add any exceptions which your web framework handles
# normally (that you don't want server_error to trap).
ignored_exceptions = []

# You'll want set this to True when you can't guarantee
# that each response will immediately follow each request;
# for example, when handling requests via multiple threads.
ignore_all = False

class ServerError(Exception):
    on = False


def server_error(exc=None):
    """server_error(exc=None) -> True if exception handled, False if ignored.
    
    You probably want to wrap this, so you can still handle an error using
    your framework when it's ignored.
    """
    if exc is None: 
        exc = sys.exc_info()
    
    if ignore_all or exc[0] in ignored_exceptions:
        return False
    else:
        ServerError.on = True
        print
        print "".join(traceback.format_exception(*exc))
        return True
