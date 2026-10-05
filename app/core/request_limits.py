# SPDX-License-Identifier: AGPL-3.0-only
from starlette.responses import JSONResponse

class RequestSizeLimit:
    """Bound request bodies before JSON decoding, including streamed bodies."""
    def __init__(self, app, max_bytes=262144):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        lengths = [value for name, value in scope['headers'] if name.lower() == b'content-length']
        if lengths:
            try:
                if len(lengths) != 1 or not lengths[0].isdigit():
                    raise ValueError()
                length = int(lengths[0])
            except ValueError:
                return await JSONResponse({'detail': 'Invalid Content-Length'}, status_code=400)(scope, receive, send)
            if length > self.max_bytes:
                return await JSONResponse({'detail': 'Request body too large'}, status_code=413)(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            if message['type'] != 'http.request':
                continue
            chunk = message.get('body', b'')
            if len(body) + len(chunk) > self.max_bytes:
                return await JSONResponse({'detail': 'Request body too large'}, status_code=413)(scope, receive, send)
            body.extend(chunk)
            if not message.get('more_body', False):
                break
        replayed = False
        async def replay():
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
        await self.app(scope, replay, send)
