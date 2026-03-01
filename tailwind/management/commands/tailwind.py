import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Compatibility command for projects that previously used django-tailwind."

    def add_arguments(self, parser):
        parser.add_argument(
            "action",
            nargs="?",
            default="help",
            choices=["help", "init", "install", "start", "build"],
            help="Tailwind action to run.",
        )

    def handle(self, *args, **options):
        action = options["action"]

        if action == "help":
            self.stdout.write(
                "Available actions: init, install, start, build. "
                "This project already uses the theme/static_src npm setup."
            )
            return

        if action == "init":
            self.stdout.write(self.style.SUCCESS("Tailwind theme scaffolding already exists at theme/"))
            return

        static_src = Path(settings.BASE_DIR) / "theme" / "static_src"
        npm_bin = getattr(settings, "NPM_BIN_PATH", "npm")

        if action in {"install", "build", "start"} and not static_src.exists():
            raise CommandError(f"Could not find Tailwind frontend directory: {static_src}")

        if action == "install":
            self.stdout.write(
                self.style.SUCCESS(
                    "No additional install step is required for this repo. "
                    "Run 'npm install' inside theme/static_src if dependencies are missing."
                )
            )
            return

        if action == "build":
            self._run_command([npm_bin, "run", "build"], cwd=static_src)
            return

        if action == "start":
            self._run_command([npm_bin, "run", "start"], cwd=static_src)
            return

    def _run_command(self, command, cwd):
        try:
            subprocess.run(command, cwd=str(cwd), check=True)
        except FileNotFoundError as exc:
            raise CommandError(
                f"Could not execute {command[0]!r}. Set NPM_BIN_PATH or install Node.js."
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise CommandError(f"Command failed with exit code {exc.returncode}.") from exc

