"""Original synthetic integration wire, authored here from API requirements.

No upstream captures or fixtures from another repository are used. This models
only the auth/profile/grade/attendance and modern messaging contracts, not a
live compatibility claim. Routes are test server handlers, never client routes.
"""

import asyncio
import time
from base64 import b64decode, b64encode
from collections import Counter
from contextlib import asynccontextmanager
from html import escape

from aiohttp import web

from tests_native.academic_wire import academic_response
from tests_native.history_wire import formative_table, history_response
from tests_native.legacy_wire import legacy_response


class Wire:
    def __init__(self):
        self.origin = ""
        self.calls = []
        self.dispatch_times = []
        self.logins = Counter()
        self.active = 0
        self.peak = 0
        self.bad_profile = False
        self.unavailable_profile = False
        self.grade_suffix = "3"
        self.message_count = 3
        self.message_queries = []
        self.history_empty = False
        self.formative = False
        self.formative_text = "Fixture formative assessment"
        self.sent_payloads = []
        self.send_unknown = False
        self.attachment_body = b"Fixture attachment bytes\x00"
        self.attachment_location = None
        self.schedule_malformed = False
        self.schedule_disconnect = False
        self.send_started = asyncio.Event()
        self.send_release = asyncio.Event()
        self.send_release.set()
        self.send_rejected = False
        self.send_disconnect = False

    @asynccontextmanager
    async def serve(self):
        app = web.Application()
        app.router.add_route("*", "/{path:.*}", self.respond)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        try:
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            self.origin = f"http://localhost:{runner.addresses[0][1]}"
            yield self
        finally:
            await runner.cleanup()

    async def respond(self, request):
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(0.01)
            return await self._response(request)
        finally:
            self.active -= 1

    async def _response(self, request):
        owner = request.cookies.get("oauth_token") or request.cookies.get("modern-owner")
        self.calls.append((request.method, request.path, owner))
        self.dispatch_times.append(time.monotonic())
        if request.path == "/loguj/portalRodzina":
            raise web.HTTPFound("/OAuth/Authorization?client_id=46")
        if request.path == "/OAuth/Authorization":
            if request.method == "GET":
                response = web.Response(
                    text="<html><form method='post'></form></html>", content_type="text/html"
                )
                response.set_cookie("DeviceCookie", "native-fixture", path="/")
                return response
            form = await request.post()
            assert form["action"] == "login" and form["pass"] == "not-a-real-password"
            assert request.cookies["DeviceCookie"] == "native-fixture"
            login = str(form["login"])
            self.logins[login] += 1
            if login == "denied":
                return web.json_response({"status": "error"})
            response = web.json_response({"status": "ok", "goTo": self.origin + "/loguj"})
            response.set_cookie("auth-grant", login, path="/")
            return response
        if request.path == "/loguj":
            response = web.Response(
                text="<html><body>Fixture session</body></html>", content_type="text/html"
            )
            response.set_cookie("oauth_token", request.cookies["auth-grant"], path="/")
            return response
        if request.path.startswith("/pobierz1/MultiDomainLogon/"):
            encoded = request.path.split("/login/", 1)[1].split("/", 1)[0]
            response = web.HTTPFound("/nowy")
            response.set_cookie(
                "modern-owner", b64decode(encoded + "=" * (-len(encoded) % 4)).decode(), path="/"
            )
            raise response
        if request.path == "/GetFile/fixture-key/get":
            assert not request.cookies and "Authorization" not in request.headers
            return web.Response(body=self.attachment_body, content_type="application/octet-stream")
        if not owner:
            return web.Response(status=401)
        history = history_response(request, self)
        if history is not None:
            return history
        legacy = await legacy_response(request, self)
        if legacy is not None:
            return legacy
        academic = await academic_response(request)
        if academic is not None:
            return academic
        if request.path == "/api/attachments/91/messages/81":
            return web.json_response(
                {
                    "data": {
                        "downloadLink": self.attachment_location
                        or self.origin + "/GetFile/fixture-key"
                    }
                }
            )
        if request.path == "/gateway/api/2.0/Me":
            return web.json_response(
                {
                    "Me": {
                        "Account": {"Id": owner, "FirstName": "Example", "LastName": "Owner"},
                        "User": {"Id": "shared-pupil", "FirstName": "Example", "LastName": "Pupil"},
                    }
                }
            )
        if request.path == "/terminarz/dodane_od_ostatniego_logowania":
            if self.schedule_disconnect:
                request.transport.close()
                return web.Response()
            return web.Response(
                text="<html><p>Malformed checkpoint</p></html>"
                if self.schedule_malformed
                else """<html><div class="container-background"><table>
                <tr><th>Lp.</th><th>Czas dodania</th><th>Rodzaj zdarzenia</th><th>Dane</th></tr>
                <tr><td>1</td><td>2026-09-26 10:00</td><td>Fixture event</td><td>Checkpoint text</td></tr>
                </table></div></html>""",
                content_type="text/html",
            )
        if request.path == "/wiadomosci3":
            encoded = b64encode(owner.encode()).decode().rstrip("=")
            raise web.HTTPFound(
                f"/pobierz1/MultiDomainLogon/token/{'a' * 32}/login/{encoded}/target/L25vd3k/from/c3luZXJnaWE"
            )
        if request.path == "/api/me":
            return web.json_response(
                {
                    "accountId": owner,
                    "groupId": "5",
                    "originSystem": "synergia",
                    "firstName": "Example",
                    "lastName": "Owner",
                }
            )
        if request.path == "/api/messages":
            assert request.method == "POST"
            self.sent_payloads.append(await request.json())
            self.send_started.set()
            await self.send_release.wait()
            if self.send_disconnect:
                request.transport.close()
                return web.Response()
            if self.send_rejected:
                return web.json_response({"code": "DUPLICATED_RECEIVERS"}, status=422)
            return web.json_response(
                {"data": {"messageId": 91, "status": "sent"}}
                if not self.send_unknown
                else {"unrecognized": True},
                status=201,
            )
        if request.path == "/api/receivers/types":
            return web.json_response(
                {"data": {"list": [{"id": "teachers", "name": "Fixture Teachers"}]}}
            )
        if request.path == "/api/receivers/groups/school-employees":
            assert request.query["receiverType"] == "teachers"
            return web.json_response(
                {"receivers": [{"accountId": "41", "userId": "42", "label": "Fixture Teacher"}]}
            )
        if request.path in {"/api/inbox/messages/senders", "/api/outbox/messages/receivers"}:
            role = "sender" if "inbox" in request.path else "receiver"
            return web.json_response(
                {
                    "data": [
                        {
                            f"{role}Id": number,
                            f"{role}FirstName": "Fixture",
                            f"{role}LastName": f"Person {number}",
                        }
                        for number in (501, 502)
                    ]
                }
            )
        if request.path == "/api/receivers/student-subjects":
            return web.json_response(
                {
                    "data": [
                        {"teacherIdentifier": 501, "subject": "Fixture Science"},
                        {"teacherIdentifier": 501, "subject": "Fixture Writing"},
                    ]
                }
            )
        if request.path == "/api/inbox/unreadMessagesCount":
            fields = (
                "inbox",
                "notes",
                "alerts",
                "substitutions",
                "absences",
                "justifications",
                "trash",
            )
            return web.json_response(
                {
                    "data": {
                        **{field: index for index, field in enumerate(fields)},
                        **{
                            "archive" + field.capitalize(): index + 10
                            for index, field in enumerate(fields)
                        },
                    }
                }
            )
        if request.path in {
            "/api/inbox/messages",
            "/api/outbox/messages",
            "/api/archive/inbox/messages",
            "/api/archive/outbox/messages",
        }:
            self.message_queries.append((request.path, dict(request.query), owner))
            page, size = int(request.query["page"]), int(request.query["limit"])
            received = "inbox" in request.path
            rows = [
                self.message_row(str(value), received, owner)
                for value in range(81, 81 + self.message_count)
            ]
            return web.json_response(
                {
                    "data": rows[(page - 1) * size : page * size],
                    "total": self.message_count,
                    "archivingInProgress": "/archive/" in request.path,
                }
            )
        if request.path.startswith(("/api/inbox/messages/", "/api/outbox/messages/")):
            received = "inbox" in request.path
            row = self.message_row(request.path.rsplit("/", 1)[1], received, owner)
            return web.json_response(
                {
                    "data": row
                    | {
                        "Message": b64encode(b"<p>Fixture <b>body</b></p>").decode(),
                        "attachments": [],
                    }
                }
            )
        if request.path == "/informacja":
            if self.unavailable_profile:
                return web.Response(status=302, headers={"Location": "/modul_niedostepny"})
            if self.bad_profile:
                return web.Response(
                    text="<html><p>unrecognized sensitive page</p></html>", content_type="text/html"
                )
            body = (
                "<html><body><table>"
                + "".join(
                    f"<tr><th>{label}</th><td>{escape(value)}</td></tr>"
                    for label, value in (
                        ("Numer w dzienniku", "17"),
                        ("Szkoła", owner),
                        ("Imię i nazwisko ucznia", "Example Pupil"),
                        ("Wychowawca", "Example Tutor"),
                        ("Klasa", "Example Class"),
                    )
                )
                + "</table></body></html>"
            )
            return web.Response(text=body, content_type="text/html")
        if request.path == "/przegladaj_oceny/uczen":
            if request.method == "POST":
                form = await request.post()
                assert len(form) == 1 and next(iter(form)) in {
                    "zmiany_logowanie_wszystkie",
                    "zmiany_logowanie_tydzien",
                    "zmiany_logowanie",
                }
            body = """<html><body><table class="stretch decorated"><thead><tr>
                <th>Oceny bieżące</th><th title="Ocena śródroczna z pierwszego okresu">Midterm</th>
                <th>Oceny bieżące</th><th title="Ocena roczna">Annual</th>
                </tr></thead><tbody><tr><td></td><td>Example Subject</td>
                <td><span class="grade-box"><a title="Data: 2026-09-24">4+</a></span></td>
                <td>-</td><td>-</td><td>5</td></tr></tbody></table></body></html>"""
            body = body.replace(
                "</a></span></td>",
                "</a></span>"
                + f'<span class="grade-box"><a title="Data: 2026-09-25">{escape(self.grade_suffix)}</a></span></td>',
            )
            if self.formative:
                body = body.replace(
                    '<a title="Data: 2026-09-24">',
                    '<a href="/przegladaj_oceny/szczegoly/ksztaltujace/401" title="Data: 2026-09-24">',
                ).replace("</body>", formative_table(escape(self.formative_text)) + "</body>")
            return web.Response(text=body, content_type="text/html")
        if request.path == "/przegladaj_nb/uczen":
            assert request.method == "POST"
            body = """<html><body><table class="big decorated center">
                <tr><td class="center bolded">I okres</td></tr>
                <tr><td class="center"><a title="Data: 2026-09-24">nb</a></td></tr>
                </table></body></html>"""
            return web.Response(text=body, content_type="text/html")
        raise AssertionError(f"unapproved fixture route {request.method} {request.path}")

    @staticmethod
    def message_row(identifier, received, owner):
        row = {
            "messageId": identifier,
            "topic": f"Fixture subject {identifier} for {owner}",
            "sendDate": "2026-09-24 12:00:00",
            "isAnyFileAttached": False,
            "senderName" if received else "receiverName": "Fixture Correspondent",
        }
        if received:
            row["readDate"] = None
        return row
