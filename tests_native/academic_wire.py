"""Original synthetic ordinary school wire for MCP projection acceptance."""

import calendar
from datetime import date, timedelta

from aiohttp import web


async def academic_response(request):
    path = request.path.rstrip("/")
    if path == "/gateway/api/2.0/Attendances":
        return web.json_response(
            {
                "Attendances": [
                    {
                        "Id": str(index),
                        "Date": "2026-09-24",
                        "Semester": 1,
                        "Type": {"Id": kind},
                        "Lesson": {"Id": "61"},
                    }
                    for index, kind in enumerate(("100", "1", "1266", "999"), start=1)
                ]
            }
        )
    if path == "/gateway/api/2.0/Lessons/61":
        return web.json_response({"Lesson": {"Id": "61", "Subject": {"Id": "71"}}})
    if path == "/gateway/api/2.0/Subjects/71":
        return web.json_response({"Subject": {"Id": "71", "Name": "Fixture Subject"}})
    if path == "/ogloszenia":
        body = '<table class="decorated big center printable margin-top"><thead><tr><td colspan="2">Fixture notice</td></tr></thead><tbody><tr class="line0"><th>Autor:</th><td>Fixture Author</td></tr><tr class="line1"><th>Data publikacji:</th><td>2026-09-24</td></tr><tr class="line0"><th>Treść:</th><td>Inert notice text</td></tr></tbody></table>'
    elif path == "/terminarz":
        form = await request.post()
        year, month = int(form["rok"]), int(form["miesiac"])
        body = "".join(
            f'<div class="kalendarz-dzien"><div class="kalendarz-numer-dnia">{day}</div>'
            + (
                "<table><tr><td onclick=\"openDetails('/terminarz/szczegoly/51')\">Fixture event</td></tr></table>"
                if day == 24
                else ""
            )
            + "</div>"
            for day in range(1, calendar.monthrange(year, month)[1] + 1)
        )
    elif path == "/moje_zadania":
        body = (
            '<table class="decorated myHomeworkTable"><thead><tr>'
            + "".join(
                f'<th colspan="{2 if label in {"Data zadania", "Termin wykonania"} else 1}">{label}</th>'
                for label in (
                    "Przedmiot",
                    "Nauczyciel",
                    "Temat",
                    "Kategoria",
                    "Data zadania",
                    "Termin wykonania",
                    "Status przesyłania rozwiązania",
                    "Opcje",
                )
            )
            + '</tr></thead><tbody><tr class="line0">'
            + "".join(
                f"<td>{value}</td>"
                for value in (
                    "Fixture Subject",
                    "Fixture Teacher",
                    "Fixture homework",
                    "Assignment",
                    "2026-09-24",
                    "czw.",
                    "2026-09-25",
                    "pt.",
                    "Not submitted",
                    "<a onclick=\"openDetails('/moje_zadania/podglad/52')\">Details</a>",
                )
            )
            + "</tr></tbody></table>"
        )
    elif path in {
        "/terminarz/szczegoly/51",
        "/moje_zadania/podglad/52",
        "/przegladaj_nb/szczegoly/81",
    }:
        body = '<div class="container-background"><table><tr class="line0"><th>Opis:</th><td>Fixture detail</td></tr></table></div>'
    elif path == "/przegladaj_plan_lekcji":
        form = await request.post()
        monday = date.fromisoformat(form["tydzien"].split("_")[0])
        body = (
            '<table class="decorated plan-lekcji"><tr class="line1"><td class="center">1</td>'
            + "".join(
                f'<td id="timetableEntryBox" data-date="{monday + timedelta(days=index)}" data-time_from="08:00" data-time_to="08:45"></td>'
                for index in range(7)
            )
            + "</tr></table>"
        )
    elif path == "/zrealizowane_lekcje":
        body = (
            '<table class="decorated stretch"><tbody>'
            + "".join(
                f'<tr><td class="center small">2026-09-24</td><td class="tiny">czw.</td><td>{number}</td><td>Fixture Subject, Fixture Teacher</td><td>Fixture topic {number}</td><td>-</td><td>nb</td></tr>'
                for number in (1, 2)
            )
            + "</tbody></table>"
        )
    else:
        return None
    return web.Response(text="<html>" + body + "</html>", content_type="text/html")
