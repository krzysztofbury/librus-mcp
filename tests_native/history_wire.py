"""Original synthetic 2.1 school inputs authored from native public contracts."""

from aiohttp import web


def history_response(request, wire):
    if request.path == "/gateway/api/2.0/ClassFreeDays":
        return web.json_response(
            {
                "ClassFreeDays": []
                if wire.history_empty
                else [
                    {
                        "Id": 301,
                        "Class": {"Id": 22},
                        "Type": {"Id": 5},
                        "DateFrom": "2026-10-12",
                        "DateTo": "2026-10-13",
                    },
                    {
                        "Id": 302,
                        "Class": {"Id": 22},
                        "Type": {"Id": 8},
                        "DateFrom": "2026-10-14",
                        "DateTo": "2026-10-14",
                        "LessonNoFrom": 2,
                        "LessonNoTo": 4,
                    },
                ]
            }
        )
    if request.path != "/archiwum":
        return None
    if wire.history_empty:
        body = '<div class="container-background"><div class="warning-box information medium"><div class="warning-head"><span class="warning-title">Brak danych</span></div></div></div>'
    else:
        body = """<table class="decorated"><tbody>
        <tr><td></td><td colspan="3"><span>Klasa: <b>Fixture Early</b> Rok: <b>2025/2026</b></span></td></tr>
        <tr><td></td><td>okres 1</td><td>okres 2</td><td>koniec roku</td></tr>
        <tr><th>Fixture Subject</th><td></td><td>-</td><td>5</td></tr>
        <tr><th>Fixture descriptive</th><td colspan="3">First line<br>Second line</td></tr>
        <tr class="bolded"><td colspan="4">Zachowanie</td></tr>
        <tr><th></th><td></td><td colspan="2">-</td></tr>
        <tr class="bolded"><td colspan="4">Nieobecności</td></tr>
        <tr><th>nieusprawiedlione</th><td>1</td><td>2</td><td>3</td></tr>
        <tr><th>usprawiedlione</th><td>4</td><td>5</td><td>9</td></tr>
        <tr><th>spóźnienia</th><td>0</td><td>1</td><td>1</td></tr>
        <tr><td colspan="4"></td></tr></tbody></table>
        <table class="decorated big center"><thead><tr>
        <td>Data</td><td>Klasa</td><td>Kategoria</td><td>Osiągnięcie</td>
        </tr></thead><tbody><tr><td>2026-05-11</td><td>Fixture Early</td>
        <td>Fixture award</td><td>Original achievement</td></tr></tbody></table>"""
    return web.Response(text="<html>" + body + "</html>", content_type="text/html")


def formative_table(text):
    return f"""<h3>Oceny kształtujące</h3><table class="stretch decorated">
    <thead><tr><td>Przedmiot</td><td>Ocena kształtująca</td><td>Kategoria</td>
    <td>Okres</td><td>Data</td><td>Typ</td></tr></thead><tbody>
    <tr><th>KARTA SPOSTRZEŻEŃ</th><td><a href="/przegladaj_oceny/szczegoly/ksztaltujace/401"><span class="grade-box"></span>{text}</a></td>
    <td>Fixture development</td><td>1</td><td>2026-09-25</td><td>Fixture assessment</td></tr>
    </tbody><tfoot><tr><td colspan="6"></td></tr></tfoot></table>"""
