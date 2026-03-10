import sys

import librus_apix.grades
from typing import List, Tuple, DefaultDict
from librus_apix.grades import Grade, Gpa, Tag, defaultdict, _handle_subject, _extract_grade_info


def _extract_grades_numeric_patched(
    table_rows: List[Tag],
) -> Tuple[List[DefaultDict[str, List[Grade]]], DefaultDict[str, List[Gpa]]]:
    # Two semesters: each is a dict mapping subject name to a list of grades.
    sem_grades: List[DefaultDict[str, List[Grade]]] = [defaultdict(list) for _ in range(2)]
    avg_grades: DefaultDict[str, List[Gpa]] = defaultdict(list)

    for box in table_rows:
        if box.select_one("td[class='center micro screen-only']") is None:
            continue
        semester_grades = box.select('td[class!="center micro screen-only"]')
        if len(semester_grades) < 9:
            continue
        average_grades = list(map(lambda x: x.text, box.select("td.right")))
        semesters = [semester_grades[1:4], semester_grades[4:7]]
        subject = _handle_subject(semester_grades)
        for semester_number, semester in enumerate(semesters):
            if subject not in sem_grades[semester_number]:
                sem_grades[semester_number][subject] = []
            for sg in semester:
                grade_a_improved = sg.select("td[class!='center'] > span > span.grade-box > a")
                grade_a = sg.select("td[class!='center'] > span.grade-box > a") + grade_a_improved
                for a in grade_a:
                    (
                        _grade,
                        date,
                        _href,
                        desc,
                        counts,
                        category,
                        teacher,
                        weight,
                    ) = _extract_grade_info(a, subject)
                    g = Grade(
                        subject,
                        _grade,
                        counts,
                        date,
                        a.attrs.get("href", ""),
                        desc,
                        semester_number + 1,
                        category,
                        teacher,
                        weight,
                    )
                    sem_grades[semester_number][subject].append(g)

            # Original library uses >= which causes an off-by-one IndexError
            # when average_grades has exactly semester_number elements.
            avg_gr = (
                average_grades[semester_number] if len(average_grades) > semester_number else 0.0
            )

            gpa = Gpa(semester_number + 1, avg_gr, subject)
            avg_grades[subject].append(gpa)

        avg_gr = average_grades[-1] if len(average_grades) > 0 else 0.0
        avg_grades[subject].append(Gpa(0, avg_gr, subject))

    return sem_grades, avg_grades


def apply_patches():
    """Replace buggy librus_apix grade extraction with patched version."""
    librus_apix.grades._extract_grades_numeric = _extract_grades_numeric_patched
    print("Patched librus_apix.grades._extract_grades_numeric", file=sys.stderr)
