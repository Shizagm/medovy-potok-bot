FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd -g 10001 roy && useradd -u 10001 -g roy -m roy
COPY --chown=roy:roy engine.py bot.py games.py tavern.py characters.py interface.py feature_interface.py character_interface.py instance_lock.py ./
COPY --chown=roy:roy assets/ ./assets/
COPY --chown=roy:roy catalog/ ./catalog/
RUN mkdir -p /app/data && chown roy:roy /app/data
# Repair mounted data ownership at runtime, then drop root privileges.
USER root
CMD ["python", "-c", "import os\nfrom pathlib import Path\nimport sys\nroot = Path('/app/data')\nif root.is_symlink():\n    raise SystemExit('Папка /app/data не должна быть символической ссылкой.')\nroot.mkdir(parents=True, exist_ok=True)\nif os.geteuid() == 0:\n    for base, dirs, files in os.walk(root, followlinks=False):\n        os.chown(base, 10001, 10001)\n        for name in dirs + files:\n            path = Path(base) / name\n            if not path.is_symlink():\n                os.chown(path, 10001, 10001)\n    os.setgroups([])\n    os.setgid(10001)\n    os.setuid(10001)\nprint('Папка данных готова. Запуск Роя; UID=' + str(os.geteuid()), flush=True)\nos.execv(sys.executable, [sys.executable, '/app/bot.py'])\n"]
