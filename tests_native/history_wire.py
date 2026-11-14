"""Original synthetic 2.1 school inputs authored from native public contracts."""

from html import escape

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
    if request.path == "/eusprawiedliwienia":
        return web.Response(
            text=justifications_page(wire.justifications_empty), content_type="text/html"
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


def point_table():
    """An original "Oceny punktowe" table: two percentage entries and a result."""
    entry = (
        '<span class="grade-box"><a title="Kategoria: Fixture test (0-100)&lt;br&gt;'
        'Data: 2026-09-26&lt;br&gt;Licz do wyniku: TAK" '
        'href="/przegladaj_oceny_punktowe/szczegoly/{}">{}</a></span>'
    )
    return f"""<h3 class="center">Oceny punktowe</h3><table class="decorated stretch">
    <thead><tr><td rowspan="2"></td><td rowspan="2">Przedmiot</td><td colspan="2">Okres 1</td>
    <td colspan="2">Okres 2</td></tr><tr><td>Oceny bieżące</td><td>Wyn.I</td>
    <td>Oceny bieżące</td><td title="Ocena roczna">R</td></tr></thead><tbody>
    <tr><td><img id="przedmioty_OP_81_node"></td><td>Point Subject</td>
    <td>{entry.format(501, 90)}{entry.format(502, 44)}</td><td>67</td><td>Brak ocen</td>
    <td>-</td></tr></tbody></table>"""


def formative_table(text):
    return f"""<h3>Oceny kształtujące</h3><table class="stretch decorated">
    <thead><tr><td>Przedmiot</td><td>Ocena kształtująca</td><td>Kategoria</td>
    <td>Okres</td><td>Data</td><td>Typ</td></tr></thead><tbody>
    <tr><th>KARTA SPOSTRZEŻEŃ</th><td><a href="/przegladaj_oceny/szczegoly/ksztaltujace/401"><span class="grade-box"></span>{text}</a></td>
    <td>Fixture development</td><td>1</td><td>2026-09-25</td><td>Fixture assessment</td></tr>
    </tbody><tfoot><tr><td colspan="6"></td></tr></tfoot></table>"""


def behaviour_points_box(points, detail, day):
    """An original behaviour-point entry; its tooltip opens with an unlabelled line."""
    title = escape(
        "Fixture behaviour category<br/>Zakres od: 1<br/>Zakres do: 5"
        f"<br />Data wystawienia: {day}<br />Dodał: Fixture Teacher"
        "<br>Komentarz: Fixture remark",
        quote=True,
    )
    return (
        f'<span class="grade-box"><a title="{title}" '
        f'href="/przegladaj_oceny/zachowanie_szczegoly/{detail}">{points}</a></span>'
    )


def behaviour_row():
    """The Zachowanie row: tally 50 with two entries, then -7 alone, per period."""
    first = (
        '<span class="tooltip" title="Fixture points">50</span>'
        + behaviour_points_box("+5", "11", "2026-09-21")
        + behaviour_points_box("-3", "12", "2026-09-25")
    )
    second = '<span class="tooltip" title="Fixture points">-7</span>'
    return (
        f"<tr><td></td><td>Zachowanie</td><td>{first}</td><td>-</td>"
        f"<td>{second}</td><td>-</td></tr>"
    )


JUSTIFICATION_HEADERS = (
    "Załącznik",
    "Okres usprawiedliwienia",
    "Liczba usprawiedliwionych nieobecności",
    "Treść",
    "Powiadomieni nauczyciele",
    "Data wysłania",
    "Status",
)


def justifications_page(empty=False):
    """An original e-Justifications list: a range entry, then a one-day entry."""
    rows = (
        '<tr><td colspan="7">Fixture empty list</td></tr>'
        if empty
        else """<tr class="line0"><td></td><td><b>od 2026-10-01 do 2026-10-03</b></td>
        <td>4</td><td>Fixture reason<br>second line</td>
        <td>A. Fixture, B. Fixture<br>C. Fixture</td><td>2026-10-04 08:15:00</td>
        <td>usprawiedliwione (D. Fixture)</td></tr>
        <tr class="line1"><td></td><td><b>2026-10-07, lekcje: 2, 3</b></td>
        <td>2</td><td>Fixture appointment</td><td>A. Fixture</td>
        <td>2026-10-07 19:30:05</td><td>wysłane</td></tr>"""
    )
    header = "".join(f"<td>{label}</td>" for label in JUSTIFICATION_HEADERS)
    return f"""<html><form method="post"><table class="decorated filters small center">
    <tr><td><input type="text" name="data_od" value="2026-09-24"></td>
    <td><input type="text" name="data_do" value="2026-10-24"></td>
    <td><select name="status"><option value="0">wszystkie</option>
    <option value="1">wysłane</option></select></td></tr></table></form>
    <table class="decorated stretch center"><thead><tr>{header}</tr></thead>
    <tbody>{rows}</tbody><tfoot><tr><td colspan="7"></td></tr></tfoot></table></html>"""
