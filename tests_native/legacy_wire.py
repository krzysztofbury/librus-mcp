"""Original legacy mailbox wire built from protocol requirements, not copied fixtures."""

from aiohttp import web


async def legacy_response(request, wire):
    if request.path == "/wiadomosci/2/6":
        return web.Response(
            text="""<html><table class="message-recipients"><tbody>
            <tr><td><input type="radio" class="recipiantTypeRadio" value="nauczyciele" id="radio_nauczyciele"/>
            <label for="radio_nauczyciele">Fixture teachers</label></td></tr>
            <tr><td><input type="radio" class="recipiantTypeRadio" value="grupa" id="radio_grupa"/>
            <label for="radio_grupa">Fixture groups</label></td></tr>
            </tbody></table></html>""",
            content_type="text/html",
        )
    if request.path == "/getRecipients":
        form = await request.post()
        if form["typAdresata"] == "grupa" and form["idGrupy"] == "0":
            body = '<html><p class="msgEmptyTable">Wybierz grupę</p><select id="idGrupy" name="idGrupy"><option value="0"></option><option value="7">Fixture group</option></select></html>'
        else:
            body = '<html><input type="checkbox" id="recipient_41" value="41"/><label for="recipient_41">Fixture Teacher</label></html>'
        return web.Response(text=body, content_type="text/html")
    if request.path in {"/wiadomosci/1/5", "/wiadomosci/1/6"}:
        form = await request.post()
        if "wyslij" in form:
            wire.sent_payloads.append(dict(form))
            wire.send_started.set()
            await wire.send_release.wait()
            if wire.send_disconnect:
                request.transport.close()
                return web.Response()
            return web.Response(
                text='<html><div class="container-background"><p>'
                + (
                    "Unrecognized result"
                    if wire.send_unknown
                    else "Wiadomość nie została wysłana."
                    if wire.send_rejected
                    else "Wiadomość została wysłana."
                )
                + "</p></div></html>",
                content_type="text/html",
            )
        sent = request.path.endswith("6")
        label = "Adresat" if sent else "Nadawca"
        header = ["", "", label, "Temat", "Wysłano", *(["Przeczytano"] if sent else []), ""]
        rows = []
        for identifier in (81, 82, 83):
            link = f"{request.path}/{identifier}"
            values = [
                "",
                "",
                f'<a href="{link}">Fixture Correspondent</a>',
                f'<a href="{link}">Fixture subject {identifier} for {request.cookies["oauth_token"]}</a>',
                "2026-09-24 12:00",
                *(["NIE"] if sent else []),
                "",
            ]
            rows.append("<tr>" + "".join(f"<td>{value}</td>" for value in values) + "</tr>")
        return web.Response(
            text='<html><table class="decorated stretch"><thead><tr>'
            + "".join(f"<th>{value}</th>" for value in header)
            + "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></html>",
            content_type="text/html",
        )
    if request.path.startswith(("/wiadomosci/1/5/", "/wiadomosci/1/6/")):
        label = "Adresat" if "/6/" in request.path else "Nadawca"
        receipts = (
            '<table class="stretch"><tr><th colspan="3">Przeczytano:</th></tr>'
            "<tr><td>Fixture Recipient A</td><td>Fixture Class</td><td>NIE</td></tr>"
            "<tr><td>Fixture Recipient B</td><td></td><td>2026-09-25 08:15</td></tr>"
            "</table>"
            if "/6/" in request.path
            else ""
        )
        return web.Response(
            text=f'<html><table class="stretch"><tr><th>{label}:</th><td>Fixture Correspondent</td></tr><tr><th>Temat:</th><td>Fixture subject</td></tr><tr><th>Wysłano:</th><td>2026-09-24 12:00</td></tr></table>{receipts}<div class="container-message-content"><p>Fixture body</p></div></html>',
            content_type="text/html",
        )
    if request.path == "/wiadomosci/pobierz_zalacznik/81/91":
        return web.Response(
            status=302,
            headers={"Location": wire.attachment_location or wire.origin + "/GetFile/fixture-key"},
        )
    return None
