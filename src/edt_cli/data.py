import pickle
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

import requests
from icalendar import Calendar as ICalendar


def extract_course(summary: str) -> str:
    return summary.split("-", 1)[0].split(maxsplit=1)[0] # found by experience

def extract_activity_group(summary: str) -> tuple[str, str] | None:
    """
    Extracts a tuple, with the activity type: either TD or TME and the group number (allowed A-Z and a-z and 0-9 just to be sure)
    """
    match = re.search(
        r"\b(TD|TME)\s*([A-Za-z0-9]+)\b",
        summary,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    activity = match.group(1).upper()
    group = match.group(2).upper()

    return activity, group


def is_event_allowed(summary: str, expected_group: str | None) -> bool:
    # filters an event based on groups
    if expected_group is None:
        return True

    activity_group = extract_activity_group(summary)

    if activity_group is None:
        return True

    _, event_group = activity_group

    return event_group == expected_group.upper()

@dataclass
class Event:
    summary: str
    start: datetime | date | None = None
    end: datetime | date | None = None
    description: str = ""
    location: str = ""
    resource: str = ""
    calendar: str = ""

    @property
    def start_time(self) -> datetime | date:
        if self.start is None:
            return datetime.max.replace(tzinfo=UTC)

        if hasattr(self.start, "dt"):
            return self.start.dt

        return self.start

    @property
    def course(self) -> str:
        return extract_course(self.summary)

    def is_in_future(self, now: datetime | None = None) -> bool:
        # now param allow to move into time
        now = now or datetime.now(UTC)
        start = self.start_time

        # if not datetime, then assumes start time = midnight
        if isinstance(start, date) and not isinstance(start, datetime):
            start = datetime.combine(start, datetime.min.time(), tzinfo=UTC)

        # ensures UTC information is always set
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)

        return start > now

    def formatted(self) -> dict[str, str]:
        start = self.start_time

        if isinstance(start, datetime):
            date_str = start.strftime("%Y-%m-%d")
            time_str = start.strftime("%H:%M")
        else:
            date_str = start.strftime("%Y-%m-%d")
            time_str = "N/A"

        return {
            "course": self.course,
            "date": date_str,
            "time": time_str,
            "room": self.location or "N/A",
            "summary": self.summary,
        }


@dataclass
class Resource:
    name: str
    endpoint: str
    # field ensures that each Resource instance has its own events list (not shared)
    events: list[Event] = field(default_factory=list)

    def load_events(
        self,
        *, # every other args have to be called, no more positional
        base_url: str,
        username: str,
        password: str,
        subscribed_courses: dict[str, str | None],
    ) -> None:
        resource_url = base_url + self.endpoint

        response = requests.get(
            resource_url,
            auth=(username, password),
            timeout=30,
        )
        response.raise_for_status()

        calendar = ICalendar.from_ical(response.text)

        self.events.clear()

        for component in calendar.walk():
            if component.name != "VEVENT":
                continue

            summary = str(component.get("summary", "No title"))
            course = extract_course(summary)

            if course not in subscribed_courses:
                continue

            expected_group = subscribed_courses[course]

            if not is_event_allowed(summary, expected_group):
                continue

            self.events.append(
                Event(
                    summary=summary,
                    start=component.get("dtstart"),
                    end=component.get("dtend"),
                    description=str(component.get("description", "")),
                    location=str(component.get("location", "")),
                    resource=self.name,
                    calendar="",
                )
            )


@dataclass
class Calendar:
    name: str
    url: str
    resources: dict[str, Resource] = field(default_factory=dict)

    def load_resources(
        self,
        *,
        username: str,
        password: str,
    ) -> None:
        response = requests.request(
            "PROPFIND",
            self.url,
            auth=(username, password),
            headers={"Depth": "1"},
            timeout=30,
        )
        response.raise_for_status()

        self.resources.clear()

        property_responses = re.findall(
            r"<response>(.*?)</response>",
            response.text,
            re.DOTALL,
        )

        for property_response in property_responses:
            if "<C1:calendar/>" not in property_response:
                continue

            href_match = re.search(
                r"<href>(.*?)</href>",
                property_response,
                re.DOTALL,
            )

            if not href_match:
                continue

            endpoint = href_match.group(1)
            resource_name = endpoint.rstrip("/").split("/")[-1]

            self.resources[resource_name] = Resource(
                name=resource_name,
                endpoint=endpoint,
            )

    def load_events(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        subscribed_courses: dict[str, str | None],
    ) -> None:
        for resource in self.resources.values():
            try:
                resource.load_events(
                    base_url=base_url,
                    username=username,
                    password=password,
                    subscribed_courses=subscribed_courses,
                )

                for event in resource.events:
                    event.calendar = self.name

            except requests.RequestException as error:
                print(f"Error loading {resource.name}: {error}")
            except Exception as error:
                print(f"Error parsing {resource.name}: {error}")

    @property
    def events(self) -> list[Event]:
        return [
            event
            for resource in self.resources.values()
            for event in resource.events
        ]


@dataclass
class Calendars:
    calendars: list[Calendar] = field(default_factory=list)

    @classmethod
    def from_config(cls, calendar_config: Iterable[tuple[str, str]]) -> Calendars:
        return cls(
            calendars=[
                Calendar(name=name, url=url)
                for name, url in calendar_config
            ]
        )

    def load(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        subscribed_courses: dict[str, str | None],
    ) -> None:
        for calendar in self.calendars:
            calendar.load_resources(
                username=username,
                password=password,
            )
            calendar.load_events(
                base_url=base_url,
                username=username,
                password=password,
                subscribed_courses=subscribed_courses,
            )

    @property
    def events(self) -> list[Event]:
        return [
            event
            for calendar in self.calendars
            for event in calendar.events
        ]

    def upcoming_events(
        self,
        subscribed_courses: dict[str, str | None],
        *,
        limit_per_course: int | None = None,
    ) -> dict[str, list[Event]]:
        subscribed_course_codes = set(subscribed_courses)
        grouped: dict[str, list[Event]] = {} # groups by course

        for event in self.events:
            if event.course not in subscribed_course_codes:
                continue

            if not event.is_in_future():
                continue

            if grouped.get(event.course) is None:
                grouped[event.course] = []
            grouped[event.course].append(event)

        for course_events in grouped.values():
            course_events.sort(key=lambda event: event.start_time)

        if limit_per_course is not None:
            grouped = {
                course: events[:limit_per_course]
                for course, events in grouped.items()
            }

        return dict(sorted(grouped.items()))

    def save(self, filename: str | Path) -> None:
        with open(filename, "wb") as file:
            pickle.dump(self, file, protocol=pickle.HIGHEST_PROTOCOL)

    @classmethod
    def load_pickle(cls, filename: str | Path) -> Calendars:
        with open(filename, "rb") as file:
            result = pickle.load(file)

        if not isinstance(result, cls):
            raise TypeError(f"Expected {cls.__name__}, got {type(result).__name__}")

        return result
