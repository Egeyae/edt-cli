from typing import Any
import argparse
import getpass
import json
import os
import re
import sys
from pathlib import Path

from .data import Calendars, Event

SETTINGS = os.environ.get("SETTINGS", "settings.json")
CACHE = os.environ.get("CALENDAR_CACHE", "calendars.pkl")


def choice(question: str) -> bool:
    while True:
        answer = input(f"{question} [y/n] ").strip().lower()

        if answer in {"y", "yes"}:
            return True

        if answer in {"n", "no"}:
            return False


def get_answer(question: str, *, secret: bool = False) -> str:
    while True:
        answer = (
            getpass.getpass(question)
            if secret
            else input(question)
        ).strip()

        if answer:
            return answer

        print("A value is required.")


def load_settings() -> dict:
    try:
        with open(SETTINGS, encoding="utf-8") as file:
            settings = json.load(file)
    except FileNotFoundError:
        print(f"Settings file not found: {SETTINGS}")
        sys.exit(1)
    except json.JSONDecodeError as error:
        print(f"Invalid JSON in {SETTINGS}: {error}")
        sys.exit(1)

    validate_settings(settings)
    return settings


def validate_settings(settings: dict) -> None:
    required_keys = {
        "credentials",
        "baseurl",
        "subscribed",
        "calendars",
    }

    missing = required_keys - settings.keys()
    if missing:
        raise ValueError(
            f"Settings file is missing keys: {', '.join(sorted(missing))}"
        )

    if not isinstance(settings["credentials"], dict):
        raise ValueError("'credentials' must be an object")

    if "username" not in settings["credentials"]:
        raise ValueError("Missing credentials.username")

    if "password" not in settings["credentials"]:
        raise ValueError("Missing credentials.password")

    if not isinstance(settings["calendars"], dict):
        raise ValueError("'calendars' must be an object")

    if not isinstance(settings["subscribed"], dict):
        raise ValueError("'subscribed' must be an object")


def save_settings(settings: dict) -> None:
    settings_path = Path(SETTINGS)
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    with open(settings_path, "w", encoding="utf-8") as file:
        json.dump(settings, file, indent=4)
        file.write("\n")

    print(f"Saved settings to {settings_path}")

def get_course_group() -> str | None:
    group = input(
        "Group for TD/TME "
        "(leave empty to include every group): "
    ).strip()

    if not group:
        return None

    if not re.fullmatch(r"[A-Za-z0-9]+", group):
        print("Invalid group. Ignoring group filter.")
        return None

    return group.upper()


def create_settings() -> None:
    if os.path.exists(SETTINGS):
        if not choice(f"{SETTINGS} already exists. Replace it?"):
            print("Cancelled.")
            return

    settings = {
        "credentials": {
            "username": get_answer("Username: "),
            "password": get_answer("Password: ", secret=True),
        },
        "baseurl": get_answer("Base URL: "),
        "subscribed": {},
        "calendars": {},
    }

    print("\nRegistering calendars.")
    print("Leave the calendar name empty when finished.\n")

    while True:
        name = input("Calendar name: ").strip()

        if not name:
            break

        if name in settings["calendars"]:
            print("A calendar with that name already exists.")
            continue

        url = get_answer("Calendar URL: ")
        settings["calendars"][name] = url

    if not settings["calendars"]:
        print("Warning: no calendars were configured.")

    print("\nRegistering courses.")
    print("Leave the course name empty when finished.\n")

    while True:
        course = input("Course code: ").strip()

        if not course:
            break

        group = get_course_group()

        settings["subscribed"][course] = group

    save_settings(settings)


def update_settings() -> None:
    settings = load_settings()

    while True:
        print("\nSettings menu")
        print("1. Change username")
        print("2. Change password")
        print("3. Change base URL")
        print("4. Add calendar")
        print("5. Remove calendar")
        print("6. Add subscribed course")
        print("7. Remove subscribed course")
        print("8. Save and exit")
        print("9. Exit without saving")

        option = input("> ").strip()

        if option == "1":
            settings["credentials"]["username"] = get_answer("Username: ")

        elif option == "2":
            settings["credentials"]["password"] = get_answer(
                "Password: ",
                secret=True,
            )

        elif option == "3":
            settings["baseurl"] = get_answer("Base URL: ")

        elif option == "4":
            name = get_answer("Calendar name: ")

            if name in settings["calendars"]:
                print("That calendar already exists.")
                continue

            settings["calendars"][name] = get_answer("Calendar URL: ")

        elif option == "5":
            calendars = settings["calendars"]

            if not calendars:
                print("No calendars configured.")
                continue

            print("\nConfigured calendars:")
            for name in calendars:
                print(f"  - {name}")

            name = get_answer("Calendar name to remove: ")

            if name not in calendars:
                print("Calendar not found.")
                continue

            del calendars[name]

        elif option == "6":
            course = get_answer("Course code: ")
            group = get_course_group()
            settings["subscribed"][course] = group

        elif option == "7":
            subscribed = settings["subscribed"]

            if not subscribed:
                print("No subscribed courses.")
                continue

            print("\nSubscribed courses:")
            for course in subscribed:
                print(f"  - {course}")

            course = get_answer("Course code to remove: ")

            if course not in subscribed:
                print("Course not found.")
                continue

            del subscribed[course]

        elif option == "8":
            save_settings(settings)
            return

        elif option == "9":
            print("Changes discarded.")
            return

        else:
            print("Invalid option.")


def check_settings() -> None:
    if not os.path.isfile(SETTINGS):
        print(f"Settings file not found: {SETTINGS}")

        if choice("Create a new settings file?"):
            create_settings()
        else:
            print("edt-cli requires a settings file. Exiting...")
            sys.exit(1)


def get_calendar_manager(settings: dict) -> Calendars:
    calendar_config = settings["calendars"].items()

    return Calendars.from_config(calendar_config)


def get_subscribed_courses(
    settings: dict,
) -> dict[str, str | None]:
    return settings["subscribed"]


def load_calendars(settings: dict) -> Calendars:
    calendars = get_calendar_manager(settings)
    credentials = settings["credentials"]

    print("Loading calendars...")

    calendars.load(
        base_url=settings["baseurl"],
        username=credentials["username"],
        password=credentials["password"],
        subscribed_courses=get_subscribed_courses(settings),
    )

    return calendars


def refresh_calendars(settings: dict) -> None:
    calendars = load_calendars(settings)
    calendars.save(CACHE)

    print(f"Saved calendar cache to {CACHE}")
    print(f"Loaded {len(calendars.events)} events.")


def load_cached_calendars() -> Calendars:
    try:
        return Calendars.load_pickle(CACHE)
    except FileNotFoundError:
        print("No calendar cache found. Refreshing calendars...")
        settings = load_settings()
        calendars = load_calendars(settings)
        calendars.save(CACHE)
        return calendars


def _truncate(value: Any, width: int) -> str:
    value = str(value).strip()

    if len(value) > width:
        value = f"{value[:width-3]}..."
    return value

def _print_event_table(events: list[Event]) -> None:
    widths = {
        "date": 16,
        "time": 16,
        "room": 32,
        "summary": 32,
        "source": 32
    }

    def print_row(
        date: str,
        time: str,
        room: str,
        summary: str,
        source: str
    ) -> None:
        date = _truncate(date, widths["date"])
        time = _truncate(time, widths["time"])
        room = _truncate(room, widths["room"])
        summary = _truncate(summary, widths["summary"])
        source = _truncate(source, widths["source"])

        print(
            f"{date:<{widths['date']}}  "
            f"{time:<{widths['time']}}  "
            f"{room:<{widths['room']}}  "
            f"{summary:<{widths['summary']}}  "
            f"{source:<{widths['source']}}"
        )

    print_row(
        "DATE",
        "TIME",
        "ROOM",
        "SUMMARY",
        "SOURCE"
    )

    print(
        f"{'-' * widths['date']}  "
        f"{'-' * widths['time']}  "
        f"{'-' * widths['room']}  "
        f"{'-' * widths['summary']}  "
        f"{'-' * widths['source']}"
    )

    for event in events:
        formatted = event.formatted()

        source = event.calendar
        if event.resource:
            source = f"{source} / {event.resource}"

        print_row(
            formatted["date"],
            formatted["time"],
            formatted["room"] or "—",
            formatted["summary"],
            source,
        )


def print_upcoming_events(
    calendars: Calendars,
    subscribed_courses: dict[str, str | None],
    limit: int | None,
) -> None:
    upcoming = calendars.upcoming_events(
        subscribed_courses,
        limit_per_course=limit,
    )

    if not upcoming:
        print("No upcoming events found.")
        return

    total_events = sum(len(events) for events in upcoming.values())
    print(
        f"Upcoming events: {total_events} with {len(upcoming)} course(s)"
    )

    if limit is not None:
        print(f"Limit: {limit} event(s) per course")

    for course, events in upcoming.items():
        print()
        print(f"{course}  -  {len(events)} event(s)")
        print("=" * 140)

        _print_event_table(events)


def show_settings(settings: dict) -> None:
    safe_settings = {
        "baseurl": settings["baseurl"],
        "subscribed": settings["subscribed"],
        "calendars": settings["calendars"],
        "credentials": {
            "username": settings["credentials"]["username"],
            "password": "***",
        },
    }

    print(json.dumps(safe_settings, indent=4))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="edt-cli",
        description="Command-line calendar client",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    subparsers.add_parser(
        "init",
        help="Create a new settings file",
    )

    subparsers.add_parser(
        "config",
        help="Edit the settings file",
    )

    subparsers.add_parser(
        "settings",
        help="Show the current settings",
    )

    subparsers.add_parser(
        "refresh",
        help="Fetch calendars and save the local cache",
    )

    upcoming_parser = subparsers.add_parser(
        "upcoming",
        help="Show upcoming events",
    )

    upcoming_parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=None,
        help="Maximum number of events per course",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init":
        create_settings()
        return

    if args.command == "config":
        check_settings()
        update_settings()
        return

    check_settings()

    if args.command == "settings":
        settings = load_settings()
        show_settings(settings)

    elif args.command == "refresh":
        settings = load_settings()
        refresh_calendars(settings)

    elif args.command == "upcoming":
        settings = load_settings()
        calendars = load_cached_calendars()

        print_upcoming_events(
            calendars,
            get_subscribed_courses(settings),
            args.limit,
        )


if __name__ == "__main__":
    main()
