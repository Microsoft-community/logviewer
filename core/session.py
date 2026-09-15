import time
import uuid
from datetime import datetime, timezone


class SessionDict(dict):
    def __init__(self, initial=None, sid=None):
        super().__init__(initial or {})
        self.sid = sid
        self.modified = False

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.modified = True

    def __delitem__(self, key):
        super().__delitem__(key)
        self.modified = True

    def clear(self):
        super().clear()
        self.modified = True

    def pop(self, *args, **kwargs):
        result = super().pop(*args, **kwargs)
        self.modified = True
        return result

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self.modified = True

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]


class InMemorySessionInterface:
    def __init__(
        self,
        expiry=2592000,
        httponly=True,
        cookie_name="session",
        prefix="session:",
        session_name="session",
        samesite=None,
        secure=False,
        domain=None,
        sessioncookie=False,
    ):
        self.expiry = expiry
        self.httponly = httponly
        self.cookie_name = cookie_name
        self.prefix = prefix
        self.session_name = session_name
        self.samesite = samesite
        self.secure = secure
        self.domain = domain
        self.sessioncookie = sessioncookie
        self.session_store = {}

    def _purge_expired(self):
        now = time.time()
        expired = [
            key
            for key, (_, expires) in self.session_store.items()
            if expires < now
        ]
        for key in expired:
            del self.session_store[key]

    async def open(self, request):
        self._purge_expired()
        sid = request.cookies.get(self.cookie_name)
        key = self.prefix + sid if sid else None
        if key and key in self.session_store:
            data, _ = self.session_store[key]
            session = SessionDict(data, sid=sid)
        else:
            session = SessionDict(sid=sid or uuid.uuid4().hex)
        setattr(request.ctx, self.session_name, session)

    async def save(self, request, response):
        session = getattr(request.ctx, self.session_name, None)
        if session is None:
            return

        key = self.prefix + session.sid
        if not session:
            self.session_store.pop(key, None)
            if session.modified:
                response.add_cookie(
                    self.cookie_name,
                    "",
                    path="/",
                    domain=self.domain,
                    expires=datetime.fromtimestamp(0, tz=timezone.utc),
                    max_age=0,
                    httponly=self.httponly,
                    samesite=self.samesite,
                    secure=self.secure,
                )
            return

        self.session_store[key] = (dict(session), time.time() + self.expiry)

        max_age = None if self.sessioncookie else self.expiry
        expires = (
            None
            if self.sessioncookie
            else datetime.fromtimestamp(time.time() + self.expiry, tz=timezone.utc)
        )
        response.add_cookie(
            self.cookie_name,
            session.sid,
            path="/",
            domain=self.domain,
            expires=expires,
            max_age=max_age,
            httponly=self.httponly,
            samesite=self.samesite,
            secure=self.secure,
        )


class Session:
    def __init__(self, app=None, interface=None):
        self.interface = interface or InMemorySessionInterface()
        if app:
            self.init_app(app)

    def init_app(self, app):
        app.on_request(self.interface.open)
        app.on_response(self.interface.save)
