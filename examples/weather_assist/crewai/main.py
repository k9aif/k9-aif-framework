from __future__ import annotations

import sys

from .crew import build_weather_assist_crew


def main() -> int:
    city = " ".join(sys.argv[1:]).strip() or "Atlanta"

    crew = build_weather_assist_crew(city)
    result = crew.kickoff()

    print("\n=== FINAL WEATHER SUMMARY ===\n")
    print(result)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())