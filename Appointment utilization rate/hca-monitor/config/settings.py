import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    headless: bool = os.getenv("PLAYWRIGHT_HEADLESS", "false").lower() == "true"
    db_path: str = os.getenv("DB_PATH", str(ROOT_DIR / "data" / "hca_monitor.db"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    max_lookahead_days: int = int(os.getenv("MAX_LOOKAHEAD_DAYS", "60"))
    slow_mo_ms: int = int(os.getenv("SLOW_MO_MS", "200"))
    screenshot_dir: str = os.getenv("SCREENSHOT_DIR", str(ROOT_DIR / "data" / "screenshots"))

    # Scrape cadence (24h clock, Europe/London)
    scrape_times: list = field(default_factory=lambda: ["07:00", "13:00", "19:00"])

    # T-windows in days (2 = T-48h)
    t_windows: list = field(default_factory=lambda: [21, 14, 7, 3, 2])

    # Pilot consultants
    consultants: list = field(default_factory=lambda: [
        {
            "name": "Michael Adamczyk",
            "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/michael-adamczyk",
        },
        {
            "name": "Mr Vasileios Minas",
            "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/mr-vasileios-minas",
        },
        {
            "name": "Mr Shaheen Khazali",
            "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/mr-shaheen-khazali-1",
        },
        {
            "name": "Mr Jeffrey Ahmed",
            "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/jeffrey-ahmed",
        },
        {
            "name": "Mr. Arvind Vashisht",
            "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/mr-arvind-vashisht",
        },
        {
            "name": "Mr Elias Kovoor",
            "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/mr-elias-kovoor",
        },
        {
            "name": "Prof. Janice Rymer",
            "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/professor-janice-rymer",
        },
        {
            "name": "Mr Tom Holland",
            "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/mr-tom-holland",
        },
        {
            "name": "Mr Tariq Miskry",
            "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/mr-tariq-miskry",
        },
        {
            "name": "Mr Nitish Narvekar",
            "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/mr-nitish-narvekar",
        },
        {
            "name": "Mr Ilyas Arshad",
            "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/illyas-arshad",
        },
        {
            "name": "Mr. Denis Tsepov",
            "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/mr-denis-tsepov",
        },
        {
            "name": "Ms. Nadine Di Donato",
            "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/ms-nadine-di-donato",
        },
        {
            "name": "Dr Sujata Gupta",
            "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/miss-sujata-gupta",
        },
        {
            "name": "Dr Nahid Gul",
            "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/ms-nahid-gul",
        },
        {
            "name": "Mr Yousri Afifi",
            "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/mr-yousri-afifi",
        },
        {
            "name": "Ms Eleni Mavrides",
            "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/ms-eleni-mavrides",
        },
        {
            "name": "Mohan Kumar",
            "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/mr-mohan-kumar",
        },
        {
            "name": "Mr Suku George",
            "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/mr-suku-george-1",
        },
        {
            "name": "Mr Zeiad El-Gizawy",
            "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/mr-zeiad-ei-gizawy",
        },
        {
            "name": "Prof Ertan Saridogan",
            "profile_url": "https://www.hcahealthcare.co.uk/finder/stepconsultantprofile/mr-ertan-saridogan",
        },
    ])

    # Maximum consecutive empty calendar pages before stopping
    max_empty_calendar_pages: int = 2

    # Timeout for Playwright waits (ms)
    nav_timeout_ms: int = 15000


settings = Settings()
