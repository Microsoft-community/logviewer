import os
from functools import wraps
from urllib.parse import urlencode, urlparse

from motor.motor_asyncio import AsyncIOMotorClient
from sanic import Sanic, response
from sanic.exceptions import abort, NotFound, Unauthorized
from sanic_session import Session, InMemorySessionInterface
from jinja2 import Environment, PackageLoader

import aiohttp

from core.models import LogEntry
from core.utils import get_stack_variable, authrequired, User

OAUTH2_CLIENT_ID = os.getenv("OAUTH2_CLIENT_ID")
OAUTH2_CLIENT_SECRET = os.getenv("OAUTH2_CLIENT_SECRET")
OAUTH2_REDIRECT_URI = os.getenv("OAUTH2_REDIRECT_URI")

API_BASE = "https://discordapp.com/api/"
AUTHORIZATION_BASE_URL = API_BASE + "/oauth2/authorize"
TOKEN_URL = API_BASE + "/oauth2/token"
ROLE_URL = API_BASE + "/guilds/{guild_id}/members/{user_id}"

prefix = os.getenv("URL_PREFIX", "/logs")
if prefix == "NONE":
    prefix = ""

app = Sanic(__name__)
app.using_oauth = OAUTH2_CLIENT_ID and OAUTH2_CLIENT_SECRET
app.bot_id = OAUTH2_CLIENT_ID

Session(app, interface=InMemorySessionInterface())
app.static("/static", "./static")

jinja_env = Environment(loader=PackageLoader("app", "templates"))


def render_template(name, *args, **kwargs):
    template = jinja_env.get_template(name + ".html")
    request = get_stack_variable("request")
    if request:
        kwargs["request"] = request
        kwargs["session"] = request["session"]
        kwargs["user"] = request["session"].get("user")
    kwargs.update(globals())
    return response.html(template.render(*args, **kwargs))


app.render_template = render_template


@app.listener("before_server_start")
async def init(app, loop):
    app.db = AsyncIOMotorClient(os.getenv("MONGO_URI")).modmail_bot
    app.session = aiohttp.ClientSession(loop=loop)
    if app.using_oauth:
        app.guild_id = os.getenv("GUILD_ID")
        app.bot_token = os.getenv("TOKEN")
        app.netloc = urlparse(OAUTH2_REDIRECT_URI).netloc
        print("USING OAUTH2 MODE")


async def fetch_token(code):
    data = {
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": OAUTH2_REDIRECT_URI,
        "client_id": OAUTH2_CLIENT_ID,
        "client_secret": OAUTH2_CLIENT_SECRET,
        "scope": "identify",
    }

    headers = {"Content-Type": "x-www-form-urlencoded"}

    async with app.session.post(TOKEN_URL, data=data) as resp:
        json = await resp.json()
        return json


async def get_user_info(token):
    headers = {"Authorization": f"Bearer {token}"}
    async with app.session.get(f"{API_BASE}/users/@me", headers=headers) as resp:
        return await resp.json()


async def get_user_roles(user_id):
    url = ROLE_URL.format(guild_id=app.guild_id, user_id=user_id)
    headers = {"Authorization": f"Bot {app.bot_token}"}
    async with app.session.get(url, headers=headers) as resp:
        user = await resp.json()
    return user.get("roles", [])


app.get_user_roles = get_user_roles


@app.exception(NotFound)
async def not_found(request, exc):
    return render_template("not_found")


@app.exception(Unauthorized)
async def not_authorized(request, exc):
    return render_template(
        "unauthorized", message="You do not have permission to view this page."
    )


@app.get("/")
async def index(request):
    return render_template("index")


@app.get("/login")
async def login(request):
    if not request["session"].get("from"):
        referer = request.headers.get("referer", "/")
        if referer != "/" and urlparse(referer).netloc != app.netloc:
            referer = "/"  # dont redirect to a different site
        request["session"]["from"] = referer

    data = {
        "scope": "identify",
        "client_id": OAUTH2_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": OAUTH2_REDIRECT_URI,
        "prompt": "none"
    }

    return response.redirect(f"{AUTHORIZATION_BASE_URL}?{urlencode(data)}")


@app.get("/callback")
async def oauth_callback(request):
    if request.args.get("error"):
        return response.redirect("/login")

    code = request.args.get("code")
    token = await fetch_token(code)
    access_token = token.get("access_token")
    if access_token is not None:
        request["session"]["access_token"] = access_token
        request["session"]["logged_in"] = True
        request["session"]["user"] = User(await get_user_info(access_token))
        url = "/"
        if "from" in request["session"]:
            url = request["session"]["from"]
            del request["session"]["from"]
        return response.redirect(url)
    return response.redirect("/login")


@app.get("/logout")
async def logout(request):
    request["session"].clear()
    return response.redirect("/")


@app.get(prefix + "/raw/<key>")
@authrequired()
async def get_raw_logs_file(request, document):
    """Returns the plain text rendered log entry"""

    if document is None:
        abort(404)

    log_entry = LogEntry(app, document)

    return log_entry.render_plain_text()


@app.get(prefix + "/<key>")
@authrequired()
async def get_logs_file(request, document):
    """Returns the html rendered log entry"""

    if document is None:
        abort(404)

    log_entry = LogEntry(app, document)

    return log_entry.render_html()


if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "0.0.0.0"),
        port=os.getenv("PORT", 8000),
        debug=bool(os.getenv("DEBUG", False)),
    )
